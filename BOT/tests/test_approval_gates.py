"""EVIDENCE + APPROVAL ENFORCEMENT TESTS (remediation Phase 6, T6.1-T6.4 — RED-first).

The audit: phase-8 execution quality read journal fields that don't exist (permanently n=0);
approvals enforced stage ORDER but treated evidence as informational; the serving path accepted a
champion labeled for an older strategy version; model promotion checked nothing.
"""
from __future__ import annotations

import json
from types import SimpleNamespace

import pytest

pd = pytest.importorskip("pandas")


# ── T6.1 phase-8 execution quality reads REAL fills ─────────────────────────

def test_t61_execution_quality_reads_service_fills(tmp_path):
    from bot.execution.service import ExecutionService
    from bot import phase78

    class _B:
        is_paper = True

        def account(self):
            from bot.brokers.base import AccountInfo
            return AccountInfo(equity=1.0, buying_power=1.0, cash=1.0,
                               open_position_count=0, is_paper=True)

        def positions(self):
            return []

        def submit(self, o):
            raise NotImplementedError

        def cancel(self, o):
            raise NotImplementedError

    db = tmp_path / "exec.db"
    svc = ExecutionService(_B(), db_path=db)
    eq0 = phase78.execution_quality(db_path=db)
    assert eq0["n"] == 0 and eq0["ok"] is None, "no fills must read 'insufficient', never fake"
    svc.db.execute(
        "INSERT INTO exec_orders(order_id, correlation_id, idem_key, source, symbol, side, qty, "
        "planned_entry, stop, tp, strategy_version, state, created_at, updated_at, created_epoch) "
        "VALUES('o1','c','k1','autotrade','QQQ','long',1,100.00,99,104,'v','FILLED','t','t',0)")
    svc.db.execute("INSERT INTO exec_fills VALUES('f1','o1','B1','QQQ','long',1,100.008,'t')")
    svc.db.commit()
    eq = phase78.execution_quality(db_path=db)
    assert eq["n"] == 1, ("execution quality must read the Phase-5 paper-execution record "
                          f"(broker fills), got {eq}")
    assert eq["ok"] is True and eq["avg_slip_usd"] == pytest.approx(0.008)


# ── T6.2 approvals require green evidence (or a RECORDED override) ───────────

@pytest.fixture()
def appr(tmp_path, monkeypatch):
    from bot import approval
    monkeypatch.setattr(approval, "FILE", tmp_path / "approvals.json")
    monkeypatch.setattr(approval, "REPORTS", tmp_path / "reports")
    (tmp_path / "reports").mkdir()
    approval.approve("v1", "research")
    approval.approve("v1", "replay")
    return approval, tmp_path / "reports"


def _write_reports(reports, qa_ok=True, ab_version="v1", fingerprint="fp-1", evidence_fp="efp-1"):
    (reports / "dataqa.json").write_text(json.dumps(
        {"symbols": {"QQQ": {"ok": qa_ok, "issues": [] if qa_ok else ["STALE: old"]},
                     "SPY": {"ok": qa_ok, "issues": []}},   # traded book = QQQ+SPY (2026-07-12)
         "all_ok": qa_ok, "store_fingerprint": fingerprint,
         "evidence_fingerprint": evidence_fp, "evidence_cutoff": "2026-07-10"}), encoding="utf-8")
    (reports / "ab_entry_standard.json").write_text(json.dumps(
        {"config": {"strategy_version": ab_version}}), encoding="utf-8")


def test_t62_red_evidence_blocks_paper_approval(appr):
    approval, reports = appr
    _write_reports(reports, qa_ok=False)
    with pytest.raises(Exception) as e:
        approval.approve("v1", "paper")
    assert "data_qa" in str(e.value).lower(), (
        "paper approval with red QA must be REFUSED — evidence is a gate, not information")


def test_t62b_override_is_recorded_forever(appr):
    approval, reports = appr
    _write_reports(reports, qa_ok=False)
    rec = approval.approve("v1", "paper", override=True, notes="risk accepted")
    assert rec.get("override") is True, "an override must be visible in the record forever"
    assert rec.get("evidence"), "the evidence snapshot must ride with the approval record"


