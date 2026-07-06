"""LEAKAGE CANARIES (user 2026-07-05: "we need to prevent leakage of data during training").

Two invariants the validation harness must ALWAYS satisfy:
  1. NULL canary — on labels with NO relationship to the features, purged walk-forward must
     report chance-level OOS AUC. If shuffled labels ever score, information is leaking across
     the train/test boundary (fold overlap, imputation on full data, embargo failure...).
  2. SIGNAL canary — on labels the features fully determine, it must score near-perfect
     (the harness can detect real signal; a broken splitter fails this side instead).
"""
from __future__ import annotations

import numpy as np

from bot.ml.models import model_zoo
from bot.ml.validation import purged_walk_forward


def _xy(n=600, f=10, seed=7):
    rng = np.random.default_rng(seed)
    X = rng.normal(size=(n, f))
    X[rng.random((n, f)) < 0.03] = np.nan          # NaNs ride along like the real dataset
    return rng, X


def test_null_canary_shuffled_labels_score_chance():
    rng, X = _xy()
    y = rng.integers(0, 2, len(X))                  # pure noise labels
    zoo = model_zoo()
    name = "lgbm" if "lgbm" in zoo else "logit_np"  # strongest available learner = strictest test
    wf = purged_walk_forward(X, y, zoo[name], n_splits=5, embargo=5)
    assert abs(wf["oos_auc"] - 0.5) < 0.08, (
        f"LEAKAGE: {name} scored OOS AUC {wf['oos_auc']:.3f} on SHUFFLED labels — "
        "train/test information is crossing the purged walk-forward boundary")


def test_signal_canary_real_signal_is_detected():
    rng, X = _xy(seed=11)
    y = (np.nan_to_num(X[:, 0]) + 0.5 * np.nan_to_num(X[:, 3]) > 0).astype(int)
    wf = purged_walk_forward(X, y, model_zoo()["logit_np"], n_splits=5, embargo=5)
    assert wf["oos_auc"] > 0.85, (
        f"harness blind: OOS AUC {wf['oos_auc']:.3f} on a fully learnable target — "
        "the splitter/imputer is destroying real signal")
