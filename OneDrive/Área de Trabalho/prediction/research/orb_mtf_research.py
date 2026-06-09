#!/usr/bin/env python3
"""
HIGHSTRIKE research — push the FOUR characteristics on the ORB entry via multi-timeframe
confirmation. The four (want UP / down for maxDD): expectancy (R), profit factor, win%,
max drawdown (R) — plus the gate (lower 90% CI > 0) and BOTH-signals-positive.

MTF confirmation = require N of {1h, 4h, Daily} to agree (EMA50>EMA200 stack, prior closed
bar -> no lookahead) with the breakout direction. Sweeps N=0..3 x {scale_be, tp2_full}.

    python research/orb_mtf_research.py [SYM=NQ] [TF=15m]
Computes the harness state + MTF once, then the trade sim is cheap per config.
"""
import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import numpy as np, pandas as pd
import hs_db, hs_harness as H, hs_backtest as B, hs_validate as V

rng = np.random.default_rng(7)


def metrics(tr):
    r = tr["net_R"].to_numpy()
    lo = np.percentile(rng.choice(r, (3000, len(r)), replace=True).mean(1), 5) if len(r) else 0.0
    L = tr[tr.direction == "long"]["net_R"].to_numpy()
    S = tr[tr.direction == "short"]["net_R"].to_numpy()
    return dict(n=len(tr), exp=r.mean() if len(r) else 0, pf=V.pf(r), win=100*np.mean(r > 0) if len(r) else 0,
                maxdd=V.maxdd(r) if len(r) else 0, loCI=lo,
                Lexp=L.mean() if len(L) else 0, Sexp=S.mean() if len(S) else 0,
                Ln=len(L), Sn=len(S),
                both=(len(L) > 5 and L.mean() > 0 and len(S) > 5 and S.mean() > 0))


def main():
    sym = (sys.argv[1] if len(sys.argv) > 1 else "NQ").upper()
    tf = sys.argv[2] if len(sys.argv) > 2 else "15m"
    con = hs_db.connect()
    bars = B._externals(con, hs_db.bars(con, tf, "full", sym=sym), sym)
    print(f"ORB MTF research — {sym} {tf}: computing state + MTF over {len(bars):,} bars ...")
    d = H.compute_state(bars, H.P()); d.attrs["sym"] = sym
    d = B.attach_mtf(con, sym, d)
    con.close()

    hdr = f"{'exit':9} {'mtf':>3} {'n':>5} {'exp':>7} {'PF':>5} {'win%':>5} {'maxDD':>7} {'loCI':>7} {'L':>6} {'S':>6} both"
    print("\n" + hdr); print("-" * len(hdr))
    rows = []
    for ex in ["scale_be", "tp2_full"]:
        for m in [0, 1, 2, 3]:
            mm = metrics(B.backtest(d, ex, "both", False, "orb", m))
            mm["exit"] = ex; mm["mtf"] = m; rows.append(mm)
            print(f"{ex:9} {m:>3} {mm['n']:>5} {mm['exp']:>+7.3f} {mm['pf']:>5.2f} {mm['win']:>5.1f} "
                  f"{mm['maxdd']:>7.1f} {mm['loCI']:>+7.3f} {mm['Lexp']:>+6.2f} {mm['Sexp']:>+6.2f} "
                  f"{'YES' if mm['both'] else '-'}")
    valid = [r for r in rows if r["both"] and r["loCI"] > 0]
    print("\n" + "=" * 60)
    if valid:
        best = max(valid, key=lambda r: r["exp"] + 0.1 * r["pf"])   # favor expectancy, tie-break PF
        print(f"BEST robust (both>0 & lower-CI>0): exit={best['exit']} mtf={best['mtf']}")
        print(f"  expectancy {best['exp']:+.3f}R | PF {best['pf']:.2f} | win {best['win']:.1f}% | "
              f"maxDD {best['maxdd']:.1f}R | loCI {best['loCI']:+.3f}")
        print(f"  long {best['Lexp']:+.3f}R (n={best['Ln']})   short {best['Sexp']:+.3f}R (n={best['Sn']})")
        base = next(r for r in rows if r["exit"] == best["exit"] and r["mtf"] == 0)
        print(f"  vs no-MTF baseline: exp {base['exp']:+.3f}->{best['exp']:+.3f}  PF {base['pf']:.2f}->{best['pf']:.2f}  "
              f"win {base['win']:.1f}->{best['win']:.1f}%  maxDD {base['maxdd']:.1f}->{best['maxdd']:.1f}R  "
              f"(trades {base['n']}->{best['n']})")
    else:
        print("No config with both-sides-positive AND lower CI > 0.")

    # ─── OR-window x reward sweep (the structural ORB levers; tp2_full, no MTF) ───
    hdr2 = f"{'OR window':>10} {'TP2':>4} {'n':>5} {'exp':>7} {'PF':>5} {'win%':>5} {'maxDD':>7} {'loCI':>7} both"
    print("\n\nOR-WINDOW x REWARD sweep (exit=tp2_full, mtf=0):")
    print(hdr2); print("-" * len(hdr2))
    rows2 = []
    for lbl, s, e in [("0930-0945", 570, 585), ("0930-1000", 570, 600), ("0930-1030", 570, 630)]:
        for rr in [1.5, 2.0, 3.0]:
            mm = metrics(B.backtest(d, "tp2_full", "both", False, "orb", 0, None, rr, s, e))
            mm["lbl"], mm["rr"] = lbl, rr; rows2.append(mm)
            print(f"{lbl:>10} {rr:>4.1f} {mm['n']:>5} {mm['exp']:>+7.3f} {mm['pf']:>5.2f} {mm['win']:>5.1f} "
                  f"{mm['maxdd']:>7.1f} {mm['loCI']:>+7.3f} {'YES' if mm['both'] else '-'}")
    v2 = [r for r in rows2 if r["both"] and r["loCI"] > 0]
    print("\n" + "=" * 60)
    if v2:
        b2 = max(v2, key=lambda r: r["exp"] + 0.1 * r["pf"])
        print(f"BEST OR/RR (both>0 & CI>0): OR {b2['lbl']} TP2={b2['rr']}R -> "
              f"exp {b2['exp']:+.3f}R | PF {b2['pf']:.2f} | win {b2['win']:.1f}% | "
              f"maxDD {b2['maxdd']:.1f}R | loCI {b2['loCI']:+.3f}")
    else:
        print("OR/RR: no both-positive & CI>0 config.")


if __name__ == "__main__":
    main()
