"""ONE-EXECUTION-PATH TESTS (remediation Phase 5, T5.1-T5.8).

Every order source must pass candidate → real account state → risk → persistent OMS → broker →
fills → reconciliation. The MockBroker below is fully scriptable: accepted/error/timeout
submits, position books, fill streams — so every recovery scenario is exercised without Alpaca.
"""
from __future__ import annotations

import pytest

pd = pytest.importorskip("pandas")

from bot.brokers.base import AccountInfo  # noqa: E402
from bot.contracts import (Mode, OrderEvent, OrderState, PositionPhase, PositionState, Side,
                           TradeCandidate)  # noqa: E402
from bot.execution.service import AccountUnproven, ExecutionService  # noqa: E402


class MockBroker:
    name = "mock"
    is_paper = True

    def __init__(self):
        self.submits: list = []
        self.mode = "accept"                 # accept | error | timeout | timeout_but_accepted
        self.book: list[PositionState] = []
        self.orders: list[dict] = []         # recent_orders() payloads
        self._n = 0

    def account(self):
        return AccountInfo(equity=25_000.0, buying_power=50_000.0, cash=25_000.0,
                           open_position_count=len(self.book), is_paper=True)

    def positions(self):
        return list(self.book)

    def submit(self, order):
        self.submits.append(order)
        self._n += 1
        if self.mode == "error":
            return OrderEvent(order_id=order.order_id, state=OrderState.ERROR, message="rejected by venue")
        if self.mode in ("timeout", "timeout_but_accepted"):
            if self.mode == "timeout_but_accepted":     # the broker DID take it
                self.orders.append({"id": f"B{self._n}", "client_order_id": order.idempotency_key,
                                    "status": "accepted", "filled_qty": 0, "avg_fill_price": 0})
            raise TimeoutError("gateway timeout")
        return OrderEvent(order_id=order.order_id, state=OrderState.SUBMITTED,
                          broker_order_id=f"B{self._n}", message="ok")

    def cancel(self, order_id):
        return OrderEvent(order_id=order_id, state=OrderState.CANCELLED)

    def recent_orders(self):
        return list(self.orders)


def _cand(sym="QQQ", side="long", entry=100.0, stop=99.0, tp2=104.0, version="orb-standard-2026.07.7"):
    return TradeCandidate(symbol=sym, side=side, timeframe="5m", setup="orb_stack",
                          entry=entry, stop=stop, tp2=tp2, strategy_version=version)


@pytest.fixture()
def svc(tmp_path, monkeypatch):
    monkeypatch.setattr("bot.approval.paper_approved", lambda v: True)
    b = MockBroker()
    clock = {"t": 1_000_000.0}
    s = ExecutionService(b, db_path=tmp_path / "exec.db", mode=Mode.PAPER,
                         now=lambda: clock["t"])
    s._clock = clock
    s._mock = b
    return s


def test_t51_risk_rejection_never_reaches_the_broker(svc):
    svc._mock.book = [PositionState(symbol="NQ", phase=PositionPhase.OPEN, qty=1, side=Side.LONG)]
    r = svc.submit(_cand("QQQ"), "autotrade")            # NQ open: max-open fires (then correlation)
    assert r.action == "rejected" and ("OPEN" in r.reason.upper() or
                                       "CORRELATED" in r.reason.upper()), r.reason
    assert not svc._mock.submits, "a risk-rejected order must NEVER reach the broker"


def test_t51b_unprovable_account_state_rejects(svc):
    r = svc.submit(_cand(), "autotrade", feed_healthy=None)
    assert r.action == "rejected" and "UNPROVEN" in r.reason
    svc._mock.account = lambda: (_ for _ in ()).throw(ConnectionError("down"))
    r2 = svc.submit(_cand(entry=101.0), "autotrade")
    assert r2.action == "rejected" and "UNPROVEN" in r2.reason
    assert not svc._mock.submits


def test_t52_broker_error_releases_key_accept_finalizes(svc):
    svc._mock.mode = "error"
    r1 = svc.submit(_cand(), "autotrade")
    assert r1.action == "rejected" and "broker error" in r1.reason
    svc._mock.mode = "accept"
    r2 = svc.submit(_cand(), "autotrade")                # same setup, same day: retry allowed
    assert r2.action == "submitted", "a CLEAN broker error must release the key for retry"
    r3 = svc.submit(_cand(), "autotrade")
    assert r3.action == "duplicate", "an ACCEPTED submit must finalize the key"


def test_t53_same_day_dedup_next_day_allowed(svc):
    assert svc.submit(_cand(), "autotrade").action == "submitted"
    assert svc.submit(_cand(), "autotrade").action == "duplicate"
    svc._clock["t"] += 86_400                            # next trade date
    assert svc.submit(_cand(), "autotrade").action == "submitted", \
        "the idempotency key must carry the trade date — same setup NEXT day is a new order"


