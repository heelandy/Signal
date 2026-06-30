"""Regime selector — decides which strategy may operate (Evidence "Day-Trade Regime Selector").

Trend score vs range score from slow features; the higher (above a floor) selects the engine.
This is the gate that stops trend-continuation and mean-reversion from firing against each other.
The ORB stack runs in TREND; a (still-to-be-validated) VWAP mean-reversion would run in RANGE.

    from bot.strategy.regime import classify
    classify(ema_slope=0.3, vwap_slope=0.1, adx=28, vwap_cross_rate=0.1, atr_pct=0.4)
    -> {"regime": "trend", "trend": 72, "range": 28, "strategy": "orb_stack"}
"""
from __future__ import annotations


def _clip(x, lo=0.0, hi=1.0):
    return max(lo, min(hi, x))


def classify(ema_slope: float, vwap_slope: float, adx: float,
             vwap_cross_rate: float, atr_pct: float, floor: float = 60.0) -> dict:
    """Scores in 0–100. Inputs are normalised features (see callers):
      ema_slope/vwap_slope: |slope| in ATR units; adx: 0–100; vwap_cross_rate: crossings/bar;
      atr_pct: realized-vol percentile 0–1."""
    trend = (20 * _clip(abs(ema_slope) / 0.5)             # directional MA slope
             + 20 * _clip(adx / 30.0)                     # trend strength
             + 15 * _clip(abs(vwap_slope) / 0.3)          # VWAP direction
             + 15 * _clip(1 - vwap_cross_rate / 0.2)      # few VWAP crossings
             + 15 * _clip(atr_pct)                        # enough movement
             + 15)                                        # base
    rng = (20 * _clip(1 - abs(ema_slope) / 0.5)           # flat MA
           + 20 * _clip(1 - adx / 30.0)                   # weak trend
           + 15 * _clip(1 - abs(vwap_slope) / 0.3)        # flat VWAP
           + 15 * _clip(vwap_cross_rate / 0.2)            # repeated VWAP crossings
           + 15 * _clip(1 - abs(atr_pct - 0.4) / 0.4)     # moderate vol
           + 15)
    trend, rng = round(min(trend, 100), 0), round(min(rng, 100), 0)
    if trend >= floor and trend >= rng:
        regime, strat = "trend", "orb_stack"
    elif rng >= floor and rng > trend:
        regime, strat = "range", "vwap_revert"            # research-only until validated
    else:
        regime, strat = "no_trade", None
    return {"regime": regime, "trend": trend, "range": rng, "strategy": strat}


if __name__ == "__main__":   # self-test: a clean trend, a clean range, a chop
    t = classify(ema_slope=0.4, vwap_slope=0.2, adx=30, vwap_cross_rate=0.02, atr_pct=0.6)
    r = classify(ema_slope=0.02, vwap_slope=0.01, adx=8, vwap_cross_rate=0.18, atr_pct=0.4)
    n = classify(ema_slope=0.05, vwap_slope=0.05, adx=15, vwap_cross_rate=0.1, atr_pct=0.1)
    assert t["regime"] == "trend" and t["strategy"] == "orb_stack", t
    assert r["regime"] == "range", r
    print("trend:", t); print("range:", r); print("chop :", n)
    print("regime selector OK")
