"""BUG HUNT — Wave 1 (money path) regression armor.

Red-first tests for the three seeded leads adjudicated CONFIRMED on 2026-07-12:

  L1  risk.decide sized an unknown-to-the-dict FUTURES symbol at a silent $1/pt fallback
      (a 20-100x oversize under point-value registry drift). Must fail closed.
  L2  the ExecutionService idem key omitted `setup` while its duplicate MESSAGE claims
      "same setup, same trade date" — two DIFFERENT setups at one price/side/day collided
      as a FALSE duplicate; the second (legitimate) order was silently dropped.
  L3  _replay_fills kept the OLD average on a fill that FLIPPED net direction (long->short
      through zero), so the residual position carried a wrong basis and the NEXT close
      realized the wrong P&L — which feeds the daily/weekly loss gates.

Each test FAILS on the pre-fix code and passes after the fix. Plan: docs/BUG_HUNT_PLAN.md;
findings: docs/BUG_HUNT_LOG.md.
"""
from __future__ import annotations

import threading

import pytest

pd = pytest.importorskip("pandas")

from bot.brokers.base import AccountInfo  # noqa: E402
from bot.contracts import (Mode, OrderEvent, OrderState, PositionPhase, PositionState, Side,  # noqa: E402
                           TradeCandidate)
from bot.execution.service import ExecutionService  # noqa: E402
from bot.risk import Account, decide  # noqa: E402


# ─────────────────────────── L1 — sizing fail-open ───────────────────────────

def _cand(sym="QQQ", side="long", entry=100.0, stop=99.0, tp2=104.0,
          setup="orb_stack", version="orb-standard-2026.07.7"):
    return TradeCandidate(symbol=sym, side=side, timeframe="5m", setup=setup,
                          entry=entry, stop=stop, tp2=tp2, strategy_version=version)


def test_l1_futures_symbol_missing_point_value_fails_closed():
    """DRIFT: a futures symbol lost from the sizing dict must NOT fall back to $1/pt.

    NQ is a $20/pt contract. With it dropped from the point-value registry, the pre-fix code
    read acct.point_value.get('NQ', 1.0) == 1.0 and sized it as if $1/pt — a ~20x oversize on
    a real futures position. The registry (hs_contracts.spec) fails loud on an unknown symbol;
    the risk gate must too.
    """
    acct = Account(equity=25_000, point_value={})            # NQ dropped (registry drift)
    rd = decide(_cand(sym="NQ", entry=20_000.0, stop=19_950.0, tp2=20_200.0), acct)
    assert not rd.approved, ("a futures symbol with no known point value must fail closed, not "
                             "size at a silent $1/pt fallback")
    assert "point value" in rd.notes.lower(), rd.notes


def test_l1_known_equity_still_sizes_at_one_dollar():
    """The fix must NOT break equities: QQQ/SPY legitimately trade at $1/share and are absent
    from the futures point-value dict by design."""
    rd = decide(_cand(sym="QQQ", entry=100.0, stop=99.0, tp2=104.0), Account(equity=25_000))
    assert rd.approved and rd.max_qty > 0, rd.to_json()


# ─────────────────────────── L2/L3 — execution service ───────────────────────────

class MockBroker:
    name = "mock"
    is_paper = True

    def __init__(self):
        self.submits: list = []
        self.book: list[PositionState] = []
        self.orders: list[dict] = []
        self._n = 0

    def account(self):
        return AccountInfo(equity=25_000.0, buying_power=50_000.0, cash=25_000.0,
                           open_position_count=len(self.book), is_paper=True)

    def positions(self):
        return list(self.book)

    def submit(self, order):
        self.submits.append(order)
        self._n += 1
        return OrderEvent(order_id=order.order_id, state=OrderState.SUBMITTED,
                          broker_order_id=f"B{self._n}", message="ok")

    def cancel(self, order_id):
        return OrderEvent(order_id=order_id, state=OrderState.CANCELLED)

    def recent_orders(self):
        return list(self.orders)


