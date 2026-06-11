#!/usr/bin/env python3
"""
HIGHSTRIKE F27b — WALK-FORWARD the momentum-exit lead (graduate it or kill it).
F27: on the 5m stack, a TRAIL (2-3 ATR) or a "run-more" scale (take 33% @ TP1 1.5R, TP2 6R) beat the production
scale-50%@1R/BE/4R exit. PF 5-7 in-sample → gate it like the stop: both sides>0 AND CI>0 AND positive most years
AND 70/30 OOS holds AND survives 2x slippage, on NQ+QQQ+SPY+ES 5m. Exit isolated (production OR-edge stop baseline).

    python research/orb_exit_walkforward.py [SYM ...]   (default NQ QQQ SPY ES)
"""
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "engine"))
import numpy as np, pandas as pd
import hs_db, hs_harness as H, hs_backtest as B, hs_validate as V
from orb_optimize import state

rng = np.random.default_rng(7)


def loci(r):
    return np.percentile(rng.choice(r, (3000, len(r)), replace=True).mean(1), 5) if len(r) else 0.0


def run(d, mode="scale_be", tp1=1.0, tp2=4.0, sf=0.5, trailm=None):
    st = d["st_state"].to_numpy(); d["trend_up"] = st == 1; d["trend_down"] = st == 2
    base = B.TRAIL_MULT
    if trailm is not None:
        B.TRAIL_MULT = trailm
    tr = B.backtest(d, mode, "both", False, "orb", 0, tp1, tp2, 570, 600, 0.0, 900, "stop",
                    eod_min=958, vwap_cap=2.0, scale_frac=sf)
    B.TRAIL_MULT = base
    return tr


def line(tag, tr):
    r = tr["net_R"].to_numpy()
    if len(r) < 30:
        print(f"    {tag:20} n={len(r)} (<30)"); return
    L = tr[tr.direction == "long"]["net_R"].to_numpy(); S = tr[tr.direction == "short"]["net_R"].to_numpy()
    both = len(L) > 5 and L.mean() > 0 and len(S) > 5 and S.mean() > 0
    lo = loci(r)
    t = tr.copy(); t["year"] = pd.to_datetime(t["entry_time"], utc=True).dt.tz_convert("America/New_York").dt.year
    yrs = [(int(y), g["net_R"].mean()) for y, g in t.groupby("year") if len(g) >= 10]
    pos = sum(1 for _, e in yrs if e > 0); tot = len(yrs); neg = [y for y, e in yrs if e <= 0]
    t = t.sort_values("entry_time").reset_index(drop=True); k = int(len(t) * 0.7)
    IN = t.iloc[:k]["net_R"].to_numpy(); OUT = t.iloc[k:]["net_R"].to_numpy()
    g = "PASS" if (both and lo > 0 and tot and pos >= 0.7 * tot and OUT.mean() > 0) else "FAIL"
    print(f"    {tag:20} n={len(r):>4} exp {r.mean():+.3f} PF {V.pf(r):>4.2f} win {100*np.mean(r>0):>2.0f}% "
          f"CI {lo:+.3f} both={'Y' if both else 'n'} yrs +{pos}/{tot}{(' NEG' + str(neg)) if neg else ''} "
          f"OOS {IN.mean():+.3f}->{OUT.mean():+.3f} {g}")


def main():
    syms = [s.upper() for s in (sys.argv[1:] or ["NQ", "QQQ", "SPY", "ES"])]
    bslip = B.SLIP_TICKS
    for sym in syms:
        d = state(sym, "5m")
        print(f"\n######## {sym} 5m STACK — exit walk-forward (OR-edge stop baseline) ########")
        line("scale_be prod", run(d, "scale_be", 1.0, 4.0, 0.5))
        line("trail 2ATR", run(d, "trail", trailm=2.0))
        line("trail 3ATR", run(d, "trail", trailm=3.0))
        line("run-more 33/1.5/6", run(d, "scale_be", 1.5, 6.0, 0.33))
        for tag, kw in (("trail2 2x-slip", dict(mode="trail", trailm=2.0)),
                        ("run-more 2x-slip", dict(mode="scale_be", tp1=1.5, tp2=6.0, sf=0.33))):
            B.SLIP_TICKS = bslip * 2
            tr = run(d, **kw); r = tr["net_R"].to_numpy()
            print(f"    {tag:20} n={len(r):>4} exp {r.mean():+.3f} PF {V.pf(r):>4.2f}  "
                  f"{'still +' if r.mean() > 0 else 'NEGATIVE'}")
            B.SLIP_TICKS = bslip


if __name__ == "__main__":
    main()
