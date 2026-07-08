#!/usr/bin/env python3
"""
RESEARCH (F39 candidate) — does the F38 TIME-OF-DAY edge (skip the opening hour) transfer to the ASIA and
LONDON sessions? F38 validated "skip RTH stack entries before ~11:00 ET" (= skip the first 60min after the
09:30-10:00 OR closes). The mechanism — the HH/HL st_state gate needs post-open intraday swings to MATURE —
should transfer to any session open. Test the analog: skip the first N min after EACH session's OR closes.

Sessions (trade-day mins, 18:00 ET = 0 for off-hours; matches orb_asia/london_walkforward):
  RTH    OR 09:30-10:00 (570-600), cut 15:00, eod 15:58   [reference — F38 validated delay=60]
  Asia   OR 19:00-20:00 (60-120),  cut 540 (03:00),        futures only
  London OR 03:00-03:30 (540-570), cut 840 (08:00),        futures only
Off-hours = NQ + ES only (equities don't trade). Full gauntlet incl. 2x slip + the additivity/frontier-lift
control vs vwap-cap (the F37 test — per [[highstrike-test-every-research]] every lead clears this).

    python research/orb_session_tod.py             (sweep + per-year + OOS + 2x slip)
    python research/orb_session_tod.py --additive  (frontier-lift control, NQ+ES)
"""
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "engine"))
import numpy as np, pandas as pd
import hs_db, hs_harness as H, hs_backtest as B, hs_validate as V
from orb_kernel_filter import loci, slip2x

T1, T2, KCAP = 1.0, 4.0, 2.0
SESS = {"RTH":    dict(ors=570, ore=600, cut=900, eod=958, td=False),
        "Asia":   dict(ors=60,  ore=120, cut=540, eod=540, td=True),
        "London": dict(ors=540, ore=570, cut=840, eod=840, td=True)}
DELAYS = [0, 30, 60, 90, 120]


def tod_min(d, td):
    et = pd.to_datetime(d["ts"]).dt.tz_convert("America/New_York")
    if td:
        return (((et.dt.hour - 18) % 24) * 60 + et.dt.minute).to_numpy()
    return (et.dt.hour * 60 + et.dt.minute).to_numpy()


def run(d, ses, delay, vcap=KCAP):
    c = SESS[ses]; st = d["st_state"].to_numpy(); d["trend_up"] = st == 1; d["trend_down"] = st == 2
    sk = (tod_min(d, c["td"]) < c["ore"] + delay) if delay > 0 else None
    return B.backtest(d, "scale_be", "both", False, "orb", 0, T1, T2, c["ors"], c["ore"], 0.0, c["cut"],
                      "stop", tradeday=c["td"], eod_min=c["eod"], vwap_cap=vcap, skip_mask=sk)


def line(tag, tr, eq=False):
    r = tr["net_R"].to_numpy()
    if len(r) < 30:
        print(f"  {tag:13} n={len(r)} (<30)"); return
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
    print(f"  {tag:13} n={len(r):>4} exp {r.mean():+.3f} PF {V.pf(r):>5.2f} win {100*np.mean(r>0):>2.0f}% "
          f"DD {V.maxdd(r):>+5.0f} CI {lo:+.3f} {g} | yr +{pos}/{tot}{' NEG=' + str(neg) if neg else ''} "
          f"| OOS {IN.mean():+.3f}->{OUT.mean():+.3f}{sl}")


def sweep(con):
    for ses in ("RTH", "Asia", "London"):
        syms = ["NQ", "ES"] if ses != "RTH" else ["NQ", "ES", "QQQ", "SPY"]
        for sym in syms:
            eq = sym in ("QQQ", "SPY")
            bars = B._externals(con, hs_db.bars(con, "5m", "full", sym=sym), sym)
            d = H.compute_state(bars, H.P()); d.attrs["sym"] = sym
            print(f"\n#### {ses} {sym} 5m — skip first N min after OR close ####")
            for delay in DELAYS:
                line(f"skip+{delay}m" if delay else "STACK", run(d, ses, delay), eq)


def additive(con):
    print("==== ADDITIVITY: does skip+60m lift the vwap-cap frontier in Asia/London? (NQ + ES) ====")
    ks = [2.0, 1.8, 1.6, 1.4, 1.2, 1.0]
    for ses in ("Asia", "London"):
        for sym in ("NQ", "ES"):
            bars = B._externals(con, hs_db.bars(con, "5m", "full", sym=sym), sym)
            d = H.compute_state(bars, H.P()); d.attrs["sym"] = sym
            vo = []
            for k in ks:
                r = run(d, ses, 0, k)["net_R"].to_numpy(); vo.append((len(r), r.mean()))
            vs = sorted(vo); ns = np.array([x[0] for x in vs]); es = np.array([x[1] for x in vs])
            print(f"  ---- {ses} {sym} ----")
            for k in ks:
                r = run(d, ses, 60, k)["net_R"].to_numpy(); n_s, e_s = len(r), r.mean()
                e_vo = float(np.interp(n_s, ns, es))
                print(f"  skip+60 + vwap k={k}  n={n_s:>4} exp {e_s:+.3f}  |  vwap-only@n {e_vo:+.3f}  |  delta {e_s - e_vo:+.3f}")
            print()


def main():
    con = hs_db.connect()
    additive(con) if "--additive" in sys.argv[1:] else sweep(con)
    con.close()


if __name__ == "__main__":
    main()
