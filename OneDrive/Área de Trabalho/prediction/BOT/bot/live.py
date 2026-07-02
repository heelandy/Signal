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
                   bars_back: int = 2, with_options: bool = True, persist: bool = True) -> list[dict]:
    """Signal-engine scan: data -> 4 families -> P(win) -> order-flow -> options exit-plan. No trades."""
    proposals = []
    for sym in symbols:
        sym = sym.upper()
        try:
            bars = get_bars(sym, "5m", period="5d", provider=provider)
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
        # IV estimate from realized vol (5m log-returns annualized) so options price WITHOUT manual input
        import numpy as _np
        _cl = bars["close"].to_numpy(float)[-120:]
        _ret = _np.diff(_np.log(_cl)) if len(_cl) > 6 else _np.array([0.0])
        iv_est = round(float(_np.clip(_np.std(_ret) * (252 * 78) ** 0.5, 0.10, 0.80)), 3) if len(_ret) > 5 else 0.20
        for s in families.scan(bars, sym, bars_back=bars_back):
            c = s["candidate"]
            conf = predict_candidate(c)                       # PREDICTIVE: P(win) from the champion (or prior)
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
            # GRADE = 2-D quality on the two validated, ADDITIVE conditioners (F20 structure + vol-expansion).
            #   A+ = core breakout, HH/HL structure-aligned AND wide opening range (vol-expansion) — the best
            #        cohort (+0.45-0.51R: aligned&wide on QQQ/SPY). A = one of the two. B = neither (narrow &
            #        unaligned = the dead cohort). C = info-only family or unverified asset.
            aligned = s.get("struct_aligned", False)
            wide = s.get("vol_expansion", False)
            if s["family"] == "breakout" and s["tradeable"] and s.get("asset_status") == "validated":
                grade = "A+" if (aligned and wide) else ("A" if (aligned or wide) else "B")
            else:
                grade = "C"
            # GRADE-WEIGHTED SIZING: scale the base qty by conviction; skip B where its edge is negative.
            size_mult = GRADE_MULT.get(grade, 0.4)
            skip_reco = (grade == "B" and sym in B_SKIP_SYMBOLS) or grade == "C"
            sized_qty = 0 if skip_reco else (max(1, round(qty * size_mult)) if size_mult > 0 else 0)
            conviction = ({"A+": "HIGHEST — size up (1.5x)", "A": "standard (1.0x)",
                           "B": ("SKIP — grade-B is negative on " + sym) if skip_reco else "low — size down (0.4x)",
                           "C": "info only — don't trade"}).get(grade, "")
            proposals.append({
                "symbol": sym, "source": src, "last_price": last_px, "price_source": px_src,
                "bar_age_min": age_min, "source_healthy": healthy,
                "family": s["family"], "status": s["status"],
                "tradeable": s["tradeable"], "asset_status": s.get("asset_status", "?"),
                "grade": grade, "struct_aligned": aligned, "vol_expansion": wide,
                "or_width_atr": s.get("or_width_atr"),
                "session": s.get("session"), "bars_ago": s["bars_ago"],
                "side": c.side.value, "entry": c.entry, "stop": c.stop,
                "tp1": (plan["underlying"]["tp1"] if plan else round(c.entry + c.side.sign * 1.5 * c.risk, 2)),
                "tp2": (plan["underlying"]["tp2"] if plan else round(c.entry + c.side.sign * 4.0 * c.risk, 2)),
                "rr": round(c.rr, 2), "confidence": conf, "orderflow": flow, "features": feats, "iv_est": iv_est,
                "suggested_qty": qty, "risk_per_unit": round(risk_per_unit, 2),
                "risk_pct": round(100 * qty * risk_per_unit / equity, 2),
                "size_mult": size_mult, "sized_qty": sized_qty, "conviction": conviction,
                "skip_reco": skip_reco,
                "risk_pct_sized": round(100 * sized_qty * risk_per_unit / equity, 2),
                "risk_ok": rd.approved, "risk_reason": rd.reason_code.value,
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
