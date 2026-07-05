"""Multi-head ML training (MLP-001 §4 targets) — beyond P(win):

    tp2_prob    P(trade reaches the full 4R cap)          — classifier on executed candidates
    stop_prob   P(trade takes ~a full -1R stop)           — classifier on executed candidates
    expected_r  expected net R                            — regression head (rank-IC validated)
    no_trade    P(a rule-valid-looking setup is a dud)    — classifier on the ~126k REJECTED
                setups (hypothetical first-touch outcomes; y=1 means missed_LOSER = good block)

Same honesty rules as the win-prob pipeline: purged walk-forward with embargo, hard gates,
`auto_promote=False` registers gate-passers as PENDING for manual approval. Reports saved for the
Training Lab (kind="heads").

    python -m bot.ml.heads ALL [--no-promote]
"""
from __future__ import annotations

import numpy as np

from bot.ml.features_pit import FEATURE_COLUMNS
from bot.ml.models import model_zoo, TabularModel, IsotonicCalibrator, CalibratedModel
from bot.ml.registry import ModelRegistry, FeatureStore, save_report
from bot.ml.validation import purged_walk_forward, info_coefficient, bucket_expectancy, auc, brier

_reg = ModelRegistry()
MIN_AUC = 0.52
MIN_IC = 0.03


def _regressor_zoo() -> dict:
    """Regression models behind the same wrapper idea (median imputation lives in TabularModel;
    regressors expose predict via a predict_proba-shaped adapter so purged WF plumbing reuses)."""
    zoo = {}
    try:
        from sklearn.ensemble import HistGradientBoostingRegressor
        from sklearn.linear_model import Ridge
        from sklearn.pipeline import make_pipeline
        from sklearn.preprocessing import StandardScaler

        class _RegAdapter:
            def __init__(self, est, name):
                self.est, self.name, self.med = est, name, None

            def _impute(self, X):
                X = np.atleast_2d(np.asarray(X, float))
                if self.med is None:
                    med = np.nanmedian(X, axis=0)
                    self.med = np.where(np.isfinite(med), med, 0.0)
                return np.where(np.isfinite(X), X, self.med)

            def fit(self, X, y):
                self.med = None
                self.est.fit(self._impute(X), np.asarray(y, float))
                return self

            def predict_proba(self, X):          # WF plumbing calls predict_proba — raw values out
                return np.asarray(self.est.predict(self._impute(X)), float)

        zoo["ridge"] = lambda: _RegAdapter(make_pipeline(StandardScaler(), Ridge(alpha=2.0)), "ridge")
        zoo["hgb_reg"] = lambda: _RegAdapter(HistGradientBoostingRegressor(
            max_depth=4, learning_rate=0.06, max_iter=300, l2_regularization=1.0, random_state=7), "hgb_reg")
    except ImportError:
        pass
    return zoo


