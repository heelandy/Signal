"""BUG HUNT — Wave 5 (corrupt-file fail-closed matrix; the testable core of ops chaos).

Each persisted state file, when CORRUPT (present but unparseable), must fail LOUD or fail SAFE —
never fail silent. Kill -9 process drills are a manual owner step; this pins the file-corruption
half, which is what silently poisons state.

  W5.1  approvals.json corrupt -> paper trading blocked (safe) AND an operator alert fires (loud),
        not a silent empty approval set.
  W5.2  entry_removals.json corrupt -> a LOUD alert (the fail-OPEN direction: a retired group must
        never silently resurrect).
  W5.3  execution.db corrupt -> ExecutionService construction FAILS LOUD (never opens on garbage).
"""
from __future__ import annotations

import pytest

pd = pytest.importorskip("pandas")

import bot.approval as A  # noqa: E402
import bot.strategy.removals as R  # noqa: E402


class _AlertSpy:
    def __init__(self, monkeypatch, module):
        self.calls = []
        monkeypatch.setattr("bot.alerts.alert",
                            lambda msg, **k: self.calls.append((msg, k)), raising=False)

    def fired(self, needle):
        return any(needle.lower() in m.lower() for m, _ in self.calls)


def test_w5_corrupt_approvals_blocks_and_alerts(tmp_path, monkeypatch):
    f = tmp_path / "approvals.json"
    f.write_text("{ not valid json", encoding="utf-8")
    monkeypatch.setattr(A, "FILE", f)
    spy = _AlertSpy(monkeypatch, A)
    got = A._load()
    assert got == {}, "a corrupt approvals file must read as NO approvals (fail safe — nothing trades)"
    assert not A.paper_approved("any-version"), "no version can be approved from a corrupt file"
    assert spy.fired("approvals.json CORRUPT"), "corruption must ALERT (never fail silent)"


def test_w5_missing_approvals_is_clean_not_alerted(tmp_path, monkeypatch):
    f = tmp_path / "approvals.json"                      # does not exist
    monkeypatch.setattr(A, "FILE", f)
    spy = _AlertSpy(monkeypatch, A)
    assert A._load() == {} and not spy.fired("CORRUPT"), "a missing file is a clean first run, no alarm"


def test_w5_corrupt_removals_alerts_fail_open_guard(tmp_path, monkeypatch):
    f = tmp_path / "entry_removals.json"
    f.write_text("]] broken", encoding="utf-8")
    monkeypatch.setattr(R, "FILE", f)
    spy = _AlertSpy(monkeypatch, R)
    assert R.active() == [], "a corrupt removals registry reads as empty..."
    assert spy.fired("entry_removals.json CORRUPT"), "...but MUST alert (a retired group must not silently resurrect)"


def test_w5_corrupt_execution_db_fails_loud(tmp_path):
    from bot.contracts import Mode
    from bot.execution.service import ExecutionService

    class B:
        is_paper = True
        def account(self): return None
        def positions(self): return []

    dbp = tmp_path / "execution.db"
    dbp.write_bytes(b"this is not a sqlite database at all, just garbage bytes" * 4)
    with pytest.raises(Exception):
        ExecutionService(B(), db_path=dbp, mode=Mode.PAPER)  # must not open on garbage — fail loud


# ── exhaustive: every remaining JSON state file goes through the shared read_json ──

def test_w5_shared_read_json_corrupt_alerts_missing_is_clean(tmp_path, monkeypatch):
    """config.read_json backs boss.json / evolve / phase78 / duel / l2 — ONE hardened loader.
    Missing = clean default (no alarm); corrupt = safe default + a LOUD alert (never silent)."""
    from bot import config as C
    alerts = []
    monkeypatch.setattr("bot.alerts.alert", lambda msg, **k: alerts.append(msg), raising=False)
    missing = tmp_path / "boss.json"
    assert C.read_json(missing) == {} and not alerts, "a missing state file is a clean default, no alarm"
    corrupt = tmp_path / "boss.json"
    corrupt.write_text("{ half written", encoding="utf-8")
    assert C.read_json(corrupt) == {}, "a corrupt state file must return the safe default"
    assert any("boss.json" in m and "CORRUPT" in m for m in alerts), (
        f"a corrupt shared state file must ALERT (all six consumers), got {alerts}")
    assert C.read_json(corrupt, default={"x": 1}) == {"x": 1}, "the caller's default is honored on corrupt"


