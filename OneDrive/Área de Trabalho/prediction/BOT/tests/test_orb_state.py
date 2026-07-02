"""Regression tests for the ORB zone state machine (staleness fix 2026-07).

Encodes the spec's long-side / short-side behavior tables, verifies exact long/short mirror
symmetry, the invalidation/hysteresis rules, and the direction-math invariants (ER, persistence,
normalized slope). Run: pytest BOT/tests -q
"""
import sys
from pathlib import Path

import numpy as np
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from bot.strategy.orb_state import (OrbSideState, SideState, Zone, zone_of, signal_zone_state,
                                    efficiency_ratio, directional_persistence, norm_slope,
                                    path_distance, net_move)

OR_H, OR_L = 730.0, 723.9          # the QQQ session from the bug screenshot
MID = (OR_H + OR_L) / 2.0


def _long(**kw):
    sm = OrbSideState("long", or_high=OR_H, or_low=OR_L)
    sm.arm(entry=730.01, stop=726.76, tp1=733.26, tp2=743.02, close=730.5, order_id="o1", **kw)
    return sm


def _short():
    sm = OrbSideState("short", or_high=OR_H, or_low=OR_L)
    sm.arm(entry=723.89, stop=727.15, tp1=720.65, tp2=710.89, close=723.0, order_id="o2")
    return sm


# ---- the screenshot bug: pending long must NOT stay ARMED with price below the OR low ----

def test_pending_long_invalidated_when_price_closes_below_or_low():
    sm = _long()
    assert sm.state is SideState.ARMED
    sm.on_bar(high=730.2, low=718.9, close=719.0)          # the screenshot bar: price at 719
    assert sm.state is SideState.INVALIDATED
    assert sm.pending_cancelled                            # resting order must be cancelled
    assert sm.entry is None and sm.stop is None            # levels cleared from the dashboard


def test_pending_long_invalidated_when_proposed_stop_tagged_before_entry():
    sm = _long()
    sm.on_bar(high=729.0, low=726.5, close=728.0)          # low 726.5 <= stop 726.76, close inside OR
    assert sm.state is SideState.INVALIDATED


def test_pending_long_soft_cancel_below_or_mid_then_rearm_on_rebreak():
    sm = _long()
    sm.on_bar(high=729.0, low=726.9, close=726.5)          # close < mid 726.95, stop NOT tagged
    assert sm.state is SideState.WATCH and sm.pending_cancelled
    # re-arm refused while still under the mid
    assert sm.arm(entry=730.01, stop=727.5, close=726.0) is SideState.WATCH
    # re-breakout confirmation -> re-arm allowed
    assert sm.arm(entry=730.01, stop=727.5, close=730.4) is SideState.ARMED


def test_no_rearm_after_invalidation_until_or_high_reclaimed():
    sm = _long()
    sm.on_bar(high=724.0, low=719.0, close=719.5)
    assert sm.state is SideState.INVALIDATED
    assert sm.arm(entry=730.01, stop=727.0, close=731.0) is SideState.INVALIDATED  # hysteresis
    sm.on_bar(high=726.0, low=720.0, close=725.0)          # back inside OR — still invalid
    assert sm.state is SideState.INVALIDATED
    sm.on_bar(high=730.8, low=728.0, close=730.5)          # confirmed reclaim of OR high
    assert sm.state is SideState.WAITING
    assert sm.arm(entry=730.01, stop=727.5, close=730.5) is SideState.ARMED        # fresh confirm


def test_filled_long_lifecycle_stop_first_on_same_bar():
    sm = _long(); sm.fill()
    assert sm.state is SideState.FILLED
    # same bar contains both the stop and TP1 -> STOP wins (conservative)
    sm.on_bar(high=733.5, low=726.5, close=730.0)
    assert sm.state is SideState.STOPPED
    # stopped is terminal: no re-arm ("block immediate re-entry")
    assert sm.arm(entry=730.01, stop=727.0, close=731.0) is SideState.STOPPED


def test_filled_long_tp1_then_tp2():
    sm = _long(); sm.fill()
    sm.on_bar(high=733.5, low=729.0, close=733.0)
    assert sm.state is SideState.TP1_HIT
    sm.on_bar(high=743.3, low=732.0, close=743.0)
    assert sm.state is SideState.COMPLETED


# ---- exact long/short mirror symmetry ----

def test_short_side_is_exact_mirror():
    C = 2 * MID                                            # reflect prices around the OR mid
    lm = OrbSideState("long", or_high=OR_H, or_low=OR_L)
    sh = OrbSideState("short", or_high=OR_H, or_low=OR_L)
    lm.arm(entry=730.01, stop=726.76, tp1=733.26, tp2=743.02, close=730.5)
    sh.arm(entry=C - 730.01, stop=C - 726.76, tp1=C - 733.26, tp2=C - 743.02, close=C - 730.5)
    bars = [(730.2, 727.0, 726.5),                         # -> WATCH
            (727.0, 718.9, 719.0),                         # -> INVALIDATED
            (726.0, 720.0, 725.0),                         # stays INVALIDATED
            (730.8, 728.0, 730.5)]                         # reclaim -> WAITING
    for h, l, c in bars:
        s_l = lm.on_bar(high=h, low=l, close=c)
        s_s = sh.on_bar(high=C - l, low=C - h, close=C - c)   # mirrored bar (high/low swap)
        assert s_l == s_s, (s_l, s_s)


