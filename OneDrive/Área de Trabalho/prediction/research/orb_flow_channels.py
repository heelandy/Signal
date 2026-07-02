#!/usr/bin/env python3
"""VPIN / RENKO / DONCHIAN — flow-toxicity + time-independent structure + channel breakout.
  vpin     Volume-Synchronized Prob. of Toxicity (bar-based Bulk Volume Classification): z=ΔP/σ, V_buy=V·Φ(z),
           VPIN = Σ|V_buy−V_sell| / ΣV over N buckets (0..1). Directionless TOXICITY = QUALITY filter (high=informed
           /big move). ofi = signed Σ(V_buy−V_sell) = a DIRECTIONAL order-flow-imbalance gate.
  renko    time-independent bricks (box = 1·ATR, per-day): brick trend state +1/−1. Direction on structural flip.
  donchian Turtle channel: close > max(High,N)[prev] = bull regime; < min(Low,N) = bear.  N=20.
Each: A) STANDALONE gate and B) ADDITIVE on the full stack (struct3 + vol-exp) + DROPPED cohort. NQ/QQQ/SPY RTH.

    python research/orb_flow_channels.py NQ QQQ SPY
"""
import sys, os, gc
from math import erf
sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "engine"))
import numpy as np, pandas as pd
import hs_db, hs_harness as H, hs_backtest as B, hs_validate as V

_rng = np.random.default_rng(7); _erf = np.vectorize(erf)
def Phi(z): return 0.5 * (1.0 + _erf(z / np.sqrt(2.0)))
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
        print(f"  {tag:18} n={0 if tr is None or 'net_R' not in getattr(tr,'columns',[]) else len(tr):>4}  (too few)"); return
    r = tr["net_R"].to_numpy(); L = tr.net_R[tr.direction == "long"].to_numpy(); S = tr.net_R[tr.direction == "short"].to_numpy()
    lo = ci_lo(r); p, ny = yr(tr); is_, oo = oos(tr)
    both = len(L) > 5 and L.mean() > 0 and len(S) > 5 and S.mean() > 0
    g = "PASS" if (lo > 0 and both and ny and p >= 0.7 * ny and oo > 0) else "----"
    print(f"  {tag:18} n={len(r):>4} exp {r.mean():+.3f} PF {V.pf(r):>4.2f} CIlo {lo:+.3f} "
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

def renko_state(c, atr, day):
    n = len(c); out = np.zeros(n); ref = c[0]; state = 0
    for i in range(n):
        if i == 0 or day[i] != day[i - 1]:
            ref = c[i]; state = 0
        box = atr[i] if atr[i] > 0 else abs(c[i]) * 0.001
        while c[i] >= ref + box:
            ref += box; state = 1
        while c[i] <= ref - box:
            ref -= box; state = -1
        out[i] = state
    return out

def main():
    syms = [s.upper() for s in (sys.argv[1:] or ["NQ", "QQQ", "SPY"])]
    con = hs_db.connect()
    for sym in syms:
        ext = B._externals(con, hs_db.bars(con, "5m", "rth", sym=sym), sym)
        d = H.compute_state(ext, H.P()); d.attrs["sym"] = sym
        st3 = H.compute_state(ext, H.P(struct_lb_fix=3))["st_state"].to_numpy()
        c = d["close"].to_numpy(); atr = d["atr14"].to_numpy(); vol = d["volume"].to_numpy()
        day = pd.to_datetime(d["ts"]).dt.tz_convert("America/New_York").dt.date.to_numpy()
        # VPIN (BVC) + signed OFI
        dP = np.diff(c, prepend=c[0]); sig = pd.Series(dP).rolling(50, min_periods=10).std().to_numpy()
        with np.errstate(invalid="ignore", divide="ignore"):
            z = np.where(sig > 0, dP / sig, 0.0)
        vb = vol * Phi(z); vs = vol * (1.0 - Phi(z)); imb = vb - vs
        N = 50
        sab = pd.Series(np.abs(imb)).rolling(N, min_periods=10).sum().to_numpy()
        sv = pd.Series(vol).rolling(N, min_periods=10).sum().to_numpy()
        with np.errstate(invalid="ignore", divide="ignore"):
            vpin = np.where(sv > 0, sab / sv, np.nan)
        ofi = pd.Series(imb).rolling(N, min_periods=10).sum().to_numpy()
        vpin_hi = vpin >= np.nanmedian(vpin)                    # toxic/informed regime (quality filter)
        # Renko + Donchian
        rk = renko_state(c, atr, day)
        up20 = pd.Series(d["high"].to_numpy()).rolling(20).max().shift(1).to_numpy()
        lo20 = pd.Series(d["low"].to_numpy()).rolling(20).min().shift(1).to_numpy()
        don = np.where(c > up20, 1, np.where(c < lo20, -1, 0))
        T = np.ones(len(d), bool)
        print(f"\n{'='*104}\n{sym} RTH — VPIN / RENKO / DONCHIAN\n{'='*104}")
        line("none(ORmid+seq)", run(d, T, T))
        base = run(d, st3 == 1, st3 == 2, volexp=2.4); line("STACK base(str3+vx)", base)
        print("  -- ofi (signed order-flow imbalance direction) --")
        line("A standalone", run(d, ofi > 0, ofi < 0))
        sub = run(d, (st3 == 1) & (ofi > 0), (st3 == 2) & (ofi < 0), volexp=2.4); line("B +struct3", sub); line("  DROPPED", dropped(base, sub))
        print("  -- vpin (toxicity QUALITY filter, dir from structure) --")
        sub = run(d, (st3 == 1) & vpin_hi, (st3 == 2) & vpin_hi, volexp=2.4); line("B str3 & VPIN-hi", sub); line("  DROPPED", dropped(base, sub))
        print("  -- renko (brick trend state) --")
        line("A standalone", run(d, rk > 0, rk < 0))
        sub = run(d, (st3 == 1) & (rk > 0), (st3 == 2) & (rk < 0), volexp=2.4); line("B +struct3", sub); line("  DROPPED", dropped(base, sub))
        print("  -- donchian (Turtle 20-bar channel regime) --")
        line("A standalone", run(d, don > 0, don < 0))
        sub = run(d, (st3 == 1) & (don > 0), (st3 == 2) & (don < 0), volexp=2.4); line("B +struct3", sub); line("  DROPPED", dropped(base, sub))
        del d, ext; gc.collect()
    con.close()
    print("\nKEY: graduates only if B beats STACK base on exp+CIlo, DROPPED=losers, holds NQ+QQQ+SPY. "
          "VPIN/OFI standalone > none would be the first flow edge; renko/donchian are trend-follow re-encodings.")

if __name__ == "__main__":
    main()