@pytest.fixture()
def svc(tmp_path, monkeypatch):
    monkeypatch.setattr("bot.approval.paper_approved", lambda v: True)
    monkeypatch.setattr("bot.strategy.removals.is_removed", lambda *a, **k: None)
    b = MockBroker()
    clock = {"t": 1_000_000.0}
    s = ExecutionService(b, db_path=tmp_path / "exec.db", mode=Mode.PAPER, now=lambda: clock["t"])
    s._clock = clock
    s._mock = b
    return s


def test_l2_two_setups_same_price_are_not_false_duplicates(svc):
    """Two DIFFERENT setups firing the same symbol/side/price on one day must both submit —
    the idem key must include `setup`, the very dimension its duplicate message already claims
    ('same setup, same trade date'). Pre-fix the second was dropped as a FALSE duplicate."""
    r1 = svc.submit(_cand(setup="orb_stack", entry=100.0), "autotrade")
    assert r1.action == "submitted", r1.reason
    r2 = svc.submit(_cand(setup="vwap_revert", entry=100.0), "autotrade")
    assert r2.action == "submitted", (
        f"a different setup at the same price/side/day must not false-duplicate — got "
        f"{r2.action}: {r2.reason}")
    # and the same setup twice STILL dedups (the guard we must not weaken)
    r3 = svc.submit(_cand(setup="orb_stack", entry=100.0), "autotrade")
    assert r3.action == "duplicate", "same setup, same day must still dedup"


def _fill(fid, side, qty, price, at="2026-07-13T15:00:00", sym="QQQ"):
    return (fid, f"o{fid}", f"B{fid}", sym, side, qty, price, at)


def test_l3_direction_flip_realizes_pnl_off_the_flip_price(svc):
    """A fill that FLIPS net direction opens the residual at the FLIP price, not the old avg.

    Tape (QQQ, $1/pt):
      long  10 @ 100   -> long 10 @ 100
      short 15 @ 110   -> closes 10 long for +$100; residual SHORT 5, opened @ 110
      long   5 @ 105   -> closes the short 5 for +$25 (shorted 110, covered 105)
    Correct realized total = +125. Pre-fix kept avg=100 on the residual short, so the last
    close realized (105-100)*5*(-1) = -$25, total +75 — a $50 error on a 5-lot, straight into
    the daily/weekly loss gates.
    """
    fills = [_fill("f0", "long", 10, 100.0),
             _fill("f1", "short", 15, 110.0),
             _fill("f2", "long", 5, 105.0)]
    svc.db.executemany("INSERT INTO exec_fills VALUES(?,?,?,?,?,?,?,?)", fills)
    svc.db.commit()
    book, realized = svc._replay_fills()
    total = round(sum(p for _, p, *_ in realized), 6)
    assert total == pytest.approx(125.0), (
        f"direction-flip realized P&L wrong: got {total}, expected 125.0 — the residual short "
        f"must carry the flip-fill price (110), not the stale long avg (100)")
    assert book["QQQ"]["net"] == 0, book["QQQ"]


def test_l3_partial_reduce_still_keeps_avg(svc):
    """Guard: a PARTIAL reduce (no flip) must still keep the running average — the fix touches
    only the through-zero flip case."""
    fills = [_fill("f0", "long", 10, 100.0),
             _fill("f1", "short", 4, 110.0)]        # reduce to long 6, avg still 100
    svc.db.executemany("INSERT INTO exec_fills VALUES(?,?,?,?,?,?,?,?)", fills)
    svc.db.commit()
    book, realized = svc._replay_fills()
    assert book["QQQ"]["net"] == 6 and book["QQQ"]["avg"] == pytest.approx(100.0), book["QQQ"]
    assert round(sum(p for _, p, *_ in realized), 6) == pytest.approx(40.0)   # (110-100)*4


# ─────────────────────────── Wave 1 remainder — concurrency / numeric / fuzz ──────────