def test_short_invalidated_on_confirmed_close_above_or_high():
    sm = _short()
    sm.on_bar(high=731.0, low=723.0, close=730.6)
    assert sm.state is SideState.INVALIDATED
    sm.on_bar(high=725.0, low=723.5, close=724.0)          # inside OR — still invalid
    assert sm.state is SideState.INVALIDATED
    sm.on_bar(high=724.5, low=722.9, close=723.2)          # confirmed close below OR low -> WAITING
    assert sm.state is SideState.WAITING


# ---- zones + the stateless live-proposal verdict ----

def test_zones():
    assert zone_of(731.0, OR_H, OR_L) is Zone.ABOVE_HIGH
    assert zone_of(728.0, OR_H, OR_L) is Zone.UPPER_HALF
    assert zone_of(725.0, OR_H, OR_L) is Zone.LOWER_HALF
    assert zone_of(719.0, OR_H, OR_L) is Zone.BELOW_LOW


def test_signal_zone_state_matches_screenshot():
    # the bug: long proposal shown ARMED with price 719 < OR low 723.9 -> must be 'invalid'
    assert signal_zone_state("long", 719.0, OR_H, OR_L) == "invalid"
    assert signal_zone_state("long", 725.0, OR_H, OR_L) == "watch"
    assert signal_zone_state("long", 731.0, OR_H, OR_L) == "active"
    assert signal_zone_state("short", 719.0, OR_H, OR_L) == "active"
    assert signal_zone_state("short", 731.0, OR_H, OR_L) == "invalid"
    assert signal_zone_state("long", 719.0, None, None) == "unknown"   # missing levels never = invalid


# ---- direction math invariants (spec) ----

def test_efficiency_ratio_bounds_and_zero_path():
    assert efficiency_ratio([1, 2, 3, 4, 5]) == 1.0        # straight line
    assert efficiency_ratio([5, 5, 5, 5]) == 0.0           # zero path distance — no division error
    er = efficiency_ratio([1, 2, 1, 2, 1, 2])
    assert 0.0 <= er < 0.5                                 # chop is near 0
    assert path_distance([1, 3, 2]) == 3.0 and net_move([1, 3, 2]) == 1.0


def test_persistence_formula_and_noise_threshold():
    d, p = directional_persistence([0, 1, 2, 3, 2, 4, 3, 5])   # 5 up / 2 down (wait: diffs 1,1,1,-1,2,-1,2)
    assert d == 1 and abs(p - 5 / 7) < 1e-9
    assert directional_persistence([1, 2, 1, 2, 1]) == (0, 0.5)     # balanced -> neutral
    assert directional_persistence([1, 1, 1, 1]) == (0, 0.0)        # no meaningful moves
    # noise threshold ignores sub-threshold wiggles: only the two big up-moves count
    d2, p2 = directional_persistence([100, 100.01, 99.99, 101.0, 100.99, 102.0], noise=0.5)
    assert d2 == 1 and p2 == 1.0


def test_norm_slope_scale_and_offset_behavior():
    up = [100, 101, 102, 103, 104]
    assert norm_slope(up) > 0 and norm_slope(list(reversed(up))) < 0
    assert abs(norm_slope(up) - norm_slope([x * 100 for x in up])) < 1e-12   # scale-invariant
    assert abs(norm_slope([5.0, 5.0, 5.0])) < 1e-12                          # flat -> ~0, no div error


def test_monotonic_sequences_drive_expected_states():
    # strictly rising tape: long side arms and completes; short side invalidates
    lm = OrbSideState("long", or_high=102.0, or_low=100.0)
    sh = OrbSideState("short", or_high=102.0, or_low=100.0)
    lm.arm(entry=102.05, stop=100.8, tp1=103.0, tp2=105.0, close=102.2)
    sh.arm(entry=99.95, stop=101.2, tp1=99.0, tp2=97.0, close=99.9)   # hypothetical short pending
    lm.fill()
    px = 102.0
    for _ in range(8):
        px += 0.8
        lm.on_bar(high=px + 0.2, low=px - 0.4, close=px)
        sh.on_bar(high=px + 0.2, low=px - 0.4, close=px)
    assert lm.state is SideState.COMPLETED
    assert sh.state is SideState.INVALIDATED


def test_bad_geometry_rejected():
    sm = OrbSideState("long", or_high=OR_H, or_low=OR_L)
    with pytest.raises(ValueError):
        sm.arm(entry=730.0, stop=731.0, close=730.5)       # long stop above entry
    with pytest.raises(ValueError):
        OrbSideState("long", or_high=100.0, or_low=101.0)  # inverted OR
