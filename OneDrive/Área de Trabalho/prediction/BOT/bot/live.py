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
EQUITY_OPT = {"QQQ", "SPY"}          # Alpaca-tradeable options; GC options = futures-opts / GLD proxy


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
        last_px = round(float(bars["close"].iloc[-1]), 2)             # current price (last bar)
        last_ts = pd.Timestamp(bars["ts_et"].iloc[-1])
        age_min = int((pd.Timestamp.now(tz="America/New_York") - last_ts).total_seconds() / 60)
        a = asset_config(sym)
        try:
            from bot.features import feature_snapshot
            feats = feature_snapshot(bars)                            # FEE-001 context (RSI/ADX/vol/...)
        except Exception:
            feats = {}
        for s in families.scan(bars, sym, bars_back=bars_back):
            c = s["candidate"]
            conf = predict_candidate(c)                       # PREDICTIVE: P(win) from the champion (or prior)
            flow = orderflow_confirm(c)                       # order-flow confirmation (book-level; "no feed" live)
            rd = decide(c, Account(equity=equity, source_healthy=True))   # risk gate verdict (advisory)
            if persist:
                _journal.record(c); _store.record(c); _journal.record(rd); _store.record(rd)
            plan = (options_exit_plan(c, iv=0.20, dte=0)
                    if (with_options and sym in EQUITY_OPT) else None)
            # ADVISORY sizing: how many units the risk budget buys (>=1 so futures show a real number)
            risk_per_unit = c.risk * a.point_value
            budget = equity * 0.0025
            qty = max(1, int(budget / risk_per_unit)) if risk_per_unit > 0 else 1
            proposals.append({
                "symbol": sym, "source": src, "last_price": last_px, "bar_age_min": age_min,
                "family": s["family"], "status": s["status"],
                "tradeable": s["tradeable"], "asset_status": s.get("asset_status", "?"),
                "session": s.get("session"), "bars_ago": s["bars_ago"],
                "side": c.side.value, "entry": c.entry, "stop": c.stop,
                "tp1": (plan["underlying"]["tp1"] if plan else round(c.entry + c.side.sign * 1.5 * c.risk, 2)),
                "tp2": (plan["underlying"]["tp2"] if plan else round(c.entry + c.side.sign * 4.0 * c.risk, 2)),
                "rr": round(c.rr, 2), "confidence": conf, "orderflow": flow, "features": feats,
                "suggested_qty": qty, "risk_per_unit": round(risk_per_unit, 2),
                "risk_pct": round(100 * qty * risk_per_unit / equity, 2),
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
