"""LABEL-FINAL GATE (completion-order step 10a, 2026-07-14).

T4 wrote the lifecycle (shadow / entry_filled / label_final) but no label builder consumed it —
the audited gap: 'the training-label builder selects every resolved tracker outcome without
checking lifecycle state'. Execution-grade training must use ONLY label_final rows: a
broker-linked entry whose round trip is still OPEN (entry_filled) must never be scored as a
completed trade, no matter what the theoretical first-touch resolver says."""
from __future__ import annotations

import json
import sqlite3

import pytest

pd = pytest.importorskip("pandas")


def _seed(db, cid, state, outcome="tp2", r=4.0):
    con = sqlite3.connect(str(db))
    con.execute("INSERT INTO decisions(candidate_id, symbol, side, family, session, entry, stop,"
                " tp1, tp2, taken, outcome, result_r, signal_at, decided_at, json,"
                " strategy_version, state) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                (cid, "QQQ", "long", "breakout", "rth", 100.0, 99.0, 101.5, 104.0, 1,
                 outcome, r, "2026-07-14T14:35:00+00:00", "2026-07-14T15:00:00+00:00",
                 json.dumps({"tf": "5m"}), "orb-standard-2026.07.8", state))
    con.commit(); con.close()


@pytest.fixture()
def seeded(tmp_path, monkeypatch):
    import bot.tracker as T
    monkeypatch.setattr(T, "DB", tmp_path / "hs.db")
    T._con().close()
    _seed(T.DB, "C-SHADOW", "shadow")               # pure theoretical row (the training lab)
    _seed(T.DB, "C-OPEN", "entry_filled")           # broker-linked, round trip still OPEN
    _seed(T.DB, "C-FINAL", "label_final")           # broker-closed round trip
    return T


def test_execution_labels_are_label_final_only(seeded):
    from bot.ml.live_labels import build_execution_labels
    df = build_execution_labels(save=False)
    assert len(df) == 1, f"execution-grade corpus must be label_final ONLY (got {len(df)} rows)"
    assert df.iloc[0]["state"] == "label_final"


def test_entry_filled_never_scores_as_complete(seeded):
    """The T4 keystone consumed: an open broker round trip is not a completed trade."""
    from bot.ml.live_labels import build_execution_labels
    df = build_execution_labels(save=False)
    assert not (df.get("state") == "entry_filled").any()


def test_live_labels_carry_the_lifecycle_state(seeded):
    from bot.ml.live_labels import build_live_labels
    df = build_live_labels(save=False)
    assert "state" in df.columns, "every label row must carry its lifecycle state"
    assert set(df["state"]) == {"shadow", "entry_filled", "label_final"}
