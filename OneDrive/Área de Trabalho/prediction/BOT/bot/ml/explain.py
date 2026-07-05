"""Trade-level explainability (ML-007) — why the model liked or disliked a candidate.

Three tiers, degrading gracefully with what's installed:
  1. SHAP TreeExplainer for tree models (if `shap` is installed),
  2. signed linear contributions for logistic models (dependency-free),
  3. permutation importance (dependency-free) for any model — global, not per-trade.

Output contract (dashboard/journal): {"top_positive": [(feature, +contrib)...],
"top_negative": [...], "method": "shap|linear|perturb"} — always the SAME shape.
"""
from __future__ import annotations

import numpy as np

from bot.ml.validation import auc


def _linear_parts(est, x: np.ndarray):
    """Signed standardized contributions for a linear model. Supports the numpy DirectionModel and
    sklearn pipelines ending in LogisticRegression. Returns None when the model is not linear."""
    m = getattr(est, "m", None)                       # _NumpyLogitEst adapter
    if m is not None and getattr(m, "w", None) is not None:
        xs = (x - m.mu) / m.sd
        return xs * m.w
    steps = getattr(est, "named_steps", None)         # sklearn pipeline scaler+logreg
    if steps:
        try:
            scaler = steps.get("standardscaler")
            lr = steps.get("logisticregression")
            if lr is not None:
                xs = scaler.transform(x.reshape(1, -1))[0] if scaler is not None else x
                return xs * lr.coef_[0]
        except Exception:
            return None
    if hasattr(est, "coef_"):
        return x * est.coef_[0]
    return None


def explain_candidate(model, x: np.ndarray, feature_names: list[str], top: int = 5) -> dict:
    """Per-candidate explanation for a TabularModel/CalibratedModel wrapper + one feature vector."""
    inner = getattr(model, "model", model)            # unwrap CalibratedModel
    est = getattr(inner, "est", inner)                # unwrap TabularModel
    med = getattr(inner, "med", None)
    xi = np.asarray(x, float).copy()
    if med is not None:
        xi = np.where(np.isfinite(xi), xi, med)
    # tier 1: SHAP for tree models
    try:
        import shap
        expl = shap.TreeExplainer(est)
        sv = np.asarray(expl.shap_values(xi.reshape(1, -1)))
        contrib = sv[-1][0] if sv.ndim == 3 else sv[0]
        method = "shap"
    except Exception:
        contrib = _linear_parts(est, xi)
        method = "linear"
        if contrib is None:
            # tier 3: local perturbation — flip each feature to its median, measure P(win) change
            base = float(np.atleast_1d(inner.predict_proba(xi.reshape(1, -1)))[0])
            contrib = np.zeros(len(xi))
            ref = med if med is not None else np.zeros(len(xi))
            for j in range(len(xi)):
                xj = xi.copy(); xj[j] = ref[j]
                pj = float(np.atleast_1d(inner.predict_proba(xj.reshape(1, -1)))[0])
                contrib[j] = base - pj                # positive = this feature's value ADDS confidence
            method = "perturb"
    order = np.argsort(contrib)
    pos = [(feature_names[j], round(float(contrib[j]), 4)) for j in order[::-1] if contrib[j] > 0][:top]
    neg = [(feature_names[j], round(float(contrib[j]), 4)) for j in order if contrib[j] < 0][:top]
    return {"top_positive": pos, "top_negative": neg, "method": method}


def permutation_importance(model, X: np.ndarray, y: np.ndarray, feature_names: list[str],
                           n_repeats: int = 3, seed: int = 7) -> list[tuple[str, float]]:
    """Global importance: OOS-AUC drop when a feature column is shuffled (dependency-free)."""
    rng = np.random.default_rng(seed)
    base = auc(y, model.predict_proba(X))
    out = []
    for j, name in enumerate(feature_names):
        drops = []
        for _ in range(n_repeats):
            Xp = X.copy()
            Xp[:, j] = rng.permutation(Xp[:, j])
            drops.append(base - auc(y, model.predict_proba(Xp)))
        out.append((name, round(float(np.mean(drops)), 4)))
    return sorted(out, key=lambda t: -t[1])


if __name__ == "__main__":
    from bot.ml.models import make_model
    rng = np.random.default_rng(1)
    n = 400
    X = rng.normal(size=(n, 6))
    y = ((X[:, 0] - 0.8 * X[:, 3]) > 0).astype(int)
    names = [f"f{i}" for i in range(6)]
    for name in ("logit_np", "logreg", "rf"):
        try:
            m = make_model(name).fit(X, y)
        except KeyError:
            continue
        e = explain_candidate(m, X[0], names)
        assert e["top_positive"] or e["top_negative"], (name, e)
        print(f"  {name:8} [{e['method']:7}] +{e['top_positive'][:2]} -{e['top_negative'][:2]}")
    imp = permutation_importance(make_model("logit_np").fit(X, y), X, y, names)
    assert imp[0][0] in ("f0", "f3"), imp   # the true drivers must rank on top
    print("explain OK -", imp[:3])
