"""MATRIX IDENTITY JOIN (completion-order steps 6/7, 2026-07-14).

The audited defect (entry_matrix._rows_paper): each realized round trip was attributed to the
LATEST PRIOR ORDER regardless of symbol — concurrent QQQ and SPY trades cross-attributed P&L,
family and grade. The fix: the exact identity chain candidate_id -> order_id -> fill -> realized
round trip; plus the shadow loader is VERSION-PURE (foreign/legacy rule versions excluded, like
the ML dataset)."""
from __future__ import annotations

import json
import sqlite3

import pytest

pd = pytest.importorskip("pandas")

from bot.brokers.base import AccountInfo  # noqa: E402
from bot.contracts import Mode, OrderEvent, OrderState  # noqa: E402
from bot.execution.service import ExecutionService  # noqa: E402


class _B:
    is_paper = True

    def account(self):
        return AccountInfo(equity=100_000.0, buying_power=1.0, cash=1.0,
                           open_position_count=0, is_paper=True)

    def positions(self): return []

    def submit(self, o):
        return OrderEvent(order_id=o.order_id, state=OrderState.SUBMITTED, broker_order_id="B")

    def recent_orders(self): return []


def _order(svc, oid, sym, family, grade, at):
    svc.db.execute(
        "INSERT INTO exec_orders(order_id, symbol, side, qty, planned_entry, stop, state, "
        "broker_order_id, idem_key, created_at, updated_at, created_epoch, session, family, "
        "grade, candidate_id) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
        (oid, sym, "long", 1, 100.0, 99.0, "FILLED", f"B-{oid}", f"k-{oid}", at, at, 0,
         "rth", family, grade, f"cand-{oid}"))


def _fill(svc, fid, oid, sym, side, price, at):
    svc.db.execute("INSERT INTO exec_fills VALUES(?,?,?,?,?,?,?,?)",
                   (fid, oid, f"B-{oid}", sym, side, 1, price, at))


def test_interleaved_round_trips_attribute_to_their_own_orders(tmp_path, monkeypatch):
    """QQQ wins +1, SPY loses -1, closes interleaved — each must land on ITS OWN symbol/grade."""
    svc = ExecutionService(_B(), db_path=tmp_path / "e.db", mode=Mode.PAPER)
    _order(svc, "OQ", "QQQ", "breakout", "A", "2026-07-14T14:00:00")
    _order(svc, "OS", "SPY", "breakout", "B", "2026-07-14T14:05:00")
    _fill(svc, "f1", "OQ", "QQQ", "long", 100.0, "2026-07-14T14:01:00")
    _fill(svc, "f2", "OS", "SPY", "long", 100.0, "2026-07-14T14:06:00")
    _fill(svc, "f3", "OQ", "QQQ", "short", 101.0, "2026-07-14T14:10:00")   # QQQ +$1
    _fill(svc, "f4", "OS", "SPY", "short", 99.0, "2026-07-14T14:15:00")    # SPY -$1
    svc.db.commit()
    import bot.ml.entry_matrix as EM
    monkeypatch.setattr("bot.execution.service.DB_PATH", tmp_path / "e.db")
    rows, _lineage = EM._rows_paper()
    by_sym = {r["symbol"]: r for r in rows}
    assert set(by_sym) == {"QQQ", "SPY"}, f"both symbols must appear (got {list(by_sym)})"
    assert by_sym["QQQ"]["net_r"] > 0 and by_sym["QQQ"]["grade"] == "A", by_sym["QQQ"]
    assert by_sym["SPY"]["net_r"] < 0 and by_sym["SPY"]["grade"] == "B", (
        f"SPY's LOSS must attribute to SPY grade B — the latest-prior-order join cross-attributed "
        f"it (got {by_sym['SPY']})")


def test_shadow_loader_is_version_pure(tmp_path, monkeypatch):
    import bot.tracker as T
    monkeypatch.setattr(T, "DB", tmp_path / "hs.db")
    T._con().close()
    con = sqlite3.connect(str(T.DB))
    for cid, ver in (("C-NEW", None), ("C-OLD", "orb-standard-2026.07.4"),
                     ("C-UNK", "unknown")):
        from bot.strategy.orb_candidates import STRATEGY_VERSION
        con.execute("INSERT INTO decisions(candidate_id, symbol, side, family, session, entry, "
                    "stop, tp1, tp2, taken, outcome, result_r, signal_at, decided_at, json, "
                    "strategy_version, state) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                    (cid, "QQQ", "long", "breakout", "rth", 100.0, 99.0, 101.5, 104.0, 1,
                     "tp2", 4.0, "2026-07-14T14:35:00+00:00", "2026-07-14T15:00:00+00:00",
                     json.dumps({"tf": "5m"}), ver or STRATEGY_VERSION, "shadow"))
    con.commit(); con.close()
    from bot.ml.entry_matrix import _rows_shadow
    rows, _ = _rows_shadow()
    assert len(rows) == 1, (
        f"shadow evidence must be VERSION-PURE — only the current rule version counts "
        f"(got {len(rows)} rows)")