def _cls_head(name: str, X, y, net_r, auto_promote: bool, strategy_version: str,
              features: list, min_auc: float = MIN_AUC) -> dict:
    zoo = model_zoo()
    results, oos = {}, {}
    for mname, factory in zoo.items():
        wf = purged_walk_forward(X, y, factory, n_splits=5, embargo=5)
        results[mname] = {"oos_auc": wf["oos_auc"], "oos_brier": wf["oos_brier"]}
        oos[mname] = wf
    best = max(results, key=lambda k: (results[k]["oos_auc"] if results[k]["oos_auc"] == results[k]["oos_auc"] else -1))
    wf = oos[best]
    rep = {"head": name, "kind_": "classifier", "samples": int(len(X)),
           "base_rate": round(float(y.mean()), 3), "zoo": results, "best": best,
           "oos_auc": results[best]["oos_auc"], "oos_brier": results[best]["oos_brier"]}
    base_brier = float(np.mean((y.mean() - y) ** 2))
    if not (wf["oos_auc"] == wf["oos_auc"] and wf["oos_auc"] > min_auc):
        return {**rep, "promote": False, "reason": f"OOS AUC <= {min_auc}"}
    if not (wf["oos_brier"] == wf["oos_brier"] and wf["oos_brier"] < base_brier):
        return {**rep, "promote": False,
                "reason": f"OOS Brier {wf['oos_brier']:.4f} >= base {base_brier:.4f}"}
    calib = IsotonicCalibrator().fit(wf["oos_p"], wf["oos_y"])
    if net_r is not None:
        buckets = bucket_expectancy(np.clip(calib.transform(wf["oos_p"]), 0, 1), net_r[wf["oos_idx"]])
        rep["buckets"] = buckets
    challenger = CalibratedModel(zoo[best]().fit(X, y), calib)
    version = f"{name}-{best}-auc{results[best]['oos_auc']}"
    _reg.register(challenger, name, version,
                  {"oos_auc": results[best]["oos_auc"], "oos_brier": results[best]["oos_brier"],
                   "gates_passed": True},
                  champion=bool(auto_promote), features=features, strategy_version=strategy_version)
    return {**rep, "promote": True, "version": version, "pending_approval": not auto_promote}


def _reg_head(X, y_r, auto_promote: bool, strategy_version: str, features: list) -> dict:
    zoo = _regressor_zoo()
    if not zoo:
        return {"head": "expected_r", "error": "sklearn unavailable"}
    results, oos = {}, {}
    for mname, factory in zoo.items():
        # manual chrono folds with rank-IC (purged_walk_forward assumes binary y for AUC)
        n = len(X); fold = n // 6
        ics, preds, idxs = [], [], []
        for k in range(1, 6):
            tr_end = max(fold * k - 5, 20)
            te_s, te_e = fold * k, min(fold * (k + 1), n)
            if te_e - te_s < 20:
                continue
            m = factory().fit(X[:tr_end], y_r[:tr_end])
            p = m.predict_proba(X[te_s:te_e])
            ics.append(info_coefficient(p, y_r[te_s:te_e]))
            preds.append(p); idxs.append(np.arange(te_s, te_e))
        ic = float(np.nanmean(ics)) if ics else float("nan")
        results[mname] = {"oos_ic": round(ic, 4)}
        oos[mname] = (np.concatenate(preds) if preds else np.array([]),
                      np.concatenate(idxs) if idxs else np.array([], int))
    best = max(results, key=lambda k: (results[k]["oos_ic"] if results[k]["oos_ic"] == results[k]["oos_ic"] else -9))
    rep = {"head": "expected_r", "kind_": "regression", "samples": int(len(X)),
           "zoo": results, "best": best, "oos_ic": results[best]["oos_ic"]}
    p, idx = oos[best]
    if not (rep["oos_ic"] == rep["oos_ic"] and rep["oos_ic"] > MIN_IC):
        return {**rep, "promote": False, "reason": f"OOS rank-IC <= {MIN_IC}"}
    # monotonicity: realized R by predicted-R quartile must rise bottom -> top
    q = np.quantile(p, [0.25, 0.5, 0.75])
    means = [float(y_r[idx][np.digitize(p, q) == b].mean()) for b in range(4)]
    rep["quartile_real_r"] = [round(m, 3) for m in means]
    if not means[-1] > means[0]:
        return {**rep, "promote": False, "reason": "top predicted-R quartile does not out-earn bottom OOS"}
    challenger = _regressor_zoo()[best]().fit(X, y_r)
    version = f"expected_r-{best}-ic{rep['oos_ic']}"
    _reg.register(challenger, "expected_r", version,
                  {"oos_ic": rep["oos_ic"], "gates_passed": True},
                  champion=bool(auto_promote), features=features, strategy_version=strategy_version)
    return {**rep, "promote": True, "version": version, "pending_approval": not auto_promote}


