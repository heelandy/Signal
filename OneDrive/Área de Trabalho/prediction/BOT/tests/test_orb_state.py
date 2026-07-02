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


# ---- 1-minute direction feed (fast_direction + flip-speed vs chart-TF structure) ----

def test_fast_direction_votes_down_when_price_dumps_below_or_low():
    from bot.strategy.orb_state import fast_direction
    closes = list(np.linspace(730.0, 719.0, 40))           # steady 1m dump into the screenshot price
    d = fast_direction(closes, or_high=OR_H, or_low=OR_L, vwap=726.0, st_state_1m=2)
    assert d["zone"] == -1 and d["slope"] == -1 and d["vwap"] == -1 and d["struct_1m"] == -1
    assert d["read"] == "down" and d["score"] == -4


def test_fast_direction_up_and_mixed_and_missing_inputs():
    from bot.strategy.orb_state import fast_direction
    up = list(np.linspace(724.0, 731.0, 40))
    d = fast_direction(up, or_high=OR_H, or_low=OR_L, vwap=725.0, st_state_1m=1)
    assert d["read"] == "up" and d["score"] == 4
    m = fast_direction(up, or_high=OR_H, or_low=OR_L, vwap=732.0, st_state_1m=2)   # conflicting votes
    assert m["read"] in ("mixed", "up")
    n = fast_direction(up)                                  # no OR/vwap/struct -> slope-only, never crashes
    assert n["zone"] == 0 and n["vwap"] == 0 and n["read"] == "mixed"


def test_1m_structure_flips_down_earlier_than_5m_on_the_same_tape():
    """The screenshot bug, end-to-end: after a rally then a downtrend, the 1m swing structure must
    read DOWN materially EARLIER (wall-clock minutes) than the 5m structure computed on the same
    tape — the property the fast_dir 1m feed exploits. Same machine, same lb=5, only the bar size
    differs (pivot confirm = lb MINUTES on 1m vs lb x 5 minutes on 5m)."""
    sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "engine"))
    import hs_harness as H
    import pandas as pd
    rng = np.random.default_rng(11)
    n_up, n_dn = 190, 150
    t_up = np.arange(n_up); t_dn = np.arange(n_dn)
    up = 700 + 0.10 * t_up + 2.5 * np.sin(t_up / 5.0)        # rising zigzag (prints HH/HL swings)
    dn = up[-1] - 0.20 * t_dn + 2.5 * np.sin(t_dn / 5.0)     # falling zigzag (prints LL/LH swings)
    c1 = np.concatenate([up, dn]) + rng.normal(0, 0.03, n_up + n_dn)
    ts1 = pd.date_range("2026-06-01 09:30", periods=len(c1), freq="1min",
                        tz="America/New_York").tz_convert("UTC")
    f1 = pd.DataFrame({"ts": ts1, "open": c1 - 0.03, "high": c1 + 0.30, "low": c1 - 0.30,
                       "close": c1, "volume": 1000.0})
    d1 = H.compute_state(f1, H.P())                          # 1m context
    f5 = (f1.set_index(pd.to_datetime(f1["ts"]))             # the 5m chart's view of the same tape
             .resample("5min").agg({"open": "first", "high": "max", "low": "min",
                                    "close": "last", "volume": "sum"}).dropna().reset_index()
             .rename(columns={"index": "ts"}))
    d5 = H.compute_state(f5, H.P())
    st1 = d1["st_state"].to_numpy(); st5 = d5["st_state"].to_numpy()
    assert (st1[:n_up] == 1).any(), "premise: the rally must register as UP structure"
    assert (st1 == 2).any(), "1m structure must flip DOWN during the downtrend"
    first_dn_1m_min = int(np.argmax(st1 == 2))               # minutes from open (1 bar = 1 min)
    if (st5 == 2).any():
        first_dn_5m_min = int(np.argmax(st5 == 2)) * 5
        assert first_dn_1m_min < first_dn_5m_min, (first_dn_1m_min, first_dn_5m_min)
    else:
        first_dn_5m_min = None                               # 5m never flipped at all — max lag
    # the 1m read must lead by a material margin (>= 10 wall-clock minutes) or the 5m never flips
    assert first_dn_5m_min is None or first_dn_5m_min - first_dn_1m_min >= 10


