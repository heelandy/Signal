"""EVIDENCE MANIFEST tests (Signal-Certificate T1) — the immutable record every approval pins.

Pins the keystone properties: the manifest binds strategy version + FROZEN evidence fingerprint +
cutoff + report hashes; the manifest hash is STABLE across a daily bar append (store fp moves,
evidence fp frozen) and CHANGES when the frozen evidence changes.
"""
from __future__ import annotations

import json

import pytest

from bot import evidence_manifest as EM


def _write_qa(reports, store_fp="sfp-1", evidence_fp="efp-1"):
    (reports / "dataqa.json").write_text(json.dumps(
        {"symbols": {"QQQ": {"ok": True, "span": ["2010-06-07", "2026-07-10"]},
                     "SPY": {"ok": True, "span": ["2018-05-01", "2026-07-10"]}},
         "all_ok": True, "store_fingerprint": store_fp,
         "evidence_fingerprint": evidence_fp, "evidence_cutoff": "2026-07-10"}), encoding="utf-8")
    (reports / "ab_entry_standard.json").write_text(json.dumps(
        {"config": {"strategy_version": "v1"}, "lineage": "remediation-2026-07-11"}), encoding="utf-8")


@pytest.fixture()
def reports(tmp_path, monkeypatch):
    r = tmp_path / "reports"; r.mkdir()
    monkeypatch.setattr(EM, "REPORTS", r)
    return r


def test_manifest_binds_version_and_frozen_evidence(reports):
    _write_qa(reports, store_fp="sfp-1", evidence_fp="efp-1")
    m = EM.build_manifest("orb-standard-2026.07.7")
    assert m["strategy_version"] == "orb-standard-2026.07.7"
    assert m["evidence_fingerprint"] == "efp-1" and m["evidence_cutoff"] == "2026-07-10"
    assert m["engine_version"] and m["simulator_version"] and m["report_hash"]
    assert m["manifest_hash"] == EM.manifest_hash(m)


def test_manifest_hash_stable_across_daily_append(reports):
    """A daily bar append moves store_fingerprint but not evidence_fingerprint — the manifest hash
    (immutable fields) must be IDENTICAL, so the approval it backs stays valid."""
    _write_qa(reports, store_fp="store-day1", evidence_fp="efp-frozen")
    h1 = EM.build_manifest("v")["manifest_hash"]
    _write_qa(reports, store_fp="store-day2-appended", evidence_fp="efp-frozen")   # EOD append
    h2 = EM.build_manifest("v")["manifest_hash"]
    assert h1 == h2, "the manifest hash must not move on a daily append (frozen evidence unchanged)"


def test_manifest_hash_changes_when_frozen_evidence_changes(reports):
    _write_qa(reports, evidence_fp="efp-1")
    h1 = EM.build_manifest("v")["manifest_hash"]
    _write_qa(reports, evidence_fp="efp-2")                    # historical evidence actually changed
    h2 = EM.build_manifest("v")["manifest_hash"]
    assert h1 != h2, "the manifest hash MUST change when the frozen evidence fingerprint changes"


def test_approval_record_carries_a_manifest(tmp_path, monkeypatch):
    import bot.approval as A
    monkeypatch.setattr(A, "FILE", tmp_path / "approvals.json")
    reports = tmp_path / "reports"; reports.mkdir()
    monkeypatch.setattr(A, "REPORTS", reports)
    monkeypatch.setattr(EM, "REPORTS", reports)
    _write_qa(reports, evidence_fp="efp-9")
    A.approve("v1", "research"); A.approve("v1", "replay")
    rec = A.approve("v1", "paper")
    assert rec.get("manifest", {}).get("evidence_fingerprint") == "efp-9", (
        "a paper approval must carry the immutable evidence manifest")
    assert rec["manifest"]["manifest_hash"]
