#!/usr/bin/env python3
"""
HIGHSTRIKE F31d — F26-style prop-eval sim, production vs UNBLOCK-B (~2.4x trade frequency).
Same canonical streams + profiles as orb_prop_eval.py so the numbers are directly comparable.

    python research/orb_prop_eval_b.py
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
    streams = {}
    for s in ("rth", "asia", "london"):
        streams[(s, "prod")] = stack(d, s)
        streams[(s, "unbB")] = stack(d3, s)
    print("F31d prop-eval — production (B blocked) vs UNBLOCK B, same profiles as F26\n")
    for s in ("rth", "asia", "london"):
        simulate(f"{s.upper()} prod", streams[(s, "prod")], profiles)
        simulate(f"{s.upper()} unblock-B", streams[(s, "unbB")], profiles)
        print()
    simulate("ALL THREE prod", cat(*[streams[(s, "prod")] for s in ("rth", "asia", "london")]), profiles)
    simulate("ALL THREE unblock-B", cat(*[streams[(s, "unbB")] for s in ("rth", "asia", "london")]), profiles)


if __name__ == "__main__":
    main()
