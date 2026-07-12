"""OPERATOR-CONSOLE TESTS (Phase U steps 0–8, 2026-07-12).

The readiness endpoint is THE single truth source (TU.1: it can never return a bare green while
a blocking gate is red); the exec/risk endpoints serve real store shapes; both pages carry every
view container and every honest state label the acceptance criteria name.
"""
from __future__ import annotations

import os

import pytest

pd = pytest.importorskip("pandas")

from fastapi.testclient import TestClient  # noqa: E402

import bot.api.server as srv  # noqa: E402

STATIC = os.path.join(os.path.dirname(__file__), "..", "bot", "api", "static")


@pytest.fixture()
def client():
    srv._state["kill_switch"] = False
    srv._ready_cache.update(ts=0.0, out=None)          # never serve a stale verdict to a test
    yield TestClient(srv.app)
    srv._state["kill_switch"] = False
    srv._ready_cache.update(ts=0.0, out=None)


def test_tu1_readiness_enumerates_gates_never_bare_green(client):
    r = client.get("/api/readiness").json()
    assert r["overall"] in ("OK", "BLOCKED")
    assert r["gates"] and all({"name", "ok", "reason", "blocking"} <= set(g) for g in r["gates"])
    red = [g for g in r["gates"] if g["blocking"] and g["ok"] is not True]
    if red:
        assert r["overall"] == "BLOCKED" and r["blocking"], (
            "a red blocking gate MUST force BLOCKED — there is no bare-green code path")
    # the QA gate is traded-book scoped (2026-07-12); its verdict tracks the store, so assert
    # CONSISTENCY, not a snapshot: a red gate must appear in blocking; all-green must be OK
    names = {g["name"]: g for g in r["gates"]}
    assert "data QA (traded book)" in names
    dq = names["data QA (traded book)"]
    if dq["ok"] is not True:
        assert r["overall"] == "BLOCKED" and "data QA (traded book)" in r["blocking"]
    elif not red:
        assert r["overall"] == "OK"


def test_tu1b_kill_switch_flips_the_verdict(client):
    srv._state["kill_switch"] = True
    srv._ready_cache.update(ts=0.0, out=None)
    r = client.get("/api/readiness").json()
    ks = next(g for g in r["gates"] if g["name"] == "kill switch")
    assert ks["ok"] is False and "ARMED" in ks["reason"] and "kill switch" in r["blocking"]


def test_exec_orders_shape_and_qty_breakdown(client, tmp_path, monkeypatch):
    from bot.contracts import Mode
    from bot.execution.service import ExecutionService

    class _B:
        is_paper = True

        def account(self):
            from bot.brokers.base import AccountInfo
            return AccountInfo(equity=25_000.0, buying_power=1.0, cash=1.0,
                               open_position_count=0, is_paper=True)

        def positions(self):
            return []

        def submit(self, o):
            from bot.contracts import OrderEvent, OrderState
            return OrderEvent(order_id=o.order_id, state=OrderState.SUBMITTED, broker_order_id="B1")

        def cancel(self, o):
            raise NotImplementedError

        def recent_orders(self):
            return []

    svc = ExecutionService(_B(), db_path=tmp_path / "e.db", mode=Mode.PAPER)
    monkeypatch.setattr(srv, "_exec_service", lambda: svc)
    monkeypatch.setattr("bot.approval.paper_approved", lambda v: True)
    from bot.contracts import TradeCandidate
    c = TradeCandidate(symbol="QQQ", side="long", timeframe="5m", setup="orb_stack",
                       entry=100.0, stop=99.0, tp2=104.0, strategy_version="v")
    assert svc.submit(c, "manual").action == "submitted"
    svc.db.execute("INSERT INTO exec_fills VALUES('f1','%s','B1','QQQ','long',3,100.01,'t')"
                   % svc.db.execute("SELECT order_id FROM exec_orders").fetchone()[0])
    svc.db.commit()
    d = client.get("/api/exec/orders").json()
    o = d["orders"][0]
    assert {"timeline", "fills", "qty_breakdown", "correlation_id"} <= set(o)
    qb = o["qty_breakdown"]
    assert qb["filled"] == 3 and qb["remaining"] == qb["requested"] - 3
    f = client.get("/api/exec/fills").json()
    assert f["fills"] and f["open_book"].get("QQQ", {}).get("net") == 3


def test_risk_state_blocks_on_unprovable_account(client, monkeypatch):
    class _Dead:
        def account_truth(self, **kw):
            from bot.execution.service import AccountUnproven
            raise AccountUnproven("broker unreachable: test")
    monkeypatch.setattr(srv, "_exec_service", lambda: _Dead())
    r = client.get("/api/risk/state").json()
    assert r["blocked"] is True and "UNPROVEN" in r["reason"], (
        "an unprovable account must render BLOCKED — never zeros (rules 2/5/6)")


def test_removals_and_incidents_shapes(client):
    rm = client.get("/api/removals").json()
    assert "active" in rm and "nominations" in rm
    inc = client.get("/api/incidents").json()
    assert {"crashes", "watchdog", "last_backup", "log_bytes", "gate1"} <= set(inc)
    assert inc["gate1"]["of"] == 7


VIEW_IDS = {"dashboard.html": ("u-entry", "u-orders", "u-risk", "u-recon", "u-mission"),
            "training.html": ("g-lab", "g-evidence", "g-models", "g-datatrust", "g-incidents")}
STATE_LABELS = ("REMOVED", "INVALIDATED", "do not chase", "INFO-ONLY", "UNKNOWN",
                "FIRED", "ALREADY TRADED", "DO NOT ENTER YET", "SUBMISSION STATUS UNKNOWN")


def test_views_and_state_labels_present():
    dash = open(os.path.join(STATIC, "dashboard.html"), encoding="utf-8").read()
    trn = open(os.path.join(STATIC, "training.html"), encoding="utf-8").read()
    for fn, ids in VIEW_IDS.items():
        src = dash if fn == "dashboard.html" else trn
        for i in ids:
            assert f'id="{i}"' in src, f"{fn}: view container #{i} missing"
    for lbl in STATE_LABELS:
        assert lbl in dash, f"Entry Console/Orders must render state {lbl!r}"
    for lbl in ("INSUFFICIENT SAMPLE", "NEVER mixed", "OVERRIDE", "MODEL BLOCKED"):
        assert lbl in trn, f"GOVERN page must render {lbl!r}"
    for src, name in ((dash, "dashboard"), (trn, "training")):
        assert "/api/readiness" in dash and "/api/entry_matrix" in trn
