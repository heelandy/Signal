"""SIGNAL CERTIFICATE tests — the firing guarantee.

Pins the acceptance criteria: zero fire when any gate is false OR unknown (UNKNOWN==BLOCKED),
identical inputs → identical decision, the certificate persists BEFORE any alert, a blocked
candidate produces an auditable BLOCKED cert and NO alert / NO order.
"""
from __future__ import annotations

import pytest

from bot.contracts import RiskDecision, RiskStatus, ReasonCode, Side, TradeCandidate
from bot import signal_certificate as SC


def _cand():
    return TradeCandidate(symbol="QQQ", side="long", timeframe="5m", setup="orb_stack",
                          entry=100.0, stop=99.0, tp2=104.0, strategy_version="orb-standard-2026.07.7",
                          candidate_id="C1")


def _ok_rd():
    return RiskDecision(candidate_id="C1", status=RiskStatus.APPROVED, reason_code=ReasonCode.OK,
                        max_qty=10, max_risk_dollars=250.0)


def _all_green_ctx():
    return {
        "strategy_version": "orb-standard-2026.07.7", "config_hash": "cfg1", "code_commit": "abc",
        "data_qa_ok": True, "data_age_sec": 30, "data_provider": "webull",
        "closed_bar": True, "entry_state": "confirmed",
        "entry_group_id": "PR-EQ-RTH-5M-ORB_C-L-v1", "removed": False,
        "profitability_evidence": "certified",
        "risk_decision": _ok_rd(),
        "broker_reachable": True, "idempotency_ready": True, "halted": None,
        "ml_status": "abstain", "manifest_hash": "m1", "session": "rth",
    }


@pytest.fixture(autouse=True)
def _isolate_cert_db(tmp_path, monkeypatch):
    monkeypatch.setattr(SC, "CERT_DB", tmp_path / "certificates.db")


def test_all_green_certifies_order_ready():
    cert = SC.certify(_cand(), _all_green_ctx())
    assert cert["overall"] == "ORDER_READY" and not cert["blocking"], cert["blocking"]
    assert cert["certificate_hash"] and len(cert["gates"]) == 8


@pytest.mark.parametrize("gate_key,bad", [
    ("data_qa_ok", False), ("closed_bar", False), ("entry_state", "watching"),
    ("profitability_evidence", "unproven"), ("removed", True), ("broker_reachable", False),
    ("ml_status", "stale"),
])
def test_any_false_gate_blocks(gate_key, bad):
    ctx = _all_green_ctx(); ctx[gate_key] = bad
    cert = SC.certify(_cand(), ctx)
    assert cert["overall"] == "BLOCKED" and cert["blocking"], (gate_key, cert["overall"])


@pytest.mark.parametrize("gate_key", ["strategy_version", "config_hash", "data_qa_ok", "data_age_sec",
                                      "closed_bar", "entry_state", "entry_group_id",
                                      "profitability_evidence", "risk_decision", "broker_reachable"])
def test_unknown_is_treated_as_blocked(gate_key):
    """UNKNOWN (a missing/None proof) must block exactly like an explicit failure."""
    ctx = _all_green_ctx(); ctx[gate_key] = None
    cert = SC.certify(_cand(), ctx)
    assert cert["overall"] == "BLOCKED", f"missing {gate_key} must block (UNKNOWN==BLOCKED)"


def test_ml_abstain_does_not_block_but_silent_fallback_does():
    ok = SC.certify(_cand(), {**_all_green_ctx(), "ml_status": "abstain"})
    assert ok["overall"] == "ORDER_READY"
    bad = SC.certify(_cand(), {**_all_green_ctx(), "ml_status": "score", "ml_full_inputs": False})
    assert bad["overall"] == "BLOCKED", "a model scored on incomplete inputs is a silent fallback"


def test_identical_inputs_identical_decision():
    ctx = _all_green_ctx()
    a, b = SC.certify(_cand(), ctx), SC.certify(_cand(), ctx)
    assert [g["ok"] for g in a["gates"]] == [g["ok"] for g in b["gates"]]
    assert a["overall"] == b["overall"]


def test_certify_and_fire_persists_before_alerting_and_only_fires_when_ready():
    alerts, submits = [], []
    cert = SC.certify_and_fire(_cand(), _all_green_ctx(),
                               alert_fn=lambda m: alerts.append(m), submit_fn=lambda c: submits.append(c) or "submitted")
    assert cert["fired"] is True and cert["overall"] == "ORDER_READY"
    assert alerts and cert["certificate_hash"] in alerts[0], "the alert must carry the cert hash"
    assert submits, "an ORDER_READY cert may submit"
    # persisted + audit gate resolved
    import sqlite3
    con = sqlite3.connect(str(SC.CERT_DB))
    assert con.execute("SELECT count(*) FROM certificates").fetchone()[0] == 1
    con.close()
    assert any(g["gate"] == "audit" and g["ok"] for g in cert["gates"])


def test_certify_and_fire_survives_a_submit_that_raises():
    """The one firing door must NOT propagate a submit exception after it has already alerted —
    the caller gets the certificate back with the failure captured, never a crash mid-fire."""
    alerts = []

    def boom(c):
        raise RuntimeError("broker socket died mid-submit")

    cert = SC.certify_and_fire(_cand(), _all_green_ctx(),
                               alert_fn=lambda m: alerts.append(m), submit_fn=boom)
    assert cert["overall"] == "ORDER_READY" and cert["fired"] is True
    assert alerts, "the ORDER READY alert fired before the submit"
    assert "submit_result" in cert and "error" in str(cert["submit_result"]).lower(), (
        "a submit that raises must be captured into the cert, not propagated to the caller")


def test_blocked_candidate_fires_nothing_but_is_audited():
    alerts, submits = [], []
    ctx = _all_green_ctx(); ctx["data_qa_ok"] = False       # a red gate
    cert = SC.certify_and_fire(_cand(), ctx, alert_fn=lambda m: alerts.append(m),
                               submit_fn=lambda c: submits.append(c))
    assert cert["fired"] is False and cert["overall"] == "BLOCKED"
    assert not alerts and not submits, "a blocked candidate must NOT alert or submit"
    import sqlite3
    con = sqlite3.connect(str(SC.CERT_DB))
    assert con.execute("SELECT overall FROM certificates").fetchone()[0] == "BLOCKED", (
        "even a blocked signal is persisted for audit")
    con.close()
