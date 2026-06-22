#!/usr/bin/env python3
"""
RESEARCH (F38 candidate) — TIME-OF-DAY is the orthogonal lead from orb_stack_features.py: on the 5m stack,
opening-hour breakouts (09:30-11:00) are near-dead (PF ~1.1-1.6) while 11:00-15:00 breakouts carry the edge
(PF 7-23), consistently on NQ+QQQ+SPY. Tradeable + causal (clock known at entry). The gauntlet:

  1. skip-mornings sweep: skip stack entries before T (engine skip_mask -> stay flat, a later break same day
     can still fire). Full gate + per-year + OOS on NQ+QQQ+SPY, sweep T.
  2. ADDITIVITY / frontier-lift (the F37 control): does skip-mornings lift the WHOLE vwap-cap frontier, or
     just ride it? delta = (skip + vwap k) MINUS vwap-only-at-matched-n, across the k grid, NQ+QQQ.
  3. is it a proxy for vwap_ext? (already in the corr table: tod is its own axis) — the additivity test settles it.

    python research/orb_stack_tod.py            (sweep + per-year + OOS)
    python research/orb_stack_tod.py --additive (frontier-lift control)
"""
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "engine"))
import numpy as np, pandas as pd
import hs_db, hs_harness as H, hs_backtest as B, hs_validate as V
from orb_kernel_filter import loci, slip2x, ORS, ORE, CUT, T1, T2, EOD, KCAP


def tod_arr(d):
    et = pd.to_datetime(d["ts"]).dt.tz_convert("America/New_York")
    return (et.dt.hour * 60 + et.dt.minute).to_numpy()


def run(d, tmin=None, vcap=KCAP):
    st = d["st_state"].to_numpy(); d["trend_up"] = st == 1; d["trend_down"] = st == 2
    sk = (tod_arr(d) < tmin) if tmin else None
    return B.backtest(d, "scale_be", "both", False, "orb", 0, T1, T2, ORS, ORE, 0.0, CUT, "stop",
                      eod_min=EOD, vwap_cap=vcap, skip_mask=sk)


def report(tag, tr, slip_eq=None):
    r = tr["net_R"].to_numpy()
    L = tr[tr.direction == "long"]["net_R"].to_numpy(); S = tr[tr.direction == "short"]["net_R"].to_numpy()
    both = len(L) > 5 and L.mean() > 0 and len(S) > 5 and S.mean() > 0
    lo = loci(r)
    t = tr.copy(); t["year"] = pd.to_datetime(t["entry_time"], utc=True).dt.tz_convert("America/New_York").dt.year
    yrs = [(int(y), g["net_R"].mean()) for y, g in t.groupby("year") if len(g) >= 10]
    pos = sum(1 for _, e in yrs if e > 0); tot = len(yrs); neg = [y for y, e in yrs if e <= 0]
    t = t.sort_values("entry_time").reset_index(drop=True); k = int(len(t) * 0.7)
    IN = t.iloc[:k]["net_R"].to_numpy(); OUT = t.iloc[k:]["net_R"].to_numpy()
    g = "PASS" if (both and lo > 0) else "fail"
    sl = ""
    if slip_eq is not None:
        s2 = slip2x(tr, slip_eq); sl = f" | 2x {s2.mean():+.3f}"
    print(f"  {tag:11} n={len(r):>4} exp {r.mean():+.3f} PF {V.pf(r):>5.2f} win {100*np.mean(r>0):>2.0f}% "
          f"DD {V.maxdd(r):>+5.0f} CI {lo:+.3f} {g} | yr +{pos}/{tot}{'  NEG=' + str(neg) if neg else ''} "
          f"| OOS {IN.mean():+.3f}->{OUT.mean():+.3f}{sl}")


def sweep(con):
    for sym in ["NQ", "ES", "QQQ", "SPY"]:
        eq = sym in ("QQQ", "SPY")
        bars = B._externals(con, hs_db.bars(con, "5m", "full", sym=sym), sym)
        d = H.compute_state(bars, H.P()); d.attrs["sym"] = sym
        print(f"\n############ {sym} 5m — stack + skip-mornings sweep (skip entries before T) ############")
        report("STACK", run(d), None if eq else eq)
        for T, lbl in [(600, "skip<10:00"), (630, "skip<10:30"), (660, "skip<11:00"),
                       (690, "skip<11:30"), (720, "skip<12:00")]:
            report(lbl, run(d, T), None if eq else eq)


def additive(con):
    print("==== ADDITIVITY: does skip<11:00 lift the vwap-cap frontier? (NQ + QQQ) ====")
    print("delta = (skip<11:00 + vwap k) MINUS vwap-only exp interpolated at the SAME trade count.\n")
    ks = [2.0, 1.8, 1.6, 1.4, 1.2, 1.0]
    for sym in ("NQ", "QQQ"):
        bars = B._externals(con, hs_db.bars(con, "5m", "full", sym=sym), sym)
        d = H.compute_state(bars, H.P()); d.attrs["sym"] = sym
        vo = []
        for k in ks:
            r = run(d, None, k)["net_R"].to_numpy(); vo.append((len(r), r.mean()))
        vs = sorted(vo); ns = np.array([x[0] for x in vs]); es = np.array([x[1] for x in vs])
        print(f"  ---- {sym} ----")
        for k in ks:
            r = run(d, 660, k)["net_R"].to_numpy(); n_s, e_s = len(r), r.mean()
            e_vo = float(np.interp(n_s, ns, es))
            print(f"  skip<11:00 + vwap k={k}  n={n_s:>4} exp {e_s:+.3f}  |  vwap-only@n {e_vo:+.3f}  |  delta {e_s - e_vo:+.3f}")
        print()


def main():
    con = hs_db.connect()
    if "--additive" in sys.argv[1:]:
        additive(con)
    else:
        sweep(con)
    con.close()


if __name__ == "__main__":
    main()
