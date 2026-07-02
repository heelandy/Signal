#!/usr/bin/env python3
"""ADDITIVITY control for the SMC survivors — the make-or-break test (raw edge proves nothing; F36/F37
looked good but were redundant). For each survivor, split its trades into those that OVERLAP the ORB
(same day + direction — the ORB already catches that move) vs UNIQUE (days/directions the ORB skips).
If the UNIQUE subset is dead, the strategy is just a noisier ORB = redundant, not additive.

    python research/smc_additivity.py QQQ
"""
import sys, os, gc
sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "engine"))
import numpy as np, pandas as pd
import hs_db, hs_harness as H, hs_backtest as B, hs_validate as V
from smc_cluster import sig_fvg, sig_mss, sig_orderblock, sig_breaker, T1, T2, CUT, EOD, ci_lo

SURV = [("FVG", sig_fvg), ("MSS", sig_mss), ("OrderBlock", sig_orderblock), ("Breaker", sig_breaker)]


def _dd(tr):
    d = pd.to_datetime(tr["entry_time"], utc=True).dt.tz_convert("America/New_York")
    return set(zip(d.dt.date.astype(str), tr["direction"]))


def _tagset(tr):
    d = pd.to_datetime(tr["entry_time"], utc=True).dt.tz_convert("America/New_York")
    return list(zip(d.dt.date.astype(str), tr["direction"]))


def main():
    sym = (sys.argv[1] if len(sys.argv) > 1 else "QQQ").upper()
    con = hs_db.connect()
    d = H.compute_state(B._externals(con, hs_db.bars(con, "5m", "rth", sym=sym), sym), H.P()); d.attrs["sym"] = sym
    con.close()
    st = d["st_state"].to_numpy()
    d["trend_up"] = (st == 1); d["trend_down"] = (st == 2)
    orb = B.backtest(d, "tp2_full", "both", False, "orb", 0, T1, T2, 570, 600, 0.0, CUT, "close",
                     eod_min=EOD, stop_mode="struct", entry_delay=0, chase_atr=1.0, strong_body=0.25, ft_confirm=True)
    orbset = _dd(orb)
    print(f"\n{'='*92}\n{sym}  ADDITIVITY vs ORB  (ORB n={len(orb)}, exp {orb['net_R'].mean():+.3f})\n{'='*92}")
    print(f"  {'survivor':11} {'all n/exp':>16}  {'OVERLAP n/exp':>18}  {'UNIQUE n/exp/CIlo':>24}  verdict")
    for name, fn in SURV:
        d["trend_up"] = True; d["trend_down"] = True
        el, es = fn(d)
        tr = B.backtest(d, "tp2_full", "both", False, "ext", 0, T1, T2, 570, 600, 0.0, CUT, "close",
                        eod_min=EOD, stop_mode="struct", ext_long=el, ext_short=es)
        tags = _tagset(tr); r = tr["net_R"].to_numpy()
        mask_ov = np.array([t in orbset for t in tags])
        ro, ru = r[mask_ov], r[~mask_ov]
        add = "ADDITIVE" if (len(ru) >= 30 and ru.mean() > 0 and ci_lo(ru) > 0) else "redundant" if len(ru) >= 30 else "n/a"
        print(f"  {name:11} {len(r):>5}/{r.mean():+.3f}  {len(ro):>7}/{(ro.mean() if len(ro) else 0):+.3f}  "
              f"{len(ru):>7}/{(ru.mean() if len(ru) else 0):+.3f}/{(ci_lo(ru) if len(ru)>=10 else float('nan')):+.3f}  {add}")
    del d; gc.collect()
    print("  UNIQUE = trades on (day,direction) the ORB did NOT take. ADDITIVE needs UNIQUE exp>0 AND its CIlo>0.")


if __name__ == "__main__":
    main()