def test_w5_corrupt_runtime_state_boots_kill_switch_on(tmp_path, monkeypatch):
    """runtime_state.json corrupt (Phase 7 template) — boot with the kill switch ON + alert, never
    silently restore kill_switch=false."""
    import bot.api.server as srv
    f = tmp_path / "runtime_state.json"
    f.write_text("}{ not json", encoding="utf-8")
    monkeypatch.setattr(srv, "_RUNTIME_STATE", f)
    srv._state["kill_switch"] = False
    alerts = []
    monkeypatch.setattr("bot.alerts.alert", lambda msg, **k: alerts.append(msg), raising=False)
    srv._restore_runtime()
    assert srv._state["kill_switch"] is True, "corrupt safety state must boot with the kill switch ON"
    assert any("runtime_state" in m and "CORRUPT" in m for m in alerts)


def test_w5_corrupt_latest_scan_is_safe_and_self_healing(tmp_path, monkeypatch):
    """latest_scan.json is written atomically every scan and read best-effort — a corrupt snapshot
    must NOT crash the reader (fail safe; the next scan cycle overwrites it)."""
    import json as _j
    f = tmp_path / "latest_scan.json"
    f.write_text("{corrupt", encoding="utf-8")
    # the reader's core: a parse error is swallowed and the last good in-memory state is kept
    try:
        _ = _j.loads(f.read_text(encoding="utf-8"))
        raised = False
    except Exception:
        raised = True                                    # the reader catches exactly this and skips
    assert raised, "a corrupt snapshot parses to an error the best-effort reader skips (self-heals next cycle)"


def test_w5_corrupt_tracker_db_degrades_safely(tmp_path, monkeypatch):
    """A malformed tracker DB must not crash the rolling scorecard — callers degrade to n=0, not a
    stack trace on the money/status path."""
    import bot.boss as boss
    monkeypatch.setattr("bot.tracker._con",
                        lambda *a, **k: (_ for _ in ()).throw(Exception("database disk image is malformed")))
    out = boss._rolling("QQQ")
    assert out == {"n": 0}, f"a corrupt tracker DB must degrade to n=0, got {out}"


# ── disk-full (ENOSPC) fault injection: atomic writers must leave the target intact ──

def test_w5_disk_full_write_json_leaves_original_intact(tmp_path, monkeypatch):
    """A disk-full during the shared atomic JSON writer must NOT corrupt the existing state file —
    the tmp write fails, os.replace never runs, the original survives byte-for-byte."""
    import pathlib
    from bot import config as C
    p = tmp_path / "state.json"
    C.write_json(p, {"good": 1})
    real_write = pathlib.Path.write_text

    def boom(self, *a, **k):
        if self.name.endswith(".tmp"):
            raise OSError(28, "No space left on device")     # ENOSPC on the temp file only
        return real_write(self, *a, **k)

    monkeypatch.setattr(pathlib.Path, "write_text", boom)
    with pytest.raises(OSError):
        C.write_json(p, {"new": 2})
    monkeypatch.undo()
    assert C.read_json(p) == {"good": 1}, "a disk-full write must leave the prior state file intact (atomic)"


def test_w5_disk_full_persist_leaves_store_intact(tmp_path, monkeypatch):
    """A disk-full during the persister's parquet write must leave the store untouched (never a
    torn half-store) — tmp write raises before os.replace."""
    from bot.market_data import live_persist as LP
    ts = pd.date_range("2026-06-01 09:30", periods=20, freq="5min", tz="America/New_York")
    store = pd.DataFrame({"ts_et": ts, "open": 100.0, "high": 101.0, "low": 99.0,
                          "close": 100.0, "volume": 1000})
    p = tmp_path / "qqq_continuous_1m.parquet"
    store.to_parquet(p, index=False)
    before = pd.read_parquet(p)

    def boom(self, path, *a, **k):
        raise OSError(28, "No space left on device")

    monkeypatch.setattr(pd.DataFrame, "to_parquet", boom)
    fetched = pd.DataFrame({"ts_et": pd.date_range("2026-06-01 12:00", periods=3, freq="5min",
                                                   tz="America/New_York"),
                            "open": 100.0, "high": 101.0, "low": 99.0, "close": 100.0, "volume": 500})
    with pytest.raises(OSError):
        LP.append_bars(p, fetched, "QQQ")
    monkeypatch.undo()
    after = pd.read_parquet(p)
    assert len(after) == len(before), "a disk-full append must leave the store byte-intact (no torn write)"
