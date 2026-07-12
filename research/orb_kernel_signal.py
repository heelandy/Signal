#!/usr/bin/env python3
"""
RESEARCH (F49) — STANDALONE accuracy of the "Neural Kernel Bands" Buy/Sell signals (5m & 15m).

CONTEXT: the user reports the stack's 5m/15m ORB entries "are not working" and that the kernel-band
Buy/Sell labels "look accurate / on point" on the chart. F36 already tested this indicator as a FILTER
on the ORB stack (REDUNDANT with VWAP-cap). This script tests something different: the band-cross
signal AS ITS OWN ENTRY — i.e. is the thing that looks good on the chart actually predictive?

The "kernel regression" is (per F36) a CAUSAL one-sided weighted MA: kernelMA = EMA(Σwᵢ·close[i]/Σwᵢ),
wᵢ = exp(-i²/2h²); bands = kernelMA ± mult·σ(resid). Non-repainting. The Pine "Buy"/"Sell" labels fire on
a STATE FLIP: state→+1 when close>upperBand, →-1 when close<lowerBand; a label prints when the held state
flips to the opposite non-zero value. crossBull/crossBear are the raw band crosses (alerts).

THREE READS (all causal — signal confirmed at close of bar t → tradeable at OPEN of bar t+1):
  1. forward-return accuracy   hit-rate & mean ATR-normalised move at H = 1,3,5,10,20 bars after entry
  2. flip-to-flip trade        always-in, reverse on opposite flip; expectancy in R(=ATR) + %, PF, win%, net of costs
  3. the chart illusion        the Buy label is drawn at bar LOW but you fill at the CLOSE (already above the
                               upper band): mean (close-low)/atr gap = why hindsight looks perfect.

    python research/orb_kernel_signal.py [SYM ...]    (default NQ QQQ ; both 5m & 15m, full session)
"""
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "engine"))
import numpy as np, pandas as pd
import hs_db, hs_harness as H, hs_backtest as B, hs_validate as V
from hs_contracts import spec as _CS

# kernel indicator defaults (match the Pine / F36)
K_TYPE, K_LEN, K_H, K_ATRLEN, K_SMOOTH = "Gaussian", 30, 8.0, 14, 3
B_MULT, B_LEN, B_SMOOTH = 1.0, 24, 5
HORIZONS = (1, 3, 5, 10, 20)


def kernel_calc(d, ktype=K_TYPE, length=K_LEN, base_h=K_H, atrlen=K_ATRLEN, smooth=K_SMOOTH,
                adaptive=True, bmult=B_MULT, blen=B_LEN, bsmooth=B_SMOOTH):
    """UNSHIFTED causal port of the Pine indicator. Returns kma/upper/lower + confirmed-bar held state
    + Buy/Sell flip events + raw band crosses (all aligned to the SIGNAL bar t)."""
    c = d["close"].to_numpy(float); n = len(c)
    atr = d["atr14"].to_numpy(float)
    atr_norm = np.where(c > 0, atr / c, 0.0)
    atr_factor = H.ema(pd.Series(atr_norm), atrlen).to_numpy()
    h = base_h * (1.0 + atr_factor * 200.0) if adaptive else np.full(n, base_h)
    h = np.maximum(h, 1e-6)
    # accumulate Σwᵢ·close[t-i] / Σwᵢ in O(n) memory (no big (n×length) matrices)
    nwSum = np.zeros(n); nwWeight = np.zeros(n)
    for i in range(length):
        if ktype == "Gaussian":
            w = np.exp(-(i ** 2) / (2.0 * h ** 2))
        elif ktype == "Epanechnikov":
            w = np.maximum(0.0, 1.0 - (i ** 2) / (h ** 2))
        else:
            w = np.maximum(0.0, (1.0 - np.abs(i / h) ** 3) ** 3)
        ct = np.full(n, np.nan); ct[i:] = c[:n - i]          # close[t-i]
        valid = ~np.isnan(ct)
        nwSum[valid] += w[valid] * ct[valid]
        nwWeight[valid] += w[valid]
    den = nwWeight
    raw = np.where(den > 0, nwSum / np.where(den > 0, den, 1.0), c)
    raw[:length - 1] = np.nan
    kma = H.ema(pd.Series(raw), smooth)
    resid = pd.Series(c) - kma
    sigma = H.ema(resid.rolling(blen, min_periods=blen).std(ddof=0), bsmooth)
    upper = (kma + bmult * sigma).to_numpy(); lower = (kma - bmult * sigma).to_numpy()
    kma = kma.to_numpy()
    # held band state (Pine: update on confirmed close vs band, else hold)
    raw_state = np.where(c > upper, 1.0, np.where(c < lower, -1.0, np.nan))
    state = pd.Series(raw_state).ffill().fillna(0.0).to_numpy()
    prev = np.concatenate([[0.0], state[:-1]])
    buy_flip = (state == 1) & (prev == -1)          # Pine "Buy" label  (state flips -1 -> +1)
    sell_flip = (state == -1) & (prev == 1)         # Pine "Sell" label (state flips +1 -> -1)
    cu = np.concatenate([[np.nan], upper[:-1]]); cl = np.concatenate([[np.nan], lower[:-1]])
    cprev = np.concatenate([[np.nan], c[:-1]])
    cross_bull = (c > upper) & (cprev <= cu)        # ta.crossover(close, upperBand)
    cross_bear = (c < lower) & (cprev >= cl)        # ta.crossunder(close, lowerBand)
    return dict(kma=kma, upper=upper, lower=lower, state=state,
                buy_flip=buy_flip, sell_flip=sell_flip, cross_bull=cross_bull, cross_bear=cross_bear)


