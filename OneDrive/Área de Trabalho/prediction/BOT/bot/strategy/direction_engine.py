"""Multi-timeframe ROLLING direction engine (user research 2026-07-02).

One 1-minute feed, multiple directional windows — the 1m candle array is the single source of
truth; every timeframe direction is INDEPENDENTLY calculated from a different number of 1m bars:

    2M  = last   2 × 1m   immediate movement          30M = last  30 × 1m   session trend
    5M  = last   5 × 1m   micro trend                 1H  = last  60 × 1m   hourly trend
    15M = last  15 × 1m   short intraday trend        4H  = last 240 × 1m   four-hour trend

Each window scores  D = 0.30·S + 0.20·P + 0.20·E + 0.15·B + 0.15·M  ∈ [−1, +1]:
    S = ATR-normalized regression slope of closes (clipped at the ±0.30 'strong' band)
    P = signed directional persistence  (U−D)/(U+D) over meaningful ΔP
    E = Kaufman efficiency × sign(net move)
    B = recency-weighted candle-body pressure
    M = micro market-structure (higher-highs/lows vs lower-highs/lows, bar-to-bar)
Classification: ±0.12 / ±0.30 / ±0.65 → RANGE · WEAK_UP/DOWN · UP/DOWN · STRONG_UP/DOWN, with a
RANGE override when efficiency is low and price keeps crossing the window midpoint.

ROLLING states update on every completed 1m candle (no waiting for the aligned HTF close);
CONFIRMED states are the last completed clock-aligned candle blocks (5/15/30/60m) — both are
reported ("15M ROLLING: DOWN · 15M CONFIRMED: UP" = pullback inside a larger uptrend).

This is DETECTION/awareness (backs up — does not replace — the confirmed swing st_state, which
remains the validated edge gate). Entries stay on the every-2-bars cadence per the spec. All
inputs are completed 1m bars; an optional live price only refreshes the IMMEDIATE read between
minute closes (the 10–15 s update — full intrabar updates arrive with tick data later).

    from bot.strategy.direction_engine import update_all_directions, review_window
    states = update_all_directions(bars_1m)      # {'2M': {...}, '5M': {...}, ...}
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from bot.strategy.orb_state import efficiency_ratio, _reg_slope

TIMEFRAME_WINDOWS = {"2M": 2, "5M": 5, "15M": 15, "30M": 30, "1H": 60, "4H": 240}
WEIGHTS = {"S": 0.30, "P": 0.20, "E": 0.20, "B": 0.15, "M": 0.15}
BAND_WEAK, BAND_DIR, BAND_STRONG = 0.12, 0.30, 0.65
S_CLIP_ATR = 0.30                     # slope saturates at the 'strong' band (±0.30 ATR/bar -> ±1)


def classify(score: float) -> str:
    a = abs(score)
    if a < BAND_WEAK:
        return "RANGE"
    lab = "UP" if score > 0 else "DOWN"
    if a >= BAND_STRONG:
        return f"STRONG_{lab}"
    if a >= BAND_DIR:
        return lab
    return f"WEAK_{lab}"


def _mid_crossings(closes: np.ndarray, mid: float) -> int:
    side = np.sign(closes - mid)
    side = side[side != 0]
    return int((np.diff(side) != 0).sum()) if len(side) > 1 else 0


def review_window(opens, highs, lows, closes, atr: float) -> dict:
    """Score one directional window (any number of 1m bars ≥ 2). Symmetric, causal, guarded."""
    o = np.asarray(opens, float); h = np.asarray(highs, float)
    l = np.asarray(lows, float); c = np.asarray(closes, float)
    n = len(c)
    if n < 2 or not np.isfinite(atr) or atr <= 0:
        return {"state": "INSUFFICIENT_DATA", "score": 0.0}
    # S — regression slope of closes, ATR units, clipped to the strong band
    S = float(np.clip(_reg_slope(c) / atr / S_CLIP_ATR, -1.0, 1.0)) if n >= 3 else \
        float(np.clip((c[-1] - c[0]) / atr / S_CLIP_ATR, -1.0, 1.0))
    # P — signed persistence (U−D)/(U+D) over meaningful moves (noise = 5% of ATR)
    dP = np.diff(c)
    dP = dP[np.abs(dP) > 0.05 * atr]
    P = float((np.sum(dP > 0) - np.sum(dP < 0)) / len(dP)) if len(dP) else 0.0
    # E — efficiency × direction of the net move
    net = c[-1] - c[0]
    E = float(efficiency_ratio(c) * np.sign(net))
    # B — recency-weighted body pressure
    w = 1.0 + np.arange(n, dtype=float) / max(n - 1, 1)
    body = c - o
    den = float((w * np.abs(body)).sum())
    B = float((w * body).sum() / den) if den > 0 else 0.0
    # M — micro structure: bar-to-bar higher-highs/lows vs lower-highs/lows
    if n >= 2:
        hh = np.sum(np.diff(h) > 0); lh = np.sum(np.diff(h) < 0)
        hl = np.sum(np.diff(l) > 0); ll = np.sum(np.diff(l) < 0)
        M = float(((hh - lh) + (hl - ll)) / (2.0 * (n - 1)))
    else:
        M = 0.0
    D = (WEIGHTS["S"] * S + WEIGHTS["P"] * P + WEIGHTS["E"] * E
         + WEIGHTS["B"] * B + WEIGHTS["M"] * M)
    state = classify(D)
    # RANGE override (spec: low efficiency + repeated midpoint crossings + overlap = ranging)
    mid = (float(h.max()) + float(l.min())) / 2.0
    crossings = _mid_crossings(c, mid)
    ranging = abs(E) < 0.25 and crossings >= max(2, n // 5)
    if ranging and "STRONG" not in state:
        state = "RANGE"
    return {"state": state, "score": round(float(D), 4),
            "S": round(S, 3), "P": round(P, 3), "E": round(E, 3), "B": round(B, 3),
            "M": round(M, 3), "mid_crossings": crossings, "n": int(n)}


def _cols(bars_1m: pd.DataFrame):
    tcol = "ts_et" if "ts_et" in bars_1m.columns else ("ts" if "ts" in bars_1m.columns else None)
    return tcol


def update_all_directions(bars_1m: pd.DataFrame, atr: float | None = None,
                          live_price: float | None = None) -> dict:
    """All rolling window states from the completed-1m-bar frame (ts_et/ts, OHLCV).
    atr: 1m ATR (computed here if absent). live_price refreshes only the IMMEDIATE read."""
    if bars_1m is None or len(bars_1m) < 2:
        return {k: {"state": "INSUFFICIENT_DATA", "score": 0.0} for k in TIMEFRAME_WINDOWS} | \
               {"immediate": {"state": "INSUFFICIENT_DATA"}}
    o = bars_1m["open"].to_numpy(float); h = bars_1m["high"].to_numpy(float)
    l = bars_1m["low"].to_numpy(float); c = bars_1m["close"].to_numpy(float)
    if atr is None or not np.isfinite(atr) or atr <= 0:
        tr = np.maximum(h[1:] - l[1:], np.maximum(np.abs(h[1:] - c[:-1]), np.abs(l[1:] - c[:-1])))
        atr = float(pd.Series(tr).ewm(alpha=1 / 14, adjust=False).mean().iloc[-1]) if len(tr) else 0.0
    out = {}
    for name, win in TIMEFRAME_WINDOWS.items():
        if len(c) < win:
            out[name] = {"state": "INSUFFICIENT_DATA", "score": 0.0, "n": int(len(c))}
        else:
            out[name] = review_window(o[-win:], h[-win:], l[-win:], c[-win:], atr)
    # IMMEDIATE (2 completed bars; live price gives the between-minute 'now' arrow)
    imm_dir = 1 if c[-1] > c[-2] else (-1 if c[-1] < c[-2] else 0)
    imm = {"state": "UP" if imm_dir > 0 else ("DOWN" if imm_dir < 0 else "FLAT"),
           "last_two_closes": [round(float(c[-2]), 4), round(float(c[-1]), 4)]}
    if live_price is not None and np.isfinite(live_price):
        now_dir = 1 if live_price > c[-1] else (-1 if live_price < c[-1] else 0)
        imm["now"] = "UP" if now_dir > 0 else ("DOWN" if now_dir < 0 else "FLAT")
        imm["live_price"] = round(float(live_price), 4)
    out["immediate"] = imm
    return out


def confirmed_states(bars_1m: pd.DataFrame, atr: float | None = None) -> dict:
    """Last COMPLETED clock-aligned candle block per TF (5/15/30/60m) — the stable confirmation
    shown next to the rolling read ('15M ROLLING: DOWN · 15M CONFIRMED: UP')."""
    tcol = _cols(bars_1m)
    if tcol is None or len(bars_1m) < 5:
        return {}
    ts = pd.to_datetime(bars_1m[tcol])
    out = {}
    for name, mins in (("5M", 5), ("15M", 15), ("30M", 30), ("1H", 60)):
        blk = ts.dt.floor(f"{mins}min")
        blocks = blk.unique()
        if len(blocks) < 2:
            out[name] = {"state": "INSUFFICIENT_DATA"}
            continue
        last_complete = blocks[-2]                       # [-1] is the developing block
        m = (blk == last_complete).to_numpy()
        sub = bars_1m.loc[m]
        out[name] = review_window(sub["open"].to_numpy(float), sub["high"].to_numpy(float),
                                  sub["low"].to_numpy(float), sub["close"].to_numpy(float),
                                  atr if (atr and atr > 0) else max(float(sub["high"].max() - sub["low"].min()) / max(len(sub), 1), 1e-9))
    return out


if __name__ == "__main__":   # self-test: the research file's own example — hour up, last 5 min down
    rng = np.random.default_rng(3)
    n = 70
    c = np.concatenate([100 + 0.06 * np.arange(60), 103.6 - 0.25 * np.arange(1, 11)])
    c = c + rng.normal(0, 0.01, n)
    bars = pd.DataFrame({"ts_et": pd.date_range("2026-06-01 09:30", periods=n, freq="1min", tz="UTC"),
                         "open": c - 0.03, "high": c + 0.08, "low": c - 0.08, "close": c,
                         "volume": 1000.0})
    st = update_all_directions(bars)
    print({k: (v.get("state"), v.get("score")) for k, v in st.items()})
    assert st["immediate"]["state"] == "DOWN"
    assert "DOWN" in st["2M"]["state"] and "DOWN" in st["5M"]["state"]
    assert "UP" in st["1H"]["state"], st["1H"]
    print("multi-TF rolling direction engine OK — pullback inside the larger uptrend detected")
