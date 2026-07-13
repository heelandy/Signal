"""FAIL-CLOSED OPS TESTS (remediation Phase 7, T7.1-T7.4 — RED-first).

The audit: corrupt runtime state silently restored kill_switch=false; /api/health hardcoded
source_healthy=true and derived 'healthy' from the kill switch alone; the watchdog was satisfied
by any HTTP 200; there was no backup, no tested restore.
"""
from __future__ import annotations

import json
import time

import pytest

pd = pytest.importorskip("pandas")


def test_t71_corrupt_runtime_state_boots_kill_switch_on(tmp_path, monkeypatch):
    import bot.api.server as srv
    alerts = []
    monkeypatch.setattr("bot.alerts.alert",
                        lambda msg, level="warn", source="bot": alerts.append((level, msg)))
    p = tmp_path / "runtime_state.json"
    p.write_text('{"kill_switch": fal', encoding="utf-8")     # truncated / corrupt
    monkeypatch.setattr(srv, "_RUNTIME_STATE", p)
    srv._state["kill_switch"] = False
    srv._restore_runtime()
    assert srv._state["kill_switch"] is True, (
        "corrupt safety state must FAIL CLOSED (kill switch ON) — the audited defect silently "
        "restored the unsafe default")
    assert alerts and any("state" in m.lower() or "corrupt" in m.lower() for _, m in alerts), \
        "the operator must be alerted"
    srv._state["kill_switch"] = False                          # leave the module clean


def test_t71b_missing_state_is_a_clean_boot(tmp_path, monkeypatch):
    import bot.api.server as srv
    monkeypatch.setattr(srv, "_RUNTIME_STATE", tmp_path / "nope.json")
    srv._state["kill_switch"] = False
    srv._restore_runtime()                                     # fresh boot: no file, no drama
    assert srv._state["kill_switch"] is False


def test_t72_stale_scan_heartbeat_is_unhealthy(monkeypatch):
    import bot.api.server as srv
    srv._state["kill_switch"] = False
    # HERMETIC: _semantic_health() probes the live paper broker (alpaca_paper defaults True). In CI
    # (no alpaca-py / no creds / no network) that probe raises -> broker="down" -> it would wrongly
    # drag `healthy` to False. Stub it so this test isolates the SCAN-heartbeat + beats logic it
    # actually covers; broker health is exercised by its own tests.
    monkeypatch.setattr(srv, "_paper_broker",
                        lambda: type("B", (), {"is_market_open": lambda self: True})())
    old = pd.Timestamp.now(tz="UTC") - pd.Timedelta(minutes=30)
    monkeypatch.setitem(srv._latest, "ts", old.isoformat())
    h = srv._semantic_health()
    assert h["source_healthy"] is False and h["healthy"] is False, (
        f"a 30-minute-old scan heartbeat must read UNHEALTHY — the audited endpoint hardcoded "
        f"source_healthy=true (got {h})")
    fresh = pd.Timestamp.now(tz="UTC").isoformat()
    monkeypatch.setitem(srv._latest, "ts", fresh)
    monkeypatch.setattr(srv, "_beats", {})
    h2 = srv._semantic_health()
    assert h2["source_healthy"] is True and h2["healthy"] is True, h2


def test_t73_watchdog_field_says_false_while_http_200(monkeypatch):
    """The watchdog consumes /api/live semantically: HTTP 200 + healthy=false must be a
    restart-worthy verdict (the old watchdog was satisfied by ANY response)."""
    from fastapi.testclient import TestClient
    import bot.api.server as srv
    srv._state["kill_switch"] = False
    old = pd.Timestamp.now(tz="UTC") - pd.Timedelta(minutes=30)
    monkeypatch.setitem(srv._latest, "ts", old.isoformat())
    r = TestClient(srv.app).get("/api/live")
    assert r.status_code == 200
    assert r.json()["healthy"] is False, "HTTP up but semantically dead must be visible"


def test_t74_backup_restore_roundtrip(tmp_path):
    from bot import backup
    src = tmp_path / "data"
    src.mkdir()
    (src / "highstrike.db").write_bytes(b"sqlite-bytes")
    (src / "journal.jsonl").write_text('{"a":1}\n', encoding="utf-8")
    (src / "approvals.json").write_text("{}", encoding="utf-8")
    b = backup.backup(src_root=src, dst_root=tmp_path / "backups")
    assert b["files"] >= 3 and b["ok"]
    v = backup.verify(b["path"])
    assert v["ok"], f"backup must verify against its manifest: {v}"
    (src / "journal.jsonl").unlink()                           # simulate loss
    r = backup.restore(b["path"], dst_root=tmp_path / "restored")
    assert r["ok"] and (tmp_path / "restored" / "journal.jsonl").read_text(encoding="utf-8") == '{"a":1}\n'
    from pathlib import Path
    b2 = backup.backup(src_root=src, dst_root=tmp_path / "backups2")
    (Path(b2["path"]) / "highstrike.db").write_bytes(b"tampered")
    assert not backup.verify(b2["path"])["ok"], "a tampered backup must FAIL verification"
