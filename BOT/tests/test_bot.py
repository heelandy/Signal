"""Fast unit suite for the BOT (no engine/data needed). Run: pytest BOT/tests -q

Covers the pure decision/contract/feature logic. Engine-backed replay (`bot.replay`) and the
MBO/Alpaca paths are exercised by their own `__main__` self-tests (need data / network).
"""
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))   # BOT/ on path

from bot.contracts import (TradeCandidate, RiskDecision, RiskStatus, ReasonCode, OrderRequest,
                           OrderType, PositionState, PositionPhase, Side, can_transition,
                           POSITION_TRANSITIONS)
from bot.risk import decide, Account, RiskLimits
from bot.market_truth import assess
from bot.journal import Journal
from bot.strategy.regime import classify
from bot.news_lockout import NewsLockout
from bot.orderflow.score import score_row, DirectionStateMachine, Dir
import pandas as pd


# ---- contracts ----
def test_candidate_geometry_and_rr():
    c = TradeCandidate(symbol="QQQ", side="long", timeframe="5m", setup="orb_stack",
                       entry=100, stop=99, tp2=104, strategy_version="t")
    assert c.risk == 1 and abs(c.rr - 4) < 1e-9
    assert TradeCandidate.from_dict(c.to_dict()).idempotency_key == c.idempotency_key

def test_candidate_rejects_bad_stop():
    with pytest.raises(ValueError):
        TradeCandidate(symbol="QQQ", side="long", timeframe="5m", setup="x", entry=100, stop=101)

def test_position_transitions_fail_closed():
    assert can_transition(POSITION_TRANSITIONS, PositionPhase.OPEN, PositionPhase.CLOSING)
    assert not can_transition(POSITION_TRANSITIONS, PositionPhase.CLOSED, PositionPhase.OPEN)
    with pytest.raises(ValueError):
        PositionState(symbol="QQQ", phase=PositionPhase.CLOSED).transition(PositionPhase.OPEN)

def test_order_requires_limit_price():
    with pytest.raises(ValueError):
        OrderRequest(candidate_id="x", symbol="QQQ", side="long", qty=1, order_type=OrderType.LIMIT)


# ---- risk gate ----
def _c(entry=100.0, stop=99.0, tp2=104.0, sym="QQQ"):
    return TradeCandidate(symbol=sym, side="long", timeframe="5m", setup="orb_stack",
                          entry=entry, stop=stop, tp2=tp2, strategy_version="t")

def test_risk_approves_and_sizes():
    d = decide(_c(), Account(equity=25_000))
    assert d.approved and d.max_qty == 62

@pytest.mark.parametrize("acct,code", [
    (Account(equity=25_000, kill_switch=True), ReasonCode.KILL_SWITCH),
    (Account(equity=25_000, source_healthy=False), ReasonCode.SOURCE_HEALTH_CRITICAL),
    (Account(equity=25_000, daily_pnl=-200), ReasonCode.DAILY_LOSS_LIMIT),
    (Account(equity=25_000, trades_today=3), ReasonCode.MAX_TRADES_PER_DAY),
    (Account(equity=25_000, consecutive_losses=2), ReasonCode.CONSECUTIVE_LOSSES),
    (Account(equity=25_000, open_positions=1), ReasonCode.MAX_OPEN_POSITIONS),
])
def test_risk_blocks(acct, code):
    d = decide(_c(), acct)
    assert not d.approved and d.reason_code is code

def test_risk_rejects_low_rr():
    assert decide(_c(tp2=101.0), Account(equity=25_000)).reason_code is ReasonCode.RR_TOO_LOW


# ---- market truth ----
def _bars(n=60):
    ts = pd.date_range("2026-06-01 13:30", periods=n, freq="1min", tz="UTC")
    return pd.DataFrame({"ts_et": ts, "open": 100.0, "high": 100.5, "low": 99.5, "close": 100.2, "volume": 10})

