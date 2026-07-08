#!/usr/bin/env python3
"""MARKOV / HURST / EHMA — the 'now try to PREDICT' round (follow is already saturated).
  ehma     Exponential Hull MA slope (low-lag FOLLOW trend)          dir = EHMA rising/falling
  hurst    Hurst exponent (variance-ratio, W bars): H>0.5 trending,  QUALITY filter (regime); dir from structure
           H<0.5 mean-reverting. Used additive: only take breakouts in a TRENDING regime (H>=0.5).
  markov   PREDICTION: causal 3-state (up/flat/down, ε=0.1ATR) transition matrix built from all PAST bars;
           predict next-bar direction = argmax expected next-state from the CURRENT state.  dir = predicted.
Each: A) STANDALONE (gate = the signal) and B) ADDITIVE on the full stack (struct3 + vol-exp), + DROPPED cohort.
Graduation = B beats base on exp AND CIlo AND dropped=losers AND holds on NQ+QQQ+SPY (no instrument flip).

    python research/orb_predict.py NQ QQQ SPY
"""
import sys, os, gc
sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "engine"))
import numpy as np, pandas as pd
import hs_db, hs_harness as H, hs_backtest as B, hs_validate as V

_rng = np.random.default_rng(7)
def ci_lo(r):
    return float(np.percentile(_rng.choice(r, size=(1200, len(r)), replace=True).mean(axis=1), 5)) if len(r) >= 10 else float("nan")
def yr(tr):
    t = tr.copy(); t["y"] = pd.to_datetime(t["entry_time"], utc=True).dt.tz_convert("America/New_York").dt.year
    g = t.groupby("y")["net_R"].mean(); return int((g > 0).sum()), len(g)
def oos(tr):
    r = tr.sort_values("entry_time")["net_R"].to_numpy(); k = int(len(r) * 0.7)
    return (r[:k].mean(), r[k:].mean()) if (k >= 5 and len(r) - k >= 5) else (float("nan"), float("nan"))
def line(tag, tr):
    if tr is None or len(tr) < 20 or "net_R" not in tr.columns:
        print(f"  {tag:20} n={0 if tr is None or 'net_R' not in getattr(tr,'columns',[]) else len(tr):>4}  (too few)"); return
    r = tr["net_R"].to_numpy()
    L = tr.net_R[tr.direction == "long"].to_numpy(); S = tr.net_R[tr.direction == "short"].to_numpy()
    lo = ci_lo(r); p, ny = yr(tr); is_, oo = oos(tr)
    both = len(L) > 5 and L.mean() > 0 and len(S) > 5 and S.mean() > 0
    g = "PASS" if (lo > 0 and both and ny and p >= 0.7 * ny and oo > 0) else "----"
    print(f"  {tag:20} n={len(r):>4} exp {r.mean():+.3f} PF {V.pf(r):>4.2f} CIlo {lo:+.3f} "
          f"L{(L.mean() if len(L) else 0):+.2f} S{(S.mean() if len(S) else 0):+.2f} yr+{p}/{ny} OOS{is_:+.2f}/{oo:+.2f} {g}")

def run(d, tup, tdn, volexp=0.0):
    d2 = d.copy(); d2["trend_up"] = tup; d2["trend_down"] = tdn; d2.attrs["sym"] = d.attrs.get("sym", "NQ")
    return B.backtest(d2, "tp2_full", "both", False, "orb", 0, 1.0, 4.0, 570, 600, 0.0, 900, "close",
                      eod_min=958, stop_mode="struct", entry_delay=0, chase_atr=1.0, strong_body=0.25,
                      ft_confirm=True, dir_seq=True, or_mid_bias=True, min_or_width=volexp)

def dropped(base, sub):
    if sub is None or len(sub) == 0 or "entry_time" not in sub.columns:
        return base
    ks = set(zip(pd.to_datetime(sub["entry_time"]).astype("int64"), sub["direction"]))
    return base[[(ts, dr) not in ks for ts, dr in zip(pd.to_datetime(base["entry_time"]).astype("int64"), base["direction"])]]

def ema(a, span):
    return pd.Series(a).ewm(span=max(1, span), adjust=False).mean().to_numpy()

