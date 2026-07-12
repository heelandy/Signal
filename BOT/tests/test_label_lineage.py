"""LABEL LINEAGE TESTS (P1.1, 2026-07-11): every journal row carries the rule version that
generated it, immutably; datasets are version-pure (the audited defect back-stamped the CURRENT
version onto every historical row)."""
from __future__ import annotations

import json
import sqlite3

import pytest

pd = pytest.importorskip("pandas")


@pytest.fixture()
def scratch_db(tmp_path, monkeypatch):
    import bot.tracker as T
    monkeypatch.setattr(T, "DB", tmp_path / "hs.db")
    return T


def _sig(**over):
    s = {"candidate_id": "c1", "symbol": "QQQ", "side": "long", "family": "breakout",
         "session": "rth", "entry": 100.0, "stop": 99.0, "tp1": 101.5, "tp2": 104.0,
         "generated_at": "2026-07-11T14:30:00+00:00", "strategy_version": "orb-standard-2026.07.7"}
    s.update(over)
    return s


def test_rows_carry_version_and_state(scratch_db):
    T = scratch_db
    r = T.record_decision(_sig(), taken=True, auto=True)
    assert r["strategy_version"] == "orb-standard-2026.07.7"
    assert r["state"] == "shadow", "auto rows are SHADOW — never confusable with human decisions"
    r2 = T.record_decision(_sig(candidate_id="c2"), taken=False, auto=False)
    assert r2["state"] == "manually_skipped"
    con = sqlite3.connect(str(T.DB))
    got = dict(con.execute("SELECT candidate_id, strategy_version FROM decisions").fetchall())
    con.close()
    assert got == {"c1": "orb-standard-2026.07.7", "c2": "orb-standard-2026.07.7"}


def test_legacy_rows_backfill_from_json_else_unknown(scratch_db):
    T = scratch_db
    con = T._con()                                             # create schema
    con.execute("INSERT INTO decisions(id, candidate_id, symbol, side, entry, stop, taken, "
                "outcome, json, strategy_version, state) VALUES('old1','old1','QQQ','long',"
                "100,99,1,'tp2', ?, NULL, NULL)",
                (json.dumps({"strategy_version": "orb-standard-2026.07.4"}),))
    con.execute("INSERT INTO decisions(id, candidate_id, symbol, side, entry, stop, taken, "
                "outcome, json, strategy_version, state) VALUES('old2','old2','QQQ','long',"
                "100,99,1,'stop', '{}', NULL, NULL)")
    con.commit(); con.close()
    con = T._con()                                             # migration pass backfills NULLs
    rows = dict(con.execute("SELECT id, strategy_version FROM decisions").fetchall())
    states = dict(con.execute("SELECT id, state FROM decisions").fetchall())
    con.close()
    assert rows["old1"] == "orb-standard-2026.07.4", "version recovered from the signal JSON"
    assert rows["old2"] == "unknown", "no recorded version = UNKNOWN, never back-stamped current"
    assert states["old1"] == states["old2"] == "legacy"
