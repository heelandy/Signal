#!/usr/bin/env python3
"""
RESEARCH (signal-level, strict-causal): the CLEAN-DAY breakout filter (F19's #1 lead) done HONESTLY —
skip the breakout the moment a false break (sweep+reclaim of EITHER OR edge) has ALREADY printed on a
STRICTLY PRIOR bar today. The flag is known before the entry bar, so NO same-bar lookahead. This is the
F16-style graduation test (the screen reimplemented as a real signal-time skip).

Production = the deployed breakout (execm=stop, OR 0930-1000, cut 15:00, per-TF buffer, 4R/scale, EOD-flat).
CLEAN = production + skip messy-day entries (stay flat).  MESSY = the complement (only messy days).
NQ + QQQ + SPY × 5m+15m. Gate = both sides >0 AND lower-90%-CI >0; a real lever must also beat production.

    python research/orb_cleanday.py [SYM ...]   (default NQ QQQ SPY)
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
    print(f"  {tag:24} {m['n']:>5} {m['exp']:>+7.3f} {m['pf']:>5.2f} {m['win']:>5.1f} "
          f"{m['maxdd']:>7.1f} {m['loCI']:>+7.3f} {m['Lexp']:>+5.2f}({m['Ln']:>4}) "
          f"{m['Sexp']:>+5.2f}({m['Sn']:>4}) {g}")


def clean_flag_prior(d):
    """per-bar bool: a false break (touch the OR edge then CLOSE back inside, either edge) was confirmed on
    a STRICTLY PRIOR bar today -> known before this bar's entry (strict-causal, no same-bar lookahead)."""
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
        flag[i] = fb                              # state as of the PRIOR bar (strict-causal)
        if mins[i] < ORE or np.isnan(orh[i]):
            continue
        if h[i] >= orh[i]: bl = True
        if l[i] <= orl[i]: bs = True
        if (bl and c[i] < orh[i]) or (bs and c[i] > orl[i]): fb = True
    return flag


def bt(d, brk, skip=None):
    return B.backtest(d, "scale_be", "both", False, "orb", 0, T1, T2, ORS, ORE, brk, CUT, "stop",
                      eod_min=EOD, skip_mask=skip)


def main():
    syms = [s.upper() for s in (sys.argv[1:] or ["NQ", "QQQ", "SPY"])]
    con = hs_db.connect()
    hdr = (f"  {'variant':24} {'n':>5} {'exp':>7} {'PF':>5} {'win%':>5} {'maxDD':>7} {'loCI':>7} "
           f"{'long(n)':>11} {'short(n)':>11} gate")
    npass = ncell = 0
    for sym in syms:
        for tf in ("5m", "15m"):
            brk = 0.0 if tf == "5m" else 0.25
            bars = B._externals(con, hs_db.bars(con, tf, "full", sym=sym), sym)
            d = H.compute_state(bars, H.P()); d.attrs["sym"] = sym
            fb = clean_flag_prior(d)
            print(f"\n############ {sym} {tf}  (strict-causal prior-bar clean-day filter) ############")
            print(hdr)
            prod = metrics(bt(d, brk)); line("PRODUCTION (all)", prod)
            clean = metrics(bt(d, brk, fb)); line("CLEAN-DAY (skip messy)", clean)
            line("MESSY-DAY (complement)", metrics(bt(d, brk, ~fb)))
            ncell += 1
            ok = clean["both"] and clean["loCI"] > 0 and clean["exp"] > prod["exp"]
            npass += 1 if ok else 0
            print(f"  -> clean keeps {clean['n']}/{prod['n']} = {100*clean['n']/max(prod['n'],1):.0f}% of trades; "
                  f"d_exp {clean['exp']-prod['exp']:+.3f}R  d_PF {clean['pf']-prod['pf']:+.2f}  "
                  f"d_DD {clean['maxdd']-prod['maxdd']:+.1f}R  {'BEATS prod + gate' if ok else '--'}")
    print(f"\n==== CLEAN beats production AND clears the gate on {npass}/{ncell} cells ====")
    con.close()


if __name__ == "__main__":
    main()
