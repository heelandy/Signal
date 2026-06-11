#!/usr/bin/env python3
"""
HIGHSTRIKE F25 — exit/risk levers on the NQ 5m stack (the last UNTESTED scorecard row).
(a) STOP placement: OR-edge anchor (production) vs STRUCTURE-anchor (last HH/HL swing) vs a tighter
    ATR cap. Tighter risk → fewer points risked → higher R if win-rate survives.
(b) VOL-scaled reward: does the optimal TP2 differ in high- vs low-vol regimes? F7 says >4R is a tail
    trap ON AVERAGE — maybe not in high volatility. Causal split on prior-bar atr_pct vs its rolling median.
Off-by-default engine hooks: stop_mode="struct" (uses harness sph/spl), skip_mask (regime isolation).

    python research/orb_exit_levers.py
"""
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "engine"))
import numpy as np, pandas as pd
import hs_db, hs_harness as H, hs_backtest as B, hs_validate as V
from orb_optimize import state, metrics


def setgate(d):
    st = d["st_state"].to_numpy(); d["trend_up"] = st == 1; d["trend_down"] = st == 2


def run(d, tp2=4.0, stop_mode="or", skip=None):
    return B.backtest(d, "scale_be", "both", False, "orb", 0, 1.0, tp2, 570, 600, 0.0, 900, "stop",
                      eod_min=958, vwap_cap=2.0, skip_mask=skip, stop_mode=stop_mode)


def line(tag, tr):
    m = metrics(tr)
    if m is None:
        print(f"  {tag:22} <30 trades"); return
    rp = tr["risk_pts"].mean()
    print(f"  {tag:22} n={m['n']:>4} exp {m['exp']:+.3f} PF {m['pf']:>4.2f} CI {m['loCI']:+.3f} "
          f"both={'Y' if m['both'] else 'n'} avg-risk {rp:5.1f}pts")


def main():
    d = state("NQ", "5m"); setgate(d)
    print("F25 exit/risk levers — NQ 5m STACK (st_state gate + VWAP-cap k2)\n")
    print("  (a) STOP placement (tp2=4R):")
    line("OR-edge (prod)", run(d, 4.0, "or"))
    line("STRUCTURE swing", run(d, 4.0, "struct"))
    base = B.SL_MAX_ATR
    for mx in (1.5, 2.0):
        B.SL_MAX_ATR = mx
        line(f"OR, max-stop {mx}ATR", run(d, 4.0, "or"))
    B.SL_MAX_ATR = base
    print("\n  (b) VOL-scaled reward — best TP2 by regime (causal prior-bar atr_pct vs 500-bar median):")
    ap = d["atr_pct"].to_numpy()
    med = pd.Series(ap).rolling(500, min_periods=100).median().shift(1).to_numpy()
    hi_skip = np.where(np.isnan(med), True, ~(ap > med))     # take only high-vol entries
    lo_skip = np.where(np.isnan(med), True, ~(ap <= med))    # take only low-vol entries
    for lab, msk in (("HIGH-vol days", hi_skip), ("LOW-vol days", lo_skip)):
        print(f"   {lab}:")
        for tp2 in (3.0, 4.0, 5.0, 6.0):
            line(f"   tp2={tp2:.0f}R", run(d, tp2, "or", msk))


if __name__ == "__main__":
    main()
