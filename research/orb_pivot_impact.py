#!/usr/bin/env python3
"""
HIGHSTRIKE — does the stack edge SURVIVE TradingView's exact pivot rule? (offline reconcile of st_state)
The harness used strict-> pivots; TradingView ta.pivothigh allows a tie on the LEFT (qa/pivot_check.py: ~16%
of pivots differ). The Pine STRUCTURE/ASIA scripts use the real ta.pivothigh, so the harness should run with
pivot_tie='tv' to match. Re-run the 5m stack walk-forward under BOTH rules on NQ+QQQ+SPY: if 'tv' still PASSES
(both sides+, CI+, every year+, OOS holds) AND tracks 'strict', the edge is rule-robust and live==backtest is
secured up to confirming ta.pivothigh's tie rule itself (a free 2-min Data-Window spot-check).

    python research/orb_pivot_impact.py [SYM ...]
"""
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "engine"))
import numpy as np, pandas as pd
import hs_db, hs_harness as H, hs_backtest as B, hs_validate as V

rng = np.random.default_rng(7)


def loci(r):
    return np.percentile(rng.choice(r, (3000, len(r)), replace=True).mean(1), 5) if len(r) else 0.0


def state_tie(con, sym, tie):
    p = H.P(pivot_tie=tie)
    d = H.compute_state(B._externals(con, hs_db.bars(con, "5m", "full", sym=sym), sym), p)
    d.attrs["sym"] = sym
    return d


def stack(d):
    st = d["st_state"].to_numpy(); d["trend_up"] = st == 1; d["trend_down"] = st == 2
    return B.backtest(d, "scale_be", "both", False, "orb", 0, 1.0, 4.0, 570, 600, 0.0, 900, "stop",
                      eod_min=958, vwap_cap=2.0)


def line(tag, tr):
    r = tr["net_R"].to_numpy()
    if len(r) < 30:
        print(f"  {tag:14} n={len(r)} (<30)"); return
    L = tr[tr.direction == "long"]["net_R"].to_numpy(); S = tr[tr.direction == "short"]["net_R"].to_numpy()
    both = len(L) > 5 and L.mean() > 0 and len(S) > 5 and S.mean() > 0
    lo = loci(r)
    t = tr.copy(); t["year"] = pd.to_datetime(t["entry_time"], utc=True).dt.tz_convert("America/New_York").dt.year
    yrs = [(int(y), g["net_R"].mean()) for y, g in t.groupby("year") if len(g) >= 10]
    pos = sum(1 for _, e in yrs if e > 0); tot = len(yrs)
    t = t.sort_values("entry_time").reset_index(drop=True); k = int(len(t) * 0.7)
    IN = t.iloc[:k]["net_R"].to_numpy(); OUT = t.iloc[k:]["net_R"].to_numpy()
    g = "PASS" if (both and lo > 0 and tot and pos >= 0.7 * tot and OUT.mean() > 0) else "FAIL"
    print(f"  {tag:14} n={len(r):>4} exp {r.mean():+.3f} PF {V.pf(r):>4.2f} CI {lo:+.3f} both={'Y' if both else 'n'} "
          f"yrs +{pos}/{tot} OOS {IN.mean():+.3f}->{OUT.mean():+.3f} {g}")


def main():
    syms = [s.upper() for s in (sys.argv[1:] or ["NQ", "QQQ", "SPY"])]
    con = hs_db.connect()
    for sym in syms:
        print(f"\n######## {sym} 5m STACK — pivot-rule impact ########")
        line("strict (old)", stack(state_tie(con, sym, "strict")))
        line("tv (=Pine)", stack(state_tie(con, sym, "tv")))
    con.close()


if __name__ == "__main__":
    main()