def test_market_truth_clean_and_dirty():
    assert assess(_bars()).healthy
    bad = _bars(); bad.loc[10, "low"] = 200
    assert not assess(bad).healthy
    assert not assess(_bars().iloc[0:0]).healthy            # empty fails closed


# ---- journal ----
def test_journal_metrics(tmp_path):
    from bot.contracts import JournalEntry, Mode, ExitReason
    j = Journal(tmp_path / "j.jsonl")
    for r in (4.0, -1.0, 4.0, -1.0, 0.5):
        j.record(JournalEntry(candidate_id="x", symbol="QQQ", side="long", mode=Mode.REPLAY,
                              net_r=r, exit_reason=ExitReason.TP2 if r > 0 else ExitReason.STOP))
    assert j.metrics()["total_R"] == 6.5


# ---- regime + news + order-flow score ----
def test_regime_selector():
    assert classify(0.4, 0.2, 30, 0.02, 0.6)["regime"] == "trend"
    assert classify(0.02, 0.01, 8, 0.18, 0.4)["regime"] == "range"

def test_news_lockout():
    nl = NewsLockout([("2026-06-18T18:00:00Z", 30, 15)])
    assert nl.blocked("2026-06-18T17:50:00Z") and not nl.blocked("2026-06-18T16:00:00Z")

def test_orderflow_score_and_state():
    assert score_row(0.4, 0.35, 0.25, 1.6, 1.2, 1) > 90
    assert score_row(-0.4, -0.35, -0.25, -1.6, -1.2, 1) == 0
    sm = DirectionStateMachine(Dir.LONG, persist=3)
    for s in (60, 70, 82, 85, 88):
        st = sm.update(s)
    assert st.value == "enter"


# ---- OMS / portfolio / opportunity / performance / ml (the big-block additions) ----
def test_oms_oco_partial_and_reconcile():
    from bot.execution.oms import OMS
    from bot.contracts import OrderState, PositionPhase
    oms = OMS()
    e = OrderRequest(candidate_id="c", symbol="QQQ", side="long", qty=100,
                     order_type=OrderType.LIMIT, limit_price=545, stop_price=544, take_profit=548)
    oms.submit(e); oms.on_accept(e.order_id); oms.on_fill(e.order_id, 40, 545)
    assert oms.orders[e.order_id].state is OrderState.PARTIALLY_FILLED
    oms.on_fill(e.order_id, 60, 545); assert oms.positions["QQQ"].qty == 100
    rec = oms.reconcile([PositionState(symbol="QQQ", phase=PositionPhase.OPEN, qty=50, side=Side.LONG)])
    assert "MISMATCH" in rec["QQQ"]

def test_portfolio_vetoes():
    from bot.portfolio import Portfolio
    pf = Portfolio(equity=100_000); pf.add("QQQ", 100, 545, 250, "long")
    ok, why = pf.check_add("SPY", 20, 600, 1000, "long", corr={("SPY", "QQQ"): 0.95})
    assert not ok and "cluster" in why

def test_opportunity_ranking():
    from bot.strategy.opportunity import OpportunityQueue
    def c(setup, tp, reg): return TradeCandidate(symbol="QQQ", side="long", timeframe="5m", setup=setup,
                                                 entry=100, stop=99, tp2=99+tp, strategy_version=setup, regime=reg)
    q = OpportunityQueue(); q.add(c("orb_stack", 5, "A")); q.add(c("vwap_revert", 1.6, "C"))
    assert q.best().setup == "orb_stack"

def test_ml_walk_forward_and_promotion():
    import numpy as np, tempfile
    from pathlib import Path
    from bot.ml.predictor import DirectionModel
    from bot.ml.validation import walk_forward, deflated_sharpe
    rng = np.random.default_rng(1); X = rng.normal(size=(400, 6))
    y = (X[:, 0] + 0.4 * X[:, 2] + rng.normal(scale=0.4, size=400) > 0).astype(int)
    assert walk_forward(X, y, DirectionModel, n_splits=4)["oos_auc"] > 0.6
    assert deflated_sharpe(rng.normal(0.1, 1, 252), 100) <= 1.0
