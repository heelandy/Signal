#!/usr/bin/env python3
"""
HIGHSTRIKE F31f — the user's mixed config: unblock regime B for RTH + Asia, KEEP B blocked for
London (the one stream that got riskier unblocked at tight daily limits). Eval sim, F26 profiles.

    python research/orb_prop_eval_mixed.py
"""
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "engine"))
import pandas as pd
from orb_optimize import state
from orb_prop_eval import stack, simulate


def main():
    d = state("NQ", "5m")
    d3 = d.copy(deep=False)
    d3["macro_allow_trades"] = d["macro_allow_trades"].to_numpy() | (d["macro_regime"] == "B").to_numpy()
    d3.attrs.update(d.attrs)
    profiles = [(9, 6, 4), (15, 10, 6), (30, 12, 8)]
    cat = lambda *xs: pd.concat(xs).sort_values("entry_time").reset_index(drop=True)
    rth_b, asia_b = stack(d3, "rth"), stack(d3, "asia")
    lond_p, lond_b = stack(d, "london"), stack(d3, "london")
    print("F31f — MIXED: unblock-B RTH+Asia, B BLOCKED for London (vs full unblock)\n")
    simulate("MIXED ALL THREE (London keeps B block)", cat(rth_b, asia_b, lond_p), profiles)
    print()
    simulate("FULL unblock ALL THREE (reference)", cat(rth_b, asia_b, lond_b), profiles)
    print()
    simulate("MIXED RTH+London only", cat(rth_b, lond_p), profiles)


if __name__ == "__main__":
    main()
