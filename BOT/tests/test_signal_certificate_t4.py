"""SIGNAL-CERTIFICATE T4 — label lineage: an ENTRY fill is not a final label.

The ML-correctness keystone: a profitability label finalizes ONLY when the round trip closes
(net back to 0). A still-open entry must never be scored as a completed trade, a pure shadow row
(no execution link) must never be touched, and a finalized label must never be downgraded.
"""
from __future__ import annotations

import sqlite3

import pytest

pd = pytest.importorskip("pandas")

from bot.brokers.base import AccountInfo  # noqa: E402
from bot.contracts import Mode, OrderEvent, OrderState, PositionState, Side, TradeCandidate  # noqa: E402
from bot.execution.service import ExecutionService  # noqa: E402


class MockBroker:
    name = "mock"; is_paper = True

    def __init__(self):
        self.book: list[PositionState] = []
        self.orders: list[dict] = []
        self._n = 0

    def account(self):
        return AccountInfo(equity=100_000.0, buying_power=200_000.0, cash=100_000.0,
                           open_position_count=len(self.book), is_paper=True)

    def positions(self):
        return list(self.book)

    def submit(self, order):
        self._n += 1
        return OrderEvent(order_id=order.order_id, state=OrderState.SUBMITTED, broker_order_id=f"B{self._n}")

    def recent_orders(self):
        return list(self.orders)


def _sig(cid, sym="QQQ"):
    return {"candidate_id": cid, "symbol": sym, "side": "long", "family": "breakout",
            "session": "rth", "entry": 100.0, "stop": 99.0, "tp1": 101.5, "tp2": 104.0,
            "generated_at": "2026-07-13T14:30:00+00:00", "strategy_version": "orb-standard-2026.07.7"}


def _state(T, cid):
    con = sqlite3.connect(str(T.DB))
    row = con.execute("SELECT state FROM decisions WHERE candidate_id=?", (cid,)).fetchone()
    con.close()
    return row[0] if row else None


@pytest.fixture()
def env(tmp_path, monkeypatch):
    import bot.tracker as T
    monkeypatch.setattr(T, "DB", tmp_path / "hs.db")
    monkeypatch.setattr("bot.approval.paper_approved", lambda v: True)
    monkeypatch.setattr("bot.strategy.removals.is_removed", lambda *a, **k: None)
    T.record_decision(_sig("C1"), taken=True, auto=True)          # the traded candidate (shadow)
    T.record_decision(_sig("SHADOW"), taken=True, auto=True)      # a pure shadow row, never submitted
    svc = ExecutionService(MockBroker(), db_path=tmp_path / "exec.db", mode=Mode.PAPER,
                           now=lambda: 1_000_000.0)
    return T, svc


def test_t4_entry_fill_is_entry_filled_not_final(env):
    T, svc = env
    c = TradeCandidate(symbol="QQQ", side="long", timeframe="5m", setup="orb_stack",
                       entry=100.0, stop=99.0, tp2=104.0, strategy_version="orb-standard-2026.07.7",
                       candidate_id="C1")
    r = svc.submit(c, "autotrade")
    assert r.action == "submitted", r.reason
    # an ENTRY fill (position opens, net != 0)
    svc._mock = svc.broker
    svc.broker.orders = [{"id": r.broker_order_id, "client_order_id": None, "status": "partially_filled",
                          "filled_qty": 1, "avg_fill_price": 100.0,
                          "legs": [{"status": "accepted"}, {"status": "accepted"}]}]
    svc.poll_fills()
    assert _state(T, "C1") == "entry_filled", (
        "an entry fill must set entry_filled, NOT a final label (the round trip is still open)")
    book, _ = svc._replay_fills()
    assert book["QQQ"]["net"] == 1                                # position open


def test_t4_closed_round_trip_is_label_final(env):
    T, svc = env
    c = TradeCandidate(symbol="QQQ", side="long", timeframe="5m", setup="orb_stack",
                       entry=100.0, stop=99.0, tp2=104.0, strategy_version="orb-standard-2026.07.7",
                       candidate_id="C1")
    r = svc.submit(c, "autotrade")
    oid = r.order_id
    # entry fill -> entry_filled
    svc.broker.orders = [{"id": r.broker_order_id, "status": "partially_filled", "filled_qty": 1,
                          "avg_fill_price": 100.0, "legs": [{"status": "accepted"}]}]
    svc.poll_fills()
    assert _state(T, "C1") == "entry_filled"
    # the round trip CLOSES: seed the exit fill (short 1) so net -> 0, then finalize
    svc.db.execute("INSERT INTO exec_fills VALUES(?,?,?,?,?,?,?,?)",
                   ("exit1", oid, r.broker_order_id, "QQQ", "short", 1, 101.0, "2026-07-13T15:30:00"))
    svc.db.commit()
    book, _ = svc._replay_fills()
    assert book["QQQ"]["net"] == 0                                # flat -> round trip complete
    svc._mark_tracker_filled(oid, final=True)
    assert _state(T, "C1") == "label_final", "a closed round trip must finalize the label"


