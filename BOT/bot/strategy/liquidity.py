"""Liquidity-zone CLEAN-AIR filter (F67, GRADUATED 2026-07-03: step-1 beats random; step-2 additive on the
validated stack lifts exp+CIlo on NQ+QQQ, survives 2x slip + walk-forward, WALL cohort = losers).

Production wrapper over the validated zone engine — PROMOTED 2026-07-06 into this package
(`bot.strategy.liquidity_zones.detect_zones`; `research/orb_liquidity_zones.py` is now a shim over
it). ONE source of truth for the zone math (the engine that passed the gauntlet), no research/
dependency from production code anymore.

`clean_air_atr(bars_1m, entry, side)` -> distance (in ATR) to the nearest MAJOR/STRONG zone AHEAD in the
trade direction (math.inf = clear to the horizon; None = not computable). The live scan downgrades a
breakout to a WALL grade when this is below the threshold (default 2.0 ATR).
"""
from __future__ import annotations

import math

import numpy as np

CLEAN_AIR_ATR = 2.0     # graduated threshold: no MAJOR/STRONG zone within this many ATR ahead = clean air

_detect = None


def _engine():
    """Lazy import of the validated detect_zones (bot.strategy.liquidity_zones is the source of truth)."""
    global _detect
    if _detect is None:
        from bot.strategy.liquidity_zones import detect_zones
        _detect = detect_zones
    return _detect


def clean_air_atr(bars_1m, entry: float, side: str, sym: str = "?") -> float | None:
    """ATR-distance to the nearest MAJOR/STRONG zone ahead of the trade (causal: uses only bars_1m, which the
    caller passes as the session up to now). inf = clear ahead; None = insufficient data / engine error."""
    if bars_1m is None or len(bars_1m) < 40 or "high" not in bars_1m:
        return None
    try:
        zs = [z for z in _engine()(bars_1m, sym=sym) if z.get("label") in ("MAJOR", "STRONG")]
    except Exception:
        return None
    h = bars_1m["high"].to_numpy(float)[:30]; l = bars_1m["low"].to_numpy(float)[:30]
    atr = float(np.mean(h - l)) or 1.0
    sgn = 1 if side == "long" else -1
    ahead = [sgn * (z["center"] - entry) / atr for z in zs if sgn * (z["center"] - entry) > 0]
    return min(ahead) if ahead else math.inf