def ehma(c, n):
    e = 2.0 * ema(c, max(1, n // 2)) - ema(c, n)
    return ema(e, max(1, int(round(np.sqrt(n)))))

def hurst_vr(c, W):
    d1 = np.diff(c, prepend=c[0]); d2 = c - np.concatenate([[c[0], c[0]], c[:-2]])
    v1 = pd.Series(d1).rolling(W).var().to_numpy(); v2 = pd.Series(d2).rolling(W).var().to_numpy()
    with np.errstate(invalid="ignore", divide="ignore"):
        return 0.5 * np.log(np.where((v1 > 0) & (v2 > 0), v2 / v1, np.nan)) / np.log(2.0)

def markov_pred(c, atr, day, eps_mult=0.1):
    """causal 3-state Markov: state=+1/0/-1 by ΔP vs ε; expanding transition counts from PAST only;
    predict next-bar direction = sign(P(up|cur) - P(down|cur))."""
    n = len(c); dP = np.diff(c, prepend=c[0]); eps = eps_mult * atr
    st = np.where(dP > eps, 1, np.where(dP < -eps, -1, 0))          # 0..2 index = st+1
    cnt = np.ones((3, 3)) * 0.5                                     # Laplace prior
    pred = np.zeros(n)
    for i in range(n):
        cur = st[i] + 1
        row = cnt[cur]
        pred[i] = (row[2] - row[0]) / row.sum()                    # E[next dir] from current state (uses PAST counts)
        if i + 1 < n and day[i + 1] == day[i]:                     # update counts with the realized transition (causal)
            cnt[cur, st[i + 1] + 1] += 1.0
    return pred

def main():
    syms = [s.upper() for s in (sys.argv[1:] or ["NQ", "QQQ", "SPY"])]
    con = hs_db.connect()
    for sym in syms:
        ext = B._externals(con, hs_db.bars(con, "5m", "rth", sym=sym), sym)
        d = H.compute_state(ext, H.P()); d.attrs["sym"] = sym
        st3 = H.compute_state(ext, H.P(struct_lb_fix=3))["st_state"].to_numpy()
        c = d["close"].to_numpy(); atr = d["atr14"].to_numpy()
        day = pd.to_datetime(d["ts"]).dt.tz_convert("America/New_York").dt.date.to_numpy()
        eh = ehma(c, 16); eh_up = eh > np.concatenate([[np.nan], eh[:-1]]); eh_dn = eh < np.concatenate([[np.nan], eh[:-1]])
        Hn = hurst_vr(c, 30); trend_regime = Hn >= 0.5
        mp = markov_pred(c, atr, day)
        T = np.ones(len(d), bool)
        print(f"\n{'='*104}\n{sym} RTH — PREDICT round: EHMA (follow) / HURST (regime) / MARKOV (predict)\n{'='*104}")
        line("none(ORmid+seq)", run(d, T, T))
        base = run(d, st3 == 1, st3 == 2, volexp=2.4); line("STACK base(str3+vx)", base)
        print("  -- ehma (low-lag trend slope) --")
        line("A standalone", run(d, eh_up, eh_dn))
        sub = run(d, (st3 == 1) & eh_up, (st3 == 2) & eh_dn, volexp=2.4); line("B +struct3", sub); line("  DROPPED", dropped(base, sub))
        print("  -- hurst (H>=0.5 trending regime = quality filter, dir from structure) --")
        line("A standalone", run(d, (st3 == 1) & trend_regime, (st3 == 2) & trend_regime))
        sub = run(d, (st3 == 1) & trend_regime, (st3 == 2) & trend_regime, volexp=2.4); line("B +struct3", sub); line("  DROPPED", dropped(base, sub))
        print("  -- markov (PREDICTED next-bar direction) --")
        line("A standalone", run(d, mp > 0, mp < 0))
        sub = run(d, (st3 == 1) & (mp > 0), (st3 == 2) & (mp < 0), volexp=2.4); line("B +struct3", sub); line("  DROPPED", dropped(base, sub))
        del d, ext; gc.collect()
    con.close()
    print("\nKEY: graduates only if B beats STACK base on exp+CIlo, DROPPED=losers, and holds NQ+QQQ+SPY. "
          "MARKOV standalone > none would be the first sign PREDICTION beats FOLLOW.")

if __name__ == "__main__":
    main()
