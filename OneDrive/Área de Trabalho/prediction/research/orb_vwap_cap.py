#!/usr/bin/env python3
"""
HIGHSTRIKE research — SIGNAL-LEVEL test of the VWAP-EXTENSION CAP (the Finding-15 lead). RESEARCH ONLY.

The lead: breakouts that fire while already EXTENDED beyond session VWAP underperform. Honest test (NOT a
post-hoc screen): skip the entry AT SIGNAL TIME when the breakout level sits more than k*ATR beyond the
PRIOR bar's session VWAP (causal — known before the fill). Skipping a long leaves the engine flat, so a
later short that day can still fire — a real signal change, then full re-validation.

ADOPT only if, on QQQ AND NQ (and ideally SPY): expectancy & PF improve (or DD improves at equal exp),
BOTH sides stay > 0, lower-90% CI stays > 0, and enough trades remain. Otherwise it joins the dead pile.

    python research/orb_vwap_cap.py [TF=15m]
"""
import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import numpy as np
import hs_backtest as B
from orb_optimize import state, metrics
from orb_entry_quality import brk_for

CAPS = [0.0, 3.0, 2.5, 2.0, 1.5, 1.0, 0.75, 0.5]   # 0.0 = off (baseline)


def bt(d, tf, cap):
    return B.backtest(d, "scale_be", "both", False, "orb", 0, None, 4.0, 570, 600, brk_for(tf), 900, "stop",
                      vwap_cap=cap)


def line(lbl, m, base):
    if m is None:
        print(f"  {lbl:18} (<30 trades)"); return
    keep = f"{100*m['n']/base['n']:3.0f}%" if base else "  - "
    de = m["exp"] - base["exp"] if base else 0.0
    both = "both+" if m["both"] else "ONE<0"
    flag = ""
    if base:
        flag = "  <== beats+clears" if (m["exp"] >= base["exp"] and m["pf"] >= base["pf"]
                                        and m["both"] and m["loCI"] > 0 and m["n"] >= 0.5*base["n"]) else ""
    print(f"  {lbl:18} n={m['n']:4} ({keep}) exp={m['exp']:+.3f} (d{de:+.3f}) PF={m['pf']:.2f} "
          f"win={m['win']:4.1f}% maxDD={m['maxdd']:6.1f} CI={m['loCI']:+.3f} L={m['Lexp']:+.2f} S={m['Sexp']:+.2f} {both}{flag}")


def run(sym, tf):
    d = state(sym, tf)
    print(f"\n{'='*86}\n{sym} {tf} — VWAP-extension cap sweep (skip if level > k*ATR beyond prior-bar VWAP)\n{'='*86}")
    base = metrics(bt(d, tf, 0.0))
    for cap in CAPS:
        m = metrics(bt(d, tf, cap))
        line("baseline (off)" if cap == 0 else f"cap k={cap}", m, None if cap == 0 else base)


def main():
    tf = sys.argv[1] if len(sys.argv) > 1 else "15m"
    for s in ["QQQ", "NQ", "SPY"]:
        run(s, tf)


if __name__ == "__main__":
    main()
