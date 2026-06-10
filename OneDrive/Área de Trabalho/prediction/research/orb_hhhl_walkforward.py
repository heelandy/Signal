#!/usr/bin/env python3
"""
WALK-FORWARD (F15 protocol) on the HH/HL st_state STRUCTURE GATE — F17's #1 lead. Replaces the EMA up/down
trend filter with the harness swing-structure state (long requires st_state==1 = HH+HL, short st_state==2 =
LL+LH); range gate held at prod ADX20, everything else production. It's CAUSAL / signal-level (5-bar confirmed
pivots) — unlike the clean-day filter it has no same-bar lookahead — so it earns the real robustness test.

Per sym/TF: full-sample gate (both sides >0 AND lower-90%-CI >0), per-YEAR positive count (which years fail),
and the 70/30 OOS time split (does the edge hold out of sample?). HH/HL vs PRODUCTION (EMA 21/50) side by side.

    python research/orb_hhhl_walkforward.py [SYM ...]   (default NQ QQQ SPY)
"""
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "engine"))
import numpy as np, pandas as pd
import hs_db, hs_harness as H, hs_backtest as B, hs_validate as V

rng = np.random.default_rng(7)
ORS, ORE, CUT, T1, T2, EOD = 570, 600, 900, 1.0, 4.0, 958


def loci(r):
    return np.percentile(rng.choice(r, (3000, len(r)), replace=True).mean(1), 5) if len(r) else 0.0


def run(d, brk, gate):
    if gate == "hhhl":
        st = d["st_state"].to_numpy()
        d["trend_up"] = st == 1; d["trend_down"] = st == 2
    else:
        d["trend_up"] = d["_tu"]; d["trend_down"] = d["_td"]
    return B.backtest(d, "scale_be", "both", False, "orb", 0, T1, T2, ORS, ORE, brk, CUT, "stop", eod_min=EOD)


def report(tag, tr):
    r = tr["net_R"].to_numpy()
    L = tr[tr.direction == "long"]["net_R"].to_numpy(); S = tr[tr.direction == "short"]["net_R"].to_numpy()
    both = len(L) > 5 and L.mean() > 0 and len(S) > 5 and S.mean() > 0
    lo = loci(r)
    t = tr.copy()
    t["year"] = pd.to_datetime(t["entry_time"], utc=True).dt.tz_convert("America/New_York").dt.year
    yrs = [(int(y), g["net_R"].mean(), len(g)) for y, g in t.groupby("year") if len(g) >= 10]
    pos = sum(1 for _, e, _ in yrs if e > 0); tot = len(yrs)
    neg = [y for y, e, _ in yrs if e <= 0]
    t = t.sort_values("entry_time").reset_index(drop=True); k = int(len(t) * 0.7)
    IN = t.iloc[:k]["net_R"].to_numpy(); OUT = t.iloc[k:]["net_R"].to_numpy()
    g = "PASS" if (both and lo > 0) else "fail"
    print(f"  {tag:6} n={len(r):>4} exp {r.mean():+.3f} PF {V.pf(r):>4.2f} win {100*np.mean(r>0):>2.0f}% "
          f"DD {V.maxdd(r):>+5.0f} CI {lo:+.3f} {g} | yrs +{pos}/{tot}{'  NEG=' + str(neg) if neg else ''} | "
          f"OOS in {IN.mean():+.3f}/{V.pf(IN):.2f} -> out {OUT.mean():+.3f}/{V.pf(OUT):.2f}")


def main():
    syms = [s.upper() for s in (sys.argv[1:] or ["NQ", "QQQ", "SPY"])]
    con = hs_db.connect()
    for sym in syms:
        for tf in ("5m", "15m"):
            brk = 0.0 if tf == "5m" else 0.25
            bars = B._externals(con, hs_db.bars(con, tf, "full", sym=sym), sym)
            d = H.compute_state(bars, H.P()); d.attrs["sym"] = sym
            d["_tu"] = d["trend_up"].to_numpy().copy(); d["_td"] = d["trend_down"].to_numpy().copy()
            print(f"\n############ {sym} {tf}  (HH/HL structure gate vs production EMA trend) ############")
            report("PROD", run(d, brk, "prod"))
            report("HH/HL", run(d, brk, "hhhl"))
    con.close()


if __name__ == "__main__":
    main()
