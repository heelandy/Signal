"""Advisory predictor — estimates P(trade reaches TP2 before stop) from a candidate's features.

Pipeline: journal (labels) → features → model → confidence on the next candidate. The model output
is a SIZING/FILTER input on top of the rule-based candidate; it has NO authority to trade.

Ships a dependency-free numpy logistic-regression baseline so it runs today; production swaps in
XGBoost/LightGBM (in requirements as optional) behind the same `fit/predict_proba` interface, with
walk-forward / Deflated-Sharpe validation (Evidence) before any output is trusted for sizing.

    from bot.ml.predictor import DirectionModel, features_from_candidate, dataset_from_journal
"""
from __future__ import annotations

import numpy as np

# the candidate-level features the baseline uses (subset of the example.txt feature list that we
# already carry on the candidate / its evidence)
FEATURES = ["rr", "risk_pts", "mfe_r", "mae_r", "hold_bars", "regime_A"]


def features_from_candidate(c) -> np.ndarray:
    ev = c.evidence or {}
    return np.array([
        c.rr,
        ev.get("risk_pts", c.risk),
        ev.get("mfe_r", 0.0),
        ev.get("mae_r", 0.0),
        ev.get("hold_bars", 0),
        1.0 if (c.regime == "A") else 0.0,
    ], dtype=float)


def dataset_from_journal(journal) -> tuple[np.ndarray, np.ndarray]:
    """Build (X, y) from JournalEntry rows; y=1 if the trade hit TP2 (or net_r>0). NOTE: mfe/mae
    are realised — for live prediction use only pre-trade features; this baseline shows the wiring."""
    rows = journal.read("JournalEntry")
    X, y = [], []
    for r in rows:
        if r.get("net_r") is None:
            continue
        X.append([r.get("rr", 4.0), r.get("risk_pts", 1.0), r.get("mfe_r", 0.0),
                  r.get("mae_r", 0.0), r.get("hold_bars", 0), 0.0])
        y.append(1 if (r.get("exit_reason") == "tp2" or r["net_r"] > 0) else 0)
    return np.array(X, float), np.array(y, int)


class DirectionModel:
    """Numpy logistic regression (standardised features) — baseline, swappable for GBMs."""

    def __init__(self, lr: float = 0.1, epochs: int = 800, l2: float = 1e-3):
        self.lr, self.epochs, self.l2 = lr, epochs, l2
        self.w = self.b = self.mu = self.sd = None

    def fit(self, X: np.ndarray, y: np.ndarray) -> "DirectionModel":
        self.mu, self.sd = X.mean(0), X.std(0) + 1e-9
        Xs = (X - self.mu) / self.sd
        n, d = Xs.shape
        self.w, self.b = np.zeros(d), 0.0
        for _ in range(self.epochs):
            p = 1 / (1 + np.exp(-(Xs @ self.w + self.b)))
            g = p - y
            self.w -= self.lr * (Xs.T @ g / n + self.l2 * self.w)
            self.b -= self.lr * g.mean()
        return self

    def predict_proba(self, X: np.ndarray) -> np.ndarray:
        Xs = (np.atleast_2d(X) - self.mu) / self.sd
        return 1 / (1 + np.exp(-(Xs @ self.w + self.b)))

    def confidence(self, c) -> float:
        return float(self.predict_proba(features_from_candidate(c))[0])


if __name__ == "__main__":   # self-test on a synthetic separable set (wiring + learning)
    rng = np.random.default_rng(0)
    n = 400
    X = rng.normal(size=(n, len(FEATURES)))
    y = (X[:, 0] + 0.5 * X[:, 2] - 0.5 * X[:, 3] + rng.normal(scale=0.3, size=n) > 0).astype(int)
    m = DirectionModel().fit(X, y)
    acc = ((m.predict_proba(X) > 0.5).astype(int) == y).mean()
    assert acc > 0.8, acc
    print(f"DirectionModel baseline trained: in-sample acc {acc:.1%} on {n} rows")
    print("features:", FEATURES, "| ADVISORY ONLY — no trade authority")
    print("ml predictor OK")
