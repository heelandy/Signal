#!/usr/bin/env python3
"""
HIGHSTRIKE research — is the ASIA (and London) session ORB profitable, vs US RTH?
Uses trade-day coordinates (mins since 18:00 ET) so sessions crossing midnight work.
Same engine: stop-entry, 4R, scale, breakout-strength 0.1, macro/regime/trend gates on.

    python research/orb_sessions.py [TF=15m]
Windows (trade-day mins, 18:00 ET = 0): 20:00=120, 00:00=360, 03:00=540, 09:30=930, 13:00=1140.
"""
import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import hs_backtest as B
from orb_optimize import metrics, state

SESSIONS = [
    ("US RTH  09:30-10:00", 930, 960, 1140),
    ("Asia    18:00-18:30",   0,  30,  540),
    ("Asia    19:00-19:30",  60,  90,  540),
    ("Asia    20:00-20:30", 120, 150,  540),
    ("Asia    20:00-21:00", 120, 180,  540),
    ("London  03:00-03:30", 540, 570,  840),
]


def main():
    tf = sys.argv[1] if len(sys.argv) > 1 else "15m"
    d = state("NQ", tf)
    print(f"Session ORB — NQ {tf}, stop-entry 4R scale brk0.1 (gates on)\n")
    print(f"{'session':22} {'n':>4} {'exp':>7} {'PF':>5} {'win%':>5} {'maxDD':>7} {'CI':>7}  {'L':>6} {'S':>6} pass")
    print("-" * 86)
    for name, s, e, tod in SESSIONS:
        mm = metrics(B.backtest(d, "scale_be", "both", False, "orb", 0, None, 4.0, s, e, 0.1, tod, "stop", True))
        if mm is None:
            print(f"{name:22}  (<30 trades — too few breakouts qualify)")
            continue
        ok = mm["exp"] >= 0.05 and mm["loCI"] > 0 and mm["both"]
        print(f"{name:22} {mm['n']:>4} {mm['exp']:>+7.3f} {mm['pf']:>5.2f} {mm['win']:>5.1f} "
              f"{mm['maxdd']:>7.1f} {mm['loCI']:>+7.3f}  {mm['Lexp']:>+6.2f} {mm['Sexp']:>+6.2f} {'YES' if ok else '-'}")


if __name__ == "__main__":
    main()
