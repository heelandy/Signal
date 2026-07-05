"""The 4 standing strategy families the system always scans (F62).

Until more research expands the set, these are it — each tagged with its validated status so the
system (and the user, at their discretion) knows how much to trust a signal:

  1. breakout / vol-expansion  — VALIDATED on NQ + QQQ + SPY (the core edge)
  2. trend / momentum          — validated EQUITY-ONLY (QQQ/SPY); a selectivity filter, ~0 additive net
  3. structure / order-flow    — validated EQUITY-ONLY (QQQ/SPY) SMC order-block; also a filter
  4. mean-reversion / fade     — NEGATIVE expectancy (F18/F53/F62) — scanned for context, DO NOT trade

`scan(bars_df)` runs all four on a router-provided bar frame and returns any signal active on the
latest bar (with entry/stop/tp), tagged by family. The live loop attaches options + risk to each.
"""
from __future__ import annotations

import os
import sys
from dataclasses import dataclass

import numpy as np
import pandas as pd

from bot.config import BOT_ROOT
sys.path.insert(0, str(BOT_ROOT.parent / "engine"))

from bot.contracts import Session

ORS, ORE, CUT, DELAY, SB = 570, 600, 900, 60, 0.25
T1_RR, T2_RR = 1.5, 4.0      # F64 (2026-06-29): 1.5R is the best scale point (beats 1.0R); 4R is the cap knee
OR_WIDTH_WIDE = 2.4          # vol-expansion conditioner: OR-width/ATR >= this = wide open (graduated 2026-07,
                             # narrow-OR third is dead; robust q20-q50; +49-64% exp NQ/QQQ/SPY RTH, additive to HH/HL)


@dataclass
class Family:
    key: str
    name: str
    status: str                 # "validated" | "equity_only" | "negative"
    gate: str                   # "none" | "trend"
    execm: str                  # "close" | "stop" | "fade" | "sweepgo"
    ob: bool = False
    tradeable: bool = True


FAMILIES = [
    # STRUCTURE-AS-GRADE (user 2026-07-03, latency-backed): the breakout fires WITHOUT a hard structure gate —
    # HH/HL structure LAGS (median 40-50 min behind OR/VWAP/SLOPE agreement) so gating it MISSES clean breakouts
    # that ran past the OR. Direction is still gated by OR-mid bias + dir-sequence (validated +0.164R NQ). st_state
    # alignment drives the GRADE (A+/A/B) + GRADE_MULT size (unconfirmed=B=0.4x, confirmed=A/A+=full/1.5x = scale-in),
    # NOT a veto. Matches the STACK Pine default (trend gate Off). Set gate="trend" to REQUIRE structure again.
    Family("breakout", "breakout / vol-expansion", "validated", "none", "close"),
    Family("trend", "trend / momentum", "equity_only", "trend", "close"),
    Family("smc", "structure / order-flow (SMC OB)", "equity_only", "trend", "close", ob=True),
    Family("meanrev", "mean-reversion / range-fade", "negative", "none", "fade", tradeable=False),
]


_MACRO_CACHE: dict = {}     # {"date": iso, "df": daily frame} — one SPY/^VIX fetch per day


def _macro_daily() -> pd.DataFrame | None:
    """SPY + VIX daily externals for the harness macro regime — the engine `_externals` twin on live
    data (yfinance): spy_close/e20/e50/adx + vix_sma5/vix_prev5 keyed by ET date. Cached for the day;
    any failure returns None (caller falls back to the permissive gates — live must never break)."""
    import datetime as _dt
    import hs_harness as H
    today = _dt.date.today().isoformat()
    if _MACRO_CACHE.get("date") == today:
        return _MACRO_CACHE.get("df")
    try:
        import yfinance as yf
        spy = yf.download("SPY", interval="1d", period="1y", progress=False, auto_adjust=True)
        vix = yf.download("^VIX", interval="1d", period="1y", progress=False, auto_adjust=True)
        if spy.empty or vix.empty:
            raise ValueError("empty SPY/VIX download")
        for f in (spy, vix):
            if isinstance(f.columns, pd.MultiIndex):
                f.columns = f.columns.get_level_values(0)
        out = pd.DataFrame(index=spy.index)
        out["spy_close"] = spy["Close"].astype(float)
        out["spy_e20"] = H.ema(out["spy_close"], 20)
        out["spy_e50"] = H.ema(out["spy_close"], 50)
        _, _, out["spy_adx"] = H.dmi(spy["High"].astype(float), spy["Low"].astype(float), out["spy_close"], 14, 14)
        vc = vix["Close"].astype(float).reindex(out.index).ffill()
        out["vix_sma5"] = vc.rolling(5).mean()
        out["vix_prev5"] = vc.shift(5)
        out["date"] = pd.to_datetime(out.index).normalize().tz_localize(None)
        out = out.reset_index(drop=True)
        _MACRO_CACHE.update(date=today, df=out)
        return out
    except Exception:
        _MACRO_CACHE.update(date=today, df=None)     # don't retry every scan on a dead feed
        return None


