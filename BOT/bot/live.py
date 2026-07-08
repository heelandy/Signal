"""Live signal loop — the system 'always looking for the 4 families' (discretion model).

Per scan: pull recent bars from the data router (Alpaca → Yahoo fallback) → scan the 4 families →
risk-gate each fresh signal → attach the 0DTE options play (QQQ/SPY) → journal → return the
proposals for the user to take or skip. Nothing is auto-executed; mean-reversion is info-only.

    python -m bot.live SPY QQQ NQ        # one scan of the watchlist
    from bot.live import scan_watchlist
"""
from __future__ import annotations

import sys

import time

import pandas as pd

from bot.market_data.providers import get_bars
from bot.strategy import families
from bot.strategy.asset_config import asset_config
from bot.risk import decide, Account
from bot.journal import Journal
from bot.store import Store
from bot.options.exit_plan import options_exit_plan
from bot.ml.pipeline import predict_candidate
from bot.orderflow.confirm import orderflow_confirm

_journal = Journal()
_store = Store()                     # persist signals + decisions to SQLite as well
# the standing tracked set (F62/F30): equities + index futures + GOLD
WATCHLIST = ["SPY", "QQQ", "NQ", "GC"]
# STALE-DATA GATE (review 2026-07): a proposal built on old bars must not pass the risk gate.
# Max age of the LAST bar for the feed to count as healthy. 5m bars + provider lag -> 15 min
# covers a live session; when the market is closed everything is "stale" and entries stay blocked,
# which is the fail-closed behavior we want. Override per call via max_bar_age_min.
MAX_BAR_AGE_MIN = 15.0


def _zone_state(side: str, price: float, or_high, or_low) -> str:
    from bot.strategy.orb_state import signal_zone_state
    try:
        return signal_zone_state(side, price, or_high, or_low)
    except Exception:
        return "unknown"


def _dir_fast(ctx, or_high, or_low):
    """1m-feed DIR-fast votes + combined slope engine for a proposal (None when 1m unavailable)."""
    if not ctx:
        return None
    from bot.strategy.orb_state import fast_direction
    try:
        closes, vwap, st1, opens, atr1 = ctx
        return fast_direction(closes, or_high, or_low, vwap=vwap, st_state_1m=st1,
                              opens_1m=opens, atr=atr1)
    except Exception:
        return None


_KELLY_B: dict = {}          # symbol -> payoff b from the backtest matrix (cached once per process)


def _kelly_advice(sym: str, p_win) -> dict | None:
    """Quarter-Kelly advisory from calibrated P(win) + the symbol's realized win/loss profile."""
    if not isinstance(p_win, float):
        return None
    if sym not in _KELLY_B:
        b = 2.2                                       # 4R-cap profile fallback (mixed exits)
        try:
            import json as _json
            from bot.ml.registry import REPORTS_DIR
            m = _json.loads((REPORTS_DIR / "backtest_matrix.json").read_text(encoding="utf-8"))
            o = m["symbols"][sym]["overall"]          # derive b from win% + avg R:  avg = p*w - (1-p)*l
            p_hist, avg = o["win_pct"] / 100.0, o["avg_r"]
            l = 1.0                                   # full-stop loss ~= 1R in this system
            w = (avg + (1 - p_hist) * l) / max(p_hist, 1e-9)
            b = max(w / l, 0.1)
        except Exception:
            pass
        _KELLY_B[sym] = round(b, 2)
    from bot.risk import kelly_fraction
    return kelly_fraction(p_win, _KELLY_B[sym], 1.0)


def source_health(bars, max_bar_age_min: float = MAX_BAR_AGE_MIN,
                  now: pd.Timestamp | None = None) -> tuple[bool, float]:
    """Fail-closed feed check for one symbol's bar frame: market-truth issues + last-bar age.
    Returns (healthy, age_minutes). Empty/dirty/old data -> (False, age)."""
    from bot.market_truth import assess
    if bars is None or not len(bars):
        return False, float("inf")
    now = now or pd.Timestamp.now(tz="UTC")
    h = assess(bars, source="router", ts_col="ts_et", freq_min=5,
               max_staleness_sec=max_bar_age_min * 60.0, now=now)
    age_min = (h.staleness_sec or 0.0) / 60.0
    return bool(h.healthy), age_min
