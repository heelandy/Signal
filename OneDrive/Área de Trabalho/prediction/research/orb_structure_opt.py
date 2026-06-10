#!/usr/bin/env python3
"""
RESEARCH (no production change): can the ORB's up/down/range STRUCTURE read be optimized?

The production entry gates direction two ways:
  up/down  = EMA trend filter: close vs EMA50 AND EMA21 vs EMA50 stack  (in _orb_signals)
  range    = local-regime block: ADX<20 (and ATR%<2.5) => RANGE => signals blocked

This sweeps alternative definitions of each, holding everything else at the Pine-mirrored prod
config (OR 0930-1000, cutoff 15:00, per-TF buffer, 1R/4R scale_be, EOD-flat, macro gates ON).
Adoption gate (the discipline): must beat prod on the four metrics AND clear both-sides>0 +
lower-90%-CI>0 on BOTH NQ and QQQ. Efficient: compute harness state ONCE/sym/TF, then only the
cheap trade loop re-runs per variant (trend/range columns are swapped in).

TREND variants (up/down):  none | c>EMA50 | 21/50(PROD) | 8/21 | 50/200 | HH/HL(st_state)
RANGE variants:            none | ADX15 | ADX20(PROD) | ADX25 | ADX30 | st_state-3(structure range)

    python research/orb_structure_opt.py [SYM ...]   (default: NQ QQQ)
"""
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "engine"))
import numpy as np, pandas as pd
import hs_db, hs_harness as H, hs_backtest as B, hs_validate as V

rng = np.random.default_rng(7)
ORS, ORE, CUT, T1, T2, EOD = 570, 600, 900, 1.0, 4.0, 958
ATR_HI = 2.5   # prod ATR% volatile threshold (held fixed)


def ema_np(c, n):
    return pd.Series(c).ewm(span=n, adjust=False).mean().to_numpy()


def trend_arrays(d, kind):
    c = d["close"].to_numpy()
    if kind == "none":    return np.ones(len(c), bool), np.ones(len(c), bool)
    if kind == "c>ema50": e = ema_np(c, 50); return c > e, c < e
    if kind == "21/50":   e21, e50 = ema_np(c, 21), ema_np(c, 50); return (c > e50) & (e21 > e50), (c < e50) & (e21 < e50)
    if kind == "8/21":    e8, e21 = ema_np(c, 8), ema_np(c, 21);   return (c > e21) & (e8 > e21), (c < e21) & (e8 < e21)
    if kind == "50/200":  e50, e200 = ema_np(c, 50), ema_np(c, 200); return (c > e200) & (e50 > e200), (c < e200) & (e50 < e200)
    if kind == "hh_hl":   st = d["st_state"].to_numpy(); return st == 1, st == 2
    raise ValueError(kind)


def regime_array(d, kind):
    """Returns local_regime where ==2 is the BLOCKED 'range' bucket."""
    n = len(d)
    if kind == "none": return np.ones(n, int)
    if kind == "st3":  st = d["st_state"].to_numpy(); return np.where(st == 3, 2, 1)
    amin = float(kind[3:])               # 'adx20' -> 20
    atr_pct, adx = d["atr_pct"].to_numpy(), d["adx"].to_numpy()
    return np.where(atr_pct >= ATR_HI, 3, np.where(adx >= amin, 1, 2))


def metrics(tr):
    r = tr["net_R"].to_numpy()
    lo = np.percentile(rng.choice(r, (3000, len(r)), replace=True).mean(1), 5) if len(r) else 0.0
    L = tr[tr.direction == "long"]["net_R"].to_numpy(); S = tr[tr.direction == "short"]["net_R"].to_numpy()
    return dict(n=len(tr), exp=r.mean() if len(r) else 0, pf=V.pf(r),
                win=100 * np.mean(r > 0) if len(r) else 0, maxdd=V.maxdd(r) if len(r) else 0, loCI=lo,
                Lexp=L.mean() if len(L) else 0, Sexp=S.mean() if len(S) else 0, Ln=len(L), Sn=len(S),
                both=(len(L) > 5 and L.mean() > 0 and len(S) > 5 and S.mean() > 0))


def run(d, brk, trend_kind, range_kind):
    tu, td = trend_arrays(d, trend_kind)
    d["trend_up"], d["trend_down"] = tu, td
    d["local_regime"] = regime_array(d, range_kind)
    tr = B.backtest(d, "scale_be", "both", False, "orb", 0, T1, T2, ORS, ORE, brk, CUT, "stop", eod_min=EOD)
    return metrics(tr)


def line(tag, m, base=None):
    gate = "PASS" if (m["both"] and m["loCI"] > 0) else "fail"
    flag = ""
    if base is not None and tag != "21/50 (PROD)" and tag != "adx20 (PROD)":
        beats = (m["exp"] > base["exp"] and m["pf"] >= base["pf"] and m["win"] >= base["win"]
                 and m["maxdd"] >= base["maxdd"] and m["both"] and m["loCI"] > 0)
        flag = "  <<< beats prod on all 4 + gate" if beats else ""
    print(f"  {tag:18} {m['n']:>5} {m['exp']:>+7.3f} {m['pf']:>5.2f} {m['win']:>5.1f} "
          f"{m['maxdd']:>7.1f} {m['loCI']:>+7.3f} {m['Lexp']:>+5.2f}({m['Ln']:>4}) "
          f"{m['Sexp']:>+5.2f}({m['Sn']:>4}) {gate}{flag}")


def main():
    syms = [s.upper() for s in (sys.argv[1:] or ["NQ", "QQQ"])]
    con = hs_db.connect()
    hdr = (f"  {'variant':18} {'n':>5} {'exp':>7} {'PF':>5} {'win%':>5} {'maxDD':>7} {'loCI':>7} "
           f"{'long(n)':>11} {'short(n)':>11} gate")
    for sym in syms:
        for tf in ("5m", "15m"):
            brk = 0.0 if tf == "5m" else 0.25
            bars = B._externals(con, hs_db.bars(con, tf, "full", sym=sym), sym)
            d = H.compute_state(bars, H.P()); d.attrs["sym"] = sym
            print(f"\n========== {sym} {tf}  (buffer {brk} ATR; OR 0930-1000, cut 15:00, 4R scale, EOD-flat) ==========")
            base = run(d, brk, "21/50", "adx20")     # production baseline
            print("TREND (up/down) filter — range held at prod ADX20 block:")
            print(hdr)
            for k, lbl in [("none", "none"), ("c>ema50", "c>EMA50"), ("21/50", "21/50 (PROD)"),
                           ("8/21", "8/21"), ("50/200", "50/200"), ("hh_hl", "HH/HL st_state")]:
                line(lbl, run(d, brk, k, "adx20"), base)
            print("RANGE filter — trend held at prod 21/50:")
            print(hdr)
            for k, lbl in [("none", "no range block"), ("adx15", "adx15"), ("adx20", "adx20 (PROD)"),
                           ("adx25", "adx25"), ("adx30", "adx30"), ("st3", "st_state-3 block")]:
                line(lbl, run(d, brk, "21/50", k), base)
    con.close()


if __name__ == "__main__":
    main()
