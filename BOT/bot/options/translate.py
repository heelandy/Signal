"""Attach the options translation to an ORB signal (TradeCandidate) — the bridge the user reads.

The system PROPOSES: for each signal it shows the equity plan + the three options structures
(naked / debit / credit, real premium & Greeks). The user takes it at their discretion.
"""
from __future__ import annotations

import pandas as pd

from bot.contracts import TradeCandidate
from bot.options.pricing import year_frac
from bot.options.strategies import signal_to_options


def _t_years(generated_at: str | None, dte: int) -> float:
    """0DTE → minutes to 16:00 ET (theta-real); else dte trading days + the intraday remainder."""
    mins_left = 60.0
    if generated_at:
        t = pd.Timestamp(generated_at)
        t = t.tz_convert("America/New_York") if t.tz else t.tz_localize("America/New_York")
        close = t.normalize() + pd.Timedelta(hours=16)
        mins_left = max((close - t).total_seconds() / 60.0, 5.0)
    return year_frac(mins_left) + dte / 365.0


def chain_price_fn(date: str, minute_et: str, root: str = "QQQ"):
    """Real OPRA-mid price_fn(K, right) from the local CBBO chain (QQQ only, slow ~60s/day).
    Returns None if the chain isn't available so the caller falls back to Black-Scholes."""
    try:
        from bot.market_data import databento_local as L
        ch = L.load_cbbo_day(date, root, minute_et=minute_et)
        if ch.empty:
            return None
        idx = {(round(float(s), 2), r): float(m) for s, r, m in zip(ch.strike, ch.right, ch.mid) if m == m}
        return lambda K, right: idx.get((round(float(K), 2), right), float("nan"))
    except Exception:
        return None


def options_for_candidate(c: TradeCandidate, iv: float = 0.20, dte: int = 0, sel_n: int = 1,
                          contracts: int = 1, use_chain: bool = False) -> dict:
    """Return {underlying signal, options:{naked,debit,credit}} for a candidate."""
    S = c.entry
    tp1 = c.tp1 if c.tp1 is not None else c.entry + c.side.sign * c.risk     # 1R debit cap
    T = _t_years(c.generated_at, dte)
    price_fn = None
    if use_chain and c.symbol.upper() == "QQQ" and c.generated_at:
        price_fn = chain_price_fn(c.generated_at[:10], c.generated_at[11:16], "QQQ")
    plays = signal_to_options(c.side.value, c.entry, c.stop, tp1, c.tp2, S, iv, T,
                              sel_n=sel_n, contracts=contracts, price_fn=price_fn)
    return {
        "underlying": {"symbol": c.symbol, "side": c.side.value, "entry": c.entry,
                       "stop": c.stop, "tp1": round(tp1, 2), "tp2": c.tp2, "rr": round(c.rr, 2)},
        "expiry": f"0DTE entry, max {dte}-DTE hold" if dte else "0DTE",
        "iv_used": iv, "priced_from": "OPRA chain" if price_fn else "Black-Scholes estimate",
        "options": {k: {"name": p.name,
                        "legs": [f"{l.side} {l.right}{l.strike:g}@{l.price}" for l in p.legs],
                        "cost_or_credit_usd": p.cost_or_credit_usd,
                        "max_profit_usd": ("unlimited" if p.max_profit_usd == float("inf") else p.max_profit_usd),
                        "max_loss_usd": p.max_loss_usd, "breakeven": p.breakeven,
                        "net_delta": p.net_delta, "rr": p.rr, "note": p.note}
                    for k, p in plays.items()},
    }


if __name__ == "__main__":
    import json
    c = TradeCandidate(symbol="QQQ", side="long", timeframe="5m", setup="orb_stack",
                       entry=722.0, stop=719.0, tp1=725.0, tp2=734.0, strategy_version="t",
                       generated_at="2026-06-29T13:45:00+00:00")
    res = options_for_candidate(c, iv=0.18, dte=0, sel_n=1)
    print(json.dumps(res, indent=2)[:900])
    print("\noptions translate OK")
