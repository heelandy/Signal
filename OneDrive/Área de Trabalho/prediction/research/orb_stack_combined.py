#!/usr/bin/env python3
"""
RESEARCH (F45) — CONSOLIDATION: do the session's two new edges STACK? F38 (skip entries before 11:00 ET) and
F41 (order-block confluence) each graduated independently and each lifts the vwap-cap frontier; F41's additive
run already hinted they add on top of each other. Validate the COMBINED config (stack + skip<11:00 + OB) across
NQ+QQQ+SPY+ES with the full gauntlet (per-year, OOS, 2x slip), and confirm the combined still lifts the vwap-cap
frontier (orthogonality preserved). No propagation ([[highstrike-defer-propagation]]) — this is validation only.

    python research/orb_stack_combined.py             (4-way table per instrument)
    python research/orb_stack_combined.py --additive  (combined frontier-lift vs vwap-cap, NQ+QQQ)
"""
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "engine"))
import numpy as np, pandas as pd
import hs_db, hs_harness as H, hs_backtest as B, hs_validate as V
from orb_kernel_filter import loci, slip2x, ORS, ORE, CUT, T1, T2, EOD, KCAP


def run(d, f38=False, f41=False, vcap=KCAP):
    st = d["st_state"].to_numpy(); tu = st == 1; td = st == 2
    if f41:
        tu = tu & d["in_bull_ob"].shift(1).fillna(False).to_numpy().astype(bool)
        td = td & d["in_bear_ob"].shift(1).fillna(False).to_numpy().astype(bool)
    sk = None
    if f38:
        et = pd.to_datetime(d["ts"]).dt.tz_convert("America/New_York")
        sk = ((et.dt.hour * 60 + et.dt.minute).to_numpy()) < 660
    d["trend_up"] = tu; d["trend_down"] = td
    return B.backtest(d, "scale_be", "both", False, "orb", 0, T1, T2, ORS, ORE, 0.0, CUT, "stop",
                      eod_min=EOD, vwap_cap=vcap, skip_mask=sk)


def line(tag, tr, eq=False):
    r = tr["net_R"].to_numpy()
    if len(r) < 30:
        print(f"  {tag:16} n={len(r)} (<30)"); return
    L = tr[tr.direction == "long"]["net_R"].to_numpy(); S = tr[tr.direction == "short"]["net_R"].to_numpy()
    both = len(L) > 5 and L.mean() > 0 and len(S) > 5 and S.mean() > 0
    lo = loci(r)
    t = tr.copy(); t["year"] = pd.to_datetime(t["entry_time"], utc=True).dt.tz_convert("America/New_York").dt.year
    yrs = [(int(y), g["net_R"].mean()) for y, g in t.groupby("year") if len(g) >= 8]
    pos = sum(1 for _, e in yrs if e > 0); tot = len(yrs); neg = [y for y, e in yrs if e <= 0]
    t = t.sort_values("entry_time").reset_index(drop=True); k = int(len(t) * 0.7)
    IN = t.iloc[:k]["net_R"].to_numpy(); OUT = t.iloc[k:]["net_R"].to_numpy()
    g = "PASS" if (both and lo > 0 and tot and pos >= 0.7 * tot and OUT.mean() > 0) else "fail"
    sl = "" if eq else f" 2x {slip2x(tr, eq).mean():+.3f}"
    print(f"  {tag:16} n={len(r):>4} exp {r.mean():+.3f} PF {V.pf(r):>5.2f} win {100*np.mean(r>0):>2.0f}% "
          f"DD {V.maxdd(r):>+5.0f} CI {lo:+.3f} {g} | yr +{pos}/{tot}{' NEG=' + str(neg) if neg else ''} "
          f"| OOS {IN.mean():+.3f}->{OUT.mean():+.3f}{sl}")


def table(con):
    for sym in ["NQ", "ES", "QQQ", "SPY"]:
        eq = sym in ("QQQ", "SPY")
        bars = B._externals(con, hs_db.bars(con, "5m", "full", sym=sym), sym)
        d = H.compute_state(bars, H.P()); d.attrs["sym"] = sym
        print(f"\n#### {sym} 5m — F38 (skip<11:00) x F41 (order-block), combined ####")
        line("STACK", run(d), eq)
        line("+F38 time", run(d, f38=True), eq)
        line("+F41 OB", run(d, f41=True), eq)
        line("+F38+F41 BOTH", run(d, f38=True, f41=True), eq)


def additive(con):
    ks = [2.0, 1.8, 1.6, 1.4, 1.2, 1.0]
    for sym in ("NQ", "QQQ"):
        bars = B._externals(con, hs_db.bars(con, "5m", "full", sym=sym), sym)
        d = H.compute_state(bars, H.P()); d.attrs["sym"] = sym
        vo = [(len(t := run(d, vcap=k)), t["net_R"].mean()) for k in ks]
        vs = sorted(vo); ns = np.array([x[0] for x in vs]); es = np.array([x[1] for x in vs])
        print(f"\n==== {sym}: F38+F41 BOTH ADDITIVITY vs vwap-cap frontier ====")
        for k in ks:
            r = run(d, f38=True, f41=True, vcap=k)["net_R"].to_numpy()
            if len(r) < 25:
                print(f"  both + vwap k={k}  n={len(r):>4} (<25)"); continue
            e_vo = float(np.interp(len(r), ns, es))
            print(f"  both + vwap k={k}  n={len(r):>4} exp {r.mean():+.3f} | vwap-only@n {e_vo:+.3f} | delta {r.mean() - e_vo:+.3f}")


def main():
    con = hs_db.connect()
    additive(con) if "--additive" in sys.argv[1:] else table(con)
    con.close()


if __name__ == "__main__":
    main()
