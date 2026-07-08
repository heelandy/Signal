"""Feature Engineering Engine (FEE-001) — momentum, volume, volatility, trend features on a bar frame.

Pure pandas/numpy (no TA-Lib). `compute_features(bars)` returns the full latest snapshot the signal
carries as context (and the ML layer's feature source). Covers the FEE-001 / example.txt groups:
momentum (RSI/MACD/ROC), volume (rel-vol, spike, VWAP-dist), volatility (ATR%, ATR-expansion, BB &
Keltner width, realized vol), trend (EMA slopes, ADX).
"""
from __future__ import annotations

import numpy as np
import pandas as pd


def ema(s, n):
    return s.ewm(span=n, adjust=False).mean()


def rsi(close, n=14):
    d = close.diff()
    up = d.clip(lower=0).ewm(alpha=1 / n, adjust=False).mean()
    dn = (-d.clip(upper=0)).ewm(alpha=1 / n, adjust=False).mean()
    rs = up / (dn + 1e-12)
    return 100 - 100 / (1 + rs)


def atr(df, n=14):
    h, l, c = df["high"], df["low"], df["close"]
    tr = pd.concat([h - l, (h - c.shift()).abs(), (l - c.shift()).abs()], axis=1).max(axis=1)
    return tr.ewm(alpha=1 / n, adjust=False).mean()


def adx(df, n=14):
    h, l, c = df["high"], df["low"], df["close"]
    up = h.diff(); dn = -l.diff()
    plus = np.where((up > dn) & (up > 0), up, 0.0)
    minus = np.where((dn > up) & (dn > 0), dn, 0.0)
    a = atr(df, n)
    pdi = 100 * pd.Series(plus, index=df.index).ewm(alpha=1 / n, adjust=False).mean() / (a + 1e-12)
    mdi = 100 * pd.Series(minus, index=df.index).ewm(alpha=1 / n, adjust=False).mean() / (a + 1e-12)
    dx = 100 * (pdi - mdi).abs() / (pdi + mdi + 1e-12)
    return dx.ewm(alpha=1 / n, adjust=False).mean()


def session_vwap(df):
    et = pd.to_datetime(df["ts_et"]) if "ts_et" in df else pd.to_datetime(df.index)
    day = et.dt.date.values
    tp = (df["high"] + df["low"] + df["close"]) / 3
    pv = (tp * df["volume"]).groupby(day).cumsum()
    vv = df["volume"].groupby(day).cumsum()
    return pv / (vv + 1e-12)


def compute_features(bars: pd.DataFrame) -> dict:
    """Latest feature snapshot from a bar frame (ts_et, o/h/l/c/v)."""
    df = bars.copy()
    c, h, l, v = df["close"], df["high"], df["low"], df["volume"].astype(float)
    e9, e21, e50 = ema(c, 9), ema(c, 21), ema(c, 50)
    a = atr(df, 14)
    macd = ema(c, 12) - ema(c, 26); sig = ema(macd, 9)
    bb_w = (c.rolling(20).std() * 2 * 2) / (c.rolling(20).mean() + 1e-12)        # band width / price
    kelt_w = (a * 2 * 2) / (ema(c, 20) + 1e-12)
    rv = c.pct_change().rolling(20).std() * np.sqrt(252 * 78)                     # annualised intraday vol
    vwap = session_vwap(df)
    rsi14 = rsi(c, 14)
    adx14 = adx(df, 14)
    vavg = v.rolling(20).mean()

    def last(s):
        x = s.iloc[-1]
        return None if pd.isna(x) else round(float(x), 4)
    px = float(c.iloc[-1])
    return {
        # momentum
        "rsi": last(rsi14), "macd": last(macd), "macd_signal": last(sig), "macd_hist": last(macd - sig),
        "roc_10": last(100 * (c / c.shift(10) - 1)), "roc_5": last(100 * (c / c.shift(5) - 1)),
        # trend
        "ema9_slope": last((e9 - e9.shift(3)) / a), "ema21_slope": last((e21 - e21.shift(5)) / a),
        "above_ema50": bool(px > e50.iloc[-1]) if not pd.isna(e50.iloc[-1]) else None,
        "ema_stack_bull": bool(e9.iloc[-1] > e21.iloc[-1] > e50.iloc[-1]), "adx": last(adx14),
        # volatility
        "atr": last(a), "atr_pct": last(100 * a / c), "atr_expansion": last(a / a.rolling(50).mean()),
        "bb_width_pct": last(100 * bb_w), "keltner_width_pct": last(100 * kelt_w), "realized_vol": last(rv),
        # volume
        "rel_volume": last(v / (vavg + 1e-12)), "volume_spike": bool(v.iloc[-1] > 2 * (vavg.iloc[-1] or 1e9)),
        "vwap_dist_atr": last((c - vwap) / a),
        "price": round(px, 2),
    }


def feature_snapshot(bars: pd.DataFrame) -> dict:
    """Compact, non-null subset for attaching to a signal's evidence."""
    f = compute_features(bars)
    return {k: f[k] for k in ("rsi", "macd_hist", "roc_5", "adx", "atr_pct", "atr_expansion",
                              "rel_volume", "vwap_dist_atr", "ema_stack_bull", "above_ema50") if f.get(k) is not None}


if __name__ == "__main__":
    import sys; sys.path.insert(0, ".")
    from bot.market_data.providers import get_bars
    for sym in ("QQQ", "SPY"):
        b = get_bars(sym, "5m", period="5d")
        f = compute_features(b)
        print(f"\n{sym} ({b.attrs.get('provider')}) features @ {f['price']}:")
        for grp, keys in [("momentum", ("rsi", "macd_hist", "roc_5")), ("trend", ("adx", "ema9_slope", "ema_stack_bull", "above_ema50")),
                          ("volatility", ("atr_pct", "atr_expansion", "bb_width_pct", "realized_vol")), ("volume", ("rel_volume", "volume_spike", "vwap_dist_atr"))]:
            print(f"  {grp:11}: " + ", ".join(f"{k}={f[k]}" for k in keys))
    print("\nfeature engine OK")
