#!/usr/bin/env python3
"""
HIGHSTRIKE F31b — robustness check on the regime-B finding (follow-up to orb_regimeb_entries.py).
Regime-B trades passed the full gate in all 3 sessions. Before recommending block_b=off:
  - IS (2009-2021) vs OOS (2022+) split of the B slice per session
  - 2x slippage stress (SLIP_TICKS 2 -> 4)
  - the combined "unblock B" config (prod trades + B trades together) vs production

    python research/orb_regimeb_oos.py
"""
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "engine"))
import numpy as np, pandas as pd
import hs_db, hs_harness as H, hs_backtest as B, hs_validate as V
from orb_optimize import state

rng = np.random.default_rng(7)
SESSIONS = [
    ("RTH",    570, 600, 900, False, 958),
    ("Asia",   60,  120, 540, True,  540),
    ("London", 540, 570, 840, True,  840),
]


def run(d, ors, ore, cut, tdy, eod):
    return B.backtest(d, "trail", "both", False, "orb", 0, 1.0, 4.0, ors, ore, 0.0, cut, "stop",
                      tradeday=tdy, eod_min=eod, vwap_cap=2.0, stop_mode="struct")


def loci(r):
    return np.percentile(rng.choice(r, (3000, len(r)), replace=True).mean(1), 5) if len(r) else 0.0


def report(tag, tr, min_n=20):
    if tr is None or len(tr) < min_n:
        print(f"    {tag:24} n={0 if tr is None else len(tr):>4}  (<{min_n} — no read)")
        return
    r = tr["net_R"].to_numpy()
    L = tr[tr.direction == "long"]["net_R"].to_numpy()
    S = tr[tr.direction == "short"]["net_R"].to_numpy()
    print(f"    {tag:24} n={len(r):>4} exp {r.mean():+.3f} PF {V.pf(r):>4.2f} win {100*np.mean(r>0):>2.0f}% "
          f"CI {loci(r):+.3f}  L {L.mean() if len(L) else 0:+.2f}({len(L)}) S {S.mean() if len(S) else 0:+.2f}({len(S)})")


def main():
    d = state("NQ", "5m")
    d2 = d.copy(deep=False)
    d2["macro_allow_trades"] = True
    d2.attrs.update(d.attrs)
    # "unblock B" config: allow B, keep blocking D (the actual proposed setting change)
    d3 = d.copy(deep=False)
    d3["macro_allow_trades"] = d["macro_allow_trades"].to_numpy() | (d["macro_regime"] == "B").to_numpy()
    d3.attrs.update(d.attrs)
    for name, ors, ore, cut, tdy, eod in SESSIONS:
        print(f"\n  {name}")
        tr_open = run(d2, ors, ore, cut, tdy, eod)
        trB = tr_open[tr_open.regime == "B"].copy()
        yr = pd.to_datetime(trB["entry_time"], utc=True).dt.tz_convert("America/New_York").dt.year
        report("B slice — IS 2009-21", trB[yr <= 2021])
        report("B slice — OOS 2022+", trB[yr >= 2022])
        report("prod (B+D blocked)", run(d, ors, ore, cut, tdy, eod))
        report("unblock B (keep D off)", run(d3, ors, ore, cut, tdy, eod))
        B.SLIP_TICKS = 4
        report("unblock B @ 2x slip", run(d3, ors, ore, cut, tdy, eod))
        B.SLIP_TICKS = 2


if __name__ == "__main__":
    main()
