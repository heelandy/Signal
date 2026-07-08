"""Regression tests for the 2026-07 trading-bot review fixes.

Covers: duplicate-order prevention (webhook + manual ticket), stale-data gating, OMS fill guards,
tracker same-bar stop priority, direction-state math sanity, pivots fast-path equivalence, and the
paper/live separation gates. Run: pytest BOT/tests -q
"""
import sys
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

BOT_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BOT_DIR))                            # BOT/ on path
sys.path.insert(0, str(BOT_DIR.parent / "engine"))          # engine/ on path

from bot.contracts import OrderRequest, OrderState, OrderType, ReasonCode
from bot.risk import decide, Account


# ---------- stale-data gate (live.source_health -> risk gate) ----------

def _bars(n=60, end="2026-06-01 14:30", freq="5min"):
    ts = pd.date_range(end=end, periods=n, freq=freq, tz="UTC").tz_convert("America/New_York")
    return pd.DataFrame({"ts_et": ts, "open": 100.0, "high": 100.5, "low": 99.5,
                         "close": 100.2, "volume": 10})


def test_fresh_feed_is_healthy():
    from bot.live import source_health
    b = _bars()
    now = pd.Timestamp("2026-06-01 14:33", tz="UTC")
    healthy, age = source_health(b, max_bar_age_min=15, now=now)
    assert healthy and age < 15


def test_stale_feed_blocks_entries():
    from bot.live import source_health
    b = _bars()
    now = pd.Timestamp("2026-06-01 16:00", tz="UTC")          # last bar 90 min old
    healthy, age = source_health(b, max_bar_age_min=15, now=now)
    assert not healthy and age > 15
    d = decide_candidate(source_healthy=healthy)
    assert not d.approved and d.reason_code is ReasonCode.SOURCE_HEALTH_CRITICAL


def test_empty_and_dirty_feeds_fail_closed():
    from bot.live import source_health
    assert source_health(None)[0] is False
    assert source_health(_bars(0))[0] is False
    bad = _bars()
    bad.loc[10, "low"] = 200.0                                # low > high
    now = pd.Timestamp("2026-06-01 14:33", tz="UTC")
    assert source_health(bad, now=now)[0] is False


def decide_candidate(source_healthy=True):
    from bot.contracts import TradeCandidate
    c = TradeCandidate(symbol="QQQ", side="long", timeframe="5m", setup="orb_stack",
                       entry=100, stop=99, tp2=104, strategy_version="t")
    return decide(c, Account(equity=25_000, source_healthy=source_healthy))


# ---------- duplicate-order prevention (webhook + manual ticket) ----------

@pytest.fixture()
def client(monkeypatch):
    from fastapi.testclient import TestClient
    import bot.api.server as srv
    monkeypatch.setenv("BOT_AUTOSCAN", "0")
    monkeypatch.setattr(srv.settings.__class__, "webhook_token",
                        property(lambda self: "test-token"), raising=False)
    srv._SUBMITTED_KEYS.clear()
    srv._state["kill_switch"] = False
    srv._state["mode"] = "replay"                              # broker None -> shadow, nothing transmits
    return TestClient(srv.app)


def _wh(client, **over):
    body = {"token": "test-token", "ticker": "QQQ", "action": "buy",
            "entry": 100.0, "stopLoss": 99.0, "takeProfit": 104.0}
    body.update(over)
    return client.post("/webhook/tradingview", json=body).json()


def test_repeated_webhook_creates_one_order(client):
    r1 = _wh(client)
    assert r1["action"] in ("shadow", "submitted")             # first one processes
    r2 = _wh(client)                                           # identical retry
    assert r2["action"] == "duplicate"
    r3 = _wh(client, signalId="sig-9")                         # explicit unique id -> processes
    assert r3["action"] in ("shadow", "submitted")
    assert _wh(client, signalId="sig-9")["action"] == "duplicate"


def test_webhook_bad_token_rejected(client):
    r = _wh(client, token="wrong")
    assert r["action"] == "rejected" and "token" in r["reason"]


def test_manual_ticket_dedup_and_distinct_orders_pass(client):
    t = {"symbol": "QQQ", "side": "long", "entry": 100.0, "stop": 99.0, "tp2": 104.0}
    r1 = client.post("/api/order", json=t).json()
    assert r1["action"] == "shadow"
    r2 = client.post("/api/order", json=t).json()              # double-click / retry
    assert r2["action"] == "duplicate"
    t2 = dict(t, entry=101.0)                                  # genuinely different ticket passes
    assert client.post("/api/order", json=t2).json()["action"] == "shadow"


def test_kill_switch_blocks_webhook(client):
    client.post("/api/control/kill?on=true")
    assert _wh(client, signalId="k1")["action"] == "blocked"
    client.post("/api/control/kill?on=false")


# ---------- OMS fill guards ----------

