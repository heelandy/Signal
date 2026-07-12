#!/usr/bin/env python3
"""
HIGHSTRIKE F32b — robustness on the two marginal 1m passers from orb_1m.py:
RTH OR 09:30-09:35 (+0.145R CI +0.06) and London OR 03:00-03:05 (+0.159R CI +0.02).
IS/OOS split + 2x and 3x slippage. The std windows already died on 1m; these two only
survive if they hold OOS and at 2x slip (the user gate before any further 1m testing).

    python research/orb_1m_robust.py
"""
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "engine"))
import numpy as np, pandas as pd
import hs_db, hs_harness as H, hs_backtest as B, hs_validate as V
from orb_1m import state_1m, run, report

CASES = [
    ("RTH 09:30-09:35",    570, 575, 900, False, 958),
    ("London 03:00-03:05", 540, 545, 840, True,  840),
]


def main():
    d = state_1m()
    print(f"NQ 1m — {len(d):,} bars. F32b robustness on the two marginal 1m windows.\n")
    for name, ors, ore, cut, tdy, eod in CASES:
        print(f"\n  {name}")
        tr = run(d, ors, ore, cut, tdy, eod)
        yr = pd.to_datetime(tr["entry_time"], utc=True).dt.tz_convert("America/New_York").dt.year
        report("full sample", tr)
        report("IS 2010-21", tr[yr <= 2021])
        report("OOS 2022+", tr[yr >= 2022], min_n=20)
        B.SLIP_MULT = 2.0
        report("2x slip", run(d, ors, ore, cut, tdy, eod))
        B.SLIP_MULT = 3.0
        report("3x slip", run(d, ors, ore, cut, tdy, eod))
        B.SLIP_MULT = 1.0


if __name__ == "__main__":
    main()
