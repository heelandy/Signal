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


def brier(y: np.ndarray, p: np.ndarray) -> float:
    """Brier score (mean squared probability error) — lower is better; 0.25 = coin flip."""
    y = np.asarray(y, float); p = np.asarray(p, float)
    return float(np.mean((p - y) ** 2)) if len(y) else float("nan")


def purged_walk_forward(X: np.ndarray, y: np.ndarray, model_factory,
                        n_splits: int = 5, embargo: int = 5) -> dict:
    """Purged chronological walk-forward with an EMBARGO gap: `embargo` samples straddling each
    train/test boundary are dropped from training so overlapping label horizons cannot leak
    (López de Prado's purged CV, sample-index approximation). Returns per-fold AUC/Brier plus the
    POOLED out-of-sample predictions — the honest inputs for calibration + bucket analysis."""
    X = np.asarray(X, dtype=float)          # one dtype/shape for fit AND predict (warning sweep
    y = np.asarray(y)                       # 2026-07-11: mixed frame/ndarray tripped sklearn's
    n = len(X)                              # feature-name check on every canary fold)
    fold = n // (n_splits + 1)
    aucs, briers = [], []
    oos_p, oos_y, oos_idx = [], [], []
    for k in range(1, n_splits + 1):
        tr_end = max(fold * k - embargo, 0)               # purge the boundary from TRAIN
        te_start = fold * k
        te_end = min(fold * (k + 1), n)
        if te_end - te_start < 5 or tr_end < 20:
            continue
        m = model_factory().fit(X[:tr_end], y[:tr_end])
        p = m.predict_proba(X[te_start:te_end])
        yt = y[te_start:te_end]
        aucs.append(auc(yt, p)); briers.append(brier(yt, p))
        oos_p.append(p); oos_y.append(yt); oos_idx.append(np.arange(te_start, te_end))
    if not aucs:
        return {"folds": 0, "oos_auc": float("nan"), "oos_brier": float("nan"),
                "oos_p": np.array([]), "oos_y": np.array([]), "oos_idx": np.array([], int)}
    return {"folds": len(aucs),
            "oos_auc": round(float(np.nanmean(aucs)), 3),
            "oos_auc_folds": [round(float(a), 3) for a in aucs],
            "oos_brier": round(float(np.nanmean(briers)), 4),
            "oos_p": np.concatenate(oos_p), "oos_y": np.concatenate(oos_y),
            "oos_idx": np.concatenate(oos_idx)}


def bucket_expectancy(p: np.ndarray, net_r: np.ndarray,
                      edges=(0.35, 0.45, 0.55)) -> dict:
    """Expected R by confidence bucket on OOS predictions — the HARD RULE: if high-confidence
    trades do not out-earn low-confidence trades out-of-sample, the model is not useful.
    Returns per-bucket (n, exp_R) + `monotone_ok` (top bucket beats bottom bucket)."""
    p = np.asarray(p, float); r = np.asarray(net_r, float)
    bounds = [0.0, *edges, 1.0]
    out = {}
    means = []
    for lo, hi in zip(bounds[:-1], bounds[1:]):
        m = (p >= lo) & (p < hi if hi < 1.0 else p <= 1.0)
        exp_r = float(r[m].mean()) if m.sum() else float("nan")
        out[f"{lo:.2f}-{hi:.2f}"] = {"n": int(m.sum()), "exp_r": round(exp_r, 3) if exp_r == exp_r else None}
        means.append(exp_r)
    filled = [x for x in means if x == x]
    out["monotone_ok"] = bool(len(filled) >= 2 and filled[-1] > filled[0])
    return out


def info_coefficient(pred: np.ndarray, realized: np.ndarray) -> float:
    """Rank information coefficient (Spearman) between a prediction and the realized value —
    the regression-head analogue of AUC. > 0.05 OOS is already useful for sizing."""
    a = np.asarray(pred, float); b = np.asarray(realized, float)
    m = np.isfinite(a) & np.isfinite(b)
    a, b = a[m], b[m]
    if len(a) < 10 or a.std() == 0 or b.std() == 0:
        return float("nan")
    ra = np.argsort(np.argsort(a)).astype(float)
    rb = np.argsort(np.argsort(b)).astype(float)
    return float(np.corrcoef(ra, rb)[0, 1])


def slice_report(p: np.ndarray, y: np.ndarray, net_r: np.ndarray, slices: dict,
                 min_n: int = 80) -> dict:
    """PER-SLICE validation gates (MLP-001 §5): for every named slice (symbol/side/year/...),
    AUC + the top-half-vs-bottom-half expected-R spread on OOS predictions. A model FAILS when any
    slice with >= min_n samples has an INVERTED spread (high confidence earns LESS than low).
    `slices` = {"symbol": array, "side": array, ...} aligned with p/y/net_r."""
    p = np.asarray(p, float); y = np.asarray(y, int); r = np.asarray(net_r, float)
    out = {"slices": {}, "min_n": min_n, "all_ok": True}
    for dim, values in slices.items():
        v = np.asarray(values)
        for key in np.unique(v):
            m = v == key
            n = int(m.sum())
            if n < min_n:
                continue
            med = np.median(p[m])
            hi, lo_ = m & (p >= med), m & (p < med)
            spread = (float(r[hi].mean()) - float(r[lo_].mean())) if hi.sum() and lo_.sum() else float("nan")
            a = auc(y[m], p[m])
            ok = not (spread == spread and spread < -0.05)      # inverted beyond noise = fail
            out["slices"][f"{dim}={key}"] = {"n": n, "auc": round(float(a), 3) if a == a else None,
                                             "exp_r_spread": round(spread, 3) if spread == spread else None,
                                             "ok": bool(ok)}
            if not ok:
                out["all_ok"] = False
    return out


def calibration_table(y: np.ndarray, p: np.ndarray, bins: int = 10) -> list[dict]:
    """Reliability table: predicted-probability bin -> observed frequency (dashboard raw material)."""
    y = np.asarray(y, float); p = np.asarray(p, float)
    rows = []
    for b in range(bins):
        lo, hi = b / bins, (b + 1) / bins
        m = (p >= lo) & (p < hi if b < bins - 1 else p <= 1.0)
        rows.append({"bin": f"{lo:.1f}-{hi:.1f}", "n": int(m.sum()),
                     "p_mean": round(float(p[m].mean()), 3) if m.sum() else None,
                     "y_rate": round(float(y[m].mean()), 3) if m.sum() else None})
    return rows


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
