#!/usr/bin/env python3
"""
F33-debug — isolate why trail+struct+st-gate prints +3.6R/PF 17 while trail+struct+EMA-gate
printed +0.39R. RTH, unblock-B frame, 2x2x2 matrix: gate {EMA, ST} x exit {scale_be, trail}
x stop {or, struct}. Prints n / exp / PF / win / mean & median risk_pts / mean win R / mean loss R.
"""
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "engine"))
import numpy as np, pandas as pd
import hs_db, hs_harness as H, hs_backtest as B, hs_validate as V
from orb_optimize import state


def main():
    d = state("NQ", "5m")
    d["_tu"] = d["trend_up"].to_numpy().copy()
    d["_td"] = d["trend_down"].to_numpy().copy()
    d["_st"] = d["st_state"].to_numpy().copy()
    d["macro_allow_trades"] = d["macro_allow_trades"].to_numpy() | (d["macro_regime"] == "B").to_numpy()
    print(f"NQ 5m RTH, unblock-B. gate x exit x stop matrix\n")
    print(f"{'gate':4} {'exit':9} {'stop':7} {'n':>5} {'exp':>8} {'PF':>7} {'win%':>5} {'riskM':>7} {'riskMed':>8} {'avgWinR':>8} {'avgLossR':>9}")
    for gate in ("ema", "st"):
        if gate == "st":
            d["trend_up"] = d["_st"] == 1
            d["trend_down"] = d["_st"] == 2
        else:
            d["trend_up"] = d["_tu"]
            d["trend_down"] = d["_td"]
        for exit_mode in ("scale_be", "trail"):
            for stop_mode in ("or", "struct"):
                tr = B.backtest(d, exit_mode, "both", False, "orb", 0, 1.0, 4.0, 570, 600, 0.0, 900,
                                "stop", eod_min=958, vwap_cap=2.0, stop_mode=stop_mode)
                r = tr["net_R"].to_numpy()
                w = r[r > 0]; l = r[r <= 0]
                print(f"{gate:4} {exit_mode:9} {stop_mode:7} {len(r):>5} {r.mean():>+8.3f} {V.pf(r):>7.2f} "
                      f"{100*np.mean(r>0):>5.1f} {tr.risk_pts.mean():>7.1f} {tr.risk_pts.median():>8.1f} "
                      f"{w.mean() if len(w) else 0:>+8.2f} {l.mean() if len(l) else 0:>+9.2f}")


if __name__ == "__main__":
    main()
