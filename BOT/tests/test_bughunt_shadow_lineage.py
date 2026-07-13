"""BUG HUNT (3rd pass, 2026-07-13) — shadow-book lineage must not pollute the canonical matrix.

The audit flagged 'shadow and paper loaders do not isolate strategy versions'; landing the RTH5F
shadow books makes it concrete: `entry_matrix._rows_shadow` selects EVERY resolved tracker
decision with no family/version filter, so rth5f (and worker-/trail-/options-native-) rows would
blend into the CANONICAL shadow evidence cells the moment they resolve. The ML dataset already
has this lineage separation (dataset.py feat-notna + version-pure + family-prefix exclusion);
the matrix shadow loader must apply the same principle."""
from __future__ import annotations

import json
import sqlite3

import pytest

pd = pytest.importorskip("pandas")


def _seed(db, cid, family, version, sym="NQ"):
    con = sqlite3.connect(str(db))
    con.execute("INSERT INTO decisions(candidate_id, symbol, side, family, session, entry, stop,"
                " tp1, tp2, taken, outcome, result_r, signal_at, decided_at, json, strategy_version,"
                " state) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                (cid, sym, "long", family, "rth", 100.0, 99.0, 101.5, 104.0, 1,
                 "tp2", 4.0, "2026-07-13T14:35:00+00:00", "2026-07-13T15:00:00+00:00",
                 json.dumps({"tf": "5m"}), version, "shadow"))
    con.commit(); con.close()


def test_matrix_shadow_rows_exclude_shadow_book_lineages(tmp_path, monkeypatch):
    import bot.tracker as T
    monkeypatch.setattr(T, "DB", tmp_path / "hs.db")
    T._con().close()                                       # create schema
    _seed(T.DB, "C-CORE", "breakout", "orb-standard-2026.07.7")
    _seed(T.DB, "C-5F", "rth5f", "rth5f-0.1")
    _seed(T.DB, "C-WORKER", "worker-q", "worker-q-0.1")
    _seed(T.DB, "C-TRAIL", "trail-eq", "trail-eq-0.1")
    from bot.ml.entry_matrix import _rows_shadow
    rows, _lineage = _rows_shadow()
    fams = sorted({r["family"] for r in rows})
    assert "rth5f" not in fams, (
        "the RTH5F shadow book must NEVER enter the canonical matrix shadow evidence "
        f"(got families {fams})")
    assert not any(str(f).startswith(("worker-", "trail-", "options-native-", "emergent-"))
                   for f in fams), f"worker/study lineages must not blend in either (got {fams})"
    assert "breakout" in fams, "the canonical row must still be counted"


def test_prepare_survives_a_frame_without_volume():
    """Same defect class, canonical path (families.prepare had the identical df.get idiom):
    a volume-less frame must prepare with zero volume (gates fail closed), never crash."""
    from bot.strategy import families
    ts = pd.date_range("2026-07-13 09:30", periods=40, freq="5min", tz="America/New_York")
    px = pd.Series(range(40), dtype=float) + 20000
    bars = pd.DataFrame({"ts_et": ts.astype(str), "open": px, "high": px + 5,
                         "low": px - 5, "close": px + 2})
    d = families.prepare(bars, "NQ")                       # must not raise
    assert (d["volume"] == 0).all()