def test_t62c_green_evidence_approves_and_snapshots(appr):
    approval, reports = appr
    _write_reports(reports, qa_ok=True, ab_version="v1", fingerprint="fp-9", evidence_fp="efp-9")
    rec = approval.approve("v1", "paper")
    assert not rec.get("override")
    assert rec["evidence"]["store_fingerprint"] == "fp-9"
    assert rec["evidence"]["evidence_fingerprint"] == "efp-9", (
        "T1: the approval must pin the FROZEN evidence fingerprint it was granted against")


def test_t62d_evidence_fingerprint_drift_marks_approval_stale(appr):
    """A change to the FROZEN evidence fingerprint (historical evidence actually changed) must mark
    downstream approvals STALE."""
    approval, reports = appr
    _write_reports(reports, qa_ok=True, ab_version="v1", fingerprint="fp-9", evidence_fp="efp-9")
    approval.approve("v1", "paper")
    assert approval.paper_approved("v1")
    _write_reports(reports, qa_ok=True, ab_version="v1", fingerprint="fp-9", evidence_fp="efp-CHANGED")
    st = approval.status("v1")
    assert st.get("stale"), "an EVIDENCE-fingerprint change must mark downstream approvals STALE"
    assert not approval.paper_approved("v1"), (
        "auto-invalidation: arm checks must refuse a stale approval until re-evidenced")


def test_t1_daily_bar_append_does_not_invalidate_approval(appr):
    """SIGNAL-CERTIFICATE T1 (keystone): the live-bar persister appends bars daily, changing the
    STORE fingerprint — but not the FROZEN evidence fingerprint. A fresh approval must stay valid
    across those appends (the pre-T1 bug invalidated it every EOD)."""
    approval, reports = appr
    _write_reports(reports, qa_ok=True, fingerprint="store-day1", evidence_fp="efp-frozen")
    approval.approve("v1", "paper")
    assert approval.paper_approved("v1")
    # EOD append: store fingerprint moves, evidence (data <= cutoff) is unchanged
    _write_reports(reports, qa_ok=True, fingerprint="store-day2-appended", evidence_fp="efp-frozen")
    assert not approval.status("v1").get("stale"), (
        "a daily append (store fp changes, evidence fp frozen) must NOT invalidate the approval")
    assert approval.paper_approved("v1")


# ── T6.3 champion strategy-version guard at serving time ────────────────────

def test_t63_mismatched_champion_never_serves(monkeypatch):
    from bot.ml import pipeline
    model = SimpleNamespace(predict_proba=lambda x: [0.93])
    meta = SimpleNamespace(strategy_version="orb-standard-2026.07.4", features=None)
    monkeypatch.setattr(pipeline._reg, "champion", lambda name: (model, meta))
    monkeypatch.setattr(pipeline, "_schema_ok", lambda m: True)
    monkeypatch.setattr(pipeline, "to_vector", lambda f: __import__("numpy").zeros(4))
    c = SimpleNamespace(symbol="QQQ", side=SimpleNamespace(value="long"), confidence=None)
    p = pipeline.predict_candidate(c, feats={"any": 1.0})
    assert p == pipeline._PRIOR, (
        f"a champion labeled 07.4 must NOT serve under the current strategy — got {p} "
        f"(silent version-crossed serving is the audited defect)")


def test_t63b_similarity_guard(monkeypatch):
    from bot.nn import similarity
    model = SimpleNamespace(assign=lambda x: [0], stats={0: {"win_rate": 0.9, "avg_r": 1.0}})
    meta = SimpleNamespace(strategy_version="orb-standard-2026.07.4")
    monkeypatch.setattr(similarity._reg, "champion", lambda name: (model, meta))
    import numpy as np
    assert similarity.similarity_score(np.zeros((64, 3))) is None, (
        "the similarity champion is 07.4-labeled — serving it under 07.7 crosses versions")


# ── T6.4 promotion requires gates_passed ─────────────────────────────────────

def test_t64_promotion_without_gates_refused(tmp_path):
    from bot.ml.registry import ModelRegistry
    reg = ModelRegistry(root=tmp_path)
    reg.register(object(), "m", "v-fail", {"gates_passed": False})
    reg.register(object(), "m", "v-pass", {"gates_passed": True})
    assert reg.promote("m", "v-fail") is False, (
        "promoting a model whose gates FAILED must be refused — manual promotion is a decision, "
        "not a bypass")
    assert reg.promote("m", "v-pass") is True