def prepare(bars: pd.DataFrame, sym: str = "") -> pd.DataFrame:
    """Router bar frame (ts_et, ohlcv) -> engine harness-state frame."""
    import hs_harness as H
    from .asset_config import struct_lb
    df = bars.rename(columns={"ts_et": "ts"}).copy()
    df["ts"] = pd.to_datetime(df["ts"], utc=True)
    for col in ("open", "high", "low", "close"):
        df[col] = df[col].astype(float)
    df["volume"] = df.get("volume", 0).astype("float64")
    # STACK-IDENTITY (user 2026-07-03): merge live SPY/VIX daily externals so compute_state produces the
    # REAL macro regime gates (regime D block + SPY stand-down), matching the STACK Pine's Regime group.
    m = _macro_daily()
    if m is not None:
        df["date"] = df["ts"].dt.tz_convert("America/New_York").dt.normalize().dt.tz_localize(None)
        df = df.merge(m[["date", "spy_close", "spy_e20", "spy_e50", "spy_adx", "vix_sma5", "vix_prev5"]],
                      on="date", how="left")
    d = H.compute_state(df, H.P(struct_lb_fix=struct_lb(sym)) if sym else H.P())   # futures lb=3 / equity lb=5
    # feed unavailable -> permissive gates (previous behavior; breakout core doesn't need them)
    for c, v in {"macro_allow_trades": True, "macro_long_ok": True, "macro_short_ok": True,
                 "local_regime": 0}.items():
        if c not in d.columns:
            d[c] = v
    return d


def _levels(d, i, sign, min_stop_atr=0.75, sl_max_atr=2.5):
    """Struct-anchored stop + capped-TP2 at bar i (mirrors the engine).
    min_stop_atr = per-asset min-stop floor (F51): futures 0.5, equity 0.75.
    sl_max_atr  = per-asset MAX stop width (reversal cap): equity 1.5 (tight), futures 2.5 (room).
    Both must match asset_config, else BOT stops differ from the engine/Pine (live != backtest)."""
    import hs_backtest as B
    entry = float(d["close"].iloc[i]); atr = float(d["atr14"].iloc[i])
    spl = d["spl"].iloc[i] if "spl" in d else np.nan
    sph = d["sph"].iloc[i] if "sph" in d else np.nan
    anc = (spl if sign == 1 else sph)
    if anc != anc:  # nan -> OR edge fallback handled in engine; use a 1.5ATR stop here
        anc = entry - sign * 1.5 * atr
    raw = anc - sign * atr * B.SL_BUF_ATR
    stop = (min(max(raw, entry - atr * sl_max_atr), entry - atr * min_stop_atr) if sign == 1
            else max(min(raw, entry + atr * sl_max_atr), entry + atr * min_stop_atr))
    risk = abs(entry - stop)
    return round(entry, 2), round(stop, 2), round(entry + sign * risk * T1_RR, 2), round(entry + sign * risk * T2_RR, 2)


