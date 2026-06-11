#!/usr/bin/env python3
"""
HIGHSTRIKE F24 — cross-instrument + RTH⊕Asia correlation.
(a) Does the 5m RTH stack hold on ES (the only untested index future; NQ/QQQ/SPY done in F20/F21)?
(b) On NQ, are the RTH-stack and Asia-stack trade streams INDEPENDENT (real diversification) or
    same-day correlated? Low daily-PnL correlation + a combined drawdown below the sum = stack the sessions.

    python research/orb_xinstrument.py
"""
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "engine"))
import numpy as np, pandas as pd
import hs_db, hs_harness as H, hs_backtest as B, hs_validate as V
from orb_optimize import state, metrics


def _gate(d):
    st = d["st_state"].to_numpy(); d["trend_up"] = st == 1; d["trend_down"] = st == 2


def stack_rth(d):
    _gate(d)
    return B.backtest(d, "scale_be", "both", False, "orb", 0, 1.0, 4.0, 570, 600, 0.0, 900, "stop",
                      eod_min=958, vwap_cap=2.0)


def stack_asia(d):
    _gate(d)
    return B.backtest(d, "scale_be", "both", False, "orb", 0, 1.0, 4.0, 60, 120, 0.0, 540, "stop",
                      tradeday=True, eod_min=540, vwap_cap=2.0)


def report(tag, tr):
    m = metrics(tr)
    if m is None:
        print(f"  {tag:14} <30 trades"); return
    t = tr.copy(); t["year"] = pd.to_datetime(t["entry_time"], utc=True).dt.tz_convert("America/New_York").dt.year
    yrs = [g["net_R"].mean() for _, g in t.groupby("year") if len(g) >= 10]
    pos = sum(1 for e in yrs if e > 0)
    print(f"  {tag:14} n={m['n']:>4} exp {m['exp']:+.3f} PF {m['pf']:>4.2f} CI {m['loCI']:+.3f} "
          f"both={'Y' if m['both'] else 'n'} L{m['Lexp']:+.2f} S{m['Sexp']:+.2f} yrs +{pos}/{len(yrs)}")


def daily_R(tr):
    t = tr.copy()
    t["d"] = pd.to_datetime(t["entry_time"], utc=True).dt.tz_convert("America/New_York").dt.normalize()
    return t.groupby("d")["net_R"].sum()


def main():
    print("F24a -- ES 5m RTH stack (completes the index set NQ/QQQ/SPY -> +ES)\n")
    report("ES RTH", stack_rth(state("ES", "5m")))

    print("\nF24b -- NQ RTH + Asia correlation (5m stack)\n")
    d = state("NQ", "5m")
    rth = stack_rth(d); asia = stack_asia(d)
    report("NQ RTH", rth); report("NQ Asia", asia)
    dr, da = daily_R(rth), daily_R(asia)
    alld = dr.index.union(da.index); both = dr.index.intersection(da.index)
    A = pd.DataFrame({"rth": dr.reindex(alld).fillna(0.0), "asia": da.reindex(alld).fillna(0.0)})
    comb = (A["rth"] + A["asia"]).to_numpy()
    print(f"\n  active days: RTH {len(dr)}, Asia {len(da)}, BOTH same day {len(both)} "
          f"({100*len(both)/max(len(alld),1):.0f}% of active days)")
    print(f"  daily-PnL corr(RTH, Asia) = {A['rth'].corr(A['asia']):+.3f}   (near 0 = good diversification)")
    print(f"  maxDD (daily path): RTH {V.maxdd(dr.to_numpy()):+.0f}R  Asia {V.maxdd(da.to_numpy()):+.0f}R  "
          f"COMBINED {V.maxdd(comb):+.0f}R   (combined < RTH+Asia => sessions diversify)")


if __name__ == "__main__":
    main()
