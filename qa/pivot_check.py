#!/usr/bin/env python3
"""
HIGHSTRIKE — OFFLINE pivot-rule check (shrinks / removes the TradingView reconcile dependency).
The Pine st_state port's ONLY un-verified piece is whether the harness pivots() matches TradingView's
ta.pivothigh TIE-handling. Harness uses STRICT > on both sides; TradingView's ta.pivothigh effectively
allows a TIE on the LEFT (>=) and is strict on the RIGHT. They can only differ on bars with equal
highs/lows in the window. This counts those bars on real data — i.e. exactly how much TradingView is needed.

    python qa/pivot_check.py [SYM=NQ] [TF=5m] [LB=5]
"""
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "engine"))
import numpy as np, pandas as pd
import hs_db


def rules(arr, L, kind):
    s = pd.Series(arr)
    n = len(arr)
    if kind == "high":
        lm = s.rolling(L).max().shift(1).to_numpy()                 # max of the L bars BEFORE the candidate
        rmax_rev = pd.Series(arr[::-1]).rolling(L).max().shift(1).to_numpy()
        rm = rmax_rev[::-1]                                          # max of the L bars AFTER the candidate
        strict = (arr > lm) & (arr > rm)                            # harness: strict both sides
        tv = (arr >= lm) & (arr > rm)                               # TradingView: tie OK on left, strict right
    else:
        lm = s.rolling(L).min().shift(1).to_numpy()
        rmin_rev = pd.Series(arr[::-1]).rolling(L).min().shift(1).to_numpy()
        rm = rmin_rev[::-1]
        strict = (arr < lm) & (arr < rm)
        tv = (arr <= lm) & (arr < rm)
    valid = ~np.isnan(lm) & ~np.isnan(rm)
    return (strict & valid), (tv & valid), valid


def main():
    sym = (sys.argv[1] if len(sys.argv) > 1 else "NQ").upper()
    tf = sys.argv[2] if len(sys.argv) > 2 else "5m"
    L = int(sys.argv[3]) if len(sys.argv) > 3 else 5
    con = hs_db.connect(); b = hs_db.bars(con, tf, "full", sym=sym); con.close()
    h = b["high"].to_numpy(); l = b["low"].to_numpy(); n = len(b)
    print(f"pivot-rule check — {sym} {tf} full, lb={L}, {n:,} bars")
    print(f"  (harness = strict > both sides; TradingView ta.pivothigh = tie OK on LEFT, strict RIGHT)\n")
    tot_diff = 0
    for kind, arr in (("high", h), ("low", l)):
        a, t, valid = rules(arr, L, kind)
        na, nt, diff = int(a.sum()), int(t.sum()), int((a != t).sum())
        tot_diff += diff
        print(f"  {kind:4}: strict-both {na:>7,} pivots | TV-rule {nt:>7,} | DIFFER on {diff:>6,} bars "
              f"({100*diff/max(n,1):.3f}% of bars, {100*diff/max(nt,1):.2f}% of pivots)")
    print(f"\n  total differing pivot bars: {tot_diff:,}")
    if tot_diff == 0:
        print("  => the tie-rule is MOOT on this data: harness pivots == TradingView pivots. Port validated offline,")
        print("     no TradingView needed (st_state machine already verified line-by-line).")
    else:
        print(f"  => {tot_diff:,} bars are tie-sensitive. Either (a) switch the harness to the TV rule and re-validate")
        print("     (I can do this + measure the stack-number impact), or (b) free-plan spot-check just these bars in")
        print("     TradingView's Data Window. Everything else is already verified.")


if __name__ == "__main__":
    main()
