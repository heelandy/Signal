#!/usr/bin/env python3
"""
RESEARCH (F31 candidate) — does the "Neural Kernel Bands" indicator add value as a FILTER on the
validated 5m ORB stack (F21: HH/HL st_state gate + VWAP-cap k2)?

The indicator's "kernel regression" is, on inspection, a CAUSAL one-sided weighted moving average
(weights decay with bar AGE i, not a predictor feature): kernelMA = EMA( Σ wᵢ·close[i] / Σ wᵢ , smooth),
wᵢ = exp(-i²/2h²) [Gaussian] (Epanechnikov / Tricube optional). Bands = kernelMA ± mult·σ(residual).
Its primary signal is a VOLATILITY-BAND BREAKOUT (close crosses the upper/lower band) — a momentum read,
same family as the ORB. We test it AS A FILTER by AND-ing a causal (prior-bar) kernel-agreement condition
into the stack's trend gate (exactly how orb_stack_walkforward injects the st_state gate). Variants:

  state  : require the held band STATE (last cross) to agree with the ORB direction   <- the literal "band-cross filter"
  slope  : require kernelMA SLOPE to agree (rising for longs / falling for shorts)
  side   : require close to be on the agreeing SIDE of kernelMA
  cap    : DON'T-CHASE — skip if price is already > kcap·σ beyond kernelMA (overextension, VWAP-cap analog)

Gate (F15/F17/F20/F21 protocol, reused report()): beat the stack on the four metrics AND PASS
(both sides>0, lower-90% CI>0) on NQ+QQQ+SPY, positive every year, 70/30 OOS holds.

    python research/orb_kernel_filter.py [SYM ...]                 (default NQ QQQ SPY)
    python research/orb_kernel_filter.py --adaptive off NQ         (robustness: fixed bandwidth)
"""
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "engine"))
import numpy as np, pandas as pd
import hs_db, hs_harness as H, hs_backtest as B, hs_validate as V

rng = np.random.default_rng(7)
ORS, ORE, CUT, T1, T2, EOD, KCAP = 570, 600, 900, 1.0, 4.0, 958, 2.0

# --- kernel indicator defaults (match the Pine) ---
K_TYPE, K_LEN, K_H, K_ATRLEN, K_SMOOTH = "Gaussian", 30, 8.0, 14, 3
B_MULT, B_LEN, B_SMOOTH = 1.0, 24, 5
SLOPE_N, CAP_K = 3, 1.0


def kernel_state(d, ktype=K_TYPE, length=K_LEN, base_h=K_H, atrlen=K_ATRLEN, smooth=K_SMOOTH,
                 adaptive=True, bmult=B_MULT, blen=B_LEN, bsmooth=B_SMOOTH, slope_n=SLOPE_N):
    """Causal port of HIGHSTRIKE 'Neural Kernel Bands'. Returns prior-bar (shifted) filter columns so
    nothing is known later than an intrabar stop-fill can see (same causality as vwap_cap's vs_prev)."""
    c = d["close"].to_numpy(float); n = len(c)
    atr = d["atr14"].to_numpy(float)                                   # already rma(TR,14) in harness
    atr_norm = np.where(c > 0, atr / c, 0.0)
    atr_factor = H.ema(pd.Series(atr_norm), atrlen).to_numpy()
    h = base_h * (1.0 + atr_factor * 200.0) if adaptive else np.full(n, base_h)
    h = np.maximum(h, 1e-6)
    lags = np.arange(length)
    # lagged close matrix Clag[t,i] = close[t-i]  (column i = close shifted down by i)
    Clag = np.full((n, length), np.nan)
    for i in range(length):
        Clag[i:, i] = c[:n - i]
    # per-bar kernel weights w[t,i]
    if ktype == "Gaussian":
        W = np.exp(-(lags[None, :] ** 2) / (2.0 * h[:, None] ** 2))
    elif ktype == "Epanechnikov":
        W = np.maximum(0.0, 1.0 - (lags[None, :] ** 2) / (h[:, None] ** 2))
    else:                                                              # Tricube
        W = np.maximum(0.0, (1.0 - np.abs(lags[None, :] / h[:, None]) ** 3) ** 3)
    den = np.nansum(W, axis=1)
    raw = np.where(den > 0, np.nansum(W * Clag, axis=1) / den, c)
    raw[:length - 1] = np.nan                                          # need a full window (early 2010 bars only)
    kma = H.ema(pd.Series(raw), smooth)
    resid = pd.Series(c) - kma
    sigma = H.ema(resid.rolling(blen, min_periods=blen).std(ddof=0), bsmooth)   # ta.stdev = population (ddof0)
    upper = kma + bmult * sigma
    lower = kma - bmult * sigma
    # held band state (Pine: update on each confirmed bar, else hold last)
    raw_state = np.where(c > upper.to_numpy(), 1.0, np.where(c < lower.to_numpy(), -1.0, np.nan))
    state = pd.Series(raw_state).ffill().fillna(0.0).to_numpy()
    slope = (kma - kma.shift(slope_n)).to_numpy()
    ext = np.where(sigma.to_numpy() > 0, (c - kma.to_numpy()) / sigma.to_numpy(), 0.0)   # signed σ-extension from kernel
    sh = lambda a: pd.Series(a).shift(1).to_numpy()                    # prior CONFIRMED bar (causal)
    return dict(state=sh(state), slope=sh(slope), side=sh((c - kma.to_numpy())), ext=sh(ext))


