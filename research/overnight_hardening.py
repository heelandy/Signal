"""Overnight-drift HARDENING battery — promotion needs the edge to survive 2x cost AND stay alive in
the recent regime. Also probes conditioning (prior-day sign, weekday) for a stronger cut.

  1x / 2x cost     : does a ~0.03%/night edge survive doubled slippage?
  2022-2026        : is it still alive in the recent regime (not a pre-2018 relic)?
  after DOWN / UP  : the drift is stronger after weak closes? (a conditioning lever)
  Mon / non-Mon    : weekend-gap concentration?

    python research/overnight_hardening.py [SYM ...]   (default QQQ SPY NQ)
"""
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "engine"))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import numpy as np, pandas as pd
import hs_db
from strat_daily import load, cost_pct, atr, report


def stream(d, cost_mult=1.0, cond=None, since=None):
    o, c = d["open"].to_numpy(), d["close"].to_numpy()
    a, dt, sym = atr(d), d["dt"], d.attrs["sym"]
    tr = []
    for i in range(1, len(c) - 1):
        if since is not None and dt.iloc[i] < since:
            continue
        if cond is not None and not cond(c, dt, i):
            continue
        e, x = c[i], o[i + 1]
        ret = (x - e) / e - cost_mult * cost_pct(sym, e)
        tr.append((dt.iloc[i], 1, ret, (x - e) / a[i] if a[i] > 0 else 0.0))
    return tr


def main():
    syms = [s.upper() for s in (sys.argv[1:] or ["QQQ", "SPY", "NQ"])]
    since22 = pd.Timestamp("2022-01-01", tz="UTC")
    con = hs_db.connect()
    for sym in syms:
        d = load(con, sym); d.attrs["sym"] = sym
        print(f"\n######## {sym} — overnight drift hardening ########")
        report("1x cost", stream(d, 1.0))
        report("2x cost", stream(d, 2.0))                                   # <-- the real test
        report("2022-26 (1x)", stream(d, 1.0, since=since22))
        report("2022-26 (2x)", stream(d, 2.0, since=since22))
        report("after DOWN day", stream(d, 1.0, cond=lambda c, dt, i: c[i] < c[i - 1]))
        report("after UP day",   stream(d, 1.0, cond=lambda c, dt, i: c[i] > c[i - 1]))
        report("Monday only",    stream(d, 1.0, cond=lambda c, dt, i: dt.iloc[i].dayofweek == 0))
        report("non-Monday",     stream(d, 1.0, cond=lambda c, dt, i: dt.iloc[i].dayofweek != 0))
    con.close()
    print("\nPROMOTE if: 2x-cost PASS AND 2022-26 positive. Conditioning cuts are upside, not required.")


if __name__ == "__main__":
    main()