def test_t4_shadow_row_never_marked(env):
    T, svc = env
    c = TradeCandidate(symbol="QQQ", side="long", timeframe="5m", setup="orb_stack",
                       entry=100.0, stop=99.0, tp2=104.0, strategy_version="orb-standard-2026.07.7",
                       candidate_id="C1")
    r = svc.submit(c, "autotrade")
    svc.broker.orders = [{"id": r.broker_order_id, "status": "filled", "filled_qty": 1,
                          "avg_fill_price": 100.0, "legs": [{"status": "accepted"}]}]
    svc.poll_fills()
    assert _state(T, "SHADOW") == "shadow", (
        "a pure shadow row (no execution link) must NEVER be marked filled/final")


def test_t4_label_final_is_never_downgraded(env):
    T, svc = env
    c = TradeCandidate(symbol="QQQ", side="long", timeframe="5m", setup="orb_stack",
                       entry=100.0, stop=99.0, tp2=104.0, strategy_version="orb-standard-2026.07.7",
                       candidate_id="C1")
    r = svc.submit(c, "autotrade")
    svc._mark_tracker_filled(r.order_id, final=True)
    assert _state(T, "C1") == "label_final"
    svc._mark_tracker_filled(r.order_id, final=False)            # a late/duplicate poll
    assert _state(T, "C1") == "label_final", "a finalized label must never revert to entry_filled"


# ── T4 LIVE-PATH FINALIZATION (bug hunt find, FIXED 2026-07-12) ──────────────────────────────
# Found as two xfail-pinned defects: (1) a bracket stop/TP is a NESTED leg of the entry order
# (recent_orders nested=True), not a separate matchable order — poll_fills never saw the close,
# so net never returned to 0 and label_final was unreachable via the live path; (2) finalization
# marked the CLOSING order's candidate, not the entry's. FIX: poll_fills ingests a FILLED leg as
# the offsetting fill booked against the ENTRY order, and finalization walks the SYMBOL's filled
# entries when the book returns to net 0. These are now the live-path regression tests.

def test_t4_bracket_exit_finalizes_the_entry(env):
    T, svc = env
    c = TradeCandidate(symbol="QQQ", side="long", timeframe="5m", setup="orb_stack",
                       entry=100.0, stop=99.0, tp2=104.0, strategy_version="orb-standard-2026.07.7",
                       candidate_id="C1")
    r = svc.submit(c, "autotrade")
    # entry fill -> entry_filled, book net +1 (legs working, not yet filled)
    svc.broker.orders = [{"id": r.broker_order_id, "client_order_id": None, "status": "filled",
                          "filled_qty": 1, "avg_fill_price": 100.0,
                          "legs": [{"id": "TP-1", "status": "accepted", "filled_qty": 0,
                                    "avg_fill_price": 0.0},
                                   {"id": "SL-1", "status": "accepted", "filled_qty": 0,
                                    "avg_fill_price": 0.0}]}]
    svc.poll_fills()
    assert _state(T, "C1") == "entry_filled"
    # the bracket TP fills at the broker — it arrives as a FILLED NESTED LEG of the entry order
    svc.broker.orders = [{"id": r.broker_order_id, "client_order_id": None, "status": "filled",
                          "filled_qty": 1, "avg_fill_price": 100.0,
                          "legs": [{"id": "TP-1", "status": "filled", "filled_qty": 1,
                                    "avg_fill_price": 104.0,
                                    "updated_at": "2026-07-13T15:30:00+00:00"},
                                   {"id": "SL-1", "status": "canceled", "filled_qty": 0,
                                    "avg_fill_price": 0.0}]}]
    svc.poll_fills()
    book, _ = svc._replay_fills()
    assert book["QQQ"]["net"] == 0, "the filled TP leg must close the internal book"
    assert _state(T, "C1") == "label_final", "a closed round trip must finalize the ENTRY label"
    # idempotent: a late duplicate poll neither re-books the leg nor downgrades the label
    svc.poll_fills()
    book2, _ = svc._replay_fills()
    assert book2["QQQ"]["net"] == 0 and _state(T, "C1") == "label_final"