def gates(variant, K):
    """Direction-aware kernel agreement masks (long_ok, short_ok) for AND-ing into the stack trend gate."""
    if variant == "state":
        return K["state"] == 1, K["state"] == -1
    if variant == "slope":
        return K["slope"] > 0, K["slope"] < 0
    if variant == "side":
        return K["side"] > 0, K["side"] < 0
    if variant == "cap":                                              # don't-chase: not already extended beyond +cap·σ
        return K["ext"] <= CAP_K, K["ext"] >= -CAP_K
    raise ValueError(variant)


def loci(r):
    return np.percentile(rng.choice(r, (3000, len(r)), replace=True).mean(1), 5) if len(r) else 0.0


def run(d, variant=None, K=None):
    st = d["st_state"].to_numpy()
    tu = (st == 1); td = (st == 2)
    if variant is not None:
        kl, ks = gates(variant, K)
        tu = tu & kl; td = td & ks
    d["trend_up"] = tu; d["trend_down"] = td
    return B.backtest(d, "scale_be", "both", False, "orb", 0, T1, T2, ORS, ORE, 0.0, CUT, "stop",
                      eod_min=EOD, vwap_cap=KCAP)


def report(tag, tr):
    r = tr["net_R"].to_numpy()
    L = tr[tr.direction == "long"]["net_R"].to_numpy(); S = tr[tr.direction == "short"]["net_R"].to_numpy()
    both = len(L) > 5 and L.mean() > 0 and len(S) > 5 and S.mean() > 0
    lo = loci(r)
    t = tr.copy()
    t["year"] = pd.to_datetime(t["entry_time"], utc=True).dt.tz_convert("America/New_York").dt.year
    yrs = [(int(y), g["net_R"].mean(), len(g)) for y, g in t.groupby("year") if len(g) >= 10]
    pos = sum(1 for _, e, _ in yrs if e > 0); tot = len(yrs)
    neg = [y for y, e, _ in yrs if e <= 0]
    t = t.sort_values("entry_time").reset_index(drop=True); k = int(len(t) * 0.7)
    IN = t.iloc[:k]["net_R"].to_numpy(); OUT = t.iloc[k:]["net_R"].to_numpy()
    g = "PASS" if (both and lo > 0) else "fail"
    print(f"  {tag:11} n={len(r):>4} exp {r.mean():+.3f} PF {V.pf(r):>5.2f} win {100*np.mean(r>0):>2.0f}% "
          f"DD {V.maxdd(r):>+5.0f} CI {lo:+.3f} {g} | yrs +{pos}/{tot}{'  NEG=' + str(neg) if neg else ''} "
          f"| OOS in {IN.mean():+.3f}/{V.pf(IN):.2f} -> out {OUT.mean():+.3f}/{V.pf(OUT):.2f}")


