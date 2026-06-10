#!/usr/bin/env python3
"""
HIGHSTRIKE research — EXITS & SIZING (Item 3). RESEARCH ONLY. Uses the frozen engine; the only engine
addition is an off-by-default `time_stop` param (reproduces production exactly when 0, like vol_conf).
No Pine file or production default is touched.

  A. EXIT MODE   — scale_be (prod) vs tp2_full (2R/-1R) vs trail (ATR chandelier) at the prod config.
  B. TIME-STOP   — flatten at the close after N bars if the trade hasn't resolved (cut dead trades).
                   Sweep N; adopt only if DD improves WITHOUT killing expectancy on QQQ AND NQ.
  C. SIZING      — fixed-$-RISK per trade (= volatility sizing: fewer contracts when ATR is high) vs
                   fixed-CONTRACTS. The R-based metrics already assume fixed-risk; this quantifies the
                   drawdown efficiency (Calmar) you get from it, so no new knob is needed.

    python research/orb_exits.py [SYM] [TF=15m]
"""
import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import numpy as np, pandas as pd
import hs_backtest as B, hs_validate as V
from orb_optimize import state, metrics


def brk_for(tf):
    return 0.0 if tf in ("1m", "5m") else 0.25


def bt(d, tf, mode="scale_be", time_stop=0):
    return B.backtest(d, mode, "both", False, "orb", 0, None, 4.0, 570, 600, brk_for(tf), 900, "stop",
                      time_stop=time_stop)


def show(lbl, tr):
    m = metrics(tr)
    if m is None:
        print(f"  {lbl:22} (<30 trades)"); return None
    both = "both+" if m["both"] else "ONE<0"
    print(f"  {lbl:22} n={m['n']:4} exp={m['exp']:+.3f} PF={m['pf']:.2f} win={m['win']:4.1f}% "
          f"maxDD={m['maxdd']:6.1f} CI={m['loCI']:+.3f} {both}")
    return m


def run(sym, tf):
    d = state(sym, tf)
    print(f"\n{'='*74}\n{sym} {tf} — exits & sizing (buffer={brk_for(tf)} ATR, all-day, 4R)\n{'='*74}")

    print("A) EXIT MODE")
    base = show("scale_be (prod)", bt(d, tf, "scale_be"))
    show("tp2_full (2R/-1R)", bt(d, tf, "tp2_full"))
    show("trail (ATR chandelier)", bt(d, tf, "trail"))

    print("B) TIME-STOP (flatten at close after N bars if unresolved)")
    show("none (prod)", bt(d, tf, "scale_be", 0))
    for n in (16, 12, 10, 8, 6):
        show(f"time_stop={n} bars", bt(d, tf, "scale_be", n))

    print("C) SIZING — fixed-$-risk (vol sizing) vs fixed-contracts, on the prod trade list")
    tr = bt(d, tf, "scale_be")
    r = tr["net_R"].to_numpy()
    rp = tr["risk_pts"].to_numpy()
    cal_R = r.sum() / abs(V.maxdd(r)) if V.maxdd(r) else float("inf")          # fixed-risk: 1R/trade
    dollar = r * rp                                                            # fixed-lot: $ swings with ATR
    cal_lot = dollar.sum() / abs(V.maxdd(dollar)) if V.maxdd(dollar) else float("inf")
    print(f"  fixed-$-RISK (vol sizing): maxDD {V.maxdd(r):.1f}R  Calmar(total/DD) {cal_R:.2f}")
    print(f"  fixed-CONTRACTS         : risk_pts CV={rp.std()/rp.mean():.2f}  Calmar {cal_lot:.2f}")
    print(f"  -> {'vol sizing smoother (use fixed-% risk)' if cal_R >= cal_lot else 'fixed-lot comparable'}; "
          f"R-metrics already assume fixed-risk.")


def main():
    tf = sys.argv[2] if len(sys.argv) > 2 else "15m"
    syms = [sys.argv[1]] if len(sys.argv) > 1 else ["QQQ", "NQ", "SPY"]
    for s in syms:
        run(s, tf)


if __name__ == "__main__":
    main()