def cost_R(sym, atr_entry):
    """Round-trip cost in R(=ATR) units. EQ: 1 tick/side @ $0.01. Futures: SLIP_TICKS/side + commission."""
    if sym.upper() in ("SPY", "QQQ"):
        cost_pts = 2 * 0.01 * 1                                  # 1 tick slippage each side
    else:
        cost_pts = 2 * _CS(sym).tick * _CS(sym).slip_ticks * B.SLIP_MULT + 2 * _CS(sym).commission / _CS(sym).point_value
    return cost_pts / atr_entry


def fwd_accuracy(d, K, longs, shorts):
    """Causal forward returns from NEXT bar open after each signal, ATR-normalised. dict[H]=(hit%, meanR, n)."""
    o = d["open"].to_numpy(); atr = d["atr14"].to_numpy(); n = len(o)
    sig_idx = np.where(longs | shorts)[0]
    sig_idx = sig_idx[sig_idx + 1 < n]                          # need a next-bar entry
    dirn = np.where(longs[sig_idx], 1.0, -1.0)
    out = {}
    for Hn in HORIZONS:
        rows = []
        for k, t in enumerate(sig_idx):
            e = t + 1
            if e + Hn >= n or not np.isfinite(atr[t]) or atr[t] <= 0:
                continue
            rows.append(dirn[k] * (o[e + Hn] - o[e]) / atr[t])
        r = np.array(rows)
        out[Hn] = (100 * np.mean(r > 0) if len(r) else np.nan, r.mean() if len(r) else np.nan, len(r))
    return out


def flip_trades(d, K, sym):
    """Always-in flip-to-flip sim: enter open[t+1] on a flip, exit open[s+1] on next opposite flip.
    Returns per-trade net-R array (R=entry ATR), net-% array, gross-R array, avg bars held."""
    o = d["open"].to_numpy(); c = d["close"].to_numpy(); atr = d["atr14"].to_numpy(); n = len(o)
    buy, sell = K["buy_flip"], K["sell_flip"]
    events = sorted([(i, 1) for i in np.where(buy)[0]] + [(i, -1) for i in np.where(sell)[0]])
    grossR, netR, netpct, held = [], [], [], []
    for (t, side), (s, _) in zip(events, events[1:]):
        e = t + 1
        if e >= n or s + 1 >= n or not np.isfinite(atr[t]) or atr[t] <= 0:
            continue
        entry = o[e]; exitp = o[s + 1]
        g = side * (exitp - entry) / atr[t]
        cR = cost_R(sym, atr[t])
        grossR.append(g); netR.append(g - cR)
        netpct.append(side * (exitp - entry) / entry * 100)
        held.append(s - t)
    return np.array(grossR), np.array(netR), np.array(netpct), (np.mean(held) if held else 0.0)


def rth_mask(d):
    et = pd.to_datetime(d["ts"]).dt.tz_convert("America/New_York")
    mins = et.dt.hour * 60 + et.dt.minute
    return ((et.dt.dayofweek < 5) & (mins >= 570) & (mins < 960)).to_numpy()


def bracket_trades(d, K, sym, polarity, stop_atr=1.0, rr=1.5, rth_only=True):
    """Charitable re-check: enter open[t+1] on each flip, fixed ATR-bracket exit (stop=stop_atr·ATR,
    target=rr·risk), also exit on the opposite flip or EOD. polarity=+1 trade the label's direction
    (momentum), polarity=-1 FADE it (mean-reversion to the kernel). Returns net-R array (R=risk)."""
    o = d["open"].to_numpy(); h = d["high"].to_numpy(); l = d["low"].to_numpy()
    atr = d["atr14"].to_numpy(); n = len(o)
    rth = rth_mask(d)
    et = pd.to_datetime(d["ts"]).dt.tz_convert("America/New_York")
    daykey = (et.dt.year * 10000 + et.dt.month * 100 + et.dt.day).to_numpy()
    flip = np.where(K["buy_flip"], 1, np.where(K["sell_flip"], -1, 0))
    opp = np.where(K["buy_flip"] | K["sell_flip"])[0]
    netR = []
    for t in np.where(flip != 0)[0]:
        if rth_only and not rth[t]:
            continue
        e = t + 1
        if e >= n or not np.isfinite(atr[t]) or atr[t] <= 0:
            continue
        side = polarity * flip[t]
        entry = o[e]; risk = stop_atr * atr[t]
        stop = entry - side * risk; target = entry + side * rr * risk
        nxt_flip = opp[opp > t]; flip_exit = nxt_flip[0] if len(nxt_flip) else n
        out = -side * risk  # default: timeout at flip-exit open (filled below)
        res = None
        for j in range(e, n):
            if daykey[j] != daykey[e]:                      # EOD flat at this bar's open
                res = side * (o[j] - entry); break
            hit_stop = (l[j] <= stop) if side == 1 else (h[j] >= stop)
            hit_tgt = (h[j] >= target) if side == 1 else (l[j] <= target)
            if hit_stop and hit_tgt:                        # ambiguous bar -> assume stop first (conservative)
                res = -risk; break
            if hit_stop:
                res = -risk; break
            if hit_tgt:
                res = rr * risk; break
            if j >= flip_exit:                              # opposite signal -> exit at this open
                res = side * (o[j] - entry); break
        if res is None:
            res = side * (o[-1] - entry)
        netR.append(res / risk - cost_R(sym, atr[t]))
    return np.array(netR)


