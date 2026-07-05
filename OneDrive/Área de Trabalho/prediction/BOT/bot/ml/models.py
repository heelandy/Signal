"""Model zoo (ML-004) — every tabular model behind ONE interface: fit(X, y) / predict_proba(X)->1d.

Baselines always available (numpy); the heavier learners load only if their package is installed
(scikit-learn / LightGBM / XGBoost are in the venv as of 2026-07-04; CatBoost optional). All models
impute NaNs with TRAIN medians and share the same wrapper so walk-forward validation, calibration,
the registry and the explainability layer treat them identically.

    from bot.ml.models import model_zoo, make_model, PlattCalibrator, IsotonicCalibrator
    zoo = model_zoo()                    # {"logit_np": factory, "logreg": ..., "lgbm": ...}
    m = make_model("lgbm").fit(X, y)
    p = m.predict_proba(X)               # 1-d P(y=1)
"""
from __future__ import annotations

import numpy as np

from bot.ml.predictor import DirectionModel


class TabularModel:
    """Uniform wrapper: median imputation (train-fit) + underlying estimator + 1-d proba output."""

    def __init__(self, name: str, est):
        self.name = name
        self.est = est
        self.med = None

    def _impute(self, X):
        X = np.atleast_2d(np.asarray(X, float))
        if self.med is None:
            med = np.nanmedian(X, axis=0)
            self.med = np.where(np.isfinite(med), med, 0.0)
        X = np.where(np.isfinite(X), X, self.med)
        return X

    def fit(self, X, y):
        self.med = None
        X = self._impute(X)
        self.est.fit(X, np.asarray(y, int))
        return self

    def predict_proba(self, X):
        X = self._impute(X)
        p = self.est.predict_proba(X)
        p = np.asarray(p, float)
        return p[:, 1] if p.ndim == 2 else p       # sklearn 2-col vs numpy 1-d


class _NumpyLogitEst:
    """Adapter: DirectionModel (numpy logistic) -> sklearn-ish estimator API."""

    def __init__(self):
        self.m = DirectionModel()

    def fit(self, X, y):
        self.m.fit(X, y)
        return self

    def predict_proba(self, X):
        return self.m.predict_proba(X)


def model_zoo() -> dict:
    """Name -> zero-arg factory for every model available in this environment."""
    zoo = {"logit_np": lambda: TabularModel("logit_np", _NumpyLogitEst())}
    try:
        from sklearn.linear_model import LogisticRegression
        from sklearn.ensemble import RandomForestClassifier, HistGradientBoostingClassifier
        from sklearn.pipeline import make_pipeline
        from sklearn.preprocessing import StandardScaler
        zoo["logreg"] = lambda: TabularModel("logreg", make_pipeline(
            StandardScaler(), LogisticRegression(max_iter=2000, C=0.5)))
        zoo["rf"] = lambda: TabularModel("rf", RandomForestClassifier(
            n_estimators=400, max_depth=6, min_samples_leaf=10, n_jobs=-1, random_state=7))
        zoo["hgb"] = lambda: TabularModel("hgb", HistGradientBoostingClassifier(
            max_depth=4, learning_rate=0.06, max_iter=300, l2_regularization=1.0, random_state=7))
    except ImportError:
        pass
    try:
        from lightgbm import LGBMClassifier
        zoo["lgbm"] = lambda: TabularModel("lgbm", LGBMClassifier(
            n_estimators=400, num_leaves=15, max_depth=4, learning_rate=0.05,
            min_child_samples=20, subsample=0.9, colsample_bytree=0.9,
            reg_lambda=1.0, random_state=7, verbosity=-1))
    except ImportError:
        pass
    try:
        from xgboost import XGBClassifier
        zoo["xgb"] = lambda: TabularModel("xgb", XGBClassifier(
            n_estimators=400, max_depth=4, learning_rate=0.05, subsample=0.9,
            colsample_bytree=0.9, reg_lambda=1.0, eval_metric="logloss",
            random_state=7, verbosity=0))
    except ImportError:
        pass
    try:
        from catboost import CatBoostClassifier
        zoo["catboost"] = lambda: TabularModel("catboost", CatBoostClassifier(
            iterations=400, depth=4, learning_rate=0.05, verbose=False, random_seed=7))
    except ImportError:
        pass
    return zoo


def make_model(name: str) -> TabularModel:
    zoo = model_zoo()
    if name not in zoo:
        raise KeyError(f"model '{name}' unavailable — installed zoo: {sorted(zoo)}")
    return zoo[name]()


# ─────────────────────────── probability calibration (ML-006) ───────────────────────────
# "a model saying 0.72 should mean roughly 72% historically" — calibrators are fit on OUT-OF-SAMPLE
# predictions (the pooled walk-forward folds), never on training fits.

