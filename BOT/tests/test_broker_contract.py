"""BROKER MAPPING CONTRACT TEST (P1.6 completion, 2026-07-12): the exact dict shape
`recent_orders()` produces is what ExecutionService.poll_fills / recovery / bracket-integrity
consume. `_map_order` is pure (no SDK) — this pins the contract offline, in CI."""
from __future__ import annotations

from types import SimpleNamespace

from bot.brokers.alpaca_broker import _map_order

CONTRACT_KEYS = {"id", "client_order_id", "symbol", "status", "filled_qty",
                 "avg_fill_price", "updated_at", "legs"}


def _fake(status="OrderStatus.FILLED", legs=None, filled="2", avg="101.25"):
    return SimpleNamespace(id="abc-123", client_order_id="k1", symbol="QQQ",
                           status=status, filled_qty=filled, filled_avg_price=avg,
                           updated_at="2026-07-12T14:31:00Z", legs=legs)


def test_contract_keys_and_types():
    m = _map_order(_fake())
    assert set(m) == CONTRACT_KEYS
    assert m["status"] == "filled", "status must be the lowercase tail of the SDK enum"
    assert m["filled_qty"] == 2.0 and m["avg_fill_price"] == 101.25
    assert m["id"] == "abc-123" and m["client_order_id"] == "k1"


def test_contract_handles_bracket_legs_and_nulls():
    legs = [SimpleNamespace(status="OrderStatus.NEW"), SimpleNamespace(status="OrderStatus.REJECTED")]
    m = _map_order(_fake(legs=legs))
    assert m["legs"] == [{"status": "new"}, {"status": "rejected"}], \
        "leg statuses feed the bracket-integrity halt — shape is load-bearing"
    m2 = _map_order(_fake(legs=None, filled=None, avg=None))
    assert m2["legs"] is None and m2["filled_qty"] == 0.0 and m2["avg_fill_price"] == 0.0
