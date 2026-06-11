#!/usr/bin/env python3
"""
HIGHSTRIKE F23 — ROBUSTNESS of the structure stack to its pivot params (de-risks adoption).
The 5m stack rests on st_state with struct_lb=5, tol=0.10%. Is that a PLATEAU (neighbours behave the
same) or a SPIKE (a fitted sweet spot)? Sweep lb + tol on NQ 5m (+ QQQ cross-check), stack config
(st_state gate + VWAP-cap k2, RTH 0930-1000), and check the gate + per-year stability at each point.

    python research/orb_struct_robust.py
"""
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "engine"))
import numpy as np, pandas as pd
import hs_db, hs_harness as H, hs_backtest as B, hs_validate as V

rng = np.random.default_rng(7)


def loci(r):
    return np.percentile(rng.choice(r, (3000, len(r)), replace=True).mean(1), 5) if len(r) else 0.0


def state_p(con, sym, tf, lb, tol, adaptive):
    p = H.P(struct_lb_fix=lb, struct_tol_pct=tol, struct_adaptive=adaptive)
    d = H.compute_state(B._externals(con, hs_db.bars(con, tf, "full", sym=sym), sym), p)
    d.attrs["sym"] = sym
    return d


def run_stack(d):
    st = d["st_state"].to_numpy(); d["trend_up"] = st == 1; d["trend_down"] = st == 2
    return B.backtest(d, "scale_be", "both", False, "orb", 0, 1.0, 4.0, 570, 600, 0.0, 900, "stop",
                      eod_min=958, vwap_cap=2.0)


def line(tag, tr):
    r = tr["net_R"].to_numpy()
    if len(r) < 30:
        print(f"  {tag:18} n={len(r)} (<30)"); return
    L = tr[tr.direction == "long"]["net_R"].to_numpy(); S = tr[tr.direction == "short"]["net_R"].to_numpy()
    both = len(L) > 5 and L.mean() > 0 and len(S) > 5 and S.mean() > 0
    lo = loci(r)
    t = tr.copy(); t["year"] = pd.to_datetime(t["entry_time"], utc=True).dt.tz_convert("America/New_York").dt.year
    yrs = [(int(y), g["net_R"].mean()) for y, g in t.groupby("year") if len(g) >= 10]
    pos = sum(1 for _, e in yrs if e > 0); tot = len(yrs)
    g = "PASS" if (both and lo > 0 and tot and pos >= 0.7 * tot) else "----"
    print(f"  {tag:18} n={len(r):>4} exp {r.mean():+.3f} PF {V.pf(r):>4.2f} CI {lo:+.3f} "
          f"both={'Y' if both else 'n'} yrs +{pos}/{tot} {g}")


def main():
    con = hs_db.connect()
    print("F23 structure-param robustness — NQ 5m STACK (st_state gate + VWAP-cap k2), RTH 0930-1000")
    print("  adopted point = lb5 tol0.10\n  -- lb sweep (tol=0.10) --")
    for lb in (3, 4, 5, 6, 8, 10):
        line(f"lb{lb} tol0.10", run_stack(state_p(con, "NQ", "5m", lb, 0.10, False)))
    print("  -- tol sweep (lb=5) --")
    for tol in (0.05, 0.15, 0.20):
        line(f"lb5 tol{tol}", run_stack(state_p(con, "NQ", "5m", 5, tol, False)))
    print("  -- adaptive lookback (tol=0.10) --")
    line("adaptive", run_stack(state_p(con, "NQ", "5m", 5, 0.10, True)))
    print("\n  -- QQQ cross-asset (tol=0.10) --")
    for lb in (5, 8):
        line(f"QQQ lb{lb}", run_stack(state_p(con, "QQQ", "5m", lb, 0.10, False)))
    con.close()


if __name__ == "__main__":
    main()
