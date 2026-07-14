"""EXIT ROUTING (completion-order step 5, 2026-07-14): cancel/exit/flatten must route through
the ExecutionService — and a webhook 'exit' for ONE ticker must NEVER flatten the whole account.

The audited defect: the webhook exit branch called broker.flatten() directly (= Alpaca
close_all_positions) — an exit signal for QQQ would close SPY and everything else, with no OMS
record of the exit at all."""
from __future__ import annotations

import pytest

pd = pytest.importorskip("pandas")

from bot.brokers.base import AccountInfo  # noqa: E402
from bot.contracts import Mode, OrderEvent, OrderState, PositionState, Side  # noqa: E402
from bot.execution.service import ExecutionService  # noqa: E402


class MockBroker:
    name = "mock"; is_paper = True

    def __init__(self, positions=()):
        self._pos = list(positions)
        self.closed_symbols = []
        self.flatten_calls = 0
        self.cancelled = []

    def account(self):
        return AccountInfo(equity=100_000.0, buying_power=200_000.0, cash=100_000.0,
                           open_position_count=len(self._pos), is_paper=True)

    def positions(self):
        return list(self._pos)

    def submit(self, order):
        return OrderEvent(order_id=order.order_id, state=OrderState.SUBMITTED, broker_order_id="B1")

    def recent_orders(self):
        return []

    def close_position(self, symbol):
        self.closed_symbols.append(symbol)
        return {"closed": True, "broker_order_id": f"CLOSE-{symbol}"}

    def flatten(self):
        self.flatten_calls += 1
        return {"flattened": True}

    def cancel(self, order_id):
        self.cancelled.append(order_id)
        return OrderEvent(order_id=str(order_id), state=OrderState.CANCELLED, broker_order_id=str(order_id))


def _pos(sym, qty=5):
    return PositionState(symbol=sym, side="long", qty=qty, avg_price=100.0)


def _svc(tmp_path, positions=()):
    return ExecutionService(MockBroker(positions), db_path=tmp_path / "e.db", mode=Mode.PAPER)


def test_close_symbol_closes_only_that_symbol(tmp_path):
    svc = _svc(tmp_path, positions=[_pos("QQQ"), _pos("SPY")])
    res = svc.close_symbol("QQQ", source="webhook")
    assert res["action"] == "closed", res
    assert svc.broker.closed_symbols == ["QQQ"], "ONLY the named symbol closes"
    assert svc.broker.flatten_calls == 0, "a single-ticker exit must NEVER flatten the account"
    row = svc.db.execute("SELECT symbol, side, qty, source, broker_order_id FROM exec_orders "
                         "WHERE source='webhook-exit'").fetchone()
    assert row is not None, "the exit must be OMS-recorded"
    assert row[0] == "QQQ" and row[1] == "short" and row[2] == 5 and row[4] == "CLOSE-QQQ"


def test_close_symbol_without_position_is_a_noop(tmp_path):
    svc = _svc(tmp_path, positions=[_pos("SPY")])
    res = svc.close_symbol("QQQ", source="webhook")
    assert res["action"] == "no_position"
    assert svc.broker.closed_symbols == [] and svc.broker.flatten_calls == 0


def test_close_symbol_allowed_during_halt(tmp_path):
    """Halts block ENTRIES; an exit REDUCES risk and must always be possible."""
    svc = _svc(tmp_path, positions=[_pos("QQQ")])
    svc.set_halt("reconcile mismatch: test")
    res = svc.close_symbol("QQQ", source="webhook")
    assert res["action"] == "closed", "an exit must work even while submissions are halted"


def test_flatten_all_routes_through_service_with_audit(tmp_path):
    svc = _svc(tmp_path, positions=[_pos("QQQ")])
    res = svc.flatten_all(source="ui")
    assert res.get("flattened") is True and svc.broker.flatten_calls == 1
    ev = svc.db.execute("SELECT message FROM exec_events WHERE state='FLATTEN_ALL'").fetchone()
    assert ev is not None, "flatten-all must leave an audit event"


def test_cancel_updates_the_oms_row(tmp_path):
    svc = _svc(tmp_path)
    svc.db.execute("INSERT INTO exec_orders(order_id, symbol, side, qty, state, broker_order_id, "
                   "idem_key, created_at, updated_at, created_epoch) "
                   "VALUES('O1','QQQ','long',1,'SUBMITTED','B77','k1','t','t',0)")
    svc.db.commit()
    res = svc.cancel_order("B77", source="ui")
    assert res["cancelled"] == "cancelled"
    st = svc.db.execute("SELECT state FROM exec_orders WHERE order_id='O1'").fetchone()[0]
    assert st == "CANCELLED", "the OMS row must reflect the cancel — not just the broker"
