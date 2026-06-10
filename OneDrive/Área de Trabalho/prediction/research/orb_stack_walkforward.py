#!/usr/bin/env python3
"""
WALK-FORWARD on the STACKED 5m config (F21): HH/HL structure gate + VWAP-cap (k=2.0) TOGETHER — the final
validation before adoption. Per-year positivity + 70/30 OOS split, STACK vs PRODUCTION, on NQ+QQQ+SPY 5m.
The stack's full-sample PF (4.5-5.3) is in the curve-fit zone, so the question is: is the stacked edge
TIME-STABLE (positive every year + OOS holds) or a concentrated artifact?

    python research/orb_stack_walkforward.py [SYM ...]   (default NQ QQQ SPY)
"""
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "engine"))
import numpy as np, pandas as pd
import hs_db, hs_harness as H, hs_backtest as B, hs_validate as V

rng = np.random.default_rng(7)
ORS, ORE, CUT, T1, T2, EOD, KCAP = 570, 600, 900, 1.0, 4.0, 958, 2.0


def loci(r):
    return np.percentile(rng.choice(r, (3000, len(r)), replace=True).mean(1), 5) if len(r) else 0.0


def run(d, stack):
    if stack:
        st = d["st_state"].to_numpy(); d["trend_up"] = st == 1; d["trend_down"] = st == 2; cap = KCAP
    else:
        d["trend_up"] = d["_tu"]; d["trend_down"] = d["_td"]; cap = 0.0
    return B.backtest(d, "scale_be", "both", False, "orb", 0, T1, T2, ORS, ORE, 0.0, CUT, "stop",
                      eod_min=EOD, vwap_cap=cap)


def report(tag, tr):
    r = tr["net_R"].to_numpy()
    L = tr[tr.direction == "long"]["net_R"].to_numpy(); S = tr[tr.direction == "short"]["net_R"].to_numpy()
    both = len(L) > 5 and L.mean() > 0 and len(S) > 5 and S.mean() > 0
    lo = loci(r)
    t = tr.copy()
    t["year"] = pd.to_datetime(t["entry_time"], utc=True).dt.tz_convert("America/New_York").dt.year
    yrs = [(int(y), g["net_R"].mean(), len(g)) for y, g in t.groupby("year") if len(g) >= 10]
    pos = sum(1 for _, e, _ in yrs if e > 0); tot = len(yrs)
    neg = [y for y, e, _ in yrs if e <= 0]
    thin = [int(y) for y, g in t.groupby("year") if len(g) < 10]
    t = t.sort_values("entry_time").reset_index(drop=True); k = int(len(t) * 0.7)
    IN = t.iloc[:k]["net_R"].to_numpy(); OUT = t.iloc[k:]["net_R"].to_numpy()
    g = "PASS" if (both and lo > 0) else "fail"
    print(f"  {tag:6} n={len(r):>4} exp {r.mean():+.3f} PF {V.pf(r):>4.2f} win {100*np.mean(r>0):>2.0f}% "
          f"DD {V.maxdd(r):>+5.0f} CI {lo:+.3f} {g} | yrs +{pos}/{tot}{'  NEG=' + str(neg) if neg else ''}"
          f"{'  thin=' + str(thin) if thin else ''} | OOS in {IN.mean():+.3f}/{V.pf(IN):.2f} -> out {OUT.mean():+.3f}/{V.pf(OUT):.2f}")


def main():
    syms = [s.upper() for s in (sys.argv[1:] or ["NQ", "QQQ", "SPY"])]
    con = hs_db.connect()
    for sym in syms:
        bars = B._externals(con, hs_db.bars(con, "5m", "full", sym=sym), sym)
        d = H.compute_state(bars, H.P()); d.attrs["sym"] = sym
        d["_tu"] = d["trend_up"].to_numpy().copy(); d["_td"] = d["trend_down"].to_numpy().copy()
        print(f"\n############ {sym} 5m  (STACK = HH/HL gate + VWAP-cap k2 vs production) ############")
        report("PROD", run(d, False))
        report("STACK", run(d, True))
    con.close()


if __name__ == "__main__":
    main()
