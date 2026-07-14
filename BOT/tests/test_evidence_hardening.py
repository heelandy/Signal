"""EVIDENCE HARDENING (completion-order step 3, 2026-07-14).

(a) The evidence fingerprint hashed only count/min-ts/max-ts/volume-sum — HISTORICAL PRICES COULD
CHANGE WITHOUT MOVING THE FINGERPRINT (the audit's exact words). It must be row-content-sensitive
while staying append-stable (bars after the cutoff never move it).
(b) approve(paper/live) built the manifest best-effort — a silent construction failure still
produced an approval with no manifest. Required stages now FAIL CLOSED (override records the
error forever, like every other override)."""
from __future__ import annotations

import sys

import pytest

duckdb = pytest.importorskip("duckdb")

sys.path.insert(0, r"C:\Users\heela\prediction\pipeline")
import hs_data_qa as QA  # noqa: E402


def _store(rows):
    con = duckdb.connect()
    con.execute("CREATE TABLE bars(sym VARCHAR, tf VARCHAR, session VARCHAR, ts TIMESTAMP, "
                "open DOUBLE, high DOUBLE, low DOUBLE, close DOUBLE, volume DOUBLE)")
    con.executemany("INSERT INTO bars VALUES(?,?,?,?,?,?,?,?,?)", rows)
    return con


def _rows(closes, day="2026-07-0", vol=100.0):
    return [("QQQ", "5m", "rth", f"{day}{i+1} 10:00:00", c, c + 1, c - 1, c, vol)
            for i, c in enumerate(closes)]


def test_price_mutation_moves_the_fingerprint():
    """Same count, same ts span, same total volume — ONE close changed => new fingerprint."""
    a = _store(_rows([100.0, 101.0, 102.0]))
    b = _store(_rows([100.0, 999.0, 102.0]))       # one mutated price
    fa = QA.evidence_fingerprint(a, ["QQQ"], "5m", "rth", "2026-07-10")
    fb = QA.evidence_fingerprint(b, ["QQQ"], "5m", "rth", "2026-07-10")
    assert fa != fb, ("a price-only mutation MUST move the evidence fingerprint — "
                      "count/span/volume-sum digests cannot see it")


def test_append_after_cutoff_never_moves_it():
    a = _store(_rows([100.0, 101.0, 102.0]))
    b = _store(_rows([100.0, 101.0, 102.0]) +
               [("QQQ", "5m", "rth", "2026-07-13 10:00:00", 200.0, 201.0, 199.0, 200.0, 500.0)])
    fa = QA.evidence_fingerprint(a, ["QQQ"], "5m", "rth", "2026-07-10")
    fb = QA.evidence_fingerprint(b, ["QQQ"], "5m", "rth", "2026-07-10")
    assert fa == fb, "an operational append AFTER the cutoff must never re-identify the evidence"


def test_approve_fails_closed_when_manifest_construction_fails(tmp_path, monkeypatch):
    from bot import approval
    monkeypatch.setattr(approval, "FILE", tmp_path / "approvals.json")
    monkeypatch.setattr(approval, "evidence",
                        lambda v: {"data_qa_traded_ok": True, "ab_strategy_version_match": True})
    import bot.evidence_manifest as EM
    monkeypatch.setattr(EM, "build_manifest",
                        lambda *a, **k: (_ for _ in ()).throw(OSError("reports unreadable")))
    approval.approve("vX", "research"); approval.approve("vX", "replay")
    with pytest.raises(ValueError, match="manifest"):
        approval.approve("vX", "paper")
    # override records the failure FOREVER instead of silently approving without a manifest
    rec = approval.approve("vX", "paper", override=True)
    assert rec.get("override") is True and "manifest_error" in rec, rec
