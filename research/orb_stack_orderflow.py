#!/usr/bin/env python3
"""
RESEARCH (F48 candidate) — ORDER FLOW family (agenda item: the one 'untested' family). TRUE order flow needs
tick / bid-ask / trade-delta data we DON'T have — only OHLCV 1m bars. The OHLCV proxies that exist (raw volume
F11, bar body F12/13) are already DEAD. The remaining honest proxy = CUMULATIVE VOLUME DELTA (CVD): sign each
bar's volume by its close-location-value clv = ((c-l)-(h-c))/(h-l) ∈ [-1,1] (≈ net buy/sell pressure), cumulate
per RTH session. Test CVD confluence on the stack, causal (prior bar), full gauntlet + additivity vs vwap-cap
+ on top of the F45 combined (skip<11:00 + order-block).

  cvd_agree : CVD rising (net buying) for longs / falling for shorts   (order-flow momentum confirmation)
  cvd_lvl   : session CVD positive for longs / negative for shorts

    python research/orb_stack_orderflow.py            (gate test)
    python research/orb_stack_orderflow.py --additive (frontier-lift + on top of F45)
"""
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "engine"))
import numpy as np, pandas as pd
import hs_db, hs_harness as H, hs_backtest as B, hs_validate as V
from orb_kernel_filter import loci, slip2x, ORS, ORE, CUT, T1, T2, EOD, KCAP

VARIANTS = ("cvd_agree", "cvd_lvl")
SLOPE_N = 6


def feats(d):
    h, l, c, vol = (d[k].to_numpy(float) for k in ("high", "low", "close", "volume"))
    et = pd.to_datetime(d["ts"]).dt.tz_convert("America/New_York")
    date = et.dt.normalize().dt.tz_localize(None); mins = (et.dt.hour * 60 + et.dt.minute).to_numpy()
    rng = np.where(h > l, h - l, np.nan)
    clv = np.nan_to_num(((c - l) - (h - c)) / rng, nan=0.0)          # +1 close at high, -1 at low
    sv = pd.Series(clv * vol)
    cvd = sv.groupby(date.to_numpy()).cumsum()                       # session-cumulative volume delta
    cvd_slope = (cvd - cvd.shift(SLOPE_N)).shift(1).to_numpy()       # prior-bar slope (causal)
    cvd_lvl = cvd.shift(1).to_numpy()
    masks = {"cvd_agree": (cvd_slope > 0, cvd_slope < 0), "cvd_lvl": (cvd_lvl > 0, cvd_lvl < 0)}
    return masks, mins


def run(d, v=None, M=None, vcap=KCAP, f45=False):
    st = d["st_state"].to_numpy(); tu = st == 1; td = st == 2
    if f45:
        tu = tu & d["in_bull_ob"].shift(1).fillna(False).to_numpy().astype(bool)
        td = td & d["in_bear_ob"].shift(1).fillna(False).to_numpy().astype(bool)
    if v is not None:
        kl, ks = M[0][v]; tu = tu & kl; td = td & ks
    sk = None
    if f45:
        et = pd.to_datetime(d["ts"]).dt.tz_convert("America/New_York")
        sk = ((et.dt.hour * 60 + et.dt.minute).to_numpy()) < 660
    d["trend_up"] = tu; d["trend_down"] = td
    return B.backtest(d, "scale_be", "both", False, "orb", 0, T1, T2, ORS, ORE, 0.0, CUT, "stop",
                      eod_min=EOD, vwap_cap=vcap, skip_mask=sk)


def fline(tag, tr, eq=False):
    r = tr["net_R"].to_numpy()
    if len(r) < 30:
        print(f"  {tag:12} n={len(r)} (<30)"); return
    L = tr[tr.direction == "long"]["net_R"].to_numpy(); S = tr[tr.direction == "short"]["net_R"].to_numpy()
    both = len(L) > 5 and L.mean() > 0 and len(S) > 5 and S.mean() > 0
    lo = loci(r)
    t = tr.copy(); t["year"] = pd.to_datetime(t["entry_time"], utc=True).dt.tz_convert("America/New_York").dt.year
    yrs = [(int(y), g["net_R"].mean()) for y, g in t.groupby("year") if len(g) >= 10]
    pos = sum(1 for _, e in yrs if e > 0); tot = len(yrs)
    sl = "" if eq else f" 2x {slip2x(tr, eq).mean():+.3f}"
    g = "PASS" if (both and lo > 0) else "fail"
    print(f"  {tag:12} n={len(r):>4} exp {r.mean():+.3f} PF {V.pf(r):>5.2f} win {100*np.mean(r>0):>2.0f}% "
          f"DD {V.maxdd(r):>+5.0f} CI {lo:+.3f} {g} | yr +{pos}/{tot}{sl}")


def sweep(con):
    for sym in ["NQ", "QQQ", "SPY"]:
        eq = sym in ("QQQ", "SPY")
        bars = B._externals(con, hs_db.bars(con, "5m", "full", sym=sym), sym)
        d = H.compute_state(bars, H.P()); d.attrs["sym"] = sym
        M = feats(d)
        print(f"\n#### {sym} 5m — Order-flow proxy (CVD) confluence ####")
        fline("STACK", run(d), eq)
        for v in VARIANTS:
            fline("+" + v, run(d, v, M), eq)


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
            base = run(d, f45=True)["net_R"]; comb = run(d, v, M, f45=True)["net_R"]
            print(f"  -- on top of F45 (skip11+ob) -- base n={len(base)} exp {base.mean():+.3f} || +{v} n={len(comb)} exp {comb.mean():+.3f}")


def main():
    con = hs_db.connect()
    additive(con) if "--additive" in sys.argv[1:] else sweep(con)
    con.close()


if __name__ == "__main__":
    main()
