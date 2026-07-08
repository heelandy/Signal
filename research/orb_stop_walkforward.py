#!/usr/bin/env python3
"""
HIGHSTRIKE F25b — WALK-FORWARD the tighter/structure STOP lead (graduate it or kill it).
The 5m stack with a STRUCTURE-anchored stop (last HH/HL swing) or a 1.5-ATR cap beat the production
OR-edge+2.5ATR stop (exp +0.74->+1.00R) — but PF 5.5 is curve-fit territory. Gate it like everything else:
both sides>0 AND CI>0 AND positive most years AND 70/30 OOS holds AND survives 2x slippage — on NQ+QQQ+SPY+ES 5m.

    python research/orb_stop_walkforward.py [SYM ...]   (default NQ QQQ SPY ES)
"""
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "engine"))
import numpy as np, pandas as pd
import hs_db, hs_harness as H, hs_backtest as B, hs_validate as V
from orb_optimize import state

rng = np.random.default_rng(7)


def loci(r):
    return np.percentile(rng.choice(r, (3000, len(r)), replace=True).mean(1), 5) if len(r) else 0.0


def run(d, stop_mode="or", slmax=None):
    st = d["st_state"].to_numpy(); d["trend_up"] = st == 1; d["trend_down"] = st == 2
    base = B.SL_MAX_ATR
    if slmax is not None:
        B.SL_MAX_ATR = slmax
    tr = B.backtest(d, "scale_be", "both", False, "orb", 0, 1.0, 4.0, 570, 600, 0.0, 900, "stop",
                    eod_min=958, vwap_cap=2.0, stop_mode=stop_mode)
    B.SL_MAX_ATR = base
    return tr


def line(tag, tr):
    r = tr["net_R"].to_numpy()
    if len(r) < 30:
        print(f"    {tag:20} n={len(r)} (<30)"); return
    L = tr[tr.direction == "long"]["net_R"].to_numpy(); S = tr[tr.direction == "short"]["net_R"].to_numpy()
    both = len(L) > 5 and L.mean() > 0 and len(S) > 5 and S.mean() > 0
    lo = loci(r); rp = tr["risk_pts"].mean()
    t = tr.copy(); t["year"] = pd.to_datetime(t["entry_time"], utc=True).dt.tz_convert("America/New_York").dt.year
    yrs = [(int(y), g["net_R"].mean()) for y, g in t.groupby("year") if len(g) >= 10]
    pos = sum(1 for _, e in yrs if e > 0); tot = len(yrs); neg = [y for y, e in yrs if e <= 0]
    t = t.sort_values("entry_time").reset_index(drop=True); k = int(len(t) * 0.7)
    IN = t.iloc[:k]["net_R"].to_numpy(); OUT = t.iloc[k:]["net_R"].to_numpy()
    g = "PASS" if (both and lo > 0 and tot and pos >= 0.7 * tot and OUT.mean() > 0) else "FAIL"
    print(f"    {tag:20} n={len(r):>4} exp {r.mean():+.3f} PF {V.pf(r):>4.2f} CI {lo:+.3f} risk {rp:4.0f}pt "
          f"both={'Y' if both else 'n'} yrs +{pos}/{tot}{(' NEG' + str(neg)) if neg else ''} "
          f"OOS {IN.mean():+.3f}->{OUT.mean():+.3f} {g}")


def main():
    syms = [s.upper() for s in (sys.argv[1:] or ["NQ", "QQQ", "SPY", "ES"])]
    bslip = B.SLIP_TICKS
    for sym in syms:
        d = state(sym, "5m")
        print(f"\n######## {sym} 5m STACK — stop walk-forward ########")
        line("OR-edge 2.5ATR prod", run(d, "or"))
        line("STRUCTURE swing", run(d, "struct"))
        line("OR 1.5ATR cap", run(d, "or", 1.5))
        for mult in (2,):                                  # slippage stress on the structure candidate
            B.SLIP_TICKS = bslip * mult
            tr = run(d, "struct"); r = tr["net_R"].to_numpy()
            print(f"    {'STRUCT 2x-slip':20} n={len(r):>4} exp {r.mean():+.3f} PF {V.pf(r):>4.2f}  "
                  f"{'still +' if r.mean() > 0 else 'NEGATIVE'}")
        B.SLIP_TICKS = bslip


if __name__ == "__main__":
    main()
