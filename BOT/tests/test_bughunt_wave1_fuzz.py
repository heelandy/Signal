"""BUG HUNT — Wave 1 state-machine fuzz (category 2, generative).

Drives poll_fills with adversarial broker-response orderings and asserts the money invariants:
a fill is never minted, lost, or double-counted; the internal position matches the broker's
CUMULATIVE filled_qty exactly; no ordering crashes the service.

W1F.1  filled_qty is CUMULATIVE — a partial-then-full sequence must net to the order size, not the
       sum of the cumulative snapshots (the confirmed double-count bug).
W1F.2  fuzz: random interleavings of partial/full/dup/out-of-order/cancel/unknown payloads keep the
       book == the max cumulative filled seen per order, always.
"""
from __future__ import annotations

import random

import pytest

pd = pytest.importorskip("pandas")

from bot.brokers.base import AccountInfo  # noqa: E402
from bot.contracts import Mode, OrderEvent, OrderState  # noqa: E402
from bot.execution.service import ExecutionService  # noqa: E402


class ScriptBroker:
    is_paper = True

    def __init__(self):
        self.orders: list = []

    def account(self):
        return AccountInfo(equity=25_000.0, buying_power=50_000.0, cash=25_000.0,
                           open_position_count=0, is_paper=True)

    def positions(self):
        return []

    def submit(self, order):
        return OrderEvent(order_id=order.order_id, state=OrderState.SUBMITTED, broker_order_id="B1")

    def recent_orders(self):
        return list(self.orders)


@pytest.fixture()
def svc(tmp_path):
    s = ExecutionService(ScriptBroker(), db_path=tmp_path / "e.db", mode=Mode.PAPER, now=lambda: 1e6)
    s.db.execute(
        "INSERT INTO exec_orders(order_id,correlation_id,idem_key,source,symbol,side,qty,"
        "planned_entry,stop,tp,strategy_version,state,created_at,updated_at,created_epoch,"
        "broker_order_id) VALUES('o1','c','k1','autotrade','QQQ','long',10,100,99,104,'v',"
        "'SUBMITTED','2026-07-13T15:00:00','2026-07-13T15:00:00',1e6,'B1')")
    s.db.commit()
    return s


def _order(status, filled, price=100.0):
    return {"id": "B1", "client_order_id": None, "status": status, "filled_qty": filled,
            "avg_fill_price": price, "legs": [{"status": "accepted"}, {"status": "accepted"}]}


def _net(svc):
    book, _ = svc._replay_fills()
    return book.get("QQQ", {}).get("net", 0)


def test_w1f_cumulative_partial_then_full_nets_to_order_size(svc):
    svc.broker.orders = [_order("partially_filled", 5)]
    svc.poll_fills()
    svc.broker.orders = [_order("filled", 10)]
    svc.poll_fills()
    assert _net(svc) == 10, "cumulative filled_qty must net to the order size (10), not 5+10=15"


def test_w1f_repolling_same_cumulative_is_idempotent(svc):
    svc.broker.orders = [_order("partially_filled", 4)]
    for _ in range(5):
        svc.poll_fills()                                  # same cumulative re-polled repeatedly
    assert _net(svc) == 4, "re-polling the same cumulative fill must not add shares"


def test_w1f_fill_after_cancel_does_not_uncount(svc):
    svc.broker.orders = [_order("filled", 10)]
    svc.poll_fills()
    svc.broker.orders = [_order("canceled", 10)]          # a late cancel of an already-filled order
    svc.poll_fills()
    assert _net(svc) == 10, "a cancel after a fill must not remove the filled shares"


@pytest.mark.parametrize("seed", range(25))
def test_w1f_random_orderings_book_equals_max_cumulative(svc, seed):
    """FUZZ: feed a random interleaving of partial/full/dup/out-of-order/cancel/unknown payloads.
    The booked position must ALWAYS equal the max cumulative filled seen (never more, never less),
    and no ordering may raise."""
    rnd = random.Random(seed)
    cumulatives = sorted({rnd.randint(1, 10) for _ in range(rnd.randint(1, 5))}) or [10]
    payloads = []
    for c in cumulatives:
        payloads.append(_order("partially_filled" if c < 10 else "filled", c))
        if rnd.random() < 0.5:
            payloads.append(_order("partially_filled" if c < 10 else "filled", c))  # duplicate
    if rnd.random() < 0.4:
        payloads.append({"id": "GHOST", "status": "filled", "filled_qty": 7, "avg_fill_price": 9.0})
    if rnd.random() < 0.3:
        payloads.append(_order("canceled", max(cumulatives)))
    rnd.shuffle(payloads)                                  # ADVERSARIAL ordering (may be out-of-order)
    # deliver them one poll at a time, in the shuffled order, each as the sole broker truth
    max_seen = 0
    for p in payloads:
        svc.broker.orders = [p]
        svc.poll_fills()                                  # must never raise
        if p.get("id") == "B1":
            max_seen = max(max_seen, int(p["filled_qty"]))
    # after all polls, the book equals the HIGHEST cumulative the broker ever reported for the order
    highest = max((int(p["filled_qty"]) for p in payloads if p.get("id") == "B1"), default=0)
    assert _net(svc) == highest, f"seed {seed}: book {_net(svc)} != max cumulative {highest}"
    # never a phantom from the GHOST order
    assert svc.db.execute("SELECT COUNT(*) FROM exec_fills WHERE order_id NOT IN "
                          "(SELECT order_id FROM exec_orders)").fetchone()[0] == 0