def test_t4_short_entry_bracket_close_and_partial_legs(env):
    """Bug hunt 3rd pass: the leg-offset side must mirror for SHORT entries, and a leg that fills
    PARTIALLY (cumulative 1 then 3) must ingest deltas — never double-book, never wrong-side."""
    T, svc = env
    c = TradeCandidate(symbol="QQQ", side="short", timeframe="5m", setup="orb_stack",
                       entry=100.0, stop=101.0, tp2=96.0, strategy_version="orb-standard-2026.07.7",
                       candidate_id="C1")
    r = svc.submit(c, "autotrade")
    assert r.action == "submitted", r.reason
    # short entry fills 3 lots -> book net -3
    svc.broker.orders = [{"id": r.broker_order_id, "client_order_id": None, "status": "filled",
                          "filled_qty": 3, "avg_fill_price": 100.0,
                          "legs": [{"id": "TP-9", "status": "accepted", "filled_qty": 0,
                                    "avg_fill_price": 0.0}]}]
    svc.poll_fills()
    book, _ = svc._replay_fills()
    assert book["QQQ"]["net"] == -3
    assert _state(T, "C1") == "entry_filled"
    # the TP leg fills PARTIALLY (cumulative 1), then fully (cumulative 3)
    svc.broker.orders = [{"id": r.broker_order_id, "client_order_id": None, "status": "filled",
                          "filled_qty": 3, "avg_fill_price": 100.0,
                          "legs": [{"id": "TP-9", "status": "partially_filled", "filled_qty": 1,
                                    "avg_fill_price": 96.0, "updated_at": "2026-07-13T15:00:00+00:00"}]}]
    svc.poll_fills()
    book, _ = svc._replay_fills()
    assert book["QQQ"]["net"] == -2, "a partial leg fill must ingest the DELTA (1), offsetting long"
    assert _state(T, "C1") == "entry_filled", "still open — must NOT finalize at net -2"
    svc.broker.orders = [{"id": r.broker_order_id, "client_order_id": None, "status": "filled",
                          "filled_qty": 3, "avg_fill_price": 100.0,
                          "legs": [{"id": "TP-9", "status": "filled", "filled_qty": 3,
                                    "avg_fill_price": 96.0, "updated_at": "2026-07-13T15:05:00+00:00"}]}]
    svc.poll_fills()
    book, _ = svc._replay_fills()
    assert book["QQQ"]["net"] == 0, "cumulative 3 after 1 must ingest delta 2 -> flat"
    assert _state(T, "C1") == "label_final", "flat round trip must finalize the SHORT entry"
    # duplicate late poll: nothing re-books, label stays final
    svc.poll_fills()
    book, _ = svc._replay_fills()
    assert book["QQQ"]["net"] == 0 and _state(T, "C1") == "label_final"


def test_t4_close_finalizes_the_entry_not_the_closing_order(env):
    T, svc = env
    T.record_decision(_sig("C2"), taken=True, auto=True)          # the closing order's candidate
    c = TradeCandidate(symbol="QQQ", side="long", timeframe="5m", setup="orb_stack",
                       entry=100.0, stop=99.0, tp2=104.0, strategy_version="orb-standard-2026.07.7",
                       candidate_id="C1")
    r = svc.submit(c, "autotrade")
    svc.broker.orders = [{"id": r.broker_order_id, "client_order_id": None, "status": "filled",
                          "filled_qty": 1, "avg_fill_price": 100.0, "legs": [{"status": "accepted"}]}]
    svc.poll_fills()
    assert _state(T, "C1") == "entry_filled"
    # a SEPARATE opposing order (its own candidate C2) closes the book: net +1 -> 0
    svc.db.execute("INSERT INTO exec_orders(order_id, symbol, side, qty, state, broker_order_id, "
                   "candidate_id, idem_key, created_at, updated_at, created_epoch) "
                   "VALUES('O2','QQQ','short',1,'SUBMITTED','B2','C2','idem-c2','t','t',1000000.0)")
    svc.db.commit()
    svc.broker.orders = [{"id": "B2", "client_order_id": None, "status": "filled",
                          "filled_qty": 1, "avg_fill_price": 101.0}]
    svc.poll_fills()
    book, _ = svc._replay_fills()
    assert book["QQQ"]["net"] == 0                                # flat -> round trip complete
    assert _state(T, "C1") == "label_final", (
        "the ENTRY whose round trip just closed (C1) must finalize — not the closing order (C2)")
