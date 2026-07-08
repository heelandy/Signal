#!/usr/bin/env python3
"""
F34b — WALK-FORWARD the capped-target candidate (F34): structure stop + a FIXED-R target cap (full
position), vs the current unlimited TRAIL. Same gate as every graduated lever (F25b stop / F27b exit):
both sides>0 AND CI>0 AND >=70% of years positive AND 70/30 OOS-out>0 AND survives 2x slippage —
on NQ+QQQ+SPY+ES+GC 5m RTH. Tests cap = 2R / 3R / 4R so the cap level is chosen by robustness, not luck.

    python research/orb_cap_walkforward.py [SYM ...]
"""
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "engine"))
import numpy as np, pandas as pd
import hs_db, hs_harness as H, hs_backtest as B, hs_validate as V
from orb_optimize import state

rng = np.random.default_rng(7)


def loci(r):
    return np.percentile(rng.choice(r, (3000, len(r)), replace=True).mean(1), 5) if len(r) else 0.0


def run(d, mode, cap=4.0):
    st = d["st_state"].to_numpy(); d["trend_up"] = st == 1; d["trend_down"] = st == 2
    return B.backtest(d, mode, "both", False, "orb", 0, 1.0, cap, 570, 600, 0.0, 900, "stop",
                      eod_min=958, vwap_cap=2.0, stop_mode="struct")


def line(tag, tr, slip2=None):
    r = tr["net_R"].to_numpy()
    if len(r) < 30:
        print(f"    {tag:18} n={len(r)} (<30)"); return
    L = tr[tr.direction == "long"]["net_R"].to_numpy(); S = tr[tr.direction == "short"]["net_R"].to_numpy()
    both = len(L) > 5 and L.mean() > 0 and len(S) > 5 and S.mean() > 0
    lo = loci(r)
    t = tr.copy(); t["year"] = pd.to_datetime(t["entry_time"], utc=True).dt.tz_convert("America/New_York").dt.year
    yrs = [(int(y), g["net_R"].mean()) for y, g in t.groupby("year") if len(g) >= 10]
    pos = sum(1 for _, e in yrs if e > 0); tot = len(yrs); neg = [y for y, e in yrs if e <= 0]
    t = t.sort_values("entry_time").reset_index(drop=True); k = int(len(t) * 0.7)
    OUT = t.iloc[k:]["net_R"].to_numpy(); IN = t.iloc[:k]["net_R"].to_numpy()
    s2 = f" 2xslip {slip2:+.3f}" if slip2 is not None else ""
    g = "PASS" if (both and lo > 0 and tot and pos >= 0.7 * tot and OUT.mean() > 0 and (slip2 is None or slip2 > 0)) else "FAIL"
    print(f"    {tag:18} n={len(r):>4} exp {r.mean():+.3f} PF {V.pf(r):>5.2f} CI {lo:+.3f} "
          f"both={'Y' if both else 'n'} yrs +{pos}/{tot}{(' NEG'+str(neg)) if neg else ''} "
          f"OOS {IN.mean():+.2f}->{OUT.mean():+.2f}{s2} {g}")


def main():
    syms = [s.upper() for s in (sys.argv[1:] or ["NQ", "QQQ", "SPY", "ES", "GC"])]
    bslip = B.SLIP_TICKS
    for sym in syms:
        d = state(sym, "5m")
        print(f"\n######## {sym} 5m STACK — capped-target walk-forward ########")
        line("trail (PROD ref)", run(d, "trail"))
        for cap in (2.0, 3.0, 4.0):
            B.SLIP_TICKS = bslip * 2
            tr2 = run(d, "tp2_full", cap); s2 = tr2["net_R"].mean()
            B.SLIP_TICKS = bslip
            line(f"cap {cap:.0f}R", run(d, "tp2_full", cap), slip2=s2)
    B.SLIP_TICKS = bslip


if __name__ == "__main__":
    main()