def slip2x(tr, eq):
    """2x extra slippage per trade via risk_pts. eq=True -> equity ticks (0.01/$1), else futures (0.25/$2)."""
    tick, pt = (0.01, 1.0) if eq else (0.25, 2.0)
    add_R = (2 * tick * pt * 2 * B.CONTRACTS) / (tr["risk_pts"] * pt * B.CONTRACTS)
    return (tr["net_R"] - add_R).to_numpy()


def robust(con):
    """The two DECIDING tests: (1) cross-asset incl ES + 2x slippage; (2) the redundancy control —
    does the kernel cull beat tightening the EXISTING vwap-cap lever to the same trade count?"""
    print("==== ROBUSTNESS: cross-asset (+ES) and 2x-slippage stress ====")
    for sym in ["NQ", "ES", "QQQ", "SPY"]:
        eq = sym in ("QQQ", "SPY")
        bars = B._externals(con, hs_db.bars(con, "5m", "full", sym=sym), sym)
        d = H.compute_state(bars, H.P()); d.attrs["sym"] = sym
        K = kernel_state(d)
        print(f"\n## {sym} 5m{'  (equity)' if eq else '  (futures, 2x-slip shown)'}")
        for tag, v in [("STACK", None), ("+kern:state", "state"), ("+kern:slope", "slope")]:
            tr = run(d, v, K) if v else run(d)
            r = tr["net_R"].to_numpy()
            sl = "" if eq else f" | 2xslip exp {slip2x(tr, eq).mean():+.3f} PF {V.pf(slip2x(tr, eq)):.2f}"
            print(f"  {tag:12} n={len(r):>4} exp {r.mean():+.3f} PF {V.pf(r):>5.2f} win {100*np.mean(r>0):>2.0f}% "
                  f"DD {V.maxdd(r):>+5.0f} CI {loci(r):+.3f}{sl}")

    print("\n\n==== REDUNDANCY CONTROL (NQ): kernel cull vs equal-frequency vwap-cap tighten ====")
    print("If tightening the EXISTING vwap-cap k to the same trade count matches/beats kernel:state,")
    print("the kernel adds no orthogonal info (it just rides the frequency<->quality frontier).\n")
    bars = B._externals(con, hs_db.bars(con, "5m", "full", sym="NQ"), "NQ")
    d = H.compute_state(bars, H.P()); d.attrs["sym"] = "NQ"
    K = kernel_state(d)
    def cap_run(k):
        st = d["st_state"].to_numpy(); d["trend_up"] = st == 1; d["trend_down"] = st == 2
        return B.backtest(d, "scale_be", "both", False, "orb", 0, T1, T2, ORS, ORE, 0.0, CUT, "stop",
                          eod_min=EOD, vwap_cap=k)
    for k in (2.0, 1.9, 1.7, 1.5, 1.3, 1.1):
        tr = cap_run(k); r = tr["net_R"].to_numpy()
        lbl = "STACK (vcap2.0)" if k == 2.0 else f"vwap-cap k={k}"
        print(f"  {lbl:22} n={len(r):>4} exp {r.mean():+.3f} PF {V.pf(r):.2f}")
    ks = run(d, "state", K)["net_R"].to_numpy()
    print(f"  {'+kern:state (vcap2.0)':22} n={len(ks):>4} exp {ks.mean():+.3f} PF {V.pf(ks):.2f}  <- compare at matched n")


def main():
    args = [a for a in sys.argv[1:]]
    if "--robust" in args:
        con = hs_db.connect(); robust(con); con.close(); return
    adaptive = True
    if "--adaptive" in args:
        j = args.index("--adaptive"); adaptive = args[j + 1].lower() not in ("off", "false", "0")
        del args[j:j + 2]
    syms = [s.upper() for s in (args or ["NQ", "QQQ", "SPY"])]
    con = hs_db.connect()
    for sym in syms:
        bars = B._externals(con, hs_db.bars(con, "5m", "full", sym=sym), sym)
        d = H.compute_state(bars, H.P()); d.attrs["sym"] = sym
        K = kernel_state(d, adaptive=adaptive)
        print(f"\n############ {sym} 5m  (STACK vs STACK + kernel-band filter; adaptive={adaptive}) ############")
        report("STACK", run(d))
        for v in ("state", "slope", "side", "cap"):
            report("+kern:" + v, run(d, v, K))
    con.close()


if __name__ == "__main__":
    main()
