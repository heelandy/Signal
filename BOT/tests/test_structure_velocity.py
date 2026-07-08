"""Regression tests for the STRUC velocity work (2026-07): the gap-aware CHoCH fix in the
engine structure machine and the multi-TF rolling direction engine (research 2026-07-02).

Gap-aware CHoCH — the found root cause of the stale structure read: the old flip rule required
a CROSSING bar (previous close on the old side of the last swing), but in a fast move the swing
reference itself steps toward price via newly confirmed pivots, so the crossing bar never
exists and st_state stays wrong for dozens of bars (41 measured on the diagnostic tape).

Run: pytest BOT/tests -q
"""
import sys
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))          # prediction root -> engine/

from engine.hs_harness import P, compute_state
from bot.strategy.direction_engine import (TIMEFRAME_WINDOWS, classify, review_window,
                                           update_all_directions, confirmed_states,
                                           BAND_WEAK, BAND_DIR, BAND_STRONG)


# ───────────────────────── tapes ─────────────────────────

def _frame(close, spread=0.6):
    """OHLCV frame around a close path (deterministic, pivot-friendly)."""
    close = np.asarray(close, float)
    n = len(close)
    op = np.concatenate([[close[0]], close[:-1]])
    hi = np.maximum(op, close) + spread
    lo = np.minimum(op, close) - spread
    ts = pd.date_range("2026-06-01 09:30", periods=n, freq="1min", tz="America/New_York")
    return pd.DataFrame({"ts": ts, "open": op, "high": hi, "low": lo, "close": close,
                         "volume": np.full(n, 1000.0)})


def _diagnostic_tape():
    """The stale-structure tape (exact construction from the 2026-07 diagnosis): 190-bar
    sinusoidal uptrend, then a fast 50-bar dump whose pullbacks keep confirming new (lower)
    pivots — the geometry where the old crossing rule never fires (41 stale bars measured)."""
    rng = np.random.default_rng(11)
    t = np.arange(240)
    up = 700 + 0.08 * t[:190] + 1.2 * np.sin(t[:190] / 6.0)
    dn = up[-1] - 0.35 * np.arange(1, 51) + 0.6 * np.sin(np.arange(50) / 3.0)
    c1 = np.concatenate([up, dn]) + rng.normal(0, 0.02, 240)
    ts = pd.date_range("2026-06-01 09:30", periods=240, freq="1min",
                       tz="America/New_York").tz_convert("UTC")
    return pd.DataFrame({"ts": ts, "open": c1 - 0.03, "high": c1 + 0.25, "low": c1 - 0.25,
                         "close": c1, "volume": 1000.0})


