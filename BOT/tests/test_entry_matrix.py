"""ENTRY PROFITABILITY MATRIX TESTS (remediation Phase E, TE.1-TE.4).

The matrix answers "has this EXACT entry type made net money?" — deterministically, one evidence
type at a time, with honest small-sample handling; removed groups can neither fire nor submit.
"""
from __future__ import annotations

import json

import pytest

pd = pytest.importorskip("pandas")

from bot.ml import entry_matrix as EM  # noqa: E402


def _seed_rows(monkeypatch, rows, lineage="test"):
    monkeypatch.setitem(EM._LOADERS, "shadow", lambda: (rows, lineage))


def _row(sym="QQQ", side="long", fam="breakout", grade="A", r=0.5, day="2026-01-05"):
    return {"symbol": sym, "side": side, "session": "rth", "family": fam,
            "grade": grade, "regime": "A", "net_r": r, "day": day}


def test_te1_matrix_is_deterministic(monkeypatch):
    rows = [_row(r=((i % 3) - 1) * 0.8, day=f"2026-01-{5 + i % 20:02d}") for i in range(80)]
    _seed_rows(monkeypatch, rows)
    a, b = EM.matrix("shadow"), EM.matrix("shadow")
    assert a["cells"] == b["cells"], "same journal must produce byte-identical cells (TE.1)"
    assert a["cells"][0]["n"] == 80


def test_te2_mixed_evidence_is_refused():
    for bad in ("all", "backtest,shadow", "", "everything"):
        with pytest.raises(ValueError):
            EM.matrix(bad)


def test_te4_under_sample_cells_are_not_verdicts(monkeypatch):
    rows = [_row(r=-1.0, day=f"2026-01-{5 + i:02d}") for i in range(9)]   # 9 losers only
    _seed_rows(monkeypatch, rows)
    c = EM.matrix("shadow")["cells"][0]
    assert c["verdict"] == "INSUFFICIENT SAMPLE" and "exp_R" not in c, (
        f"a 9-trade cell must not look like a -1R verdict (TE.4): {c}")


def test_te3_removed_group_cannot_fire_or_submit(tmp_path, monkeypatch):
    from bot.strategy import removals as RM
    monkeypatch.setattr(RM, "FILE", tmp_path / "entry_removals.json")
    RM.adopt({"symbol": "ES", "family": "orb_stack", "reason": "test removal",
              "evidence": "cohort-test link"})
    assert RM.is_removed("ES", "orb_stack", "long", "rth"), "adopted removal must match"
    assert RM.is_removed("es", "orb_stack") is not None, "matching is case-insensitive"
    assert RM.is_removed("QQQ", "orb_stack") is None, "other symbols unaffected"

    # the service refuses the removed group before the broker is ever consulted
    from bot.contracts import TradeCandidate
    from bot.execution.service import ExecutionService

    class _B:
        is_paper = True

        def account(self):
            raise AssertionError("a removed group must be rejected BEFORE any broker call")

        def positions(self):
            raise AssertionError("no broker calls for removed groups")

        def submit(self, o):
            raise AssertionError("no broker calls for removed groups")

        def cancel(self, o):
            raise AssertionError("no broker calls for removed groups")

    monkeypatch.setattr("bot.approval.paper_approved", lambda v: True)
    svc = ExecutionService(_B(), db_path=tmp_path / "exec.db")
    c = TradeCandidate(symbol="ES", side="long", timeframe="5m", setup="orb_stack",
                       entry=100.0, stop=99.0, tp2=104.0, strategy_version="v")
    r = svc.submit(c, "autotrade", session="rth")
    assert r.action == "rejected" and "REMOVED" in r.reason, r.reason


def test_te3b_removal_without_evidence_refused(tmp_path, monkeypatch):
    from bot.strategy import removals as RM
    monkeypatch.setattr(RM, "FILE", tmp_path / "entry_removals.json")
    with pytest.raises(ValueError):
        RM.adopt({"symbol": "NQ", "reason": "gut feeling"})      # no evidence link


def test_te4b_removed_cells_stay_visible(monkeypatch, tmp_path):
    from bot.strategy import removals as RM
    monkeypatch.setattr(RM, "FILE", tmp_path / "entry_removals.json")
    RM.adopt({"symbol": "QQQ", "family": "breakout", "reason": "test",
              "evidence": "link"})
    rows = [_row(r=0.4, day=f"2026-01-{5 + i % 20:02d}") for i in range(40)]
    _seed_rows(monkeypatch, rows)
    c = EM.matrix("shadow")["cells"][0]
    assert c.get("removed"), "REMOVED groups stay visible in the matrix with their evidence"
    assert c["n"] == 40, "…and their shadow data keeps accruing (removed != deleted)"
