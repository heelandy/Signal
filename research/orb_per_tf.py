#!/usr/bin/env python3
"""
HIGHSTRIKE research — best ORB config PER TIMEFRAME (for the TF-adaptive Pine mapping).
Maximizes expectancy among robust configs (PF>=1.40, exp>=0.05R, both signals>0, lower CI>0).
Sweeps breakout-strength x time-of-day cutoff x reward, scale exit, for 5m / 15m / 30m.

    python research/orb_per_tf.py
"""
import sys, os, itertools
sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "engine"))
import hs_backtest as B
from orb_optimize import metrics, state

GRID = list(itertools.product([0.0, 0.1, 0.25], [780, 720, 690], [2.0, 3.0, 4.0]))


def main():
    sym = sys.argv[1] if len(sys.argv) > 1 else "NQ"
    print(f"Best ORB config per timeframe — {sym} (max expectancy among robust configs)\n")
    print(f"{'TF':>4} {'brk':>4} {'cut':>5} {'rr':>3} {'n':>5} {'exp':>7} {'PF':>5} {'win%':>5} {'maxDD':>7} {'CI':>7}  {'L':>6} {'S':>6}")
    print("-" * 78)
    best_by_tf = {}
    for tf in ["5m", "15m", "30m"]:
        d = state(sym, tf)
        rows = []
        for brk, tod, rr in GRID:
            mm = metrics(B.backtest(d, "scale_be", "both", False, "orb", 0, None, rr, 570, 600, brk, tod))
            if mm:
                mm.update(brk=brk, tod=tod, rr=rr); rows.append(mm)
        qual = [r for r in rows if r["pf"] >= 1.40 and r["exp"] >= 0.05 and r["both"] and r["loCI"] > 0]
        b = max(qual, key=lambda r: r["exp"]) if qual else max(rows, key=lambda r: r["pf"])
        best_by_tf[tf] = b
        cut = f"{b['tod']//60:02d}{b['tod']%60:02d}"
        print(f"{tf:>4} {b['brk']:>4.2f} {cut:>5} {b['rr']:>3.0f} {b['n']:>5} {b['exp']:>+7.3f} {b['pf']:>5.2f} "
              f"{b['win']:>5.1f} {b['maxdd']:>7.1f} {b['loCI']:>+7.3f}  {b['Lexp']:>+6.2f} {b['Sexp']:>+6.2f}")
    print("\nMAPPING for the Pine (auto per-TF):")
    for tf, b in best_by_tf.items():
        print(f"  {tf:>4}: breakout {b['brk']} ATR | cutoff {b['tod']//60:02d}:{b['tod']%60:02d} | TP2 {b['rr']:.0f}R")


if __name__ == "__main__":
    main()
