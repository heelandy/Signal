#!/usr/bin/env python3
"""
HIGHSTRIKE F27 — EXIT / trade-management study on the 5m stack (the profit-side of Finding 25).
Production exit = scale 50% at TP1(1R) -> stop to BE -> runner to TP2(4R). Is that the right exit, or does
the stack want a different one? Sweep, on the NQ 5m stack (st_state gate + VWAP-cap k2, QQQ confirm):
  (0) MODE        scale_be vs tp2_full (one bracket) vs trail (ATR chandelier, no cap)
  (1) TP2 level   2..6R           (2) TP1 level  0.5/1.0/1.5R
  (3) scale frac  take 33/50/67% at TP1 (new off-by-default engine `scale_frac`)
  (4) trail mult  1.5/2.0/3.0 ATR
Beat-the-prod bar: a config only "wins" if it lifts exp AND keeps both sides>0 AND CI>0 (then walk-forward).

    python research/orb_exit_mgmt.py
"""
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "engine"))
import numpy as np, pandas as pd
import hs_db, hs_harness as H, hs_backtest as B, hs_validate as V
from orb_optimize import state, metrics


def setgate(d):
    st = d["st_state"].to_numpy(); d["trend_up"] = st == 1; d["trend_down"] = st == 2


def run(d, mode="scale_be", tp1=1.0, tp2=4.0, sf=0.5, trailm=None):
    base = B.TRAIL_MULT
    if trailm is not None:
        B.TRAIL_MULT = trailm
    tr = B.backtest(d, mode, "both", False, "orb", 0, tp1, tp2, 570, 600, 0.0, 900, "stop",
                    eod_min=958, vwap_cap=2.0, scale_frac=sf)
    B.TRAIL_MULT = base
    return tr


def line(tag, tr):
    m = metrics(tr)
    if m is None:
        print(f"  {tag:18} <30 trades"); return
    print(f"  {tag:18} n={m['n']:>4} exp {m['exp']:+.3f} PF {m['pf']:>4.2f} win {m['win']:>2.0f}% "
          f"DD {m['maxdd']:>+5.0f} CI {m['loCI']:+.3f} both={'Y' if m['both'] else 'n'}")


def main():
    d = state("NQ", "5m"); setgate(d)
    print("F27 exit management — NQ 5m STACK   (prod = scale_be, TP1 1R, TP2 4R, take 50%)\n")
    print("  (0) exit MODE:")
    line("scale_be (prod)", run(d, "scale_be", 1.0, 4.0, 0.5))
    line("tp2_full 2R", run(d, "tp2_full", 1.0, 2.0, 0.5))
    line("tp2_full 3R", run(d, "tp2_full", 1.0, 3.0, 0.5))
    line("trail 2ATR", run(d, "trail", 1.0, 4.0, 0.5, 2.0))
    print("  (1) TP2 level (scale_be, TP1=1R, 50%):")
    for tp2 in (2, 3, 4, 5, 6):
        line(f"tp2={tp2}R", run(d, "scale_be", 1.0, float(tp2), 0.5))
    print("  (2) TP1 level (scale_be, TP2=4R, 50%):")
    for tp1 in (0.5, 1.0, 1.5):
        line(f"tp1={tp1}R", run(d, "scale_be", tp1, 4.0, 0.5))
    print("  (3) scale fraction banked at TP1 (scale_be, 1R/4R):")
    for sf in (0.33, 0.5, 0.67):
        line(f"take {int(sf*100)}%", run(d, "scale_be", 1.0, 4.0, sf))
    print("  (4) trail multiplier (trail mode):")
    for tm in (1.5, 2.0, 3.0):
        line(f"trail {tm}ATR", run(d, "trail", 1.0, 4.0, 0.5, tm))

    dq = state("QQQ", "5m"); setgate(dq)
    print("\n  QQQ confirm (mode comparison):")
    line("scale_be (prod)", run(dq, "scale_be", 1.0, 4.0, 0.5))
    line("tp2_full 2R", run(dq, "tp2_full", 1.0, 2.0, 0.5))
    line("trail 2ATR", run(dq, "trail", 1.0, 4.0, 0.5, 2.0))


if __name__ == "__main__":
    main()
