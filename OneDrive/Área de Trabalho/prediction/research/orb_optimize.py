#!/usr/bin/env python3
"""
HIGHSTRIKE research — push the ORB profit factor into the 1.40-1.75 "real edge" zone while
keeping expectancy >= +0.05R, win-rate up, both signals positive, and lower 90% CI > 0.

Principled levers (not param-mining): breakout STRENGTH (clear OR by k*ATR -> kills false breaks),
TIME-OF-DAY cutoff (morning breaks are cleaner), reward, exit. Validates the winner on 5m too.

    python research/orb_optimize.py
"""
import sys, os, itertools
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import numpy as np, pandas as pd
import hs_db, hs_harness as H, hs_backtest as B, hs_validate as V

rng = np.random.default_rng(7)


def metrics(tr):
    r = tr["net_R"].to_numpy()
    if len(r) < 30:
        return None
    lo = np.percentile(rng.choice(r, (3000, len(r)), replace=True).mean(1), 5)
    L = tr[tr.direction == "long"]["net_R"].to_numpy()
    S = tr[tr.direction == "short"]["net_R"].to_numpy()
    return dict(n=len(tr), exp=r.mean(), pf=V.pf(r), win=100*np.mean(r > 0), maxdd=V.maxdd(r), loCI=lo,
                Ln=len(L), Lexp=L.mean() if len(L) else 0, Sn=len(S), Sexp=S.mean() if len(S) else 0,
                both=(len(L) > 5 and L.mean() > 0 and len(S) > 5 and S.mean() > 0))


def state(sym, tf):
    con = hs_db.connect()
    d = H.compute_state(B._externals(con, hs_db.bars(con, tf, "full", sym=sym), sym), H.P())
    d.attrs["sym"] = sym; con.close()
    return d


def main():
    d = state("NQ", "15m")
    print(f"ORB optimize — NQ 15m ({len(d):,} bars). Targets: PF 1.40-1.75, exp>=+0.05R, both>0, CI>0\n")
    grid = list(itertools.product([0.0, 0.1, 0.25, 0.4], [780, 720, 690, 660], [2.0, 3.0, 4.0], ["scale_be", "tp2_full"]))
    rows = []
    for brk, tod, rr, ex in grid:
        mm = metrics(B.backtest(d, ex, "both", False, "orb", 0, None, rr, 570, 600, brk, tod))
        if mm is None:
            continue
        mm.update(brk=brk, tod=tod, rr=rr, ex=ex)
        rows.append(mm)
    qual = [r for r in rows if r["pf"] >= 1.40 and r["exp"] >= 0.05 and r["both"] and r["loCI"] > 0]
    qual.sort(key=lambda r: (-r["pf"] if r["pf"] <= 1.75 else -1.0, -r["exp"]))
    hdr = f"{'brk':>4} {'tod':>4} {'rr':>3} {'exit':9} {'n':>4} {'exp':>7} {'PF':>5} {'win%':>5} {'maxDD':>7} {'loCI':>7}"
    print(f"QUALIFYING configs (PF>=1.40, exp>=0.05, both>0, CI>0): {len(qual)}")
    print(hdr); print("-" * len(hdr))
    for r in qual[:12]:
        print(f"{r['brk']:>4.2f} {r['tod']:>4} {r['rr']:>3.0f} {r['ex']:9} {r['n']:>4} {r['exp']:>+7.3f} "
              f"{r['pf']:>5.2f} {r['win']:>5.1f} {r['maxdd']:>7.1f} {r['loCI']:>+7.3f}")
    if not qual:
        print("  none — ORB cannot reach PF>=1.40 robustly with these levers.")
        best_all = max(rows, key=lambda r: r["pf"])
        print(f"  best PF achievable: {best_all['pf']:.2f} (brk={best_all['brk']} tod={best_all['tod']} "
              f"rr={best_all['rr']} {best_all['ex']}) exp {best_all['exp']:+.3f}")
        return
    best = qual[0]
    print(f"\nBEST: brk={best['brk']} tod={best['tod']} rr={best['rr']} exit={best['ex']}")
    print(f"  exp {best['exp']:+.3f}R | PF {best['pf']:.2f} | win {best['win']:.1f}% | maxDD {best['maxdd']:.1f}R | "
          f"CI {best['loCI']:+.3f} | long {best['Lexp']:+.2f}({best['Ln']}) short {best['Sexp']:+.2f}({best['Sn']})")
    # robustness: same config on 5m
    print("\n5m robustness check of BEST config ...")
    d5 = state("NQ", "5m")
    m5 = metrics(B.backtest(d5, best["ex"], "both", False, "orb", 0, None, best["rr"], 570, 600, best["brk"], best["tod"]))
    if m5:
        print(f"  NQ 5m: n={m5['n']} exp {m5['exp']:+.3f}R PF {m5['pf']:.2f} win {m5['win']:.1f}% "
              f"maxDD {m5['maxdd']:.1f}R CI {m5['loCI']:+.3f} both={'YES' if m5['both'] else 'no'} "
              f"-> {'HOLDS' if (m5['pf']>=1.30 and m5['exp']>=0.05 and m5['both']) else 'WEAKER on 5m'}")


if __name__ == "__main__":
    main()
