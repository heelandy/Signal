#!/usr/bin/env python3
"""
RESEARCH: does FADING the false ORB breakout have an edge? (the chart pattern — sweep the OR
edge, fail, reverse). Uses the engine's new off-by-default execm="fade":
  LONG  = price swept BELOW the OR low (clear by k*ATR) then a bar CLOSES back above it
  SHORT = price swept ABOVE the OR high (by k*ATR) then a bar CLOSES back below it
Entry = the reclaim-bar close; stop = the swept OR edge ±buffer (OR-anchored, same min/max-ATR
clamps as the breakout); targets 1R/4R scale_be; EOD-flat. Pine-mirrored OR 0930-1000 / cut 15:00.

Compared head-to-head vs the BREAKOUT (stop) entry. Two trend treatments:
  trend-aligned = engine's EMA gate (fade-long needs uptrend = "buy the failed breakdown in an
                  uptrend"; fade-short needs downtrend) ;  trend-OFF = pure mechanical fade.
Sweep depth k ∈ {0.0, 0.1, 0.25} ATR. Gate = both sides >0 AND lower-90%-CI >0, on NQ AND QQQ.

    python research/orb_false_breakout.py [SYM ...]   (default NQ QQQ)
"""
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "engine"))
import numpy as np
import hs_db, hs_harness as H, hs_backtest as B, hs_validate as V

rng = np.random.default_rng(7)
ORS, ORE, CUT, T1, T2, EOD = 570, 600, 900, 1.0, 4.0, 958


def metrics(tr):
    r = tr["net_R"].to_numpy()
    lo = np.percentile(rng.choice(r, (3000, len(r)), replace=True).mean(1), 5) if len(r) else 0.0
    L = tr[tr.direction == "long"]["net_R"].to_numpy(); S = tr[tr.direction == "short"]["net_R"].to_numpy()
    return dict(n=len(tr), exp=r.mean() if len(r) else 0, pf=V.pf(r),
                win=100 * np.mean(r > 0) if len(r) else 0, maxdd=V.maxdd(r) if len(r) else 0, loCI=lo,
                Lexp=L.mean() if len(L) else 0, Sexp=S.mean() if len(S) else 0, Ln=len(L), Sn=len(S),
                both=(len(L) > 5 and L.mean() > 0 and len(S) > 5 and S.mean() > 0))


def run(d, brk, execm, trend):
    if trend == "off":          # disable the EMA gate (engine applies trend_up/down inside _orb_signals)
        d["trend_up"] = np.ones(len(d), bool); d["trend_down"] = np.ones(len(d), bool)
    else:
        d["trend_up"] = d["_tu"]; d["trend_down"] = d["_td"]
    tr = B.backtest(d, "scale_be", "both", False, "orb", 0, T1, T2, ORS, ORE, brk, CUT, execm, eod_min=EOD)
    return metrics(tr)


def line(tag, m):
    gate = "PASS" if (m["both"] and m["loCI"] > 0) else "fail"
    print(f"  {tag:26} {m['n']:>5} {m['exp']:>+7.3f} {m['pf']:>5.2f} {m['win']:>5.1f} "
          f"{m['maxdd']:>7.1f} {m['loCI']:>+7.3f} {m['Lexp']:>+5.2f}({m['Ln']:>4}) "
          f"{m['Sexp']:>+5.2f}({m['Sn']:>4}) {gate}")


def main():
    syms = [s.upper() for s in (sys.argv[1:] or ["NQ", "QQQ"])]
    con = hs_db.connect()
    hdr = (f"  {'variant':26} {'n':>5} {'exp':>7} {'PF':>5} {'win%':>5} {'maxDD':>7} {'loCI':>7} "
           f"{'long(n)':>11} {'short(n)':>11} gate")
    for sym in syms:
        for tf in ("5m", "15m"):
            brk_def = 0.0 if tf == "5m" else 0.25
            bars = B._externals(con, hs_db.bars(con, tf, "full", sym=sym), sym)
            d = H.compute_state(bars, H.P()); d.attrs["sym"] = sym
            d["_tu"] = d["trend_up"].to_numpy().copy(); d["_td"] = d["trend_down"].to_numpy().copy()
            print(f"\n========== {sym} {tf}  (OR 0930-1000, cut 15:00, 1R/4R scale_be, EOD-flat) ==========")
            print(hdr)
            line("BREAKOUT stop (baseline)", run(d, brk_def, "stop", "aligned"))
            for k in (0.0, 0.1, 0.25):
                line(f"FADE k={k} trend-aligned", run(d, k, "fade", "aligned"))
            for k in (0.0, 0.1, 0.25):
                line(f"FADE k={k} trend-OFF",    run(d, k, "fade", "off"))
    con.close()


if __name__ == "__main__":
    main()