class PlattCalibrator:
    """Platt scaling: 1-d logistic fit p_cal = sigmoid(a*logit(p) + b). Dependency-free."""

    def __init__(self, lr: float = 0.5, epochs: int = 500):
        self.a, self.b, self.lr, self.epochs = 1.0, 0.0, lr, epochs

    @staticmethod
    def _logit(p):
        p = np.clip(np.asarray(p, float), 1e-6, 1 - 1e-6)
        return np.log(p / (1 - p))

    def fit(self, p_oos, y_oos):
        z = self._logit(p_oos); y = np.asarray(y_oos, float)
        for _ in range(self.epochs):
            q = 1 / (1 + np.exp(-(self.a * z + self.b)))
            g = q - y
            self.a -= self.lr * float((g * z).mean())
            self.b -= self.lr * float(g.mean())
        return self

    def transform(self, p):
        return 1 / (1 + np.exp(-(self.a * self._logit(p) + self.b)))


class IsotonicCalibrator:
    """Isotonic regression via sklearn when available; falls back to Platt otherwise."""

    def __init__(self):
        try:
            from sklearn.isotonic import IsotonicRegression
            self.iso = IsotonicRegression(out_of_bounds="clip", y_min=0.0, y_max=1.0)
        except ImportError:
            self.iso = None
            self._platt = PlattCalibrator()

    def fit(self, p_oos, y_oos):
        if self.iso is not None:
            self.iso.fit(np.asarray(p_oos, float), np.asarray(y_oos, float))
        else:
            self._platt.fit(p_oos, y_oos)
        return self

    def transform(self, p):
        if self.iso is not None:
            return self.iso.predict(np.asarray(p, float))
        return self._platt.transform(p)


class CalibratedModel:
    """Final artifact: fitted model + OOS-fitted calibrator, one predict_proba."""

    def __init__(self, model: TabularModel, calibrator):
        self.model = model
        self.calibrator = calibrator
        self.name = f"{model.name}+cal"

    def fit(self, X, y):              # registry/champion interface compatibility
        self.model.fit(X, y)
        return self

    def predict_proba(self, X):
        return np.clip(self.calibrator.transform(self.model.predict_proba(X)), 0.0, 1.0)


class GroupCalibrator:
    """Per-group calibration (MLP-001 §6: 'calibrate separately by symbol/side/session'):
    one isotonic calibrator per group key (e.g. 'QQQ|long') fit on that group's OOS predictions
    when it has >= min_n samples, with a GLOBAL calibrator as the fallback for thin/unseen groups."""

    def __init__(self, min_n: int = 150):
        self.min_n = min_n
        self.global_cal = IsotonicCalibrator()
        self.by_group: dict = {}

    def fit(self, p_oos, y_oos, groups):
        p = np.asarray(p_oos, float); y = np.asarray(y_oos, int)
        g = np.asarray(groups)
        self.global_cal.fit(p, y)
        for key in np.unique(g):
            m = g == key
            if m.sum() >= self.min_n and len(np.unique(y[m])) == 2:
                self.by_group[str(key)] = IsotonicCalibrator().fit(p[m], y[m])
        return self

    def transform(self, p, groups=None):
        p = np.atleast_1d(np.asarray(p, float))
        if groups is None:
            return self.global_cal.transform(p)
        g = np.atleast_1d(np.asarray(groups))
        out = np.empty_like(p)
        for key in np.unique(g):
            m = g == key
            cal = self.by_group.get(str(key), self.global_cal)
            out[m] = cal.transform(p[m])
        return out


class GroupCalibratedModel:
    """Model + GroupCalibrator: predict_proba(X, groups=None) — group-aware when the caller
    supplies keys (live: 'SYMBOL|side'), global-calibrated otherwise (registry-compatible)."""

    def __init__(self, model: TabularModel, calibrator: GroupCalibrator):
        self.model = model
        self.calibrator = calibrator
        self.name = f"{model.name}+gcal"

    def predict_proba(self, X, groups=None):
        return np.clip(self.calibrator.transform(self.model.predict_proba(X), groups), 0.0, 1.0)


if __name__ == "__main__":   # self-test: every installed model learns a separable problem
    rng = np.random.default_rng(3)
    n = 600
    X = rng.normal(size=(n, 8))
    X[rng.random((n, 8)) < 0.05] = np.nan                      # NaNs must not crash any model
    y = ((np.nan_to_num(X[:, 0]) + 0.5 * np.nan_to_num(X[:, 2])) > 0).astype(int)
    for name, factory in model_zoo().items():
        m = factory().fit(X[:450], y[:450])
        p = m.predict_proba(X[450:])
        acc = ((p > 0.5).astype(int) == y[450:]).mean()
        assert acc > 0.7, (name, acc)
        print(f"  {name:9} OOS acc {acc:.1%}")
    cal = PlattCalibrator().fit(np.clip(rng.random(200), 0.01, 0.99), rng.integers(0, 2, 200))
    assert 0 <= cal.transform([0.5])[0] <= 1
    print("models zoo + calibration OK")
