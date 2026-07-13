"""SIGNAL-CERTIFICATE T2 — one canonical entry_group_id across every path.

The audited defect: backtest 'orb@5m', live family 'breakout', execution setup 'orb_stack' all
denote the SAME ORB continuation group but carried different names, so a backtest cell and a paper
cell could never join. These pin the DoD: the same group has the same id across all evidence types.
"""
from __future__ import annotations

from bot.strategy.entry_group import entry_group_id, canonical_pattern


def test_same_group_same_id_across_legacy_names():
    """The three legacy names for the ORB continuation group must resolve IDENTICALLY."""
    ids = {entry_group_id("NQ", "long", "rth", "5m", fam)
           for fam in ("orb@5m", "breakout", "orb_stack", "orb-stack", "orb")}
    assert len(ids) == 1, f"the same group produced different ids: {ids}"
    assert ids.pop() == "PR-FT-RTH-5M-ORB_C-L-v1"


def test_id_reflects_every_dimension():
    assert entry_group_id("QQQ", "short", "rth", "15m", "breakout") == "PR-EQ-RTH-15M-ORB_C-S-v1"
    assert entry_group_id("NQ", "long", "asia", "5m", "orb@5m") == "PR-FT-ASIA-5M-ORB_C-L-v1"
    # side / category / session all move the id
    assert entry_group_id("NQ", "long", "rth", "5m", "orb") != entry_group_id("NQ", "short", "rth", "5m", "orb")
    assert entry_group_id("NQ", "long", "rth", "5m", "orb") != entry_group_id("QQQ", "long", "rth", "5m", "orb")


def test_unknown_family_is_unknown_never_guessed():
    assert canonical_pattern("something_new") == "UNKNOWN"
    assert canonical_pattern(None) == "UNKNOWN"
    gid = entry_group_id("NQ", "long", "rth", "5m", "mystery")
    assert gid.split("-")[4] == "UNKNOWN", "an unrecognized family must map to UNKNOWN, not a guess"


def test_matrix_backtest_rows_carry_group_id(monkeypatch):
    """build_backtest_rows must stamp the canonical id on every row (backtest evidence joins paper)."""
    import bot.ml.entry_matrix as EM
    import pandas as pd

    def fake_load_state(sym, tf, sess):
        d = pd.DataFrame({"ts": []}); d.attrs["sym"] = sym; return d

    def fake_run_backtest(d):
        return pd.DataFrame([{"direction": "long", "net_R": 0.3, "entry_time": "2026-07-13",
                              "regime": "A"}])

    monkeypatch.setattr("bot.strategy.orb_candidates.load_state", fake_load_state)
    monkeypatch.setattr("bot.strategy.orb_candidates.run_backtest", fake_run_backtest)
    monkeypatch.setattr(EM, "BT_ROWS", __import__("pathlib").Path(
        __import__("tempfile").mkdtemp()) / "rows.json")
    EM.build_backtest_rows(runs=(("NQ", "5m"),))
    import json
    rows = json.loads(EM.BT_ROWS.read_text())["rows"]
    assert rows and all(r.get("entry_group_id") for r in rows)
    assert rows[0]["entry_group_id"] == "PR-FT-RTH-5M-ORB_C-L-v1", rows[0]
