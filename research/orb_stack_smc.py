#!/usr/bin/env python3
"""
RESEARCH (F41 candidate) — SMART MONEY CONCEPTS family, the UNTESTED pieces. SMC market-STRUCTURE (HH/HL
st_state) already GRADUATED (F20), and SMC liquidity SWEEPS are already DEAD as entries (F18/F19 fade/
sweepgo/rebreak). The remaining untested SMC piece = ORDER BLOCKS + FAIR VALUE GAPS as a confluence FILTER on
the stack. The harness already computes these (zones built in _zones_sweep_patterns): in_bull_ob/in_bear_ob
(price inside a bull/bear order block) and at_bull_zone/at_bear_zone (at an OB OR FVG). Test them as causal
(prior-bar) AND-gates on the stack, full gauntlet incl. the additivity/frontier-lift control + on-top-of-F38.

  variants: ob   = long needs price at a bull order block / short a bear OB
            zone = long needs at a bull OB-or-FVG zone / short a bear zone

    python research/orb_stack_smc.py             (gate test)
    python research/orb_stack_smc.py --additive  (frontier-lift vs vwap-cap + on top of skip<11:00)
"""
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "engine"))
import numpy as np, pandas as pd
import hs_db, hs_harness as H, hs_backtest as B, hs_validate as V
from orb_kernel_filter import loci, slip2x, ORS, ORE, CUT, T1, T2, EOD, KCAP

VARIANTS = ("ob", "zone")


def feats(d):
    sh = lambda col: d[col].shift(1).fillna(False).to_numpy().astype(bool)
    et = pd.to_datetime(d["ts"]).dt.tz_convert("America/New_York")
    tod = (et.dt.hour * 60 + et.dt.minute).to_numpy()
    return dict(ob_l=sh("in_bull_ob"), ob_s=sh("in_bear_ob"),
                zone_l=sh("at_bull_zone"), zone_s=sh("at_bear_zone"), tod=tod)


def gates(v, M):
    if v == "ob":   return M["ob_l"], M["ob_s"]
    if v == "zone": return M["zone_l"], M["zone_s"]
    raise ValueError(v)


def run(d, v=None, M=None, vcap=KCAP, skip_morning=False):
    st = d["st_state"].to_numpy(); tu = st == 1; td = st == 2
    if v is not None:
        kl, ks = gates(v, M); tu = tu & kl; td = td & ks
    sk = None
    if skip_morning:
        et = pd.to_datetime(d["ts"]).dt.tz_convert("America/New_York")
        sk = ((et.dt.hour * 60 + et.dt.minute).to_numpy()) < 660
    d["trend_up"] = tu; d["trend_down"] = td
    return B.backtest(d, "scale_be", "both", False, "orb", 0, T1, T2, ORS, ORE, 0.0, CUT, "stop",
                      eod_min=EOD, vwap_cap=vcap, skip_mask=sk)


def line(tag, tr, eq=False):
    r = tr["net_R"].to_numpy()
    if len(r) < 30:
        print(f"  {tag:12} n={len(r)} (<30 — too rare to matter)"); return
    L = tr[tr.direction == "long"]["net_R"].to_numpy(); S = tr[tr.direction == "short"]["net_R"].to_numpy()
    both = len(L) > 5 and L.mean() > 0 and len(S) > 5 and S.mean() > 0
    lo = loci(r)
    t = tr.copy(); t["year"] = pd.to_datetime(t["entry_time"], utc=True).dt.tz_convert("America/New_York").dt.year
    yrs = [(int(y), g["net_R"].mean()) for y, g in t.groupby("year") if len(g) >= 10]
    pos = sum(1 for _, e in yrs if e > 0); tot = len(yrs); neg = [y for y, e in yrs if e <= 0]
    t = t.sort_values("entry_time").reset_index(drop=True); k = int(len(t) * 0.7)
    IN = t.iloc[:k]["net_R"].to_numpy(); OUT = t.iloc[k:]["net_R"].to_numpy()
    g = "PASS" if (both and lo > 0 and tot and pos >= 0.7 * tot and OUT.mean() > 0) else "fail"
    sl = "" if eq else f" 2x {slip2x(tr, eq).mean():+.3f}"
    print(f"  {tag:12} n={len(r):>4} exp {r.mean():+.3f} PF {V.pf(r):>5.2f} win {100*np.mean(r>0):>2.0f}% "
          f"DD {V.maxdd(r):>+5.0f} CI {lo:+.3f} {g} | yr +{pos}/{tot}{' NEG=' + str(neg) if neg else ''} "
          f"| OOS {IN.mean():+.3f}->{OUT.mean():+.3f}{sl}")


def sweep(con):
    for sym in ["NQ", "QQQ", "SPY"]:
        eq = sym in ("QQQ", "SPY")
        bars = B._externals(con, hs_db.bars(con, "5m", "full", sym=sym), sym)
        d = H.compute_state(bars, H.P()); d.attrs["sym"] = sym
        M = feats(d)
        print(f"\n#### {sym} 5m — SMC order-block / FVG confluence filter ####")
        line("STACK", run(d), eq)
        for v in VARIANTS:
            line("+" + v, run(d, v, M), eq)


def additive(con):
    ks = [2.0, 1.8, 1.6, 1.4, 1.2, 1.0]
    for sym in ("NQ", "QQQ"):
        bars = B._externals(con, hs_db.bars(con, "5m", "full", sym=sym), sym)
        d = H.compute_state(bars, H.P()); d.attrs["sym"] = sym
        M = feats(d)
        vo = [(len(t := run(d, vcap=k)), t["net_R"].mean()) for k in ks]
        vs = sorted(vo); ns = np.array([x[0] for x in vs]); es = np.array([x[1] for x in vs])
        for v in VARIANTS:
            print(f"\n==== {sym}: +{v} ADDITIVITY vs vwap-cap frontier ====")
            for k in ks:
                r = run(d, v, M, vcap=k)["net_R"].to_numpy()
                if len(r) < 25:
                    print(f"  {v} + vwap k={k}  n={len(r):>4} (<25)"); continue
                e_vo = float(np.interp(len(r), ns, es))
                print(f"  {v} + vwap k={k}  n={len(r):>4} exp {r.mean():+.3f} | vwap-only@n {e_vo:+.3f} | delta {r.mean() - e_vo:+.3f}")
            base = run(d, skip_morning=True)["net_R"]; comb = run(d, v, M, skip_morning=True)["net_R"]
            print(f"  -- on top of skip<11:00 -- skip11 n={len(base)} exp {base.mean():+.3f} || "
                  f"skip11+{v} n={len(comb)} exp {comb.mean():+.3f}")


def main():
    con = hs_db.connect()
    additive(con) if "--additive" in sys.argv[1:] else sweep(con)
    con.close()


if __name__ == "__main__":
    main()
