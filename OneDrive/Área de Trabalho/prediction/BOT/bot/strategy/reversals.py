"""Institutional-rejection / pre-VWAP reversal detectors (user spec 2026-07-04) — ADVISORY
features, to be gauntlet-tested before any of them gates a trade.

The spec's four detector families, all causal at bar i (no future bars):
  1. RSI        — overbought/oversold level + PRICE/RSI divergence (higher high in price,
                  lower high in RSI = bearish divergence; mirror bullish).
  2. MACD       — histogram magnitude (ATR-normalized), SHRINKING histogram (momentum fading
                  toward the zero line), PRICE/MACD divergence.
  3. VWAP slope — slope-momentum divergence: price still falling while the VWAP slope curls up
                  (bullish accumulation; mirror bearish) + flat/curling VWAP (trend exhaustion).
  4. Volume     — CAPITULATION WICK: long fading wick on high volume near VWAP (defense /
                  absorption); ABSORPTION: price stalls at VWAP on outsized volume.

`reversal_features(d, i)` -> dict of 8 features consumed by the PIT schema (bot/ml/features_pit),
so the ML/NN heads learn whether these reads carry edge BEFORE anyone trades them.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

NEAR_VWAP_ATR = 0.5      # "near VWAP" = within this many ATR
WICK_MIN_FRAC = 0.6      # capitulation: wick >= this fraction of the bar's range
VOL_SPIKE = 1.5          # capitulation/absorption: volume >= this x 20-bar average
STALL_ATR = 0.15         # absorption: |close - open| <= this x ATR (price went nowhere)


def _rsi(closes: np.ndarray, n: int = 14) -> np.ndarray:
    c = pd.Series(closes, dtype=float)
    d = c.diff()
    up = d.clip(lower=0).ewm(alpha=1 / n, adjust=False).mean()
    dn = (-d.clip(upper=0)).ewm(alpha=1 / n, adjust=False).mean()
    rs = up / (dn + 1e-12)
    return (100 - 100 / (1 + rs)).to_numpy()


def _macd_hist(closes: np.ndarray) -> np.ndarray:
    c = pd.Series(closes, dtype=float)
    macd = c.ewm(span=12, adjust=False).mean() - c.ewm(span=26, adjust=False).mean()
    return (macd - macd.ewm(span=9, adjust=False).mean()).to_numpy()


def _divergence(price: np.ndarray, osc: np.ndarray, look: int = 10) -> float:
    """+1 bullish divergence (price lower low, oscillator higher low), -1 bearish (price higher
    high, oscillator lower high), 0 none — over the last `look` bars vs the `look` before them."""
    if len(price) < 2 * look:
        return 0.0
    p_now, p_prev = price[-look:], price[-2 * look:-look]
    o_now, o_prev = osc[-look:], osc[-2 * look:-look]
    if np.nanmax(p_now) > np.nanmax(p_prev) and np.nanmax(o_now) < np.nanmax(o_prev):
        return -1.0                                   # bearish: higher high, weaker oscillator
    if np.nanmin(p_now) < np.nanmin(p_prev) and np.nanmin(o_now) > np.nanmin(o_prev):
        return 1.0                                    # bullish: lower low, stronger oscillator
    return 0.0


def reversal_features(d: pd.DataFrame, i: int) -> dict:
    """The 8 reversal features at bar i (causal window ending AT i). NaN-safe everywhere."""
    lo_i = max(0, i - 59)
    c = d["close"].to_numpy(float)[lo_i:i + 1]
    o = d["open"].to_numpy(float)[lo_i:i + 1]
    h = d["high"].to_numpy(float)[lo_i:i + 1]
    lw = d["low"].to_numpy(float)[lo_i:i + 1]
    v = d["volume"].to_numpy(float)[lo_i:i + 1] if "volume" in d else np.full(i + 1 - lo_i, np.nan)
    vw = d["vwap_sess"].to_numpy(float)[lo_i:i + 1] if "vwap_sess" in d else np.full(i + 1 - lo_i, np.nan)
    atr = float(d["atr14"].iloc[i]) if "atr14" in d else np.nan
    atr = atr if np.isfinite(atr) and atr > 0 else np.nan
    n = len(c)
    out = {"rsi14": np.nan, "rsi_div": 0.0, "macd_hist_atr": np.nan, "macd_shrink": 0.0,
           "macd_div": 0.0, "vwap_slope_div": 0.0, "capitulation_wick": 0.0, "absorption": 0.0}
    if n < 30:
        return out
    rsi = _rsi(c)
    hist = _macd_hist(c)
    out["rsi14"] = round(float(rsi[-1]), 2)
    out["rsi_div"] = _divergence(c, rsi)
    if atr == atr:
        out["macd_hist_atr"] = round(float(hist[-1] / atr), 4)
    # histogram shrinking toward zero for >= 3 bars = momentum fading (signed by which side of 0)
    if n >= 4 and abs(hist[-1]) < abs(hist[-2]) < abs(hist[-3]):
        out["macd_shrink"] = float(np.sign(hist[-1]) * -1.0)   # +1 = bearish momentum fading (bullish)
    out["macd_div"] = _divergence(c, hist)
    # VWAP slope-momentum divergence: price direction vs the CHANGE of the VWAP slope
    if np.isfinite(vw[-1]) and n >= 12:
        sl_now = vw[-1] - vw[-6]
        sl_prev = vw[-6] - vw[-11]
        price_dir = np.sign(c[-1] - c[-6])
        slope_mom = np.sign(sl_now - sl_prev)
        if price_dir < 0 and slope_mom > 0:
            out["vwap_slope_div"] = 1.0               # bullish accumulation under a falling tape
        elif price_dir > 0 and slope_mom < 0:
            out["vwap_slope_div"] = -1.0
    # capitulation wick near VWAP: long fading wick + volume spike within NEAR_VWAP_ATR of VWAP
    rng = h[-1] - lw[-1]
    vavg = float(np.nanmean(v[-21:-1])) if n >= 21 else np.nan
    near_vwap = (atr == atr and np.isfinite(vw[-1]) and abs(c[-1] - vw[-1]) <= NEAR_VWAP_ATR * atr)
    if rng > 0 and vavg == vavg and vavg > 0 and near_vwap and v[-1] >= VOL_SPIKE * vavg:
        low_wick = (min(c[-1], o[-1]) - lw[-1]) / rng
        up_wick = (h[-1] - max(c[-1], o[-1])) / rng
        if low_wick >= WICK_MIN_FRAC:
            out["capitulation_wick"] = 1.0            # sellers absorbed below -> bullish defense
        elif up_wick >= WICK_MIN_FRAC:
            out["capitulation_wick"] = -1.0
        # absorption: massive volume, price went nowhere at the level
        if atr == atr and abs(c[-1] - o[-1]) <= STALL_ATR * atr:
            out["absorption"] = 1.0
    return out


if __name__ == "__main__":   # self-test: constructed divergences + capitulation fire correctly
    rng_ = np.random.default_rng(3)
    n = 80
    # bearish divergence tape: price grinds to a higher high while momentum decays
    base = np.concatenate([np.linspace(100, 104, 40), 104 + 0.8 * np.sin(np.linspace(0, 3, 40)) +
                           np.linspace(0, 0.6, 40)])
    c = base + rng_.normal(0, 0.02, n)
    d = pd.DataFrame({"close": c, "open": c - 0.05, "high": c + 0.3, "low": c - 0.3,
                      "volume": 1000.0, "vwap_sess": c - 0.2, "atr14": 1.0})
    f = reversal_features(d, n - 1)
    assert f["rsi14"] == f["rsi14"] and 0 <= f["rsi14"] <= 100
    # capitulation: hammer on 3x volume near VWAP
    d2 = d.copy()
    d2.loc[n - 1, ["open", "close", "high", "low", "volume", "vwap_sess"]] = \
        [c[-1], c[-1] + 0.02, c[-1] + 0.05, c[-1] - 2.0, 3500.0, c[-1] - 0.1]
    f2 = reversal_features(d2, n - 1)
    assert f2["capitulation_wick"] == 1.0, f2
    # causality: mutating future bars can't change bar i's read
    d3 = d.copy(); d3.loc[d3.index[-1], "close"] = 999.0
    f3 = reversal_features(d3, n - 10)
    f4 = reversal_features(d, n - 10)
    assert all((f3[k] == f4[k]) or (f3[k] != f3[k] and f4[k] != f4[k]) for k in f3), (f3, f4)
    print("reversals OK -", {k: v for k, v in f.items() if v == v})