def _entry_order(qty=100):
    return OrderRequest(candidate_id="c", symbol="QQQ", side="long", qty=qty,
                        order_type=OrderType.LIMIT, limit_price=545.0)


def test_oms_rejects_zero_and_negative_fill():
    from bot.execution.oms import OMS
    oms = OMS()
    o = _entry_order()
    oms.submit(o); oms.on_accept(o.order_id)
    assert oms.on_fill(o.order_id, 0, 545.0).state is OrderState.ERROR
    assert oms.on_fill(o.order_id, -5, 545.0).state is OrderState.ERROR
    assert oms.orders[o.order_id].filled == 0


def test_oms_ignores_duplicate_fill_event():
    from bot.execution.oms import OMS
    oms = OMS()
    o = _entry_order()
    oms.submit(o); oms.on_accept(o.order_id)
    oms.on_fill(o.order_id, 100, 545.0)                        # full fill
    assert oms.positions["QQQ"].qty == 100
    dup = oms.on_fill(o.order_id, 100, 545.0)                  # broker resends the event
    assert dup.state is OrderState.ERROR
    assert oms.positions["QQQ"].qty == 100                     # position NOT doubled


def test_oms_clamps_overfill():
    from bot.execution.oms import OMS
    oms = OMS()
    o = _entry_order(qty=100)
    oms.submit(o); oms.on_accept(o.order_id)
    oms.on_fill(o.order_id, 60, 545.0)
    oms.on_fill(o.order_id, 60, 545.2)                         # 120 > order qty -> clamp to 40
    assert oms.orders[o.order_id].filled == 100
    assert oms.positions["QQQ"].qty == 100


def test_oms_partial_fill_updates_quantity_and_avg():
    from bot.execution.oms import OMS
    oms = OMS()
    o = _entry_order(qty=100)
    oms.submit(o); oms.on_accept(o.order_id)
    oms.on_fill(o.order_id, 40, 545.0)
    t = oms.orders[o.order_id]
    assert t.state is OrderState.PARTIALLY_FILLED and t.filled == 40
    oms.on_fill(o.order_id, 60, 545.5)
    assert t.state is OrderState.FILLED and abs(t.avg_price - 545.3) < 1e-9


# ---------- tracker: same-bar conservative stop priority ----------

def _walk_bars(rows):
    ts = pd.date_range("2026-06-29 14:00", periods=len(rows), freq="5min",
                       tz="UTC").tz_convert("America/New_York")
    return pd.DataFrame({"ts_et": ts, "open": [r[0] for r in rows], "high": [r[1] for r in rows],
                         "low": [r[2] for r in rows], "close": [r[3] for r in rows]})


def test_walk_same_bar_stop_and_tp2_after_tp1_scores_stop():
    from bot.tracker import _walk
    #             o      h      l      c
    bars = _walk_bars([(100, 102.0, 99.5, 101.6),              # TP1 (101.5) hit
                       (101, 104.5, 98.5, 100.0)])             # stop AND TP2 inside one bar
    out, r, _m, _a = _walk(bars, "2026-06-29T13:59:00+00:00", "long", 100, 99, 101.5, 104)
    assert out == "tp1_then_stop" and r == -1.0                # conservative: stop first


def test_walk_same_bar_stop_and_tp1_scores_stop():
    from bot.tracker import _walk
    bars = _walk_bars([(100, 102.0, 98.5, 100.0)])             # both stop and TP1 in bar 1
    out, r, _m, _a = _walk(bars, "2026-06-29T13:59:00+00:00", "long", 100, 99, 101.5, 104)
    assert out == "stop" and r == -1.0


def test_walk_clean_tp2_and_zero_risk_guard():
    from bot.tracker import _walk
    bars = _walk_bars([(100, 101.6, 99.8, 101.5), (101.5, 104.2, 101.0, 104.0)])
    out, r, mfe, mae = _walk(bars, "2026-06-29T13:59:00+00:00", "long", 100, 99, 101.5, 104)
    assert out == "tp2" and abs(r - 4.0) < 1e-6
    # zero stop distance must not divide by zero
    out2, r2, *_ = _walk(bars, "2026-06-29T13:59:00+00:00", "long", 100, 100, 101.5, 104)
    assert np.isfinite(r2)


# ---------- direction-state engine math (hs_harness) ----------

def _state_frame(closes, spread=0.3):
    n = len(closes)
    c = np.asarray(closes, float)
    ts = pd.date_range("2026-01-05 09:30", periods=n, freq="5min",
                       tz="America/New_York").tz_convert("UTC")
    return pd.DataFrame({"ts": ts, "open": c - 0.05, "high": c + spread, "low": c - spread,
                         "close": c, "volume": 1000.0})


def _zigzag(n, drift, seed=3):
    """Trending tape WITH swings (HH/HL structure needs pullbacks to print pivots)."""
    t = np.arange(n)
    rng = np.random.default_rng(seed)
    return 200 + drift * t + 2.5 * np.sin(t / 4.0) + rng.normal(0, 0.05, n)


