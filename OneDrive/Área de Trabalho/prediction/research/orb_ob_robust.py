#!/usr/bin/env python3
"""
RESEARCH (F47) — DE-RISK F41/F45: is the order-block confluence edge a PLATEAU over its (untuned V44) params or
a fitted spike? Sweep each OB param around its default and re-run +ob on the stack (NQ+QQQ), like F23 did for the
pivot params. Engine P fields are off-by-default (defaults = V44, all prior results unchanged). PASS = exp stays
strongly + across the grid (both sides+, CI>0, most years+).

  ob_body_atr (def 0.3) — min breakout-bar body in ATR to form an OB
  ob_keep     (def 5)   — how many recent OBs stay active
  ob_dist_atr (def 3.0) — invalidate an OB once price is this many ATR away

    python research/orb_ob_robust.py
"""
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "engine"))
import numpy as np, pandas as pd
import hs_db, hs_harness as H, hs_backtest as B, hs_validate as V
from orb_kernel_filter import loci, ORS, ORE, CUT, T1, T2, EOD, KCAP

GRID = [("default", {}),
        ("body0.2", {"ob_body_atr": 0.2}), ("body0.4", {"ob_body_atr": 0.4}), ("body0.5", {"ob_body_atr": 0.5}),
        ("keep3", {"ob_keep": 3}), ("keep8", {"ob_keep": 8}),
        ("dist2", {"ob_dist_atr": 2.0}), ("dist5", {"ob_dist_atr": 5.0}),
        ("vol0.5", {"ob_vol_mult": 0.5}), ("vol1.0", {"ob_vol_mult": 1.0})]


def run_ob(d):
    st = d["st_state"].to_numpy()
    d["trend_up"] = (st == 1) & d["in_bull_ob"].shift(1).fillna(False).to_numpy().astype(bool)
    d["trend_down"] = (st == 2) & d["in_bear_ob"].shift(1).fillna(False).to_numpy().astype(bool)
    return B.backtest(d, "scale_be", "both", False, "orb", 0, T1, T2, ORS, ORE, 0.0, CUT, "stop",
                      eod_min=EOD, vwap_cap=KCAP)


def line(tag, tr):
    r = tr["net_R"].to_numpy()
    L = tr[tr.direction == "long"]["net_R"].to_numpy(); S = tr[tr.direction == "short"]["net_R"].to_numpy()
    both = len(L) > 5 and L.mean() > 0 and len(S) > 5 and S.mean() > 0
    lo = loci(r)
    t = tr.copy(); t["year"] = pd.to_datetime(t["entry_time"], utc=True).dt.tz_convert("America/New_York").dt.year
    yrs = [(int(y), g["net_R"].mean()) for y, g in t.groupby("year") if len(g) >= 10]
    pos = sum(1 for _, e in yrs if e > 0); tot = len(yrs)
    g = "PASS" if (both and lo > 0) else "fail"
    print(f"  {tag:10} n={len(r):>4} exp {r.mean():+.3f} PF {V.pf(r):>5.2f} win {100*np.mean(r>0):>2.0f}% "
          f"DD {V.maxdd(r):>+5.0f} CI {lo:+.3f} {g} | yr +{pos}/{tot}")


def main():
    con = hs_db.connect()
    for sym in ["NQ", "QQQ"]:
        bars = B._externals(con, hs_db.bars(con, "5m", "full", sym=sym), sym)
        print(f"\n#### {sym} 5m — +ob param robustness (stack + order-block) ####")
        for tag, kw in GRID:
            d = H.compute_state(bars, H.P(**kw)); d.attrs["sym"] = sym
            line(tag, run_ob(d))
    con.close()


if __name__ == "__main__":
    main()
