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
    legs = [SimpleNamespace(id="L1", status="OrderStatus.NEW", filled_qty=None,
                            filled_avg_price=None, updated_at=None),
            SimpleNamespace(id="L2", status="OrderStatus.REJECTED", filled_qty=None,
                            filled_avg_price=None, updated_at=None)]
    m = _map_order(_fake(legs=legs))
    assert [l["status"] for l in m["legs"]] == ["new", "rejected"], \
        "leg statuses feed the bracket-integrity halt — shape is load-bearing"
    assert all({"id", "status", "filled_qty", "avg_fill_price", "updated_at"} <= set(l)
               for l in m["legs"]), "legs must carry fill truth (T4: a filled leg IS the close)"
    m2 = _map_order(_fake(legs=None, filled=None, avg=None))
    assert m2["legs"] is None and m2["filled_qty"] == 0.0 and m2["avg_fill_price"] == 0.0


def test_contract_filled_leg_carries_the_close():
    """T4 (bug hunt 2026-07-12): a FILLED bracket leg is the round trip's CLOSING fill —
    _map_order must surface its id/qty/price so poll_fills can book the offset."""
    legs = [SimpleNamespace(id="TP-9", status="OrderStatus.FILLED", filled_qty="3",
                            filled_avg_price="104.5", updated_at="2026-07-12T15:00:00Z")]
    m = _map_order(_fake(legs=legs))
    leg = m["legs"][0]
    assert leg == {"id": "TP-9", "status": "filled", "filled_qty": 3.0,
                   "avg_fill_price": 104.5, "updated_at": "2026-07-12T15:00:00Z"}
