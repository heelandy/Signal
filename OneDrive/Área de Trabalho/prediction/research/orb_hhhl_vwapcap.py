#!/usr/bin/env python3
"""
QUICK RESEARCH: are the two graduated 5m edges ADDITIVE? HH/HL structure gate (F20) + VWAP-extension cap
(F16, k=2.0), on 5m NQ+QQQ+SPY. Four configs: PRODUCTION, HH/HL only, CAP only, BOTH. Gate = both sides >0
AND lower-90%-CI >0. "Additive" = BOTH beats the better single filter (not just redundant / over-culled).

    python research/orb_hhhl_vwapcap.py [SYM ...]   (default NQ QQQ SPY)
"""
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "engine"))
import numpy as np
import hs_db, hs_harness as H, hs_backtest as B, hs_validate as V

rng = np.random.default_rng(7)
ORS, ORE, CUT, T1, T2, EOD, KCAP = 570, 600, 900, 1.0, 4.0, 958, 2.0


def metrics(tr):
    r = tr["net_R"].to_numpy()
    lo = np.percentile(rng.choice(r, (3000, len(r)), replace=True).mean(1), 5) if len(r) else 0.0
    L = tr[tr.direction == "long"]["net_R"].to_numpy(); S = tr[tr.direction == "short"]["net_R"].to_numpy()
    return dict(n=len(tr), exp=r.mean() if len(r) else 0, pf=V.pf(r),
                win=100*np.mean(r > 0) if len(r) else 0, maxdd=V.maxdd(r) if len(r) else 0, loCI=lo,
                both=(len(L) > 5 and L.mean() > 0 and len(S) > 5 and S.mean() > 0))


def run(d, gate, cap):
    if gate == "hhhl":
        st = d["st_state"].to_numpy(); d["trend_up"] = st == 1; d["trend_down"] = st == 2
    else:
        d["trend_up"] = d["_tu"]; d["trend_down"] = d["_td"]
    return B.backtest(d, "scale_be", "both", False, "orb", 0, T1, T2, ORS, ORE, 0.0, CUT, "stop",
                      eod_min=EOD, vwap_cap=cap)


def line(tag, m, prod_n):
    g = "PASS" if (m["both"] and m["loCI"] > 0) else "fail"
    print(f"  {tag:18} n={m['n']:>4} ({100*m['n']/max(prod_n,1):>3.0f}%) exp {m['exp']:>+7.3f} "
          f"PF {m['pf']:>4.2f} win {m['win']:>4.1f} DD {m['maxdd']:>+6.1f} CI {m['loCI']:>+7.3f} {g}")


def main():
    syms = [s.upper() for s in (sys.argv[1:] or ["NQ", "QQQ", "SPY"])]
    con = hs_db.connect()
    for sym in syms:
        bars = B._externals(con, hs_db.bars(con, "5m", "full", sym=sym), sym)
        d = H.compute_state(bars, H.P()); d.attrs["sym"] = sym
        d["_tu"] = d["trend_up"].to_numpy().copy(); d["_td"] = d["trend_down"].to_numpy().copy()
        prod = metrics(run(d, "prod", 0.0))
        hh   = metrics(run(d, "hhhl", 0.0))
        cap  = metrics(run(d, "prod", KCAP))
        both = metrics(run(d, "hhhl", KCAP))
        print(f"\n############ {sym} 5m ############")
        line("PRODUCTION", prod, prod["n"])
        line("HH/HL only", hh, prod["n"])
        line("VWAP-cap only", cap, prod["n"])
        line("BOTH", both, prod["n"])
        best_single = max(hh["exp"], cap["exp"])
        add = both["both"] and both["loCI"] > 0 and both["exp"] > best_single
        print(f"  -> BOTH exp {both['exp']:+.3f} vs best-single {best_single:+.3f}  ->  "
              f"{'ADDITIVE' if add else 'redundant/over-culled'}  (keeps {100*both['n']/max(prod['n'],1):.0f}% of trades)")
    con.close()


if __name__ == "__main__":
    main()