def fast_state_1m(d5: pd.DataFrame, bars_1m: pd.DataFrame, sym: str) -> np.ndarray:
    """1-MINUTE structure state CAUSALLY aligned onto the 5m frame (Python twin of the Pine
    `fast_dir` request.security feed): for each 5m bar, take the st_state of the LAST 1m bar
    INSIDE that 5m bar — known exactly at the 5m bar's close, never later (no look-ahead).
    Bars before 1m coverage return NaN (caller falls back to the chart-TF state there)."""
    d1 = prepare(bars_1m, sym)
    t1 = pd.to_datetime(d1["ts"], utc=True)
    # 5m ts = bar OPEN; the last 1m bar inside opens at +4 min and closes AT the 5m close
    t5 = pd.to_datetime(d5["ts"], utc=True) + pd.Timedelta(minutes=4)
    m = pd.merge_asof(pd.DataFrame({"ts": t5.to_numpy()}),
                      pd.DataFrame({"ts": t1.to_numpy(), "st": d1["st_state"].to_numpy(float)}),
                      on="ts", direction="backward")
    return m["st"].to_numpy(float)


def scan(bars: pd.DataFrame, symbol: str, bars_back: int = 2, bars_1m: pd.DataFrame | None = None) -> list[dict]:
    """Run all 4 families with the symbol's PER-ASSET config; signals active in the last `bars_back` bars.
    bars_1m (optional): 1m frame for the SAME symbol — the trend gate + struct_aligned grade then read
    the 1-MINUTE structure (staleness fix 2026-07, mirrors the Pine fast_dir input); stop geometry
    stays on the 5m swings. Without it, behavior is unchanged (chart-TF structure)."""
    import hs_backtest as B
    from bot.contracts import TradeCandidate
    from bot.strategy.asset_config import asset_config
    from bot.strategy.orb_state import ENTRY_STANDARD as ES, slope_engine, slope_grade
    a = asset_config(symbol)                       # per-asset: entry_delay, OR window, status
    d = prepare(bars, symbol)                       # futures lb=3 / equity lb=5 structure speed
    n = len(d)
    # STRUCTURE from the 1-MINUTE frame (user 2026-07-03: struct must come from 1m for SPEED — on higher TFs
    # it lags OR/VWAP/SLOPE, and THAT latency is the problem). The 1m st_state is aligned causally onto the
    # entry frame; chart-TF is the fallback where 1m has no coverage. Entry TIMING stays on the entry frame
    # (5m primary); this only speeds up the DIRECTION read. IMPLEMENTATION stays until judged live.
    st = d["st_state"].to_numpy() if "st_state" in d else np.zeros(n)
    if bars_1m is not None and len(bars_1m) >= 30:
        try:
            _fast = fast_state_1m(d, bars_1m, symbol)
            st = np.where(np.isnan(_fast), st, _fast).astype(int)   # 1m structure where covered, else chart-TF
        except Exception:
            pass                                    # 1m feed is best-effort — never break the scan
    atr = d["atr14"].to_numpy()
    out = []
    sess_enum = {"rth": Session.RTH, "asia": Session.ASIA, "london": Session.LONDON}
    cl_arr = d["close"].to_numpy(float)
    op_arr = d["open"].to_numpy(float)
    vw_arr = d["vwap_sess"].to_numpy(float) if "vwap_sess" in d else None
    _et_all = pd.to_datetime(d["ts"]).dt.tz_convert("America/New_York")
    mins_all = (_et_all.dt.hour * 60 + _et_all.dt.minute).to_numpy()
    for fam in FAMILIES:
        # ENTRY STANDARD Layer 1 — MARKET CONTEXT, per-asset PAIR (DIR-FAST A, user 2026-07-05):
        #   mid_vwap    = OR-MID side (enforced by the watch machine) + VWAP side — the NEW standard;
        #                 structure + slope no longer gate, they GRADE (struct = A+, slope = A).
        #   struct_vwap = the previous standard (fallback B): 1m-fed structure + VWAP side.
        #   none        = plain ORB arming.
        # The pairs test (research/dirfast_pairs.py) decides per symbol; ES.ctx_gate=False forces none.
        from bot.strategy.asset_config import resolve_ctx_mode
        mode = resolve_ctx_mode(a) if ES.ctx_gate else "none"
        if fam.key == "breakout" and vw_arr is not None and mode == "mid_vwap":
            with np.errstate(invalid="ignore"):
                d["trend_up"] = cl_arr > vw_arr
                d["trend_down"] = cl_arr < vw_arr
        elif fam.key == "breakout" and vw_arr is not None and mode == "struct_vwap":
            with np.errstate(invalid="ignore"):
                d["trend_up"] = (st == 1) & (cl_arr > vw_arr)
                d["trend_down"] = (st == 2) & (cl_arr < vw_arr)
        else:
            d["trend_up"] = (st == 1) if fam.gate == "trend" else True
            d["trend_down"] = (st == 2) if fam.gate == "trend" else True
        obl = d["in_bull_ob"].shift(1).fillna(False).to_numpy().astype(bool) if (fam.ob and "in_bull_ob" in d) else None
        obs = d["in_bear_ob"].shift(1).fillna(False).to_numpy().astype(bool) if (fam.ob and "in_bear_ob" in d) else None
        cl = fam.execm == "close"
        for sname, or_s, or_e, cut, tradeday in a.sessions:        # futures = 3 sessions, equity = 1
            # re-test/re-entry ON for tradeable breakouts so up to max_entries/session show (user spec); the
            # grade (B/A/A+) flags quality so weak re-entries are visible as B. STACK-IDENTITY (user 2026-07-03):
            # the breakout family FILTERS narrow-OR (min_or_width=2.4, the graduated vol-expansion filter) exactly
            # like the STACK Pine (volexp_filter ON) — same signal set on both surfaces. Info families stay 0.
            reentry = fam.tradeable
            vx = OR_WIDTH_WIDE if fam.key == "breakout" else 0.0
            # ENTRY STANDARD Layer 3 (canonical docs 2026-07-04) on the close-confirm families:
            # live WATCH at the OR mid + cooldown after a watch cancel + stale/RANGE rule + the
            # PULLBACK retest (don't chase an extended break). Mirrors the Pine + orb_state FSM.
            lsig, ssig, or_lo, or_hi, *_ = B._orb_signals(d, or_s, or_e, 0.0, cut, fam.execm, tradeday, reentry,
                                            ob_l=obl, ob_s=obs, entry_delay=a.entry_delay, chase_atr=a.chase_atr,
                                            strong_body=(SB if cl else 0.0), ft_confirm=cl, dir_seq=cl,
                                            max_entries=a.max_entries,
                                            # LIVE mid supersedes the FROZEN day bias on mid-armed
                                            # assets (user screenshots 2026-07-05: 'OR-mid: short
                                            # day' blocked a live-aligned long)
                                            or_mid_bias=(fam.key == "breakout" and
                                                         mode not in ("mid_vwap", "mid_only")),
                                            min_or_width=vx,
                                            instant_aligned=(fam.key == "breakout" and a.instant_fill),
                                            watch_live=(cl and ES.watch_gate),
                                            cooldown_bars=a.cooldown_bars if a.cooldown_bars is not None else ES.cooldown_bars,
                                            stale_bars=a.stale_bars if a.stale_bars is not None else ES.stale_bars,
                                            retest_atr=a.retest_atr if a.retest_atr is not None else ES.retest_atr,
                                            retest_mode=ES.retest_mode,
                                            min_pullback_atr=ES.min_pullback_atr,
                                            pullback_timeout=ES.pullback_timeout,
                                            vol_confirm_x=ES.vol_confirm_x)
            for i in range(max(0, n - bars_back), n):
                sign = 1 if lsig[i] else (-1 if ssig[i] else 0)
                if sign == 0:
                    continue
                e, s, t1, t2 = _levels(d, i, sign, a.min_stop_atr, a.sl_max_atr)
                # F20 (graduated): production gates ≤5m breakouts by HH/HL swing structure (st_state).
                # We don't hard-filter (discretion model) — we TAG alignment so the dashboard can grade it.
                aligned = bool((sign == 1 and st[i] == 1) or (sign == -1 and st[i] == 2))
                # vol-expansion conditioner (graduated): width of the opening range / ATR. Narrow OR = dead.
                orw = (float(or_hi[i] - or_lo[i]) / atr[i]) if (atr[i] and not np.isnan(or_hi[i])) else np.nan
                vol_exp = bool(orw == orw and orw >= OR_WIDTH_WIDE)
                # ENTRY STANDARD Layer 2 — slope QUALITY grade (A+..D) at the signal bar: grades the
                # setup along the trade direction, never gates it; stored as an ML/NN feature.
                eng = slope_engine(op_arr[max(0, i - 11):i + 1], cl_arr[max(0, i - 11):i + 1],
                                   float(atr[i]) if atr[i] == atr[i] else 0.0)
                sgrade = slope_grade(eng["S"], eng["persistence"], eng["efficiency"],
                                     side=("long" if sign == 1 else "short"))
                # PIT feature snapshot at the signal bar — the SAME function the ML dataset builder
                # uses, so the live model scores exactly what it was trained on (train/live parity).
                try:
                    from bot.ml.features_pit import pit_features
                    pit = pit_features(d, i, "long" if sign == 1 else "short", entry=e, stop=s,
                                       orh=float(or_hi[i]) if or_hi[i] == or_hi[i] else None,
                                       orl=float(or_lo[i]) if or_lo[i] == or_lo[i] else None,
                                       mins_of_day=float(mins_all[i]), or_e=or_e, rr=T2_RR,
                                       symbol=symbol)
                except Exception:
                    pit = None
                # LIVE SIMILARITY (advisory): nearest historical pattern cluster for this setup's
                # 64-bar window — scored here (only the result rides on the proposal; None when no
                # fitted clusters or not enough bars).
                sim = None
                try:
                    if i >= 63:
                        from bot.nn.dataset import _bar_channels
                        from bot.nn.similarity import similarity_score
                        M = _bar_channels(d, or_hi, or_lo)
                        seq = M[i - 63:i + 1].copy()
                        if sign == -1:                      # mirror shorts onto the long frame
                            seq[:, 0] *= -1; seq[:, 1] *= -1; seq[:, 5] *= -1; seq[:, 6] *= -1
                            seq[:, [7, 8]] = seq[:, [8, 7]]
                            seq[:, [2, 3]] = seq[:, [3, 2]]
                        sim = similarity_score(seq)
                except Exception:
                    sim = None
                ts = pd.Timestamp(d["ts"].iloc[i]); gen = ts.tz_convert("UTC").isoformat()
                try:
                    c = TradeCandidate(symbol=symbol, side=("long" if sign == 1 else "short"), timeframe="5m",
                                       setup=fam.key, entry=e, stop=s, tp1=t1, tp2=t2,
                                       strategy_version=f"{fam.key}-f62", session=sess_enum.get(sname, Session.RTH),
                                       generated_at=gen)
                    out.append({"family": fam.key, "status": fam.status, "tradeable": fam.tradeable,
                                "asset_status": a.status, "asset_note": a.note, "session": sname,
                                "bars_ago": n - 1 - i, "struct_aligned": aligned,
                                "slope_grade": sgrade, "slope_S": eng["S"], "pit_features": pit,
                                "similarity": sim,
                                "vol_expansion": vol_exp, "or_width_atr": round(orw, 2) if orw == orw else None,
                                # OR levels at the signal bar — the zone state machine (orb_state)
                                # uses these to invalidate a stale proposal at the CURRENT price
                                "or_high": round(float(or_hi[i]), 2) if or_hi[i] == or_hi[i] else None,
                                "or_low": round(float(or_lo[i]), 2) if or_lo[i] == or_lo[i] else None,
                                "candidate": c})
                except ValueError:
                    pass
    return out


if __name__ == "__main__":   # scan live router data for the 4 families
    sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
    from bot.market_data.providers import get_bars
    for sym in ("SPY", "QQQ"):
        bars = get_bars(sym, "5m", period="5d")
        sigs = scan(bars, sym, bars_back=80)        # scan recent bars to show it finds setups
        print(f"{sym} ({bars.attrs.get('provider')}, {len(bars)} bars): {len(sigs)} family signals in last 80 bars")
        for s in sigs[-4:]:
            c = s["candidate"]
            print(f"   [{s['family']:8} {s['status']:11}] {c.side.value} {c.entry}/{c.stop}/{c.tp2} "
                  f"R:R {c.rr:.1f} {c.generated_at[:16]} {'' if s['tradeable'] else '(info only)'}")
    print("\n4-family registry OK — breakout=core, trend/smc=equity filters, meanrev=info-only")
