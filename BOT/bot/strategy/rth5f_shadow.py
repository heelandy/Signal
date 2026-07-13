"""RTH5F SHADOW BOOKS — the tuned 5-filter confluence entry, WATCH-ONLY (operator go 2026-07-13;
SPY book added same day).

The book (research battery 2026-07-13, docs/REMEDIATION_PLAN §F-NQ-ASIA-1): RTH crossing
close-through of the 09:30-10:00 OR with body >= 40% of range, at least half the body beyond the
level, wick <= 25%, RISING/FALLING 5m swing structure as the ONLY direction source, per-symbol
RVOL + ADX(14) >= 18; DISTANCE is a SOFT WARN (recorded, never blocks — the hard gate would have
deleted 74-100%% of the winners). Evidence:
  NQ  (rvol 1.20): IS 2024-26 +29.9R PF 2.14 (n=66) · OOS 2016-23 +27.5R PF 1.23 (n=239)
  SPY (rvol 0.90): 2016-26 +38.3R PF 1.25 (n=258), 3 eras positive (1.54/1.19/1.19), longs
                   PF 1.47; only 14%% trade-day overlap with the canonical SPY book (additive).

FREEZE-SAFE BY CONSTRUCTION: a shadow lineage like the 15m/worker studies — records tracker
decisions under its OWN strategy_version (dataset version-purity keeps it out of the core
training corpus), places NO orders, changes NO gates, touches NO canonical signal path. The
tracker's first-touch resolver scores the rows; the journal panels render them by family.
"""
from __future__ import annotations

import sys

import numpy as np
import pandas as pd

from bot.config import BOT_ROOT

sys.path.insert(0, str(BOT_ROOT.parent / "engine"))     # hs_harness/hs_backtest (families.py:24 pattern)

VERSION = "rth5f-0.1"
FAMILY = "rth5f"
# per-symbol tuned settings (grid winners, 2026-07-13): NQ b40/rv1.20/adx18 · SPY b40/rv0.90/adx18
# (SPY deep search: 2016-26 n=258 +38.3R PF 1.25, 3 eras positive, 14% overlap with canonical).
BOOKS = {
    "NQ": {"tick": 0.25, "body": 0.40, "wick": 0.25, "rvol": 1.20, "adx": 18.0},
    "SPY": {"tick": 0.01, "body": 0.40, "wick": 0.25, "rvol": 0.90, "adx": 18.0},
}
DIST_WARN_ATR = 0.75
OR_S, OR_E, CUT = 570, 600, 900          # ET minutes: OR 09:30-10:00, trade to 15:00 (F62)


def _get_bars(sym: str):
    from bot.market_data.providers import get_bars
    return get_bars(sym, "5m", period="5d")


def _now(tz):
    """Injectable clock (tests pin it; live uses the real clock)."""
    return pd.Timestamp.now(tz=tz)


def _prev_distinct(x: np.ndarray) -> np.ndarray:
    out = np.full(len(x), np.nan)
    last = prev = np.nan
    for i, v in enumerate(x):
        if v == v and v != last:
            prev = last
            last = v
        out[i] = prev
    return out


