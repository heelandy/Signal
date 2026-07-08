#!/usr/bin/env python3
"""
RESEARCH — hunt a THIRD orthogonal axis. Re-run the F38 feature-separation study, but on the residual trades
AFTER the two new edges are applied (stack + skip<11:00 [F38] + order-block [F41]). Whatever still separates
winners from losers now is a candidate for a 3rd independent edge (and is, by construction, orthogonal to the
two we already have). Sign-consistent across NQ+QQQ+SPY only. Reuses orb_stack_features.feature_table + NUMF.

    python research/orb_stack_features2.py
"""
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "engine"))
import numpy as np, pandas as pd
import hs_db, hs_harness as H, hs_backtest as B
from orb_stack_features import feature_table, NUMF, ORS, ORE, CUT, T1, T2, EOD, KCAP


def filtered_trades(d):
    st = d["st_state"].to_numpy()
    tu = (st == 1) & d["in_bull_ob"].shift(1).fillna(False).to_numpy().astype(bool)
    td = (st == 2) & d["in_bear_ob"].shift(1).fillna(False).to_numpy().astype(bool)
    d["trend_up"] = tu; d["trend_down"] = td
    et = pd.to_datetime(d["ts"]).dt.tz_convert("America/New_York")
    sk = ((et.dt.hour * 60 + et.dt.minute).to_numpy()) < 660
    return B.backtest(d, "scale_be", "both", False, "orb", 0, T1, T2, ORS, ORE, 0.0, CUT, "stop",
                      eod_min=EOD, vwap_cap=KCAP, skip_mask=sk)


def main():
    syms = [s.upper() for s in (sys.argv[1:] or ["NQ", "QQQ", "SPY"])]
    con = hs_db.connect(); store = {}
    for sym in syms:
        bars = B._externals(con, hs_db.bars(con, "5m", "full", sym=sym), sym)
        d = H.compute_state(bars, H.P()); d.attrs["sym"] = sym
        tr = filtered_trades(d); t = feature_table(d, tr)
        print(f"\n{'='*70}\n{sym} 5m — feature study on F38+F41-FILTERED residual (n={len(t)})\n{'='*70}")
        cors = {}
        for f in NUMF:
            sub = t[[f, "net_R"]].replace([np.inf, -np.inf], np.nan).dropna()
            c = sub[f].corr(sub["net_R"], method="spearman") if len(sub) > 30 else np.nan
            cors[f] = c
            print(f"  {f:10} corr={c:+.3f}  n={len(sub)}")
        store[sym] = cors
    con.close()
    print(f"\n{'='*70}\nCROSS-ASSET sign consistency (3rd-axis candidates):\n{'='*70}")
    print(f"  {'feature':10} " + " ".join(f"{s:>8}" for s in syms))
    for f in NUMF:
        vals = [store[s].get(f, np.nan) for s in syms]
        ok = [v for v in vals if not np.isnan(v)]
        signs = {np.sign(v) for v in ok if abs(v) >= 0.05}
        tag = "LEAD" if (len(signs) == 1 and len(ok) == len(syms) and np.mean([abs(v) for v in ok]) >= 0.08) else \
              ("consistent-weak" if (len(signs) == 1 and len(ok) == len(syms)) else "flips")
        print(f"  {f:10} " + " ".join(f"{v:+8.3f}" for v in vals) + f"   {tag}")


if __name__ == "__main__":
    main()