EQUITY_OPT = {"QQQ", "SPY"}          # Alpaca-tradeable options; GC options = futures-opts / GLD proxy

# GRADE-WEIGHTED SIZING (research 2026-07: exp-by-grade — A+ is 2-3x A/B; B is NEGATIVE on ES/SPY).
# Kelly-lite multipliers on the base 0.25%-risk budget: bet more where the graded edge is higher.
GRADE_MULT = {"A+": 1.5, "A": 1.0, "B": 0.4, "C": 0.0}
B_SKIP_SYMBOLS = {"ES", "SPY"}       # grade-B expectancy is negative on these -> recommend SKIP


def scan_watchlist(symbols: list[str], provider: str | None = None, equity: float = 100_000.0,
                   bars_back: int = 2, with_options: bool = True, persist: bool = True,
                   tf: str = "5m") -> list[dict]:
    """Signal-engine scan: data -> 4 families -> P(win) -> order-flow -> options exit-plan. No trades.
    tf selects the signal timeframe (5m default; the 15m pass drives the 15m lineage's live journal)."""
    proposals = []
    _period = "20d" if tf in ("15m", "30m", "1h") else "5d"    # wider window so higher-TF bars fill
    for sym in symbols:
        sym = sym.upper()
        try:
            bars = get_bars(sym, tf, period=_period, provider=provider)
        except Exception as e:
            proposals.append({"symbol": sym, "error": str(e)})
            continue
        if not len(bars):
            continue
        src = bars.attrs.get("provider", "?")
        last_ts = pd.Timestamp(bars["ts_et"].iloc[-1])
        age_min = int((pd.Timestamp.now(tz="America/New_York") - last_ts).total_seconds() / 60)
        # STALE-DATA GATE (review 2026-07): was hardcoded source_healthy=True — a stale/dirty feed
        # could produce APPROVED proposals. Now the risk gate blocks entries when the feed fails.
        healthy, _ = source_health(bars)
        # "now" = REAL-TIME last trade, not the last 5m bar close (which lags pre-open/after-hours).
        from bot.market_data.providers import latest_price
        lp = latest_price(sym)
        last_px = lp.get("price") or round(float(bars["close"].iloc[-1]), 2)
        px_src = lp.get("source") or src
        a = asset_config(sym)
        try:
            from bot.features import feature_snapshot
            feats = feature_snapshot(bars)                            # FEE-001 context (RSI/ADX/vol/...)
        except Exception:
            feats = {}
        # 1-MINUTE DIRECTION FEED (staleness fix 2026-07, mirrors the Pine fast_dir input): structure
        # + slope + vwap computed on 1m bars so the direction read flips at 1m speed regardless of the
        # 5m signal timeframe. Best-effort: a failed 1m fetch just leaves dir_fast unavailable.
        _df_ctx, b1 = None, None
        try:
            b1 = get_bars(sym, "1m", period="2d", provider=provider)
            if len(b1) >= 30:
                d1 = families.prepare(b1, sym)                        # same engine machine, 1m context
                _df_ctx = (d1["close"].to_numpy(float),
                           float(d1["vwap_sess"].iloc[-1]) if "vwap_sess" in d1 else None,
                           int(d1["st_state"].iloc[-1]) if "st_state" in d1 else None,
                           d1["open"].to_numpy(float),                # combined slope engine inputs
                           float(d1["atr14"].iloc[-1]) if "atr14" in d1 else None)
        except Exception:
            _df_ctx, b1 = None, None
        # F67 CLEAN-AIR: today's RTH 1m bars (causal "up to now") for the liquidity-zone map
        _b1_today = None
        try:
            if b1 is not None and len(b1) >= 40 and a.clean_air:
                _et = pd.to_datetime(b1["ts_et"] if "ts_et" in b1 else b1["ts"])
                if _et.dt.tz is None:
                    _et = _et.dt.tz_localize("UTC")
                _et = _et.dt.tz_convert("America/New_York")
                _mm = _et.dt.hour * 60 + _et.dt.minute
                _tod = _et.dt.date == pd.Timestamp.now(tz="America/New_York").date()
                _b1_today = b1[_tod & (_mm >= 570) & (_mm < 960)]
                if len(_b1_today) < 40:
                    _b1_today = b1[(_mm >= 570) & (_mm < 960)]      # fallback: last available RTH session
        except Exception:
            _b1_today = None
        # MULTI-TF ROLLING DIRECTION (research 2026-07-02): every chart TF re-scored from the SAME
        # 1m array on every completed 1m bar (2/5/15/30/60/240 x 1m windows, D = 0.30S+0.20P+0.20E+
        # 0.15B+0.15M), plus the 2-bar IMMEDIATE read refreshed by the live price between minute
        # closes. DETECTION layer only — dir_fast + the confirmed 1m st_state stay as the backup /
        # validated gate. Best-effort like the 1m feed itself.
        mtf_dir = None
        try:
            if b1 is not None and len(b1) >= 2:
                from bot.strategy.direction_engine import update_all_directions
                _atr1 = _df_ctx[4] if _df_ctx else None
                mtf_dir = update_all_directions(b1, atr=_atr1, live_price=lp.get("price"))
        except Exception:
            mtf_dir = None
        # IV estimate from realized vol (5m log-returns annualized) so options price WITHOUT manual input.
        # F85 (OPRA): raw realized vol underprices market ATM IV ~1.56x — lift it before pricing.
        import numpy as _np
        from bot.options.pricing import calibrate_realized_iv as _cal, default_iv as _div
        _cl = bars["close"].to_numpy(float)[-120:]
        _ret = _np.diff(_np.log(_cl)) if len(_cl) > 6 else _np.array([0.0])
        iv_est = (_cal(float(_np.std(_ret) * (252 * 78) ** 0.5), dte=0) if len(_ret) > 5 else _div(0))
        for s in families.scan(bars, sym, bars_back=bars_back, bars_1m=b1):   # 1m feed -> gate + grade at 1m speed
            c = s["candidate"]
            # PREDICTIVE: calibrated P(win) from the champion, scored on the SAME PIT feature
            # snapshot the model was trained on (train/live parity); prior when no champion.
            conf = predict_candidate(c, feats=s.get("pit_features"))
            # MULTI-HEAD + SIMILARITY + EXPLANATION (advisory, absent models just don't vote)
            heads_out, sim_out, ml_explain = {}, s.get("similarity"), None
            try:
                if s.get("pit_features"):
                    from bot.ml.heads import predict_heads
                    heads_out = predict_heads(s["pit_features"])
                    from bot.ml.pipeline import explain_last_champion
                    ml_explain = explain_last_champion(s["pit_features"])
            except Exception:
                pass
            flow = orderflow_confirm(c)                       # order-flow confirmation (book-level; "no feed" live)
            rd = decide(c, Account(equity=equity, source_healthy=healthy))  # risk gate verdict (advisory)
            if persist:
                _journal.record(c); _store.record(c); _journal.record(rd); _store.record(rd)
            plan = (options_exit_plan(c, iv=iv_est, dte=0)
                    if (with_options and sym in EQUITY_OPT) else None)
            # ADVISORY sizing: how many units the risk budget buys (>=1 so futures show a real number)
            risk_per_unit = c.risk * a.point_value
            budget = equity * 0.0025
            qty = max(1, int(budget / risk_per_unit)) if risk_per_unit > 0 else 1
            # GRADE LADDER (user 2026-07-05 v2): ORMID arms; the extras grade CUMULATIVELY —
            # +VWAP = B · +STRUCT = A · +SLOPE = A+ (all three). No VWAP aligned = C.
            aligned = s.get("struct_aligned", False)
            wide = s.get("vol_expansion", False)             # still tagged for the dashboard/ML
            _sS = s.get("slope_S")
            slope_ok = _sS is not None and ((c.side.value == "long" and _sS >= 0.10) or
                                            (c.side.value == "short" and _sS <= -0.10))
            _pit = s.get("pit_features") or {}
            _av = _pit.get("above_vwap")
            vwap_ok = _av is not None and _av == _av and \
                ((c.side.value == "long") == bool(_av >= 0.5))
            if s["family"] == "breakout" and s["tradeable"] and s.get("asset_status") == "validated":
                grade = "A+" if (vwap_ok and aligned and slope_ok) else \
                        ("A" if (vwap_ok and aligned) else ("B" if vwap_ok else "C"))
            else:
                grade = "C"
            # GRADE-WEIGHTED SIZING: scale the base qty by conviction; skip B where its edge is negative.
            size_mult = GRADE_MULT.get(grade, 0.4)
            skip_reco = (grade == "B" and sym in B_SKIP_SYMBOLS) or grade == "C"
            conviction = ({"A+": "HIGHEST — size up (1.5x)", "A": "standard (1.0x)",
                           "B": ("SKIP — grade-B is negative on " + sym) if skip_reco else "low — size down (0.4x)",
                           "C": "info only — don't trade"}).get(grade, "")
            # F66 SIZING LADDER (ADOPTED, auto per side-of-edge): equity ladder assets take the UNCONFIRMED
            # break as a 0.4x STARTER (that cohort is +0.34R QQQ / +0.16R SPY) and go FULL when structure
            # confirms. Futures never reach here unconfirmed (binary trend gate). No cut-on-opposite (v2 rejected).
            tranche = "full"
            if a.ladder and s["family"] == "breakout" and s["tradeable"] and not aligned:
                tranche = "starter"
                size_mult, skip_reco = 0.4, False
                conviction = "STARTER 0.4x — unconfirmed break (F66 ladder); ADD to full when structure confirms"
            # F67 CLEAN-AIR (GRADUATED): a breakout into a WALL (MAJOR/STRONG zone within ~2 ATR ahead) is the
            # negative cohort — down-grade + recommend skip (discretion model; the gauntlet validated the drop).
            air_atr = None; air_ok = True
            if a.clean_air and s["family"] == "breakout" and s["tradeable"]:
                from bot.strategy.liquidity import clean_air_atr, CLEAN_AIR_ATR
                air_atr = clean_air_atr(_b1_today, c.entry, c.side.value, sym)
                if air_atr is not None and air_atr < CLEAN_AIR_ATR:
                    air_ok = False
                    grade = "B" if grade in ("A+", "A") else grade
                    size_mult = min(size_mult, 0.4)
                    skip_reco = True
                    conviction = f"SKIP — WALL: MAJOR/STRONG zone {air_atr:.1f} ATR ahead (F67 clean-air; that cohort is negative)"
            sized_qty = 0 if skip_reco else (max(1, round(qty * size_mult)) if size_mult > 0 else 0)
            # ENSEMBLE VERDICT (MLP-001 §10): rules emitted it, risk decided, AI grades confidence.
            try:
                from bot.ml.ensemble import decide_ensemble
                ai = decide_ensemble(rd.approved, ml_p=conf if isinstance(conf, float) else None,
                                     heads=heads_out, similarity=sim_out, grade=grade,
                                     nn_p=s.get("nn_seq"))
            except Exception:
                ai = None
            proposals.append({
                "symbol": sym, "source": src, "last_price": last_px, "price_source": px_src,
                "bar_age_min": age_min, "source_healthy": healthy,
                # ZONE STATE (staleness fix 2026-07): is the proposal still structurally valid at the
                # CURRENT price? invalid = price beyond the opposite OR edge (e.g. long, price < OR low);
                # watch = wrong side of OR mid; active = still on-side. UI + paper autotrade consume this.
                "or_high": s.get("or_high"), "or_low": s.get("or_low"),
                "signal_state": _zone_state(c.side.value, float(last_px or c.entry),
                                            s.get("or_high"), s.get("or_low")),
                # ENTRY STANDARD Layer 2 — slope QUALITY grade (A+..D) at the signal bar (5m frame);
                # dir_fast additionally carries the 1m-feed grade. Advisory + an ML/NN feature.
                "slope_grade": s.get("slope_grade"), "slope_S": s.get("slope_S"),
                "dir_fast": _dir_fast(_df_ctx, s.get("or_high"), s.get("or_low")),
                "mtf_direction": mtf_dir,          # rolling per-TF read (1m array); dir_fast = backup
                "family": s["family"], "status": s["status"],
                "tradeable": s["tradeable"], "asset_status": s.get("asset_status", "?"),
                "grade": grade, "struct_aligned": aligned, "vol_expansion": wide, "tranche": tranche,
                "air_atr": (None if air_atr is None else (999.0 if air_atr == float("inf") else round(air_atr, 1))),
                "clean_air": air_ok,
                "or_width_atr": s.get("or_width_atr"),
                "session": s.get("session"), "bars_ago": s["bars_ago"],
                "side": c.side.value, "entry": c.entry, "stop": c.stop,
                "tp1": (plan["underlying"]["tp1"] if plan else round(c.entry + c.side.sign * 1.5 * c.risk, 2)),
                "tp2": (plan["underlying"]["tp2"] if plan else round(c.entry + c.side.sign * 4.0 * c.risk, 2)),
                "rr": round(c.rr, 2), "confidence": conf, "orderflow": flow, "features": feats, "iv_est": iv_est,
                "heads": heads_out or None, "ai_decision": ai, "ml_explain": ml_explain,
                "nn_seq": s.get("nn_seq"), "similarity": sim_out,
                # KELLY (advisory, quarter-Kelly of the risk budget): P(win) from the champion/prior,
                # payoff b from the symbol's backtest matrix when available (fallback 4R-cap profile)
                "kelly": _kelly_advice(sym, conf),
                "suggested_qty": qty, "risk_per_unit": round(risk_per_unit, 2),
                "risk_pct": round(100 * qty * risk_per_unit / equity, 2),
                "size_mult": size_mult, "sized_qty": sized_qty, "conviction": conviction,
                "skip_reco": skip_reco,
                "risk_pct_sized": round(100 * sized_qty * risk_per_unit / equity, 2),
                "risk_ok": rd.approved, "risk_reason": rd.reason_code.value,
                "timeframe": tf,                   # journal->training-lab tf tag (5m / 15m lineages)
                # BAR IDENTITY (journal fix 2026-07-07): the candidate's id + SIGNAL-BAR time ride
                # with the proposal — without them the autotrack dedup key degenerated to one row
                # per (sym,family,session,side,tf) EVER and signal_at was NULL, so outcomes never
                # resolved (every journal row stuck 'open'). This one field feeds both.
                "candidate": {"candidate_id": c.candidate_id, "generated_at": c.generated_at},
                "options": plan})
    return proposals


