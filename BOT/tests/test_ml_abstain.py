"""ML ABSTAIN HONESTY (completion-order step 10, 2026-07-14).

The audited defect: with no compatible champion, predict_candidate returned the hardcoded prior
0.42 and live.py passed it into decide_ensemble as if it were a model vote — and since
0.42 < 0.45, the NON-EXISTENT model cast a DOWN-vote on every signal. The ensemble cannot
distinguish 'the model says 0.42' from 'there is no model'. Fix: no model / blocked model /
scoring failure => None (ABSTAIN) — absent models simply don't vote (the ensemble's own rule)."""
from __future__ import annotations

from types import SimpleNamespace

import pytest

np = pytest.importorskip("numpy")

from bot.ml import pipeline  # noqa: E402
from bot.ml.ensemble import decide_ensemble  # noqa: E402


def _cand():
    return SimpleNamespace(symbol="QQQ", side=SimpleNamespace(value="long"), confidence=None)


def test_no_champion_abstains_not_prior(monkeypatch):
    monkeypatch.setattr(pipeline._reg, "champion", lambda name: (None, None))
    p = pipeline.predict_candidate(_cand(), feats={"any": 1.0})
    assert p is None, f"no champion must ABSTAIN (None), never surface the prior as a score (got {p})"


def test_version_blocked_champion_abstains(monkeypatch):
    model = SimpleNamespace(predict_proba=lambda x: [0.93])
    meta = SimpleNamespace(strategy_version="orb-standard-2026.07.4", features=None)
    monkeypatch.setattr(pipeline._reg, "champion", lambda name: (model, meta))
    monkeypatch.setattr(pipeline, "_schema_ok", lambda m: True)
    p = pipeline.predict_candidate(_cand(), feats={"any": 1.0})
    assert p is None, "a version-blocked champion must ABSTAIN — not 0.93, not 0.42"


def test_scoring_failure_abstains(monkeypatch):
    """A model that RAISES mid-score is the certificate's 'silent fallback' — abstain, never 0.42."""
    model = SimpleNamespace(predict_proba=lambda x: (_ for _ in ()).throw(ValueError("boom")))
    meta = SimpleNamespace(strategy_version=None, features=None)
    monkeypatch.setattr(pipeline._reg, "champion", lambda name: (model, meta))
    monkeypatch.setattr(pipeline, "_schema_ok", lambda m: True)
    monkeypatch.setattr(pipeline, "version_ok", lambda m: True)
    monkeypatch.setattr(pipeline, "to_vector", lambda f: np.zeros(4))
    p = pipeline.predict_candidate(_cand(), feats={"any": 1.0})
    assert p is None


def test_ensemble_gets_no_phantom_vote():
    """ml_p=None must produce ZERO P(win) reasons — the phantom down-vote class is dead."""
    out = decide_ensemble(True, ml_p=None, heads={}, similarity=None, grade="B")
    assert not any("P(win)" in r for r in out.get("reasons", [])), out
