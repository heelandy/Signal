"""BUG HUNT — Wave 7 (swallow audit & dead wiring).

L8 inventory of ~95 `except Exception: pass` sites classified KEEP (best-effort telemetry) /
NARROW (specific exception) / ALARM (money path — must announce or fail loud). The only ALARM
class in the execution money path was the seeded example: `journal.record` failures were swallowed
silently, so a full disk would drop the paper-execution audit record without a peep (the OMS in
execution.db stays the source of truth, so the ORDER is fine — but the loss must be ANNOUNCED).

W7.1  a journal write failure during submit must fire an operator ALERT, never pass silently, and
      must NOT block the order (the OMS is truth).
"""
from __future__ import annotations

import pytest

pd = pytest.importorskip("pandas")

from bot.brokers.base import AccountInfo  # noqa: E402
from bot.contracts import Mode, OrderEvent, OrderState, Side, TradeCandidate  # noqa: E402
from bot.execution.service import ExecutionService  # noqa: E402


class MockBroker:
    name = "mock"; is_paper = True

    def __init__(self):
        self.submits = []; self._n = 0

    def account(self):
        return AccountInfo(equity=25_000.0, buying_power=50_000.0, cash=25_000.0,
                           open_position_count=0, is_paper=True)

    def positions(self):
        return []

    def submit(self, order):
        self.submits.append(order); self._n += 1
        return OrderEvent(order_id=order.order_id, state=OrderState.SUBMITTED, broker_order_id=f"B{self._n}")

    def recent_orders(self):
        return []


class ExplodingJournal:
    def record(self, *a, **k):
        raise OSError("No space left on device")          # full-disk simulation


def _cand():
    return TradeCandidate(symbol="QQQ", side="long", timeframe="5m", setup="orb_stack",
                          entry=100.0, stop=99.0, tp2=104.0, strategy_version="v")


def test_w7_journal_failure_alerts_and_does_not_block_the_order(tmp_path, monkeypatch):
    monkeypatch.setattr("bot.approval.paper_approved", lambda v: True)
    monkeypatch.setattr("bot.strategy.removals.is_removed", lambda *a, **k: None)
    alerts: list = []
    monkeypatch.setattr("bot.alerts.alert",
                        lambda msg, **k: alerts.append(msg), raising=False)
    svc = ExecutionService(MockBroker(), db_path=tmp_path / "e.db", mode=Mode.PAPER,
                           journal=ExplodingJournal(), now=lambda: 1_000_000.0)
    r = svc.submit(_cand(), "autotrade")
    assert r.action == "submitted", f"a journal write failure must NOT block the order (OMS is truth): {r.reason}"
    assert any("journal.record" in m and "FAILED" in m for m in alerts), (
        f"a swallowed journal failure must ALERT, not pass silently — alerts: {alerts}")
    # the order really is persisted in the OMS despite the journal loss
    st = svc.db.execute("SELECT state FROM exec_orders WHERE order_id=?", (r.order_id,)).fetchone()[0]
    assert st == "SUBMITTED"


class _BrokerDownOnRead(MockBroker):
    def recent_orders(self):
        raise ConnectionError("alpaca 503 — broker unreachable")   # a real transport failure


def test_w7_broker_read_failure_during_recover_does_not_fail_release(tmp_path, monkeypatch):
    """recover() must set known=None (leave rows for the next pass) when the broker read RAISES —
    NOT _fail_release a PENDING_SUBMIT order (which releases its idem key and risks a double
    submit of a possibly-live order). This only holds because recent_orders() RAISES instead of
    swallowing to [] (bug hunt W7/L8)."""
    svc = ExecutionService(_BrokerDownOnRead(), db_path=tmp_path / "e.db", mode=Mode.PAPER,
                           now=lambda: 1_000_000.0)
    svc.db.execute(
        "INSERT INTO exec_orders(order_id, correlation_id, idem_key, source, symbol, side, qty, "
        "planned_entry, stop, tp, strategy_version, state, created_at, updated_at, created_epoch) "
        "VALUES('live1','c','k1','autotrade','QQQ','long',1,100,99,104,'v','PENDING_SUBMIT',"
        "'2026-01-01T00:00:00','2026-01-01T00:00:00',999999)")
    svc.db.commit()
    svc.recover()
    st = svc.db.execute("SELECT state FROM exec_orders WHERE order_id='live1'").fetchone()[0]
    assert st == "PENDING_SUBMIT", (
        f"a broker read failure must LEAVE the order for the next pass, not fail-release it — got {st}")
