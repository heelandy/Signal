"""JOURNAL INTEGRITY GUARD (user 2026-07-07: "make sure data are not corrupt with same-bar
entry/tp/stop — we've been dealing with that since we started").

Locks the corruption classes out permanently:
  1. impossible level geometry never enters the journal (write-time reject);
  2. auto rows without bar identity are refused (the degenerate-key / never-resolving class);
  3. the integrity() auditor flags planted same-lineage duplicates and bad rows;
  4. cross-LINEAGE same-bar rows (5m vs 15m vs worker) are info, NOT corruption.
Pure-function tests — nothing touches the real journal DB.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from bot.tracker import _levels_ok


def _sig(side="long", entry=100.0, stop=99.0, tp1=101.5, tp2=104.0, **kw):
    return {"symbol": "QQQ", "side": side, "entry": entry, "stop": stop,
            "tp1": tp1, "tp2": tp2, **kw}


def test_clean_geometry_passes():
    assert _levels_ok(_sig()) is None
    assert _levels_ok(_sig(side="short", entry=100.0, stop=101.0, tp1=99.0, tp2=96.0)) is None
    # worker tight target: tp1 == tp2 beyond entry is VALID
    assert _levels_ok(_sig(tp1=100.4, tp2=100.4)) is None


def test_impossible_geometry_rejected():
    assert _levels_ok(_sig(stop=100.0)) is not None                 # entry == stop
    assert _levels_ok(_sig(stop=101.0)) is not None                 # long stop above entry
    assert _levels_ok(_sig(tp2=99.0)) is not None                   # long TP below entry
    assert _levels_ok(_sig(side="short", stop=99.0)) is not None    # short stop below entry
    assert _levels_ok(_sig(entry=None)) is not None                 # missing level
    assert _levels_ok(_sig(entry=0.0, stop=-1.0)) is not None       # non-positive


def test_auto_row_requires_bar_identity(monkeypatch):
    # record_decision refuses auto rows without generated_at/signal_at BEFORE touching the DB —
    # prove it by making the DB unreachable: if the guard failed, this would raise.
    import bot.tracker as T
    monkeypatch.setattr(T, "_con", lambda: (_ for _ in ()).throw(AssertionError("DB touched")))
    r = T.record_decision(_sig(candidate_id="x"), taken=True, auto=True)
    assert "error" in r and "bar identity" in r["error"]
    # corrupt geometry is also refused pre-DB
    r2 = T.record_decision(_sig(stop=101.0, generated_at="2026-07-07T14:00:00+00:00",
                                candidate_id="y"), taken=True, auto=True)
    assert "error" in r2 and "integrity" in r2["error"]


def test_integrity_flags_planted_corruption(monkeypatch):
    import bot.tracker as T

    class FakeCon:
        def __init__(self, rows): self._rows = rows
        def execute(self, *_a): return self
        def fetchall(self): return self._rows
        def close(self): pass

    bar = "2026-07-07T14:45:00+00:00"
    rows = [
        ("aaaaaa1", "SPY", "short", "breakout", bar, 746.72, 748.53, 744.01, 739.48, '{"tf":"15m"}'),
        ("bbbbbb2", "SPY", "short", "breakout", bar, 746.72, 748.53, 744.01, 739.48, '{"tf":"15m"}'),  # dup!
        ("cccccc3", "SPY", "short", "worker-s", bar, 745.88, 747.0, 745.51, 745.51, '{"tf":"5m"}'),    # cross-lineage: OK
        ("dddddd4", "QQQ", "long", "breakout", None, 700.0, 700.0, 702.0, 704.0, "{}"),               # no bar id + entry==stop
    ]
    monkeypatch.setattr(T, "_con", lambda: FakeCon(rows))
    rep = T.integrity()
    assert not rep["ok"]
    assert len(rep["dupes"]) == 1 and rep["dupes"][0]["symbol"] == "SPY"
    assert len(rep["bad_levels"]) == 1 and rep["bad_levels"][0]["symbol"] == "QQQ"
    assert rep["missing_bar_identity"] == ["dddddd"]
    # the SPY same-bar 15m-breakout vs 5m-worker pair is reported as INFO, not as a dupe
    assert any("worker-s@5m" in v for v in rep["same_bar_lineages_info"].values() for v in [v])


def test_integrity_clean_when_lineages_differ(monkeypatch):
    import bot.tracker as T

    class FakeCon:
        def __init__(self, rows): self._rows = rows
        def execute(self, *_a): return self
        def fetchall(self): return self._rows
        def close(self): pass

    bar = "2026-07-07T14:45:00+00:00"
    rows = [
        ("a1", "SPY", "short", "breakout", bar, 746.72, 748.53, 744.01, 739.48, '{"tf":"15m"}'),
        ("a2", "SPY", "short", "breakout", bar, 745.88, 747.0, 744.2, 741.4, '{"tf":"5m"}'),
        ("a3", "SPY", "short", "worker-s", bar, 745.88, 747.0, 745.51, 745.51, '{"tf":"5m"}'),
    ]
    monkeypatch.setattr(T, "_con", lambda: FakeCon(rows))
    rep = T.integrity()
    assert rep["ok"] and not rep["dupes"]