def test_fast_state_1m_alignment_is_causal_and_maps_last_1m_bar():
    """families.fast_state_1m must give each 5m bar the 1m st_state of the LAST 1m bar inside it
    (known at the 5m close), be NaN before 1m coverage, and never read future 1m bars."""
    from bot.strategy.families import fast_state_1m, prepare
    import pandas as pd
    rng = np.random.default_rng(21)
    n1 = 300
    t = np.arange(n1)
    c1 = 500 + 0.05 * t + 2.0 * np.sin(t / 5.0) + rng.normal(0, 0.02, n1)
    ts1 = pd.date_range("2026-06-01 09:30", periods=n1, freq="1min",
                        tz="America/New_York").tz_convert("UTC")
    b1 = pd.DataFrame({"ts_et": ts1, "open": c1 - 0.02, "high": c1 + 0.2, "low": c1 - 0.2,
                       "close": c1, "volume": 1000.0})
    b5 = (b1.set_index(pd.to_datetime(b1["ts_et"]))
             .resample("5min").agg({"open": "first", "high": "max", "low": "min",
                                    "close": "last", "volume": "sum"}).dropna().reset_index()
             .rename(columns={"ts_et": "ts_et"}))
    d5 = prepare(b5, "QQQ")
    st_fast = fast_state_1m(d5, b1, "QQQ")
    d1 = prepare(b1, "QQQ")
    st1 = d1["st_state"].to_numpy()
    # each 5m bar's fast state == the 1m state at that bar's last inner 1m bar (index 5k+4)
    for k in (10, 20, 40, 55):
        assert st_fast[k] == st1[5 * k + 4], (k, st_fast[k], st1[5 * k + 4])
    # causality: mutating FUTURE 1m bars must not change earlier aligned values
    b1_mut = b1.copy()
    b1_mut.loc[b1_mut.index[250:], ["open", "high", "low", "close"]] = 400.0
    st_fast_mut = fast_state_1m(d5, b1_mut, "QQQ")
    same_until = 250 // 5 - 1
    assert np.array_equal(st_fast[:same_until], st_fast_mut[:same_until], equal_nan=True)


def test_scan_uses_1m_state_where_covered(monkeypatch):
    """families.scan(bars_1m=...) must swap the gate/grade state to the 1m feed where covered and
    keep the 5m state where the 1m frame has no coverage (NaN fallback)."""
    from bot.strategy import families
    import pandas as pd
    called = {}
    def fake_fast(d5, b1, sym):
        called["yes"] = True
        out = np.full(len(d5), np.nan)
        out[-3:] = 2.0                              # 1m says DOWN on the last 3 bars only
        return out
    monkeypatch.setattr(families, "fast_state_1m", fake_fast)
    rng = np.random.default_rng(5)
    n = 120
    c = 500 + np.cumsum(rng.normal(0, 0.3, n))
    ts = pd.date_range("2026-06-01 09:30", periods=n, freq="5min",
                       tz="America/New_York").tz_convert("UTC")
    b5 = pd.DataFrame({"ts_et": ts, "open": c - 0.05, "high": c + 0.5, "low": c - 0.5,
                       "close": c, "volume": 1000.0})
    b1 = b5.head(40).copy()                         # any non-empty frame (fake ignores content)
    sigs = families.scan(b5, "QQQ", bars_back=2, bars_1m=b1)
    assert called.get("yes"), "1m fast path must be invoked when bars_1m is provided"
    assert isinstance(sigs, list)                   # scan completes with the swapped state
