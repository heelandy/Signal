#!/usr/bin/env python3
"""
RESEARCH (F43 candidate) — LIQUIDITY family (agenda item 3). Sweeps-as-ENTRY are dead (F18/19) and pdlvl_brk
was WEAK in the F38 study, so the prior is thin — but test the two distinct liquidity-CONFLUENCE reads as stack
filters (never done): a recent liquidity SWEEP before the break, and the breakout TAKING OUT the prior-day
high/low (the actual external stop pool). Causal (prior-bar / prior-day). Full gauntlet + additivity vs vwap-cap
+ on top of F38 (time) and F41 (order-block).

  swept   : require the harness liquidity-sweep-active in the trade dir (bull_sweep_active long / bear short)
  pdsweep : breakout takes out prior-day high (long: OR-high > prior-day RTH high) / low (short: OR-low < PDL)

    python research/orb_stack_liquidity.py            (gate test)
    python research/orb_stack_liquidity.py --additive (frontier-lift + on top of F38/F41)
"""
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "engine"))
import numpy as np, pandas as pd
import hs_db, hs_harness as H, hs_backtest as B, hs_validate as V
from orb_kernel_filter import loci, slip2x, ORS, ORE, CUT, T1, T2, EOD, KCAP

VARIANTS = ("swept", "pdsweep")


def feats(d):
    et = pd.to_datetime(d["ts"]).dt.tz_convert("America/New_York")
    date = et.dt.normalize().dt.tz_localize(None); mins = et.dt.hour * 60 + et.dt.minute
    base = pd.DataFrame({"date": date.to_numpy(), "high": d["high"].to_numpy(), "low": d["low"].to_numpy(),
                         "mins": mins.to_numpy()})
    org = base[(base.mins >= ORS) & (base.mins < ORE)].groupby("date").agg(orh=("high", "max"), orl=("low", "min"))
    rth = base[(base.mins >= ORS) & (base.mins < 960)].groupby("date").agg(rh=("high", "max"), rl=("low", "min"))
    g = org.join(rth); g["pdh"] = g["rh"].shift(1); g["pdl"] = g["rl"].shift(1)
    ds = pd.Series(date.to_numpy())
    orh = ds.map(g["orh"]).to_numpy(); orl = ds.map(g["orl"]).to_numpy()
    pdh = ds.map(g["pdh"]).to_numpy(); pdl = ds.map(g["pdl"]).to_numpy()
    swept_l = d["bull_sweep_active"].shift(1).fillna(False).to_numpy().astype(bool)
    swept_s = d["bear_sweep_active"].shift(1).fillna(False).to_numpy().astype(bool)
    masks = {"swept": (swept_l, swept_s), "pdsweep": (orh > pdh, orl < pdl)}
    return masks, mins.to_numpy()


def run(d, v=None, M=None, vcap=KCAP, extra=None):
    st = d["st_state"].to_numpy(); tu = st == 1; td = st == 2
    if v is not None:
        kl, ks = M[0][v]; tu = tu & kl; td = td & ks
    sk = None
    if extra == "skip11":
        sk = M[1] < 660
    elif extra == "ob":
        tu = tu & d["in_bull_ob"].shift(1).fillna(False).to_numpy().astype(bool)
        td = td & d["in_bear_ob"].shift(1).fillna(False).to_numpy().astype(bool)
    d["trend_up"] = tu; d["trend_down"] = td
    return B.backtest(d, "scale_be", "both", False, "orb", 0, T1, T2, ORS, ORE, 0.0, CUT, "stop",
                      eod_min=EOD, vwap_cap=vcap, skip_mask=sk)


def line(tag, tr, eq=False):
    r = tr["net_R"].to_numpy()
    if len(r) < 30:
        print(f"  {tag:13} n={len(r)} (<30)"); return
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
    print(f"  {tag:13} n={len(r):>4} exp {r.mean():+.3f} PF {V.pf(r):>5.2f} win {100*np.mean(r>0):>2.0f}% "
          f"DD {V.maxdd(r):>+5.0f} CI {lo:+.3f} {g} | yr +{pos}/{tot}{' NEG=' + str(neg) if neg else ''} "
          f"| OOS {IN.mean():+.3f}->{OUT.mean():+.3f}{sl}")


def sweep(con):
    for sym in ["NQ", "QQQ", "SPY"]:
        eq = sym in ("QQQ", "SPY")
        bars = B._externals(con, hs_db.bars(con, "5m", "full", sym=sym), sym)
        d = H.compute_state(bars, H.P()); d.attrs["sym"] = sym
        M = feats(d)
        print(f"\n#### {sym} 5m — Liquidity confluence (sweep / prior-day-level take-out) ####")
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
            for tag, ex in [("skip<11:00", "skip11"), ("+ob(F41)", "ob")]:
                base = run(d, extra=ex)["net_R"]; comb = run(d, v, M, extra=ex)["net_R"]
                print(f"  -- on top of {tag} -- base n={len(base)} exp {base.mean():+.3f} || +{v} n={len(comb)} exp {comb.mean():+.3f}")


def main():
    con = hs_db.connect()
    additive(con) if "--additive" in sys.argv[1:] else sweep(con)
    con.close()


if __name__ == "__main__":
    main()
