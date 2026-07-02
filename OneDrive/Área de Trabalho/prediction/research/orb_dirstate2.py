#!/usr/bin/env python3
"""DIRECTIONAL-STATE list v2 (user spec) — the 8 not-yet-tested detectors, on the validated ORB.
  persist_e  directional persistence with ε=0.1·ATR noise gate  (dir=sign(u−d), quality p=max(u,d)/(u+d))
  hhll       higher-high & higher-low ratios over the window     (up: HHr>0.6 & HLr>0.6)
  theilsen   Theil–Sen robust median slope                       (dir=sign)
  cusum      CUSUM sequential drift (K=0.5·ATR, h=3·ATR), per-day (up: S+ crossed first)
  kalman     constant-velocity Kalman filter, velocity sign      (dir=sign(v))
  ols_sig    OLS slope significance |t|>1.5                       (up: slope>0 & t>1.5)
  mk         Mann–Kendall S statistic                            (dir=sign(S))
  regimez    HMM proxy: net-return z-score |z|>1                  (up: z>1)
Each: A) STANDALONE gate (replaces the trend gate) and B) ADDITIVE CONFLUENCE on struct3 (require the
signal to AGREE with structure) vs the FULL stack (struct3 + vol-exp 2.4); DROPPED = struct3 trades where
the signal DISAGREED (should be the losers if the signal has info). RTH 5m, window N=10 intraday.

    python research/orb_dirstate2.py NQ QQQ SPY
"""
import sys, os, gc
sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "engine"))
import numpy as np, pandas as pd
from numpy.lib.stride_tricks import sliding_window_view
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
        print(f"  {tag:20} n={0 if (tr is None or 'net_R' not in getattr(tr,'columns',[])) else len(tr):>4}  (too few)"); return
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

