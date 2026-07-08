#!/usr/bin/env python3
"""
RESEARCH (F40 candidate) — the two SECONDARY orthogonal leads from orb_stack_features.py:
  compress = ATR(7)/ATR(28) prior bar, corr -0.29  (LOWER = squeeze/contraction before the break = BETTER)
  adx      = local trend strength prior bar, corr +0.20  (HIGHER = better)
Both sign-consistent across NQ+QQQ+SPY. Full gauntlet per [[highstrike-test-every-research]]:
  1. gate sweep (threshold) — both sides+, CI>0, per-year, OOS, 2x slip, NQ+QQQ+SPY
  2. ADDITIVITY vs the vwap-cap frontier (the F37 control — is it orthogonal to extension?)
  3. ADDITIVITY on top of the F38 skip<11:00 gate (is compress just a TIME-of-day proxy, or independent?)

  compress GATE = take only if compress <= thr (require a squeeze).  adx GATE = take only if adx >= thr.
  (engine skip_mask: skip the signal when the quality condition fails -> stay flat, a later break can fire.)

    python research/orb_stack_squeeze.py             (sweeps)
    python research/orb_stack_squeeze.py --additive  (frontier-lift vs vwap-cap AND vs skip<11:00)
"""
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "engine"))
import numpy as np, pandas as pd
import hs_db, hs_harness as H, hs_backtest as B, hs_validate as V
from orb_kernel_filter import loci, slip2x, ORS, ORE, CUT, T1, T2, EOD, KCAP


def feats(d):
    trr = H.true_range(d["high"], d["low"], d["close"])
    compress = (H.rma(trr, 7) / H.rma(trr, 28)).shift(1).to_numpy()
    adx = d["adx"].shift(1).to_numpy()
    et = pd.to_datetime(d["ts"]).dt.tz_convert("America/New_York")
    tod = (et.dt.hour * 60 + et.dt.minute).to_numpy()
    return compress, adx, tod


def run(d, kind=None, thr=None, vcap=KCAP, skip_morning=False):
    st = d["st_state"].to_numpy(); d["trend_up"] = st == 1; d["trend_down"] = st == 2
    compress, adx, tod = feats(d)
    sk = np.zeros(len(d), bool)
    if skip_morning:
        sk |= tod < 660
    if kind == "compress":
        sk |= np.nan_to_num(compress, nan=1e9) > thr      # NaN warmup -> treat as fail-the-squeeze (skip)
    elif kind == "adx":
        sk |= np.nan_to_num(adx, nan=-1.0) < thr
    sk = sk if sk.any() else None
    return B.backtest(d, "scale_be", "both", False, "orb", 0, T1, T2, ORS, ORE, 0.0, CUT, "stop",
                      eod_min=EOD, vwap_cap=vcap, skip_mask=sk)


def line(tag, tr, eq=False):
    r = tr["net_R"].to_numpy()
    if len(r) < 30:
        print(f"  {tag:14} n={len(r)} (<30)"); return
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
    print(f"  {tag:14} n={len(r):>4} exp {r.mean():+.3f} PF {V.pf(r):>5.2f} win {100*np.mean(r>0):>2.0f}% "
          f"DD {V.maxdd(r):>+5.0f} CI {lo:+.3f} {g} | yr +{pos}/{tot}{' NEG=' + str(neg) if neg else ''} "
          f"| OOS {IN.mean():+.3f}->{OUT.mean():+.3f}{sl}")


def sweep(con):
    for sym in ["NQ", "QQQ", "SPY"]:
        eq = sym in ("QQQ", "SPY")
        bars = B._externals(con, hs_db.bars(con, "5m", "full", sym=sym), sym)
        d = H.compute_state(bars, H.P()); d.attrs["sym"] = sym
        print(f"\n#### {sym} 5m — squeeze (compress<=thr) + adx(>=thr) gate sweeps ####")
        line("STACK", run(d), eq)
        for thr in (1.05, 1.0, 0.95, 0.90, 0.85):
            line(f"compress<={thr}", run(d, "compress", thr), eq)
        for thr in (20, 25, 30, 35):
            line(f"adx>={thr}", run(d, "adx", thr), eq)


def additive(con):
    ks = [2.0, 1.8, 1.6, 1.4, 1.2, 1.0]
    probes = [("compress", 0.95), ("adx", 30)]
    for sym in ("NQ", "QQQ"):
        bars = B._externals(con, hs_db.bars(con, "5m", "full", sym=sym), sym)
        d = H.compute_state(bars, H.P()); d.attrs["sym"] = sym
        vo = [(len(t := run(d, vcap=k)), t["net_R"].mean()) for k in ks]
        vs = sorted(vo); ns = np.array([x[0] for x in vs]); es = np.array([x[1] for x in vs])
        for kind, thr in probes:
            print(f"\n==== {sym}: {kind}{'<=' if kind == 'compress' else '>='}{thr} ADDITIVITY vs vwap-cap frontier ====")
            for k in ks:
                r = run(d, kind, thr, vcap=k)["net_R"].to_numpy()
                e_vo = float(np.interp(len(r), ns, es))
                print(f"  {kind} + vwap k={k}  n={len(r):>4} exp {r.mean():+.3f} | vwap-only@n {e_vo:+.3f} | delta {r.mean() - e_vo:+.3f}")
        # is compress just a TIME proxy? does it add on top of the F38 skip<11:00 gate?
        base = run(d, skip_morning=True)["net_R"]
        comb = run(d, "compress", 0.95, skip_morning=True)["net_R"]
        print(f"  -- compress on top of skip<11:00 --  skip11 n={len(base)} exp {base.mean():+.3f}  ||  "
              f"skip11+compress<=0.95 n={len(comb)} exp {comb.mean():+.3f}")


def main():
    con = hs_db.connect()
    additive(con) if "--additive" in sys.argv[1:] else sweep(con)
    con.close()


if __name__ == "__main__":
    main()