def train_heads(sym: str = "ALL", auto_promote: bool = True) -> dict:
    """Train all four heads. Executed-candidate heads use the (pooled) dataset; the no-trade head
    uses the pooled REJECTS store (y=1 when blocking was RIGHT: the setup would have lost)."""
    import pandas as pd
    from bot.ml.dataset import build_pooled, load_or_build, to_xy, _version_slug
    from bot.strategy.orb_candidates import STRATEGY_VERSION
    df = build_pooled() if sym.upper() == "ALL" else load_or_build(sym)
    out = {"sym": sym.upper(), "strategy_version": STRATEGY_VERSION, "heads": {}}
    if len(df) >= 200:
        X = df[FEATURE_COLUMNS].to_numpy(float)
        net_r = df["net_r"].to_numpy(float)
        out["heads"]["tp2_prob"] = _cls_head("tp2_prob", X, df["y_tp2"].to_numpy(int), net_r,
                                             auto_promote, STRATEGY_VERSION, list(FEATURE_COLUMNS))
        out["heads"]["stop_prob"] = _cls_head("stop_prob", X, df["y_stop"].to_numpy(int), -net_r,
                                              auto_promote, STRATEGY_VERSION, list(FEATURE_COLUMNS))
        out["heads"]["expected_r"] = _reg_head(X, net_r, auto_promote, STRATEGY_VERSION,
                                               list(FEATURE_COLUMNS))
    else:
        out["heads"]["error"] = f"only {len(df)} executed candidates"
    # no-trade head from the rejects store (pooled across symbols)
    fs = FeatureStore()
    frames = []
    for s in ("QQQ", "SPY", "NQ", "ES"):
        try:
            frames.append(fs.load(f"rejects_{s}", _version_slug()))
        except FileNotFoundError:
            pass
    if frames:
        rj = pd.concat(frames, ignore_index=True).sort_values("ts").reset_index(drop=True)
        Xr = rj[FEATURE_COLUMNS].to_numpy(float)
        y_no = rj["missed_loser"].to_numpy(int)          # 1 = the block was RIGHT (dud setup)
        hyp = rj["hyp_net_r"].to_numpy(float)
        out["heads"]["no_trade"] = _cls_head("no_trade", Xr, y_no, -hyp, auto_promote,
                                             STRATEGY_VERSION, list(FEATURE_COLUMNS), min_auc=0.55)
        out["rejects_pooled"] = int(len(rj))
    else:
        out["heads"]["no_trade"] = {"error": "no rejects stores built yet (run kind=rejects)"}
    try:
        save_report("heads", sym.upper(), out)
    except Exception:
        pass
    return out


def predict_heads(feats: dict) -> dict:
    """Champion predictions for one PIT snapshot: {tp2_prob, stop_prob, expected_r, no_trade}.
    Missing champions are simply absent — advisory only."""
    from bot.ml.features_pit import to_vector
    x = to_vector(feats).reshape(1, -1)
    out = {}
    for name in ("tp2_prob", "stop_prob", "expected_r", "no_trade"):
        model, meta = _reg.champion(name)
        if model is None:
            continue
        if meta is not None and meta.features and list(meta.features) != list(FEATURE_COLUMNS):
            continue                                      # schema mismatch -> refuse silently
        try:
            out[name] = round(float(np.atleast_1d(model.predict_proba(x))[0]), 3)
        except Exception:
            pass
    return out


if __name__ == "__main__":
    import sys
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    sym = args[0] if args else "ALL"
    auto = "--no-promote" not in sys.argv
    print(f"HEADS - train_heads({sym}, auto_promote={auto}):")
    r = train_heads(sym, auto_promote=auto)
    for h, v in r.get("heads", {}).items():
        line = {k: v.get(k) for k in ("samples", "base_rate", "best", "oos_auc", "oos_brier",
                                      "oos_ic", "promote", "reason", "version") if isinstance(v, dict) and k in v} \
            if isinstance(v, dict) else v
        print(f"  {h}: {line}")
    print("heads OK")
