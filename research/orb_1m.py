#!/usr/bin/env python3
"""
HIGHSTRIKE F32 — does the stack work on the 1-MINUTE chart, and with which OR window?
NQ 1m, adopted config (struct gate computed on 1m pivots + VWAP cap 2.0 + struct stop + 2ATR trail),
all three sessions. Per session: the standard validated OR window vs shorter 1m-native windows,
plus a 2x-slippage stress on the standard window (1m = more fills near the noise floor).

    python research/orb_1m.py
"""
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "engine"))
import numpy as np, pandas as pd
import hs_db, hs_harness as H, hs_backtest as B, hs_validate as V
from orb_optimize import state

rng = np.random.default_rng(7)
KCAP = 2.0
# session -> (cut, tradeday, eod, [(window tag, or_s, or_e), ...])
SESSIONS = [
    ("RTH",    900, False, 958, [("OR 09:30-10:00 (std)", 570, 600),
                                 ("OR 09:30-09:45",       570, 585),
                                 ("OR 09:30-09:35",       570, 575)]),
    ("Asia",   540, True,  540, [("OR 19:00-20:00 (std)", 60, 120),
                                 ("OR 19:00-19:30",       60, 90),
                                 ("OR 19:00-19:15",       60, 75)]),
    ("London", 840, True,  840, [("OR 03:00-03:30 (std)", 540, 570),
                                 ("OR 03:00-03:15",       540, 555),
                                 ("OR 03:00-03:05",       540, 545)]),
]


def state_1m():
    """1m isn't materialized in the hive bars dataset — build harness state straight from the
    continuous-1m parquet view (same columns as bars, ts_utc aliased to ts)."""
    con = hs_db.connect()
    b = con.execute("SELECT ts_utc AS ts, open, high, low, close, volume FROM nq_1m ORDER BY ts").df()
    d = H.compute_state(B._externals(con, b, "NQ"), H.P())
    d.attrs["sym"] = "NQ"
    con.close()
    return d


def run(d, ors, ore, cut, tdy, eod):
    return B.backtest(d, "trail", "both", False, "orb", 0, 1.0, 4.0, ors, ore, 0.0, cut, "stop",
                      tradeday=tdy, eod_min=eod, vwap_cap=KCAP, stop_mode="struct")


def loci(r):
    return np.percentile(rng.choice(r, (3000, len(r)), replace=True).mean(1), 5) if len(r) else 0.0


def report(tag, tr, min_n=30):
    if tr is None or len(tr) < min_n:
        print(f"    {tag:26} n={0 if tr is None else len(tr):>4}  (<{min_n} — no read)")
        return
    r = tr["net_R"].to_numpy()
    L = tr[tr.direction == "long"]["net_R"].to_numpy()
    S = tr[tr.direction == "short"]["net_R"].to_numpy()
    both = len(L) > 5 and L.mean() > 0 and len(S) > 5 and S.mean() > 0
    lo = loci(r)
    t = tr.copy()
    t["year"] = pd.to_datetime(t["entry_time"], utc=True).dt.tz_convert("America/New_York").dt.year
    yrs = [(int(y), g["net_R"].mean()) for y, g in t.groupby("year") if len(g) >= 8]
    pos = sum(1 for _, e in yrs if e > 0); tot = len(yrs)
    g = "PASS" if (both and lo > 0 and tot and pos >= 0.7 * tot) else "----"
    print(f"    {tag:26} n={len(r):>4} exp {r.mean():+.3f} PF {V.pf(r):>4.2f} win {100*np.mean(r>0):>2.0f}% "
          f"CI {lo:+.3f}  L {L.mean() if len(L) else 0:+.2f}({len(L)}) S {S.mean() if len(S) else 0:+.2f}({len(S)})  "
          f"yrs +{pos}/{tot}  {g}")


def main():
    d = state_1m()
    print(f"NQ 1m — {len(d):,} bars. Adopted stack on the 1-minute chart (5m benchmarks: "
          f"RTH +0.383R / Asia +0.396R / London +0.339R, all PASS).\n")
    for name, cut, tdy, eod, windows in SESSIONS:
        print(f"\n  {name}")
        for tag, ors, ore in windows:
            report(tag, run(d, ors, ore, cut, tdy, eod))
        B.SLIP_MULT = 2.0
        tag, ors, ore = windows[0]
        report("std window @ 2x slip", run(d, ors, ore, cut, tdy, eod))
        B.SLIP_MULT = 1.0


if __name__ == "__main__":
    main()