def evaluate_bars(bars: pd.DataFrame, sym: str = "NQ"):
    """Evaluate the LAST bar of `bars` (caller guarantees it is CLOSED) against the 5-filter
    book for `sym`. Returns (sig_dict | None, why). Pure — no I/O, no recording."""
    import hs_harness as H
    from bot.strategy.asset_config import struct_lb, asset_config
    bk = BOOKS[sym]
    df = bars.rename(columns={"ts_et": "ts"}).copy()
    df["ts"] = pd.to_datetime(df["ts"], utc=True)
    for col in ("open", "high", "low", "close"):
        df[col] = df[col].astype(float)
    # bug hunt 2026-07-13: df.get("volume", 0) returns the INT 0 when the column is missing ->
    # .astype crashes. Missing volume = zeros -> the rvol gate blocks (fail closed, never crash).
    df["volume"] = df["volume"].astype("float64") if "volume" in df.columns else 0.0
    d = H.compute_state(df, H.P(struct_lb_fix=struct_lb(sym)))
    n = len(d)
    if n < 30:
        return None, "not enough bars"
    et = pd.to_datetime(d["ts"]).dt.tz_convert("America/New_York")
    mins = (et.dt.hour * 60 + et.dt.minute).to_numpy()
    day = et.dt.date.to_numpy()
    i = n - 1
    if not (OR_E <= mins[i] < CUT):
        return None, "outside RTH trade window"
    # today's opening range
    m_or = (day == day[i]) & (mins >= OR_S) & (mins < OR_E)
    if not m_or.any():
        return None, "no OR bars for this session"
    orh = float(d["high"].to_numpy(float)[m_or].max())
    orl = float(d["low"].to_numpy(float)[m_or].min())
    o = float(d["open"].iloc[i]); h = float(d["high"].iloc[i])
    l = float(d["low"].iloc[i]); c = float(d["close"].iloc[i])
    pc = float(d["close"].iloc[i - 1])
    atr = float(d["atr14"].iloc[i]) if d["atr14"].iloc[i] == d["atr14"].iloc[i] else 0.0
    # 0. the CROSSING candle, right colour
    if c > orh and pc <= orh and c > o:
        sign, lvl = 1, orh
    elif c < orl and pc >= orl and c < o:
        sign, lvl = -1, orl
    else:
        return None, "no crossing close-through"
    body = abs(c - o); rng = max(h - l, 1e-9)
    # 1. candle quality
    if body < bk["body"] * rng:
        return None, f"body {body/rng:.2f} < {bk['body']}"
    beyond = (c - max(o, lvl)) if sign == 1 else (min(o, lvl) - c)
    if beyond < 0.5 * body:
        return None, "less than half the body beyond the level"
    wick = (h - c) if sign == 1 else (c - l)
    if wick > max(bk["tick"], bk["wick"] * rng):
        return None, f"wick {wick:.2f} > {bk['wick']} of range"
    # 2. structure (the ONLY direction source)
    sph = d["sph"].to_numpy(float); spl = d["spl"].to_numpy(float)
    sph_p = _prev_distinct(sph); spl_p = _prev_distinct(spl)
    st_bull = sph[i] > sph_p[i] and spl[i] > spl_p[i]
    st_bear = sph[i] < sph_p[i] and spl[i] < spl_p[i]
    if (sign == 1 and not st_bull) or (sign == -1 and not st_bear):
        return None, "structure not aligned"
    # 3. volume
    vol = d["volume"].to_numpy(float)
    if i < 20:
        return None, "rvol window too short"
    vavg = float(np.mean(vol[i - 20:i]))
    if not (vavg > 0 and vol[i] >= bk["rvol"] * vavg):
        return None, f"rvol {vol[i]/vavg if vavg else 0:.2f} < {bk['rvol']}"
    # 4. ADX(14) trend strength
    _, _, adx = H.dmi(d["high"], d["low"], d["close"], 14, 14)
    adx_i = float(np.asarray(adx, float)[i])
    if not adx_i >= bk["adx"]:
        return None, f"adx {adx_i:.1f} < {bk['adx']}"
    # 5. distance — SOFT WARN only (never blocks)
    dist_warn = bool(atr > 0 and (c - lvl if sign == 1 else lvl - c) > DIST_WARN_ATR * atr)
    from bot.strategy.families import _levels
    a = asset_config(sym)
    entry, stop, tp1, tp2 = _levels(d, i, sign, a.min_stop_atr, a.sl_max_atr)
    bar_close = (pd.Timestamp(d["ts"].iloc[i]) + pd.Timedelta(minutes=5)).isoformat()
    sig = {"candidate_id": f"{FAMILY}:{sym}:{bar_close}", "symbol": sym,
           "side": "long" if sign == 1 else "short", "family": FAMILY, "session": "rth",
           "entry": entry, "stop": stop, "tp1": tp1, "tp2": tp2, "grade": "5F",
           "generated_at": bar_close, "tf": "5m", "strategy_version": VERSION,
           "dist_warn": dist_warn, "or_high": orh, "or_low": orl,
           "note": "RTH5F confluence shadow (watch-only; evidence: REMEDIATION_PLAN F-NQ-ASIA-1)"}
    return sig, "fired"


def _tick_sym(sym: str) -> dict:
    """One shadow pass for one book: evaluate the last CLOSED bar; record once per bar.
    Never places an order; never touches the canonical signal path."""
    try:
        bars = _get_bars(sym)
    except Exception as e:
        return {"error": f"bars: {e}"}
    if bars is None or not len(bars):
        return {"error": "no bars"}
    # drop a still-FORMING last bar (its close drifts; the autotrack bars_ago>=1 lesson)
    et_last = pd.to_datetime(bars["ts_et"].iloc[-1])
    if et_last.tzinfo is None:
        et_last = et_last.tz_localize("America/New_York")
    if et_last + pd.Timedelta(minutes=5) > _now(et_last.tzinfo):
        bars = bars.iloc[:-1]
        if not len(bars):
            return {"error": "only a forming bar"}
    sig, why = evaluate_bars(bars, sym)
    if sig is None:
        return {"recorded": False, "why": why}
    from bot.tracker import record_decision
    res = record_decision(sig, taken=True, auto=True)
    if res.get("dup"):
        return {"recorded": False, "dup": True}
    if res.get("error"):
        return {"recorded": False, "error": res["error"]}
    return {"recorded": True, "candidate_id": sig["candidate_id"], "side": sig["side"],
            "dist_warn": sig["dist_warn"]}


def tick() -> dict:
    """Scan-loop beat: run every book (NQ + SPY). Per-symbol results keyed by symbol."""
    return {sym: _tick_sym(sym) for sym in BOOKS}