def illusion_gap(d, K):
    """The chart trap: Buy label is drawn at bar LOW, real fill is the CLOSE (already past upper band).
    Mean (close-low)/atr for buys, (high-close)/atr for sells = hindsight 'perfect entry' overstated by this."""
    h = d["high"].to_numpy(); l = d["low"].to_numpy(); c = d["close"].to_numpy(); atr = d["atr14"].to_numpy()
    bg = (c - l) / atr; sg = (h - c) / atr
    buys = K["buy_flip"] & np.isfinite(atr) & (atr > 0)
    sells = K["sell_flip"] & np.isfinite(atr) & (atr > 0)
    return (np.mean(bg[buys]) if buys.any() else np.nan, np.mean(sg[sells]) if sells.any() else np.nan)


def analyse(con, sym, tf):
    bars = B._externals(con, hs_db.bars(con, tf, "full", sym=sym), sym)
    d = H.compute_state(bars, H.P()); d.attrs["sym"] = sym
    K = kernel_calc(d)
    nb, ns = int(K["buy_flip"].sum()), int(K["sell_flip"].sum())
    print(f"\n############ {sym} {tf}  —  STANDALONE Neural-Kernel-Bands signals  (full session) ############")
    print(f"  flips: {nb} Buy / {ns} Sell   (raw band crosses: "
          f"{int(K['cross_bull'].sum())} up / {int(K['cross_bear'].sum())} down)")

    # 1. forward-return accuracy (the literal 'is the signal on point' test)
    acc = fwd_accuracy(d, K, K["buy_flip"], K["sell_flip"])
    print("  forward accuracy (entry = next bar open, ATR-normalised):")
    hdr = "    " + "  ".join(f"H{Hn:>2}" for Hn in HORIZONS)
    print(hdr)
    print("    hit%  " + "  ".join(f"{acc[Hn][0]:>4.0f}" for Hn in HORIZONS) + "    (50% = coin flip)")
    print("    meanR " + "  ".join(f"{acc[Hn][1]:>+4.2f}" for Hn in HORIZONS) + "    (R = entry ATR)")

    # 2. flip-to-flip trade P&L (how you'd actually trade the labels)
    gR, nR, npct, hold = flip_trades(d, K, sym)
    if len(nR):
        print(f"  flip-to-flip trade (always-in, reverse on opposite flip; n={len(nR)}, avg hold {hold:.0f} bars):")
        print(f"    GROSS  expR {gR.mean():+.3f}  PF {V.pf(gR):.2f}  win {100*np.mean(gR>0):.0f}%")
        print(f"    NET    expR {nR.mean():+.3f}  PF {V.pf(nR):.2f}  win {100*np.mean(nR>0):.0f}%  "
              f"| mean%/trade {npct.mean():+.3f}  total% {npct.sum():+.0f}")

    # 2b. CHARITABLE re-check: RTH-only, real ATR bracket, momentum vs FADE (mean-reversion)
    print("  charitable re-check (RTH-only, ATR bracket stop=1.0 target=1.5R, exit on opp flip/EOD):")
    for pol, nm in ((+1, "FOLLOW (momentum)"), (-1, "FADE   (mean-rev)")):
        r = bracket_trades(d, K, sym, pol)
        if len(r):
            print(f"    {nm}  n={len(r):>4}  expR {r.mean():+.3f}  PF {V.pf(r):.2f}  win {100*np.mean(r>0):.0f}%")

    # 3. the chart illusion
    bg, sg = illusion_gap(d, K)
    print(f"  chart illusion gap (label drawn at low/high, fill at close): Buy +{bg:.2f} ATR  Sell +{sg:.2f} ATR "
          f"above the marker")


def main():
    syms = [s.upper() for s in (sys.argv[1:] or ["NQ", "QQQ"])]
    con = hs_db.connect()
    for sym in syms:
        for tf in ("5m", "15m"):
            analyse(con, sym, tf)
    con.close()
    print("\nNOTE: GROSS expR>0 = signal has directional info; NET<0 = not tradeable after costs.")
    print("A large illusion gap + late entry (fill well past the band) is why it 'looks on point' but isn't.")


if __name__ == "__main__":
    main()