def _zigzag(direction=1, legs=8, leg=12, step=1.0, pull=0.4):
    """Clean trending zigzag (impulse + shallow pullback) — pivots confirm normally, the old
    crossing rule works here, so old and new must be IDENTICAL on this tape."""
    px, x = [], 700.0
    for _ in range(legs):
        for _ in range(leg):
            x += direction * step; px.append(x)
        for _ in range(leg // 2):
            x -= direction * pull * step; px.append(x)
    return _frame(px)


def _violations(out):
    """Bars claiming UP while close < last swing low, or DOWN while close > last swing high."""
    st = out["st_state"].to_numpy(); c = out["close"].to_numpy()
    spl = out["spl"].to_numpy(); sph = out["sph"].to_numpy()
    bad_up = (st == 1) & ~np.isnan(spl) & (c < spl)
    bad_dn = (st == 2) & ~np.isnan(sph) & (c > sph)
    return int(bad_up.sum() + bad_dn.sum())


# ───────────────────────── gap-aware CHoCH ─────────────────────────

def test_old_rule_goes_stale_on_the_diagnostic_tape():
    out = compute_state(_diagnostic_tape(), P(choch_gap_aware=False))
    assert _violations(out) > 20            # the measured defect (41 bars on this tape)


def test_gap_aware_zero_violations_on_the_diagnostic_tape():
    out = compute_state(_diagnostic_tape(), P(choch_gap_aware=True))
    assert _violations(out) == 0


def test_gap_aware_dump_tail_never_reads_up():
    out = compute_state(_diagnostic_tape(), P(choch_gap_aware=True))
    tail = out["st_state"].to_numpy()[-25:]                 # deep inside the dump
    assert not (tail == 1).any(), tail


@pytest.mark.parametrize("direction", [1, -1])
def test_gap_aware_identical_to_old_rule_on_clean_trends(direction):
    tape = _zigzag(direction)
    old = compute_state(tape, P(choch_gap_aware=False))
    new = compute_state(tape, P(choch_gap_aware=True))
    for col in ("st_state", "choch_bull", "choch_bear", "bos_bull", "bos_bear"):
        assert (old[col].to_numpy() == new[col].to_numpy()).all(), col


def test_gap_aware_invariant_holds_on_random_walks():
    for seed in range(5):
        rng = np.random.default_rng(seed)
        tape = _frame(700 + np.cumsum(rng.normal(0, 0.8, 300)))
        assert _violations(compute_state(tape, P(choch_gap_aware=True))) == 0, seed


# ───────────────────────── multi-TF rolling direction engine ─────────────────────────

def _bars(close, freq="1min"):
    c = np.asarray(close, float)
    op = np.concatenate([[c[0]], c[:-1]])                   # open = prior close: bodies mirror
    return pd.DataFrame({"ts_et": pd.date_range("2026-06-01 09:30", periods=len(c), freq=freq,
                                                tz="America/New_York"),
                         "open": op, "high": np.maximum(op, c) + 0.08,
                         "low": np.minimum(op, c) - 0.08, "close": c,
                         "volume": np.full(len(c), 1000.0)})


def test_classify_bands():
    assert classify(0.05) == "RANGE" and classify(-0.05) == "RANGE"
    assert classify(0.2) == "WEAK_UP" and classify(-0.2) == "WEAK_DOWN"
    assert classify(0.45) == "UP" and classify(-0.45) == "DOWN"
    assert classify(0.8) == "STRONG_UP" and classify(-0.8) == "STRONG_DOWN"
    assert BAND_WEAK < BAND_DIR < BAND_STRONG


def test_pullback_inside_uptrend_reads_both():
    """The research file's own example: 60 min up then 10 min down — short windows DOWN, 1H UP."""
    c = np.concatenate([100 + 0.06 * np.arange(60), 103.6 - 0.25 * np.arange(1, 11)])
    st = update_all_directions(_bars(c))
    assert st["immediate"]["state"] == "DOWN"
    assert "DOWN" in st["2M"]["state"] and "DOWN" in st["5M"]["state"]
    assert "UP" in st["1H"]["state"]
    assert st["4H"]["state"] == "INSUFFICIENT_DATA"         # only 70 bars


def test_mirror_symmetry():
    """Flipping the tape must flip every directional read with the same magnitude."""
    rng = np.random.default_rng(7)
    c = 100 + np.cumsum(rng.normal(0.03, 0.15, 120))
    up, dn = update_all_directions(_bars(c)), update_all_directions(_bars(200 - c))
    for k in TIMEFRAME_WINDOWS:
        su, sd = up[k], dn[k]
        if su["state"] == "INSUFFICIENT_DATA":
            continue
        assert su["score"] == pytest.approx(-sd["score"], abs=1e-9), k
        assert su["state"].replace("UP", "X").replace("DOWN", "X") == \
               sd["state"].replace("UP", "X").replace("DOWN", "X"), k


def test_range_override_on_choppy_tape():
    c = 100 + 0.6 * np.sin(np.arange(60) / 2.0)             # oscillates around the midpoint
    st = update_all_directions(_bars(c))
    assert st["30M"]["state"] == "RANGE", st["30M"]
    assert st["1H"]["state"] == "RANGE", st["1H"]


def test_live_price_refreshes_only_the_immediate_read():
    c = 100 + 0.05 * np.arange(30)
    st = update_all_directions(_bars(c), live_price=float(c[-1] - 5.0))
    assert st["immediate"]["now"] == "DOWN"                 # live tick below the last close
    assert st["immediate"]["state"] == "UP"                 # completed 2-bar read unchanged
    assert "UP" in st["15M"]["state"]                       # windows ignore the live tick


def test_insufficient_data_and_bad_atr_are_guarded():
    st = update_all_directions(_bars([100.0]))
    assert all(v["state"] == "INSUFFICIENT_DATA" for k, v in st.items() if k in TIMEFRAME_WINDOWS)
    r = review_window([1, 2], [1, 2], [1, 2], [1, 2], atr=0.0)
    assert r["state"] == "INSUFFICIENT_DATA"


def test_confirmed_states_use_last_completed_block():
    c = np.concatenate([100 + 0.1 * np.arange(30), 103 - 0.2 * np.arange(1, 8)])
    conf = confirmed_states(_bars(c))                       # bars 09:30..10:06
    assert "5M" in conf and "15M" in conf
    assert "UP" in conf["15M"]["state"]                     # 09:45-10:00 block: still climbing
