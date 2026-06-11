#!/usr/bin/env python3
"""
HIGHSTRIKE — WALK-FORWARD + stress on the Asia-session STACK (Finding 22 confirm).
The Asia 5m STACK (st_state HH/HL gate + VWAP-cap k2) passes the basic gate with PF 2.4-2.8 — in the
curve-fit zone. Before it can be a candidate it must survive ALL of:
  (a) positive in most years            (time stability)
  (b) 70/30 chronological OOS split holds (no front-loaded edge)
  (c) a 2x / 3x SLIPPAGE stress         (Asia liquidity is thinner than RTH -> worse stop fills)
  (d) a SECOND futures instrument (ES)   (Asia equities don't trade -> ES is the only cross-check)

    python research/orb_asia_walkforward.py
"""
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "engine"))
import numpy as np, pandas as pd
import hs_db, hs_harness as H, hs_backtest as B, hs_validate as V
from orb_optimize import state

rng = np.random.default_rng(7)
T1, T2, KCAP = 1.0, 4.0, 2.0
WINDOWS = [("19:00-20:00", 60, 120, 540), ("19:00-19:30", 60, 90, 540), ("18:00-18:30", 0, 30, 480)]


def loci(r):
    return np.percentile(rng.choice(r, (3000, len(r)), replace=True).mean(1), 5) if len(r) else 0.0


def stack(d, ors, ore, cut):
    st = d["st_state"].to_numpy(); d["trend_up"] = st == 1; d["trend_down"] = st == 2
    return B.backtest(d, "scale_be", "both", False, "orb", 0, T1, T2, ors, ore, 0.0, cut, "stop",
                      tradeday=True, eod_min=cut, vwap_cap=KCAP)


def line(tag, tr):
    r = tr["net_R"].to_numpy()
    if len(r) < 30:
        print(f"    {tag:20} n={len(r)} (<30)"); return
    L = tr[tr.direction == "long"]["net_R"].to_numpy(); S = tr[tr.direction == "short"]["net_R"].to_numpy()
    both = len(L) > 5 and L.mean() > 0 and len(S) > 5 and S.mean() > 0
    lo = loci(r)
    t = tr.copy()
    t["year"] = pd.to_datetime(t["entry_time"], utc=True).dt.tz_convert("America/New_York").dt.year
    yrs = [(int(y), g["net_R"].mean()) for y, g in t.groupby("year") if len(g) >= 8]
    pos = sum(1 for _, e in yrs if e > 0); tot = len(yrs); neg = [y for y, e in yrs if e <= 0]
    t = t.sort_values("entry_time").reset_index(drop=True); k = int(len(t) * 0.7)
    IN = t.iloc[:k]["net_R"].to_numpy(); OUT = t.iloc[k:]["net_R"].to_numpy()
    g = "PASS" if (both and lo > 0 and tot and pos >= 0.7 * tot and OUT.mean() > 0) else "FAIL"
    print(f"    {tag:20} n={len(r):>4} exp {r.mean():+.3f} PF {V.pf(r):>4.2f} CI {lo:+.3f} "
          f"L {L.mean():+.2f} S {S.mean():+.2f} | yrs +{pos}/{tot}{(' NEG='+str(neg)) if neg else ''} | "
          f"OOS in {IN.mean():+.3f}/{V.pf(IN):.2f} -> out {OUT.mean():+.3f}/{V.pf(OUT):.2f}  {g}")


def main():
    base_slip = B.SLIP_TICKS
    for sym in ("NQ", "ES"):
        d = state(sym, "5m")
        print(f"\n################  {sym} 5m STACK — Asia walk-forward  ################")
        for name, ors, ore, cut in WINDOWS:
            print(f"\n  Asia {name} ET")
            B.SLIP_TICKS = base_slip
            line("full (2-tick slip)", stack(d, ors, ore, cut))
            for mult in (2, 3):
                B.SLIP_TICKS = base_slip * mult
                tr = stack(d, ors, ore, cut); r = tr["net_R"].to_numpy()
                print(f"    {f'stress {mult}x slip':20} n={len(r):>4} exp {r.mean():+.3f} PF {V.pf(r):>4.2f}  "
                      f"{'still +' if r.mean() > 0 else 'NEGATIVE'}")
            B.SLIP_TICKS = base_slip


if __name__ == "__main__":
    main()
