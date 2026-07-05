"""SWING dataset (daily / weekly training — the 1d/1w timeframes the ORB replay can't serve).

A first, honest swing-module dataset: one row per BAR-CLOSE candidate on daily (store) or weekly
(resampled) bars, labeled by a TRIPLE-BARRIER walk — stop 1.5·ATR, target 3.0·ATR (2R), horizon
20 daily bars / 12 weekly bars, first-touch, stop-first on same-bar ambiguity. Long candidates
when close > EMA20 > EMA50 (trend filter), shorts mirrored — a deliberately simple, testable
setup rule so the ML layer has something real to grade while the swing STRATEGY research matures.

Features: the same PIT snapshot (OR/VWAP fields go NaN and are median-imputed) + reversal
detectors + symbol identity — so swing models share the schema and the registry.

    python -m bot.ml.swing_dataset QQQ 1d
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from bot.ml.features_pit import FEATURE_COLUMNS, pit_features
from bot.ml.registry import FeatureStore

STOP_ATR, TGT_ATR = 1.5, 3.0
HORIZON = {"1d": 20, "1w": 12}


def _daily_frame(sym: str, tf: str) -> pd.DataFrame:
    import sys
    from pathlib import Path
    from bot.config import BOT_ROOT
    sys.path.insert(0, str(BOT_ROOT.parent / "engine"))
    import hs_db
    import os
    cwd = os.getcwd()
    os.chdir(BOT_ROOT.parent)
    try:
        con = hs_db.connect()
        b = hs_db.bars(con, "1d", "rth", sym=sym)
        con.close()
    finally:
        os.chdir(cwd)
    b["ts"] = pd.to_datetime(b["ts"], utc=True)
    if tf == "1w":
        b = (b.set_index("ts").resample("1W", label="left", closed="left")
              .agg({"open": "first", "high": "max", "low": "min", "close": "last",
                    "volume": "sum"}).dropna(subset=["open"]).reset_index())
    for c in ("open", "high", "low", "close"):
        b[c] = b[c].astype(float)
    # indicators the PIT snapshot expects (ATR / EMAs / a session-less 'vwap' = typical price MA)
    h, l, cl = b["high"], b["low"], b["close"]
    tr = pd.concat([h - l, (h - cl.shift()).abs(), (l - cl.shift()).abs()], axis=1).max(axis=1)
    b["atr14"] = tr.ewm(alpha=1 / 14, adjust=False).mean()
    b["ema20"] = cl.ewm(span=20, adjust=False).mean()
    b["ema50"] = cl.ewm(span=50, adjust=False).mean()
    b["vwap_sess"] = ((h + l + cl) / 3).rolling(10).mean()   # fair-price proxy on swing bars
    b["st_state"] = np.where((cl > b["ema20"]) & (b["ema20"] > b["ema50"]), 1,
                             np.where((cl < b["ema20"]) & (b["ema20"] < b["ema50"]), 2, 0))
    b["macro_regime"] = "?"
    b["local_regime"] = 0
    return b


def build_swing(sym: str = "QQQ", tf: str = "1d", save: bool = True) -> pd.DataFrame:
    from bot.strategy.orb_candidates import STRATEGY_VERSION
    if tf not in HORIZON:
        raise ValueError("swing tf must be 1d or 1w")
    d = _daily_frame(sym, tf)
    n = len(d)
    h = d["high"].to_numpy(float); lo = d["low"].to_numpy(float)
    c = d["close"].to_numpy(float); atr = d["atr14"].to_numpy(float)
    st = d["st_state"].to_numpy()
    hz = HORIZON[tf]
    rows = []
    for i in range(60, n - 1):
        if st[i] == 0 or not np.isfinite(atr[i]) or atr[i] <= 0:
            continue
        side = "long" if st[i] == 1 else "short"
        sign = 1 if side == "long" else -1
        entry = c[i]
        stop = entry - sign * STOP_ATR * atr[i]
        tgt = entry + sign * TGT_ATR * atr[i]
        # triple-barrier first-touch walk (stop-first on same-bar ambiguity)
        r = None
        for k in range(i + 1, min(i + 1 + hz, n)):
            adverse = lo[k] if sign == 1 else h[k]
            favor = h[k] if sign == 1 else lo[k]
            if sign * (adverse - stop) <= 0:
                r = -STOP_ATR / STOP_ATR; break
            if sign * (favor - tgt) >= 0:
                r = TGT_ATR / STOP_ATR; break
        if r is None:                                       # time barrier: mark-to-close
            k = min(i + hz, n - 1)
            r = sign * (c[k] - entry) / (STOP_ATR * atr[i])
        feats = pit_features(d, i, side, entry=entry, stop=stop, symbol=sym,
                             rr=TGT_ATR / STOP_ATR)
        rows.append({"ts": pd.Timestamp(d["ts"].iloc[i]), "symbol": sym, "side": side,
                     "strategy_version": f"swing-{tf}-0.1 ({STRATEGY_VERSION} era)",
                     "session": "swing", "tf": tf,
                     **{k2: feats.get(k2, np.nan) for k2 in FEATURE_COLUMNS},
                     "y_win": int(r > 0), "y_tp2": int(r >= TGT_ATR / STOP_ATR - 1e-9),
                     "y_stop": int(r <= -0.999), "net_r": round(float(r), 3),
                     "gross_r": round(float(r), 3), "mfe_r": np.nan, "mae_r": np.nan,
                     "hold_bars": hz})
    df = pd.DataFrame(rows)
    if len(df):
        df = df.sort_values("ts").reset_index(drop=True)
        if save:
            FeatureStore().save(f"swing_{sym}_{tf}", "v1", df)
    return df


if __name__ == "__main__":
    import sys
    sym = (sys.argv[1] if len(sys.argv) > 1 else "QQQ").upper()
    tf = sys.argv[2] if len(sys.argv) > 2 else "1d"
    df = build_swing(sym, tf)
    print(f"{sym} swing {tf}: {len(df)} candidates | win {df['y_win'].mean():.3f} | "
          f"avg {df['net_r'].mean():+.3f}R | span {df['ts'].iloc[0].date()}..{df['ts'].iloc[-1].date()}"
          if len(df) else "no candidates")
    print("swing dataset OK")