def signals(d, N=10):
    et = pd.to_datetime(d["ts"]).dt.tz_convert("America/New_York"); day = et.dt.date.to_numpy()
    c = d["close"].to_numpy(); h = d["high"].to_numpy(); l = d["low"].to_numpy(); atr = d["atr14"].to_numpy()
    n = len(c); valid = np.zeros(n, bool); valid[N:] = (day[N:] == day[:-N])          # window stays intraday
    up = {}; dn = {}
    # ---- windowed (sliding) metrics ----
    wc = sliding_window_view(c, N + 1)                                                 # rows -> bars [k..k+N]; last = k+N
    x = np.arange(N + 1) - N / 2.0; Sxx = (x ** 2).sum()
    slope = (wc - wc.mean(1, keepdims=True)) @ x / Sxx
    pred = wc.mean(1, keepdims=True) + slope[:, None] * x
    sse = ((wc - pred) ** 2).sum(1); se = np.sqrt(np.maximum(sse, 1e-12) / (N - 1) / Sxx); tstat = slope / se
    SL = np.full(n, np.nan); TT = np.full(n, np.nan); SL[N:] = slope; TT[N:] = tstat
    # Theil-Sen + Mann-Kendall over the same window (pairs j>i)
    ii, jj = np.triu_indices(N + 1, 1)
    pair_sl = (wc[:, jj] - wc[:, ii]) / (jj - ii)
    ts_slope = np.median(pair_sl, axis=1); mk_S = np.sign(wc[:, jj] - wc[:, ii]).sum(1)
    TS = np.full(n, np.nan); MK = np.full(n, np.nan); TS[N:] = ts_slope; MK[N:] = mk_S
    # persistence-ε and HH/HL over deltas / candles
    dP = np.diff(c, prepend=c[0]); wdp = sliding_window_view(dP, N)                     # N deltas -> bar k+N-1
    eps = 0.1 * atr
    U = np.full(n, 0); Dn = np.full(n, 0)
    u_ct = (wdp > eps[N - 1:, None]).sum(1); d_ct = (wdp < -eps[N - 1:, None]).sum(1)
    U[N - 1:] = u_ct; Dn[N - 1:] = d_ct
    tot = np.maximum(U + Dn, 1); persist = np.maximum(U, Dn) / tot; pdir = np.sign(U - Dn)
    hh = (h[1:] > h[:-1]).astype(float); hl = (l[1:] > l[:-1]).astype(float)            # per-bar flags
    whh = sliding_window_view(hh, N); whl = sliding_window_view(hl, N)
    HHr = np.full(n, np.nan); HLr = np.full(n, np.nan)
    HHr[N:] = whh.mean(1); HLr[N:] = whl.mean(1)                                        # bar index k+N
    # regime z-score (HMM proxy): net return over window / (per-move std * sqrt(N))
    mu = np.full(n, np.nan); sd = np.full(n, np.nan)
    mu[N - 1:] = wdp.mean(1); sd[N - 1:] = wdp.std(1)
    with np.errstate(invalid="ignore", divide="ignore"):
        Z = (mu * N) / (sd * np.sqrt(N))
    # ---- recursive: CUSUM + Kalman (per-day reset) ----
    cus = np.zeros(n)                                                                   # +1 up-drift, -1 down
    sp = sm = 0.0
    for i in range(n):
        if i == 0 or day[i] != day[i - 1]:
            sp = sm = 0.0
        K = 0.5 * (atr[i] if atr[i] > 0 else 0.0); hh_ = 3.0 * (atr[i] if atr[i] > 0 else 1e9)
        sp = max(0.0, sp + dP[i] - K); sm = max(0.0, sm - dP[i] - K)
        cus[i] = 1 if sp > hh_ else (-1 if sm > hh_ else 0)
    kv = np.zeros(n)                                                                    # alpha-beta velocity tracker (stable Kalman proxy)
    lvl = c[0]; vk = 0.0; alpha = 0.3; beta = 0.05
    for i in range(n):
        if i == 0 or day[i] != day[i - 1]:
            lvl = c[i]; vk = 0.0
        pred = lvl + vk; err = c[i] - pred
        lvl = pred + alpha * err; vk = vk + beta * err
        kv[i] = vk
    def gate(cond_up, cond_dn):
        return (cond_up & valid), (cond_dn & valid)
    up["persist_e"], dn["persist_e"] = gate((pdir > 0) & (persist >= 0.6), (pdir < 0) & (persist >= 0.6))
    up["hhll"], dn["hhll"] = gate((HHr > 0.6) & (HLr > 0.6), (HHr < 0.4) & (HLr < 0.4))
    up["theilsen"], dn["theilsen"] = gate(TS > 0, TS < 0)
    up["cusum"], dn["cusum"] = gate(cus > 0, cus < 0)
    up["kalman"], dn["kalman"] = gate(kv > 0, kv < 0)
    up["ols_sig"], dn["ols_sig"] = gate((SL > 0) & (TT > 1.5), (SL < 0) & (TT < -1.5))
    up["mk"], dn["mk"] = gate(MK > 0, MK < 0)
    up["regimez"], dn["regimez"] = gate(Z > 1.0, Z < -1.0)
    return up, dn

def main():
    syms = [s.upper() for s in (sys.argv[1:] or ["NQ", "QQQ", "SPY"])]
    con = hs_db.connect()
    for sym in syms:
        ext = B._externals(con, hs_db.bars(con, "5m", "rth", sym=sym), sym)
        d = H.compute_state(ext, H.P()); d.attrs["sym"] = sym
        st3 = H.compute_state(ext, H.P(struct_lb_fix=3))["st_state"].to_numpy()
        up, dn = signals(d)
        T = np.ones(len(d), bool)
        print(f"\n{'='*104}\n{sym} RTH — DIRECTIONAL-STATE v2 (8 new detectors)\n{'='*104}")
        line("none(ORmid+seq)", run(d, T, T))
        base = run(d, st3 == 1, st3 == 2, volexp=2.4); line("STACK base(str3+vx)", base)
        for k in up:
            print(f"  -- {k} --")
            line(f"A standalone", run(d, up[k], dn[k]))
            sub = run(d, (st3 == 1) & up[k], (st3 == 2) & dn[k], volexp=2.4); line("B +struct3 confluence", sub)
            line("  DROPPED(disagree)", dropped(base, sub))
        del d, ext; gc.collect()
    con.close()
    print("\nKEY: graduates only if B (confluence) beats STACK base on exp AND CIlo AND the DROPPED (signal "
          "disagreed with structure) cohort is the LOSERS. Standalone shows if it knows direction at all.")

if __name__ == "__main__":
    main()
