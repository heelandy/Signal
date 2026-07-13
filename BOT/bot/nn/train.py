"""NN training + promotion (NN-003) — the sequence twin of bot.ml.pipeline.train_and_promote.

Same rules as the tabular layer: purged walk-forward with embargo, calibration on pooled OOS
predictions, the hard gates (AUC > 0.52, Brier beats the base rate, high-confidence bucket must
out-earn low-confidence in expected R), champion-challenger on the frozen holdout, and a registry
entry pinned to the strategy version. The NN is ADVISORY — it answers "does this rule-valid setup
look like past winners?", it never trades.

    from bot.nn.train import train_and_promote_nn
    train_and_promote_nn("QQQ")                 # all available archs
    train_and_promote_nn("QQQ", archs=("torch_gru",))
"""
from __future__ import annotations

import numpy as np

from bot.ml.models import IsotonicCalibrator, CalibratedModel
from bot.ml.registry import ModelRegistry
from bot.ml.validation import purged_walk_forward, bucket_expectancy, auc
from bot.nn.dataset import build_sequences, CHANNELS
from bot.nn.models import nn_zoo

NN_MODEL_NAME = "nn_winprob"
MIN_AUC = 0.52
_reg = ModelRegistry()


def train_and_promote_nn(sym: str = "QQQ", window: int = 64, archs: tuple | None = None,
                         n_splits: int = 4, embargo: int = 5, auto_promote: bool = True,
                         tf: str = "5m") -> dict:
    """sym="ALL" trains the pooled multi-symbol sequence set; tf = training timeframe.
    auto_promote=False registers a gate-passing challenger WITHOUT making it champion (manual
    approval — AITP governance). Every run's report is persisted for the training dashboard."""
    rep = _train_impl(sym, window, archs, n_splits, embargo, auto_promote, tf)
    try:
        from bot.ml.registry import save_report
        save_report("nn", f"{sym}" + ("" if tf == "5m" else f"@{tf}"), rep)
    except Exception:
        pass
    return rep


def _train_impl(sym: str, window: int, archs: tuple | None, n_splits: int, embargo: int,
                auto_promote: bool, tf: str = "5m") -> dict:
    from bot.nn.dataset import build_pooled_sequences
    ds = build_pooled_sequences(window=window, tf=tf) if sym.upper() == "ALL" \
        else build_sequences(sym, window=window, tf=tf)
    X, y, net_r = ds["X"], ds["y"], ds["net_r"]
    if len(X) < 80:
        return {"error": f"only {len(X)} sequences — not enough to validate honestly"}
    zoo = nn_zoo()
    names = [a for a in (archs or zoo.keys()) if a in zoo]
    results, oos = {}, {}
    for name in names:
        wf = purged_walk_forward(X, y, zoo[name], n_splits=n_splits, embargo=embargo)
        results[name] = {"oos_auc": wf["oos_auc"], "oos_brier": wf["oos_brier"], "folds": wf["folds"]}
        oos[name] = wf
    best = max(results, key=lambda k: (results[k]["oos_auc"] if results[k]["oos_auc"] == results[k]["oos_auc"] else -1))
    wf = oos[best]
    report = {"sym": sym, "sequences": len(X), "window": window, "channels": len(CHANNELS),
              "win_rate": round(float(y.mean()), 3), "strategy_version": ds["strategy_version"],
              "zoo": results, "best": best,
              "oos_auc": results[best]["oos_auc"], "oos_brier": results[best]["oos_brier"]}
    # hard gates — identical to the tabular layer
    if not (wf["oos_auc"] == wf["oos_auc"] and wf["oos_auc"] > MIN_AUC):
        return {**report, "promote": False,
                "reason": f"OOS AUC <= {MIN_AUC} (no real predictive edge) — NN NOT deployed"}
    base_brier = float(np.mean((y.mean() - y) ** 2))
    if not (wf["oos_brier"] == wf["oos_brier"] and wf["oos_brier"] < base_brier):
        return {**report, "promote": False,
                "reason": f"OOS Brier {wf['oos_brier']:.4f} does not beat the base rate {base_brier:.4f}"}
    calib = IsotonicCalibrator().fit(wf["oos_p"], wf["oos_y"])
    p_cal = np.clip(calib.transform(wf["oos_p"]), 0, 1)
    buckets = bucket_expectancy(p_cal, net_r[wf["oos_idx"]])
    report["buckets"] = buckets
    if not buckets["monotone_ok"]:
        return {**report, "promote": False,
                "reason": "high-confidence sequences do not out-earn low-confidence OOS — NN not useful"}
    # LEAKAGE FIX (Signal-Certificate T5, 2026-07-12): the promotion AUC must come from a model that
    # NEVER saw the holdout. The old code fit the challenger on ALL (X,y) then "evaluated" on the last
    # 30% X[k:] — which was IN the training set → inflated holdout AUC → wrongful promotion. The GATE
    # model is now fit on the first 70% ONLY and scored on the untouched last 30%; the DEPLOYED model
    # (registered below) still uses all data.
    k = int(len(X) * 0.7)
    gate_model = CalibratedModel(zoo[best]().fit(X[:k], y[:k]), calib)   # never sees X[k:]
    ch_auc = auc(y[k:], gate_model.predict_proba(X[k:]))                 # honest holdout AUC
    champ, _meta = _reg.champion(NN_MODEL_NAME)
    cm_auc = auc(y[k:], champ.predict_proba(X[k:])) if champ is not None else float("-inf")
    promote = champ is None or (ch_auc == ch_auc and ch_auc >= cm_auc)
    report.update({"challenger_auc": round(float(ch_auc), 3), "promote": bool(promote)})
    if promote:
        challenger = CalibratedModel(zoo[best]().fit(X, y), calib)      # deploy on ALL data
        version = f"{sym}-{best}-w{window}-auc{results[best]['oos_auc']}"
        _reg.register(challenger, NN_MODEL_NAME, version,
                      {"oos_auc": results[best]["oos_auc"], "oos_brier": results[best]["oos_brier"],
                       "holdout_auc": round(float(ch_auc), 3), "buckets": buckets,
                       "gates_passed": True},
                      champion=bool(auto_promote), features=[f"seq:{window}x{c}" for c in CHANNELS],
                      strategy_version=ds["strategy_version"])
        report["version"] = version
        report["pending_approval"] = not auto_promote
    return report


def predict_sequence(seq: np.ndarray) -> float | None:
    """Calibrated NN confidence for one [window x channels] sequence (None = no champion)."""
    model, _meta = _reg.champion(NN_MODEL_NAME)
    if model is None:
        return None
    try:
        return float(np.atleast_1d(model.predict_proba(seq[None, ...]))[0])
    except Exception:
        return None


if __name__ == "__main__":
    import sys
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    sym = args[0] if args else "QQQ"
    archs = tuple(args[1].split(",")) if len(args) > 1 else None
    auto = "--no-promote" not in sys.argv
    tf = next((a.split("=", 1)[1] for a in sys.argv[1:] if a.startswith("--tf=")), "5m")
    print(f"NN ADAPT - train_and_promote_nn({sym}, tf={tf}, auto_promote={auto}):")
    r = train_and_promote_nn(sym, archs=archs, auto_promote=auto, tf=tf)
    for k, v in r.items():
        print(f"  {k}: {v}")
    print("nn train OK")