def test_w1_concurrent_same_candidate_exactly_one_submits(svc):
    """N threads submit the IDENTICAL candidate at once → the sqlite UNIQUE(idem_key) must let
    exactly ONE through; the rest are duplicates. No thread mints a second order for one signal."""
    results: list = []
    errors: list = []

    def go():
        try:
            results.append(svc.submit(_cand(entry=100.0), "autotrade").action)
        except Exception as e:                       # a raised submit under contention = a find
            errors.append(repr(e))

    ts = [threading.Thread(target=go) for _ in range(12)]
    for t in ts:
        t.start()
    for t in ts:
        t.join()
    assert not errors, f"submit raised under concurrency: {errors}"
    assert results.count("submitted") == 1, f"exactly one order per signal, got {results}"
    assert all(a in ("submitted", "duplicate") for a in results), results
    rows = svc.db.execute("SELECT count(*) FROM exec_orders WHERE state='SUBMITTED'").fetchone()[0]
    assert rows == 1, f"exactly one SUBMITTED row must persist, got {rows}"


def test_w1_double_poll_never_double_ingests_a_fill(svc):
    """Polling the same broker fill twice must ingest it ONCE (fill_id dedup) — the money
    invariant: a share is never counted twice."""
    r = svc.submit(_cand(entry=100.0), "autotrade")
    assert r.action == "submitted"
    filled = {"id": r.broker_order_id, "client_order_id": None, "status": "filled",
              "filled_qty": 5, "avg_fill_price": 100.2,
              "legs": [{"status": "accepted"}, {"status": "accepted"}]}
    svc._mock.orders = [filled]
    svc.poll_fills()
    svc.poll_fills()                                  # idempotent replay
    n = svc.db.execute("SELECT count(*) FROM exec_fills").fetchone()[0]
    assert n == 1, f"a fill must ingest exactly once across repeated polls, got {n}"


def test_w1_fill_for_unknown_order_creates_no_phantom(svc):
    """A broker order that matches NO internal row must be skipped, never invent a fill."""
    svc._mock.orders = [{"id": "GHOST", "client_order_id": "nope", "status": "filled",
                         "filled_qty": 99, "avg_fill_price": 500.0}]
    out = svc.poll_fills()
    assert out.get("fills_ingested", 0) == 0
    assert svc.db.execute("SELECT count(*) FROM exec_fills").fetchone()[0] == 0


def test_w1_decide_never_raises_on_a_subnormal_stop():
    """A subnormally tight stop makes risk/unit round to $0.00. decide() must REJECT cleanly
    (a total function), never raise while constructing an APPROVED decision with 0 dollar risk."""
    rd = decide(_cand(sym="NQ", entry=20_000.0, stop=20_000.0 - 1e-9, tp2=20_050.0),
                Account(equity=1e9))
    assert not rd.approved and "too tight" in rd.notes.lower(), rd.to_json()


def test_w1_sizing_bounds_are_finite_and_capped_at_extremes():
    """Huge equity must stay finite and respect the caps (no overflow)."""
    # futures: absolute contract cap
    rd = decide(_cand(sym="NQ", entry=20_000.0, stop=19_900.0, tp2=20_300.0), Account(equity=1e9))
    assert rd.approved and 0 < rd.max_qty <= 50, rd.to_json()   # RiskLimits.max_contracts
    # equity: qty stays finite and never exceeds the notional cap (here the risk budget binds first)
    rd2 = decide(_cand(sym="QQQ", entry=100.0, stop=99.0, tp2=104.0), Account(equity=1e9))
    assert rd2.approved and 0 < rd2.max_qty <= int(4.0 * 1e9 / 100.0), rd2.to_json()


def test_w1_qty_mult_hint_never_sizes_above_the_risk_gate(svc):
    """A qty_mult hint may only size DOWN; it can never exceed the risk gate's max_qty."""
    r = svc.submit(_cand(sym="QQQ", entry=100.0, stop=99.0, tp2=104.0), "autotrade",
                   qty_mult=1000.0)                   # absurd up-hint
    assert r.action == "submitted"
    approved = decide(_cand(sym="QQQ", entry=100.0, stop=99.0, tp2=104.0),
                      Account(equity=25_000)).max_qty
    assert r.qty <= approved, f"qty {r.qty} exceeded the risk-gate max {approved}"


def test_w1_account_too_small_rejects_not_zero_qty(svc):
    """A budget smaller than one unit's risk must REJECT (max_qty=0 path), never submit qty 0."""
    r = svc.submit(_cand(sym="NQ", entry=20_000.0, stop=19_000.0, tp2=21_000.0), "autotrade")
    assert r.action == "rejected" and r.qty == 0, r.reason
