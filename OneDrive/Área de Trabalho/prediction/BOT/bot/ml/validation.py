"""ML validation (ML-005) — walk-forward + Deflated/Probabilistic Sharpe (Bailey & López de Prado).

The hard gate before any model output is trusted for sizing: out-of-sample only, multiple folds, and
a deflation for the number of trials tried (the factor-zoo / backtest-overfitting correction Evidence
insists on).
"""
from __future__ import annotations

import math

import numpy as np


def auc(y: np.ndarray, p: np.ndarray) -> float:
    """ROC-AUC via the rank (Mann–Whitney) identity."""
    y = np.asarray(y); p = np.asarray(p)
    pos, neg = y == 1, y == 0
    n_pos, n_neg = pos.sum(), neg.sum()
    if n_pos == 0 or n_neg == 0:
        return float("nan")
    order = p.argsort()
    ranks = np.empty(len(p)); ranks[order] = np.arange(1, len(p) + 1)
    return float((ranks[pos].sum() - n_pos * (n_pos + 1) / 2) / (n_pos * n_neg))


def walk_forward(X: np.ndarray, y: np.ndarray, model_factory, n_splits: int = 5) -> dict:
    """Chronological expanding-window walk-forward. model_factory() -> object with fit/predict_proba."""
    n = len(X)
    fold = n // (n_splits + 1)
    accs, aucs, oos = [], [], []
    for k in range(1, n_splits + 1):
        tr_end = fold * k
        te_end = fold * (k + 1)
        if te_end - tr_end < 5 or tr_end < 10:
            continue
        m = model_factory().fit(X[:tr_end], y[:tr_end])
        p = m.predict_proba(X[tr_end:te_end])
        yt = y[tr_end:te_end]
        accs.append(((p > 0.5).astype(int) == yt).mean())
        aucs.append(auc(yt, p))
        oos.append((yt, p))
    return {"folds": len(accs), "oos_acc": round(float(np.nanmean(accs)), 3) if accs else float("nan"),
            "oos_auc": round(float(np.nanmean(aucs)), 3) if aucs else float("nan")}


def sharpe(returns: np.ndarray, periods: int = 252) -> float:
    r = np.asarray(returns, float)
    sd = r.std(ddof=1)
    return float(r.mean() / sd * math.sqrt(periods)) if sd > 0 else 0.0


def probabilistic_sharpe(returns: np.ndarray, benchmark_sr: float = 0.0) -> float:
    """P(true SR > benchmark) given skew/kurtosis of the sample (Bailey–LdP)."""
    r = np.asarray(returns, float); n = len(r)
    if n < 3 or r.std(ddof=1) == 0:
        return float("nan")
    sr = r.mean() / r.std(ddof=1)
    g3 = ((r - r.mean()) ** 3).mean() / r.std() ** 3
    g4 = ((r - r.mean()) ** 4).mean() / r.std() ** 4
    denom = math.sqrt(max(1 - g3 * sr + (g4 - 1) / 4 * sr ** 2, 1e-9))
    z = (sr - benchmark_sr) * math.sqrt(n - 1) / denom
    return float(0.5 * (1 + math.erf(z / math.sqrt(2))))


def deflated_sharpe(returns: np.ndarray, n_trials: int) -> float:
    """PSR against the expected max SR from `n_trials` random strategies (deflation for selection)."""
    r = np.asarray(returns, float); n = len(r)
    if n < 3 or n_trials < 1 or r.std(ddof=1) == 0:
        return float("nan")
    emc = 0.5772156649
    z = math.sqrt(2 * math.log(max(n_trials, 2)))
    e_max = (1 - emc) * z + emc * math.sqrt(2 * math.log(max(n_trials, 2)) - 2 * math.log(math.log(max(n_trials, 2)) + 1e-9))
    sr_per = r.mean() / r.std(ddof=1)                       # per-period SR
    return probabilistic_sharpe(returns, benchmark_sr=e_max / math.sqrt(n) if n else 0.0)


if __name__ == "__main__":
    from bot.ml.predictor import DirectionModel
    rng = np.random.default_rng(1)
    n = 600
    X = rng.normal(size=(n, 6))
    y = (X[:, 0] + 0.4 * X[:, 2] + rng.normal(scale=0.4, size=n) > 0).astype(int)
    wf = walk_forward(X, y, DirectionModel, n_splits=5)
    assert wf["oos_auc"] > 0.6, wf
    print("walk-forward:", wf)

    good = rng.normal(0.08, 1.0, 252)
    print("Sharpe:", round(sharpe(good), 2),
          "| PSR>0:", round(probabilistic_sharpe(good), 3),
          "| DSR(50 trials):", round(deflated_sharpe(good, 50), 3))
    print("ml validation OK")
