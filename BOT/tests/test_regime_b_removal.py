"""REGIME-B BLOCK REMOVAL (operator decision 2026-07-14 — 'apply the fix').

Evidence (REMEDIATION_PLAN §regime-B isolation): the B-block killed 34/34 tradeable fires over
5 live days; isolating it (D-block + SPY-directional KEPT): QQQ IS +25.9→+49.0R / OOS +38.8→+55.8R
(both eras positive) · SPY IS +18.0→+32.2 / OOS +14.3→+40.8 · survives 2x slip · maxDD sub-linear.
The fix: regime B no longer blocks; regime D (extreme vol) still does; the SPY directional
stand-down is UNCHANGED (it earns its OOS keep: QQQ 1.40 vs 1.19 without it)."""
from __future__ import annotations

import sys

import numpy as np
import pytest

pd = pytest.importorskip("pandas")

from bot.config import BOT_ROOT

sys.path.insert(0, str(BOT_ROOT.parent / "engine"))
import hs_harness as H  # noqa: E402


def _frame(vix=15.0, spy_close=100.0, e20=90.0, e50=80.0, adx=20.0, n=10):
    """Crafted daily-context frame: defaults produce regime B (VIX calm-ish, SPY up but
    ADX < 25 => not 'trending')."""
    return pd.DataFrame({
        "spy_close": [spy_close] * n, "spy_e20": [e20] * n, "spy_e50": [e50] * n,
        "spy_adx": [adx] * n, "vix_sma5": [vix] * n, "vix_prev5": [vix] * n,
    })


def test_regime_b_no_longer_blocks():
    """The 34/34 five-day kill: a confirmed regime-B market must ALLOW trades now."""
    d = H._macro_regime(_frame(), H.P())
    assert d["macro_regime"].iloc[-1] == "B", "fixture must actually produce regime B"
    assert bool(d["macro_allow_trades"].iloc[-1]) is True, (
        "regime B must NOT block (operator fix 2026-07-14) — only D blocks")


def test_regime_d_still_blocks():
    """The extreme-vol block stays — removing B must never loosen D."""
    d = H._macro_regime(_frame(vix=40.0), H.P())
    assert d["macro_regime"].iloc[-1] == "D"
    assert bool(d["macro_allow_trades"].iloc[-1]) is False, "regime D must still block"


def test_directional_standdown_unchanged():
    """SPY-up must still block shorts (the directional layer earns its OOS keep — untouched)."""
    d = H._macro_regime(_frame(adx=30.0), H.P())      # SPY up + ADX>=25 => trending up
    assert bool(d["macro_short_ok"].iloc[-1]) is False, "SPY uptrend must still stand shorts down"
    assert bool(d["macro_long_ok"].iloc[-1]) is True


def test_b_block_reenable_knob_exists():
    """The removal is a CONFIG default, not an amputation — P(block_b=True) restores the old
    behavior for research replays of the pre-07.8 rules."""
    d = H._macro_regime(_frame(), H.P(block_b=True))
    assert bool(d["macro_allow_trades"].iloc[-1]) is False, (
        "block_b=True must reproduce the old B-blocking behavior")
