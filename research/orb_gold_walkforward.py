#!/usr/bin/env python3
"""
HIGHSTRIKE F30 confirm — WALK-FORWARD the GOLD (GC) stack candidates from orb_gold.py.
The 5m structure stack passed the basic gate ONLY in US-morning liquidity: COMEX open 08:20-08:50
(+0.451R, PF 2.87, 12/16 yrs) and US equity open 09:30-10:00 (+0.438R, PF 2.68, 15/15 yrs).
Gate them fully: per-year + 70/30 OOS + 2x/3x slippage. Also tests the two windows COMBINED
(they overlap 09:30-13:30 — expect correlation, NOT diversification like RTH/Asia/London on NQ).

    python research/orb_gold_walkforward.py
"""
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "engine"))
import numpy as np, pandas as pd
import hs_db, hs_harness as H, hs_backtest as B, hs_validate as V
from orb_optimize import state

rng = np.random.default_rng(7)
T1, T2, KCAP = 1.0, 4.0, 2.0
WINDOWS = [("COMEX open 08:20-08:50", 860, 890, 1170), ("US equity 09:30-10:00", 930, 960, 1260)]


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
    t = tr.copy(); t["year"] = pd.to_datetime(t["entry_time"], utc=True).dt.tz_convert("America/New_York").dt.year
    yrs = [(int(y), g["net_R"].mean()) for y, g in t.groupby("year") if len(g) >= 8]
    pos = sum(1 for _, e in yrs if e > 0); tot = len(yrs); neg = [y for y, e in yrs if e <= 0]
    t = t.sort_values("entry_time").reset_index(drop=True); k = int(len(t) * 0.7)
    IN = t.iloc[:k]["net_R"].to_numpy(); OUT = t.iloc[k:]["net_R"].to_numpy()
    g = "PASS" if (both and lo > 0 and tot and pos >= 0.7 * tot and OUT.mean() > 0) else "FAIL"
    print(f"    {tag:20} n={len(r):>4} exp {r.mean():+.3f} PF {V.pf(r):>4.2f} CI {lo:+.3f} L {L.mean():+.2f} S {S.mean():+.2f}"
          f" | yrs +{pos}/{tot}{(' NEG' + str(neg)) if neg else ''} | OOS {IN.mean():+.3f}->{OUT.mean():+.3f} {g}")


def main():
    base_slip = B.SLIP_MULT
    d = state("GC", "5m")
    print(f"\n################  GC 5m STACK — gold walk-forward  ################")
    trs = {}
    for name, ors, ore, cut in WINDOWS:
        print(f"\n  {name} ET")
        B.SLIP_MULT = base_slip
        tr = stack(d, ors, ore, cut); trs[name] = tr
        line("full (2-tick slip)", tr)
        for mult in (2, 3):
            B.SLIP_MULT = base_slip * mult
            t2 = stack(d, ors, ore, cut); r = t2["net_R"].to_numpy()
            print(f"    {f'stress {mult}x slip':20} n={len(r):>4} exp {r.mean():+.3f} PF {V.pf(r):>4.2f}  "
                  f"{'still +' if r.mean() > 0 else 'NEGATIVE'}")
        B.SLIP_MULT = base_slip
    # combined + correlation (overlapping windows -> expect HIGH corr; this is a robustness read, not diversification)
    a, b = trs[WINDOWS[0][0]], trs[WINDOWS[1][0]]
    both = pd.concat([a, b]).sort_values("entry_time").reset_index(drop=True)
    print(f"\n  COMBINED (both windows, one account)")
    line("combined", both)
    da = a.copy(); da["d"] = pd.to_datetime(da["entry_time"], utc=True).dt.tz_convert("America/New_York").dt.normalize()
    db = b.copy(); db["d"] = pd.to_datetime(db["entry_time"], utc=True).dt.tz_convert("America/New_York").dt.normalize()
    pa = da.groupby("d")["net_R"].sum(); pb = db.groupby("d")["net_R"].sum()
    j = pd.concat([pa, pb], axis=1, keys=["a", "b"]).dropna()
    if len(j) > 20:
        print(f"    daily-PnL corr (days both traded, n={len(j)}): {j['a'].corr(j['b']):+.2f}")


if __name__ == "__main__":
    main()