def test_t54_timeout_but_accepted_never_duplicates(svc):
    svc._mock.mode = "timeout_but_accepted"
    r = svc.submit(_cand(), "autotrade")
    assert r.action == "rejected" and "UNKNOWN" in r.reason and "do not resubmit" in r.reason
    r2 = svc.submit(_cand(), "autotrade")                # a blind resubmit attempt
    assert r2.action == "duplicate", "SUBMIT_UNKNOWN must keep the key claimed (no duplicate order)"
    svc._mock.mode = "accept"
    rec = svc.recover()                                  # broker truth: it was accepted
    st = svc.db.execute("SELECT state FROM exec_orders").fetchone()[0]
    assert st == "SUBMITTED", f"recovery must adopt the broker-accepted order, got {st} ({rec})"


def test_t54b_crash_before_submit_recovers_to_failed(svc):
    svc.db.execute(
        "INSERT INTO exec_orders(order_id, correlation_id, idem_key, source, symbol, side, qty, "
        "planned_entry, stop, tp, strategy_version, state, created_at, updated_at, created_epoch) "
        "VALUES('dead1','c','k1','autotrade','QQQ','long',1,100,99,104,'v','PENDING_SUBMIT',"
        "'2026-01-01T00:00:00','2026-01-01T00:00:00',999999)")
    svc.db.commit()
    svc.recover()
    st = svc.db.execute("SELECT state FROM exec_orders WHERE order_id='dead1'").fetchone()[0]
    assert st == "FAILED", "crash-before-submit must resolve to FAILED (and release its key)"


def test_t55_reconcile_mismatch_halts_until_clean(svc):
    svc._mock.book = [PositionState(symbol="QQQ", phase=PositionPhase.OPEN, qty=3, side=Side.LONG)]
    rep = svc.reconcile()                                # internal book is empty -> orphan
    assert "MISMATCH" in rep["QQQ"]
    assert svc.halted(), "a reconcile mismatch must halt submissions"
    r = svc.submit(_cand(), "manual")
    assert r.action == "halted"
    svc._mock.book = []                                  # operator flattens at the broker
    rep2 = svc.reconcile()
    assert not svc.halted(), f"a clean reconcile must clear a reconcile-scoped halt ({rep2})"
    assert svc.submit(_cand(), "manual").action == "submitted"


def test_t56_loss_limits_fire_from_real_fills(svc):
    import datetime as dt
    today = dt.date.fromisoformat(svc._trade_date())
    monday = (today - dt.timedelta(days=today.weekday())).isoformat()      # earlier this week
    for i, (side, px) in enumerate((("long", 100.0), ("short", 94.75))):   # -$525 realized
        svc.db.execute("INSERT INTO exec_fills VALUES(?,?,?,?,?,?,?,?)",
                       (f"f{i}", f"o{i}", f"B{i}", "QQQ", side, 100, px, f"{monday}T15:00:00"))
    svc.db.commit()
    acct = svc.account_truth()
    assert acct.weekly_pnl == pytest.approx(-525.0), acct.weekly_pnl
    r = svc.submit(_cand(), "autotrade")     # -525 <= -2% of 25k (weekly); daily too if Mon=today
    assert r.action == "rejected" and "LOSS_LIMIT" in r.reason.upper(), (
        f"the realized-loss gates must fire from REAL fills — the audited defect was these gates "
        f"checking empty defaults; got {r.action}: {r.reason}")


def test_t57_entry_fill_without_working_stop_halts(svc):
    r = svc.submit(_cand(), "autotrade")
    assert r.action == "submitted"
    svc._mock.orders = [{"id": r.broker_order_id, "client_order_id": None, "status": "filled",
                         "filled_qty": 1, "avg_fill_price": 100.1,
                         "legs": [{"status": "rejected"}, {"status": "canceled"}]}]
    svc.poll_fills()
    assert svc.halted() and "bracket" in svc.halted().lower(), (
        "an entry fill with no working protective leg must halt submissions (CRITICAL)")


def test_t58_stale_order_flips_to_investigation(svc):
    r = svc.submit(_cand(), "autotrade")
    assert r.action == "submitted"
    svc._clock["t"] += ExecutionService.STALE_SEC + 1
    flagged = svc.staleness_sweep()
    st = svc.db.execute("SELECT state FROM exec_orders WHERE order_id=?",
                        (r.order_id,)).fetchone()[0]
    assert flagged and st == "INVESTIGATION_REQUIRED"


def test_t58b_approval_revoked_between_pageload_and_submit(svc, monkeypatch):
    monkeypatch.setattr("bot.approval.paper_approved", lambda v: False)
    r = svc.submit(_cand(), "manual")
    assert r.action == "rejected" and "approval" in r.reason.lower(), (
        "approval must be re-checked at SUBMIT time, not page load")


def test_t5_live_broker_in_paper_mode_refused(tmp_path):
    b = MockBroker()
    b.is_paper = False
    with pytest.raises(ValueError):
        ExecutionService(b, db_path=tmp_path / "x.db", mode=Mode.PAPER)
