#!/usr/bin/env python3
"""
RESEARCH: four FALSE-BREAKOUT variations (the plain fade was DEAD — F18). NQ+QQQ × 5m+15m, all vs the
breakout-stop baseline; gate = both sides >0 AND lower-90%-CI >0 (the adoption discipline).
  1) FADE + reversion exit  — fade entry but exit tp2_full at a TIGHT target (1.0R / 1.5R), not the 4R
     runner. The honest re-test: a reversion trade needs a reversion exit.
  2) SWEEP-THEN-GO          — execm="sweepgo": swept the OPPOSITE edge first, then break THIS edge
     (stop-run -> continuation; aligned with the momentum edge — the strongest structural candidate).
  3) FALSE-BREAK day filter — split the breakout trades by whether a false break happened earlier that
     day (does a messy/whippy day lower the breakout's quality?).
  4) RE-BREAK               — execm="rebreak": only the SECOND break (broke, reclaimed inside, breaks again).
Engine carries off-by-default execm "fade"/"sweepgo"/"rebreak" (production unchanged).

    python research/orb_fb_variations.py [SYM ...]   (default NQ QQQ)
"""
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "engine"))
import numpy as np, pandas as pd
import hs_db, hs_harness as H, hs_backtest as B, hs_validate as V

rng = np.random.default_rng(7)
ORS, ORE, CUT, T1, T2, EOD = 570, 600, 900, 1.0, 4.0, 958


def metrics(tr):
    r = tr["net_R"].to_numpy()
    lo = np.percentile(rng.choice(r, (3000, len(r)), replace=True).mean(1), 5) if len(r) else 0.0
    L = tr[tr.direction == "long"]["net_R"].to_numpy(); S = tr[tr.direction == "short"]["net_R"].to_numpy()
    return dict(n=len(tr), exp=r.mean() if len(r) else 0, pf=V.pf(r),
                win=100*np.mean(r > 0) if len(r) else 0, maxdd=V.maxdd(r) if len(r) else 0, loCI=lo,
                Lexp=L.mean() if len(L) else 0, Sexp=S.mean() if len(S) else 0, Ln=len(L), Sn=len(S),
                both=(len(L) > 5 and L.mean() > 0 and len(S) > 5 and S.mean() > 0))


def line(tag, m):
    g = "PASS" if (m["both"] and m["loCI"] > 0) else "fail"
    print(f"  {tag:28} {m['n']:>5} {m['exp']:>+7.3f} {m['pf']:>5.2f} {m['win']:>5.1f} "
          f"{m['maxdd']:>7.1f} {m['loCI']:>+7.3f} {m['Lexp']:>+5.2f}({m['Ln']:>4}) "
          f"{m['Sexp']:>+5.2f}({m['Sn']:>4}) {g}")


def bt(d, brk, execm, mode="scale_be", t2=T2):
    return B.backtest(d, mode, "both", False, "orb", 0, T1, t2, ORS, ORE, brk, CUT, execm, eod_min=EOD)


def to_ns(s):
    return np.asarray(pd.to_datetime(s, utc=True)).astype("datetime64[ns]").astype("int64")


def messy_flag(d):
    """per-bar: has a raw false break (sweep+reclaim of EITHER OR edge) happened earlier today?"""
    et = pd.to_datetime(d["ts"]).dt.tz_convert("America/New_York")
    date = et.dt.date.to_numpy(); mins = (et.dt.hour * 60 + et.dt.minute).to_numpy()
    h, l, c = d["high"].to_numpy(), d["low"].to_numpy(), d["close"].to_numpy()
    df = pd.DataFrame({"date": date, "h": h, "l": l, "io": (mins >= ORS) & (mins < ORE)})
    org = df[df.io].groupby("date").agg(orh=("h", "max"), orl=("l", "min"))
    mm = pd.DataFrame({"date": date}).merge(org, on="date", how="left")
    orh, orl = mm["orh"].to_numpy(), mm["orl"].to_numpy()
    n = len(d); flag = np.zeros(n, bool); cur = None; bl = bs = fb = False
    for i in range(n):
        if date[i] != cur:
            cur = date[i]; bl = bs = fb = False
        if mins[i] < ORE or np.isnan(orh[i]):
            flag[i] = fb; continue
        if h[i] >= orh[i]: bl = True
        if l[i] <= orl[i]: bs = True
        if (bl and c[i] < orh[i]) or (bs and c[i] > orl[i]): fb = True
        flag[i] = fb
    return flag


def main():
    syms = [s.upper() for s in (sys.argv[1:] or ["NQ", "QQQ"])]
    con = hs_db.connect()
    hdr = (f"  {'variant':28} {'n':>5} {'exp':>7} {'PF':>5} {'win%':>5} {'maxDD':>7} {'loCI':>7} "
           f"{'long(n)':>11} {'short(n)':>11} gate")
    for sym in syms:
        for tf in ("5m", "15m"):
            brk = 0.0 if tf == "5m" else 0.25
            bars = B._externals(con, hs_db.bars(con, tf, "full", sym=sym), sym)
            d = H.compute_state(bars, H.P()); d.attrs["sym"] = sym
            print(f"\n############ {sym} {tf}  (OR 0930-1000, cut 15:00, EOD-flat) ############")
            print(hdr)
            line("BREAKOUT stop (baseline)",  metrics(bt(d, brk, "stop")))
            print("  -- 1) FADE + reversion exit (vs the dead 4R fade) --")
            line("FADE 4R-scale (F18 dead)",  metrics(bt(d, brk, "fade")))
            line("FADE reversion 1.0R",       metrics(bt(d, brk, "fade", "tp2_full", 1.0)))
            line("FADE reversion 1.5R",       metrics(bt(d, brk, "fade", "tp2_full", 1.5)))
            print("  -- 2) SWEEP-THEN-GO (liquidity grab -> opposite-edge breakout) --")
            line("SWEEP-THEN-GO 4R-scale",    metrics(bt(d, brk, "sweepgo")))
            print("  -- 4) RE-BREAK (second break only) --")
            line("RE-BREAK 4R-scale",         metrics(bt(d, brk, "rebreak")))
            print("  -- 3) FALSE-BREAK day filter on the breakout --")
            tb = bt(d, brk, "stop")
            fmap = dict(zip(to_ns(d["ts"]), messy_flag(d)))
            messy = pd.Series(to_ns(tb["entry_time"])).map(fmap).fillna(False).astype(bool).to_numpy()
            line("breakout | CLEAN day",      metrics(tb[~messy]))
            line("breakout | MESSY day",      metrics(tb[messy]))
    con.close()


if __name__ == "__main__":
    main()
