#!/usr/bin/env python3
"""
F64 — WHERE to take TP2: R-multiple sweep + trail, on NQ/QQQ/SPY/GC (5m RTH = US-morning for GC).

The shipped exit is full-to-4R-cap on the struct stop (F34b). This asks: is 4R the right place, or
does a nearer/farther cap win? Sweep tp2_rr {2,3,4,5,6} (full-to-cap) + the ATR-chandelier trail, same
gauntlet (exp net R>0, CIlo>0, both sides>0, >=70% yrs+, OOS>0). Also prints the median price reach of
the winners (R -> ATR -> $) so 'where' is concrete.

    python research/orb_tp2.py [SYM ...]      (default NQ QQQ SPY GC)
"""
import sys, os, gc
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "engine"))
import numpy as np, pandas as pd
import hs_db, hs_harness as H, hs_backtest as B, hs_validate as V

rng = np.random.default_rng(7)
ORS, ORE, CUT, EOD, DELAY, SB = 570, 600, 900, 958, 60, 0.25


def run(d, t1, t2, mode="tp2_full"):
    d["trend_up"] = True; d["trend_down"] = True
    return B.backtest(d, mode, "both", False, "orb", 0, t1, t2, ORS, ORE, 0.0, CUT, "close",
                      eod_min=EOD, stop_mode="struct", entry_delay=DELAY, strong_body=SB,
                      ft_confirm=True, dir_seq=True)


def gaunt(tag, tr):
    if not len(tr) or len(tr) < 30:
        print(f"  {tag:14} n={len(tr):>4} (skip)"); return
    r = tr["net_R"].to_numpy()
    t = tr.copy(); t["y"] = pd.to_datetime(t["entry_time"], utc=True).dt.tz_convert("America/New_York").dt.year
    yrs = [(y, g["net_R"].mean()) for y, g in t.groupby("y") if len(g) >= 8]
    pos = sum(1 for _, e in yrs if e > 0); tot = len(yrs)
    t = t.sort_values("entry_time"); k = int(len(t) * 0.7); OUT = t.iloc[k:]["net_R"].mean()
    L, S = tr.net_R[tr.direction == "long"], tr.net_R[tr.direction == "short"]
    both = len(L) > 5 and L.mean() > 0 and len(S) > 5 and S.mean() > 0
    ci = np.percentile(rng.choice(r, (2000, len(r)), replace=True).mean(1), 5)
    g = "PASS" if (r.mean() > 0 and ci > 0 and tot and pos >= 0.7 * tot and OUT > 0 and both) else "fail"
    # winners' median favorable reach in R (mfe) -> 'where price actually goes'
    mfe = tr["mfe_R"].median()
    print(f"  {tag:14} n={len(r):>4} expR {r.mean():+.3f} PF {V.pf(r):>4.2f} win {100*np.mean(r>0):>2.0f}% "
          f"CI {ci:+.3f} totR {r.sum():>+5.0f} yr+{pos}/{tot} OOS {OUT:+.3f} medMFE {mfe:>4.1f}R {g}")


def main():
    syms = [s.upper() for s in (sys.argv[1:] or ["NQ", "QQQ", "SPY", "GC"])]
    con = hs_db.connect()
    for sym in syms:
        bars = B._externals(con, hs_db.bars(con, "5m", "rth", sym=sym), sym)
        d = H.compute_state(bars, H.P()); d.attrs["sym"] = sym; del bars; gc.collect()
        atr_med = float(d["atr14"].median())
        print(f"\n######## {sym} 5m RTH — TP1/TP2 placement (median ATR {atr_med:.2f}) ########")
        print("  -- FULL to TP2 cap (no TP1 scale) --")
        for t2 in (2, 3, 4, 5, 6):
            gaunt(f"cap {t2}R", run(d, 1.0, t2))
        print("  -- SCALE 50% at TP1, runner to TP2 (the options TP1=debit cap) --")
        for t1, t2 in ((1.0, 3.0), (1.0, 4.0), (1.5, 3.0), (1.5, 4.0), (2.0, 4.0)):
            gaunt(f"TP1 {t1}/TP2 {t2}", run(d, t1, t2, mode="scale_be"))
        gaunt("trail 2.5ATR", run(d, 1.0, 4, mode="trail"))
        del d; gc.collect()
    con.close()
    print("\nmedMFE = median favorable excursion of all trades (how far price typically runs) — read the")
    print("TP2 cap against it. PASS = exp net>0 + CIlo>0 + both sides + >=70% yrs+ + OOS>0.")


if __name__ == "__main__":
    main()