def run(symbols: list[str]) -> None:
    props = scan_watchlist(symbols)
    actionable = [p for p in props if p.get("tradeable") and p.get("asset_status") == "validated"]
    print(f"\n=== HIGHSTRIKE SIGNAL ENGINE — {len(props)} signals across the 4 families "
          f"({len(actionable)} validated/tradeable) · place trades manually ===")
    for p in props:
        if "error" in p:
            print(f"  {p['symbol']}: data error {p['error']}"); continue
        tag = "" if p["tradeable"] else " [INFO-ONLY]"
        if p.get("asset_status") == "unverified":
            tag += " [UNVERIFIED ASSET]"
        flow = p.get("orderflow", {})
        flowtxt = f" · flow {flow.get('note','').split(' (')[0]}" if flow.get("feed") else ""
        print(f"  [{p['family']:8} {p['status']:11}] {p['symbol']} {p['side'].upper()}  "
              f"entry {p['entry']} stop {p['stop']} TP1 {p['tp1']} TP2 {p['tp2']} · R:R {p['rr']} · "
              f"P(win) {p.get('confidence')} · ~{p['suggested_qty']} units · src {p['source']}{flowtxt}{tag}")
        if p.get("options"):
            rec = p["options"]["recommended"]
            s = p["options"]["structures"][rec]
            print(f"        options -> {rec.upper()}: {' / '.join(s['legs'])}  cost ${s['cost_or_credit_usd']}  "
                  f"exit {s['exit']['target']}")
    if not props:
        print("  (no active family signals on the latest bars)")


def loop(symbols: list[str], interval_min: float = 5.0) -> None:
    """Keep scanning the watchlist every `interval_min` (the system 'always looking')."""
    print(f"HIGHSTRIKE live loop — scanning {symbols} every {interval_min}m (Ctrl-C to stop)")
    while True:
        try:
            run(symbols)
        except KeyboardInterrupt:
            print("stopped"); return
        except Exception as e:
            print(f"scan error: {e}")
        time.sleep(interval_min * 60)


if __name__ == "__main__":
    args = sys.argv[1:]
    if args and args[0] == "loop":
        loop(args[1:] or WATCHLIST, 5.0)
    else:
        run(args or WATCHLIST)
