"""Point-in-time candidate features (ML feature store, entry standard 2026-07-04).

ONE function builds the feature vector for a rule-valid candidate at its signal bar — used by BOTH
the historical dataset builder (bot.ml.dataset) and the live scan (families.scan attaches the same
snapshot to each signal), so training and live scoring share the exact same code path.

Every feature is causal: computed from bars up to and including the signal bar (the fill is booked
at that bar's close). NO realized outcomes (mfe/mae/hold_bars) ever appear here — those are labels.

Feature groups (the spec's list): OR geometry, VWAP, structure, combined-slope quality (Layer 2
grade), candle anatomy, momentum/volatility, regime, session/time, risk geometry.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from bot.strategy.orb_state import slope_engine, slope_grade

GRADE_ORD = {"A+": 5, "A": 4, "B+": 3, "B": 2, "C": 1, "D": 0}

# the canonical feature schema — ORDER MATTERS (the registry stores this list with every model and
# refuses to score when the live schema no longer matches)
FEATURE_COLUMNS = [
    # side + risk geometry
    "side_long", "risk_atr", "rr",
    # OR geometry
    "or_width_atr", "px_vs_edge_atr", "px_vs_mid_atr", "hrs_since_or_close",
    # VWAP
    "vwap_dist_atr", "vwap_slope_atr", "above_vwap",
    # structure
    "st_up", "st_down", "st_range", "dist_swing_atr",
    # Layer-2 slope quality (combined slope engine)
    "slope_S", "slope_sc_atr", "slope_bp", "slope_persistence", "slope_efficiency", "slope_grade_ord",
    # candle anatomy at the signal bar
    "body_frac", "up_wick_frac", "dn_wick_frac",
    # momentum / volatility
    "ret1_atr", "ret3_atr", "ret12_atr", "atr_pct", "atr_expansion", "rel_volume",
    # regime
    "regime_A", "regime_B", "regime_C", "regime_D", "local_trend", "local_range", "local_volatile",
    # session / time
    "hour_sin", "hour_cos", "dow",
    # symbol identity (pooled multi-symbol training — MLP-001; unknown symbols = all zeros)
    "sym_QQQ", "sym_SPY", "sym_NQ", "sym_ES", "sym_GC", "is_futures",
    # institutional-rejection / pre-VWAP reversal detectors (user spec 2026-07-04 — ADVISORY,
    # gauntlet-test before gating; old cached datasets carry NaN here until rebuilt)
    "rsi14", "rsi_div", "macd_hist_atr", "macd_shrink", "macd_div",
    "vwap_slope_div", "capitulation_wick", "absorption",
    # L2/L3 book features (bot/ml/l2_features — synthesized from registered on-disk depth data;
    # NaN when no L2 store exists for the symbol, median-imputed at train time)
    "l2_spread_bps", "l2_depth_imb", "l2_flow_imb", "l2_quote_rate",
    "l2_absorption", "l2_book_pressure",
]

POOL_SYMBOLS = ("QQQ", "SPY", "NQ", "ES")     # the validated pooled-training set (GC unverified)


def symbol_features(symbol: str | None) -> dict:
    """Symbol one-hots + futures flag so ONE pooled model can serve every instrument."""
    s = (symbol or "").upper()
    out = {f"sym_{k}": 1.0 if s == k else 0.0 for k in ("QQQ", "SPY", "NQ", "ES", "GC")}
    out["is_futures"] = 1.0 if s in ("NQ", "MNQ", "ES", "GC") else 0.0
    return out


def or_levels(d: pd.DataFrame, or_s: int = 570, or_e: int = 600):
    """Daily OR high/low aligned to every bar of the harness-state frame (same construction as the
    engine) + ET minutes-of-day. Bars before the OR close carry that day's levels too — callers
    only read them at post-OR signal bars."""
    et = pd.to_datetime(d["ts"]).dt.tz_convert("America/New_York")
    date = et.dt.date.to_numpy()
    mins = (et.dt.hour * 60 + et.dt.minute).to_numpy()
    in_or = (mins >= or_s) & (mins < or_e)
    df = pd.DataFrame({"date": date, "h": d["high"].to_numpy(float),
                       "l": d["low"].to_numpy(float), "in_or": in_or})
    org = df[df["in_or"]].groupby("date").agg(orh=("h", "max"), orl=("l", "min"))
    m = pd.DataFrame({"date": date}).merge(org, on="date", how="left")
    return m["orh"].to_numpy(float), m["orl"].to_numpy(float), mins


def _col(d, name, i, default=np.nan) -> float:
    if name in d.columns:
        v = d[name].iloc[i]
        try:
            return float(v)
        except (TypeError, ValueError):
            return default
    return default


def pit_features(d: pd.DataFrame, i: int, side: str, entry: float, stop: float,
                 orh: float | None = None, orl: float | None = None,
                 mins_of_day: float | None = None, or_e: int = 600,
                 rr: float = 4.0, symbol: str | None = None) -> dict:
    """Feature snapshot for a candidate at signal-bar index `i` of a harness-state frame.
    Missing inputs degrade to NaN (models are trained with median imputation)."""
    sign = 1 if side == "long" else -1
    c = d["close"].to_numpy(float)
    o = d["open"].to_numpy(float)
    h = d["high"].to_numpy(float)
    lo = d["low"].to_numpy(float)
    px = c[i]
    atr = _col(d, "atr14", i)
    atr = atr if np.isfinite(atr) and atr > 0 else np.nan

    def natr(x):  # normalize a price distance by ATR (NaN-safe)
        return float(x / atr) if np.isfinite(atr) and np.isfinite(x) else np.nan

    # OR geometry
    or_w = natr(orh - orl) if (orh is not None and orl is not None
                               and np.isfinite(orh) and np.isfinite(orl)) else np.nan
    mid = (orh + orl) / 2.0 if or_w == or_w else np.nan
    edge = (orh if sign == 1 else orl) if or_w == or_w else np.nan
    hrs_since = ((mins_of_day - or_e) / 60.0) if mins_of_day is not None else np.nan

    # VWAP
    vw = _col(d, "vwap_sess", i)
    vw6 = _col(d, "vwap_sess", max(0, i - 6))
    vwap_dist = natr(px - vw)
    vwap_slope = natr(vw - vw6)

    # structure
    st = int(_col(d, "st_state", i, 0.0)) if _col(d, "st_state", i, np.nan) == _col(d, "st_state", i, np.nan) else 0
    swing = _col(d, "spl", i) if sign == 1 else _col(d, "sph", i)
    dist_swing = natr(sign * (px - swing))          # how far price sits beyond its protective swing

    # Layer-2 slope quality (combined slope engine over the last 12 bars)
    eng = slope_engine(o[max(0, i - 11):i + 1], c[max(0, i - 11):i + 1],
                       atr if atr == atr else 0.0)
    grade = slope_grade(eng["S"], eng["persistence"], eng["efficiency"], side=side)

    # candle anatomy at the signal bar
    rng = h[i] - lo[i]
    body = abs(c[i] - o[i])
    body_frac = body / rng if rng > 0 else 0.0
    up_wick = (h[i] - max(c[i], o[i])) / rng if rng > 0 else 0.0
    dn_wick = (min(c[i], o[i]) - lo[i]) / rng if rng > 0 else 0.0

    # momentum / volatility
    ret1 = natr(c[i] - c[i - 1]) if i >= 1 else np.nan
    ret3 = natr(c[i] - c[i - 3]) if i >= 3 else np.nan
    ret12 = natr(c[i] - c[i - 12]) if i >= 12 else np.nan
    atr_pct = _col(d, "atr_pct", i)
    if atr_pct != atr_pct and atr == atr and px > 0:
        atr_pct = 100.0 * atr / px
    a_series = d["atr14"].to_numpy(float)[max(0, i - 49):i + 1]
    atr_exp = float(atr / np.nanmean(a_series)) if atr == atr and np.nanmean(a_series) > 0 else np.nan
    if "volume" in d.columns and i >= 20:
        v = d["volume"].to_numpy(float)[max(0, i - 19):i + 1]
        rel_vol = float(v[-1] / np.nanmean(v[:-1])) if np.nanmean(v[:-1]) > 0 else np.nan
    else:
        rel_vol = np.nan

    # regime
    reg = str(d["macro_regime"].iloc[i]) if "macro_regime" in d.columns else "?"
    loc = int(_col(d, "local_regime", i, 0.0)) if _col(d, "local_regime", i, np.nan) == _col(d, "local_regime", i, np.nan) else 0

    # session / time
    ts = pd.Timestamp(d["ts"].iloc[i])
    et = ts.tz_convert("America/New_York") if ts.tz is not None else ts
    hr = et.hour + et.minute / 60.0

    return {
        "side_long": 1.0 if sign == 1 else 0.0,
        "risk_atr": natr(abs(entry - stop)),
        "rr": float(rr),
        "or_width_atr": or_w,
        "px_vs_edge_atr": natr(sign * (px - edge)) if edge == edge else np.nan,
        "px_vs_mid_atr": natr(sign * (px - mid)) if mid == mid else np.nan,
        "hrs_since_or_close": hrs_since,
        "vwap_dist_atr": vwap_dist,
        "vwap_slope_atr": vwap_slope,
        "above_vwap": (1.0 if px > vw else 0.0) if vw == vw else np.nan,
        "st_up": 1.0 if st == 1 else 0.0,
        "st_down": 1.0 if st == 2 else 0.0,
        "st_range": 1.0 if st == 3 else 0.0,
        "dist_swing_atr": dist_swing,
        "slope_S": eng["S"],
        "slope_sc_atr": eng["sc_atr"],
        "slope_bp": eng["body_pressure"],
        "slope_persistence": eng["persistence"],
        "slope_efficiency": eng["efficiency"],
        "slope_grade_ord": float(GRADE_ORD.get(grade, 0)),
        "body_frac": body_frac,
        "up_wick_frac": up_wick,
        "dn_wick_frac": dn_wick,
        "ret1_atr": ret1,
        "ret3_atr": ret3,
        "ret12_atr": ret12,
        "atr_pct": atr_pct,
        "atr_expansion": atr_exp,
        "rel_volume": rel_vol,
        "regime_A": 1.0 if reg == "A" else 0.0,
        "regime_B": 1.0 if reg == "B" else 0.0,
        "regime_C": 1.0 if reg == "C" else 0.0,
        "regime_D": 1.0 if reg == "D" else 0.0,
        "local_trend": 1.0 if loc == 1 else 0.0,
        "local_range": 1.0 if loc == 2 else 0.0,
        "local_volatile": 1.0 if loc == 3 else 0.0,
        "hour_sin": float(np.sin(2 * np.pi * hr / 24.0)),
        "hour_cos": float(np.cos(2 * np.pi * hr / 24.0)),
        "dow": float(et.dayofweek),
        **symbol_features(symbol),
        **_reversals(d, i),
    }


def _reversals(d, i) -> dict:
    try:
        from bot.strategy.reversals import reversal_features
        return reversal_features(d, i)
    except Exception:
        return {}


def to_vector(feats: dict) -> np.ndarray:
    """Ordered feature vector (FEATURE_COLUMNS) from a snapshot dict; missing keys -> NaN."""
    return np.array([float(feats.get(k, np.nan)) if feats.get(k) is not None else np.nan
                     for k in FEATURE_COLUMNS], float)


if __name__ == "__main__":   # smoke: synthetic frame -> full vector, no NaN explosions
    rng = np.random.default_rng(0)
    n = 120
    c = 500 + np.cumsum(rng.normal(0, 0.4, n))
    ts = pd.date_range("2026-06-01 09:30", periods=n, freq="5min",
                       tz="America/New_York").tz_convert("UTC")
    d = pd.DataFrame({"ts": ts, "open": c - 0.1, "high": c + 0.5, "low": c - 0.5, "close": c,
                      "volume": 1000.0, "atr14": 1.0, "vwap_sess": c - 0.3,
                      "st_state": 1, "spl": c - 2.0, "sph": c + 2.0,
                      "macro_regime": "A", "local_regime": 1})
    orh, orl, mins = or_levels(d)
    f = pit_features(d, 100, "long", entry=c[100], stop=c[100] - 1.2,
                     orh=orh[100], orl=orl[100], mins_of_day=float(mins[100]))
    v = to_vector(f)
    assert v.shape == (len(FEATURE_COLUMNS),)
    # l2_* (6) join at the DATASET level, not in the snapshot -> NaN here by design
    assert np.isfinite(v).sum() >= len(FEATURE_COLUMNS) - 9, f"too many NaNs: {f}"
    print(f"features_pit OK - {len(FEATURE_COLUMNS)} features, {np.isfinite(v).sum()} finite on the smoke frame")