def test_rising_swing_structure_yields_up_state():
    import hs_harness as H
    d = H.compute_state(_state_frame(_zigzag(400, +0.5)), H.P())
    tail = d["st_state"].to_numpy()[-150:]
    assert (tail == 1).mean() > 0.9                            # uptrend state dominates
    assert not (tail == 2).any()                               # never classified as downtrend


def test_falling_swing_structure_yields_down_state():
    import hs_harness as H
    d = H.compute_state(_state_frame(_zigzag(400, -0.5, seed=4)), H.P())
    tail = d["st_state"].to_numpy()[-150:]
    assert (tail == 2).mean() > 0.9
    assert not (tail == 1).any()


def test_monotonic_ramp_never_labels_opposite_direction():
    """A pivot-based engine prints NO swings on a pure ramp — it must stay neutral (0/3),
    and above all never call the OPPOSITE direction."""
    import hs_harness as H
    up = H.compute_state(_state_frame(100 + 0.4 * np.arange(300)), H.P())
    dn = H.compute_state(_state_frame(400 - 0.4 * np.arange(300)), H.P())
    assert not (up["st_state"].to_numpy() == 2).any()
    assert not (dn["st_state"].to_numpy() == 1).any()


def test_flat_prices_stay_neutral_and_do_not_crash():
    import hs_harness as H
    d = H.compute_state(_state_frame(np.full(300, 100.0), spread=0.0), H.P())
    assert set(d["st_state"].unique()) <= {0, 3}               # no trend called on a flat tape


def test_direction_state_scale_invariant():
    import hs_harness as H
    rng = np.random.default_rng(5)
    closes = 100 + np.cumsum(rng.normal(0.05, 0.5, 500))
    d1 = H.compute_state(_state_frame(closes), H.P())
    d2 = H.compute_state(_state_frame(closes * 100, spread=30.0), H.P())
    assert (d1["st_state"].to_numpy() == d2["st_state"].to_numpy()).mean() > 0.99


def test_single_outlier_does_not_flip_persistent_trend():
    import hs_harness as H
    closes = _zigzag(400, +0.5, seed=6)
    spiked = closes.copy()
    spiked[350] -= 4.0                                          # one bad print against the trend
    d = H.compute_state(_state_frame(spiked), H.P())
    assert not (d["st_state"].to_numpy()[-30:] == 2).any()      # never flips to DOWNTREND


def test_pivots_fast_path_matches_loop_path():
    import hs_harness as H
    rng = np.random.default_rng(7)
    v = pd.Series(rng.normal(0, 1, 2500).cumsum() + 100)
    v.iloc[500:505] = v.iloc[500]                               # plateau exercises tie rules
    for kind in ("high", "low"):
        for tie in ("strict", "tv"):
            lb_c = pd.Series(5, index=v.index)                  # constant -> fast path
            lb_v = lb_c.copy(); lb_v.iloc[0] = 4                # varying -> loop path
            fast = H.pivots(v, lb_c, lb_c, kind, tie)
            slow = H.pivots(v, lb_v, lb_v, kind, tie)
            assert fast.fillna(-1).equals(slow.fillna(-1)), (kind, tie)


# ---------- paper/live separation ----------

def test_live_locked_by_default():
    from bot.config import settings
    assert settings.live_allowed is False                       # no BOT_MODE=live + no lock file
    from bot.contracts import TradeCandidate, Mode
    c = TradeCandidate(symbol="QQQ", side="long", timeframe="5m", setup="x",
                       entry=100, stop=99, tp2=104, strategy_version="t")
    d = decide(c, Account(equity=25_000, mode=Mode.LIVE))
    assert not d.approved and d.reason_code is ReasonCode.LIVE_LOCKED


def test_paper_autotrade_toggle_requires_paper_mode(client):
    import bot.api.server as srv
    orig = srv.settings
    # simulate ALPACA_PAPER=false: the study toggle must refuse to arm
    class _S:
        alpaca_paper = False
    srv.settings = _S()
    try:
        r = client.post("/api/control/paper_autotrade?on=1").json()
        assert r.get("paper_autotrade") is False and "error" in r
    finally:
        srv.settings = orig


def test_risk_sizing_formula_and_tight_stop_cap():
    from bot.contracts import TradeCandidate
    # equity 25k, 0.25% risk = $62.5; $1 stop -> 62 shares
    d = decide_candidate()
    assert d.approved and d.max_qty == 62
    # extremely tight stop must NOT create an oversized position: notional cap binds
    c = TradeCandidate(symbol="QQQ", side="long", timeframe="5m", setup="x",
                       entry=100, stop=99.99, tp2=104, strategy_version="t")
    d2 = decide(c, Account(equity=25_000))
    assert d2.approved
    assert d2.max_qty * c.entry <= 4.0 * 25_000 + c.entry       # <= max_notional_mult x equity
