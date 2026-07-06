"""Predictive + adaptive layer (ML-003..007) — the system learns from outcomes and scores signals.

PREDICT: for each rule-valid candidate, P(win) from PRE-TRADE point-in-time features using the live
champion (calibrated). Advisory only — it sizes/filters, never overrides the rules or the risk gate.

ADAPT: `train_and_promote(sym)` rebuilds the labeled dataset from the CANONICAL entry standard
(one rule version at a time), runs the full model zoo through PURGED walk-forward validation with
embargo, calibrates the best model on pooled OOS predictions, and promotes it only if EVERY gate
passes:  OOS AUC > 0.52  AND  OOS Brier beats the base-rate coin  AND  the high-confidence bucket
out-earns the low-confidence bucket in expected R  AND  it beats the incumbent champion. Re-run on
a schedule (weekly) — never uncontrolled online learning into the live model.

    from bot.ml.pipeline import train_and_promote, predict_candidate
    train_and_promote("QQQ")                       # adapt: learn from history, promote if better
    predict_candidate(candidate, feats=snapshot)   # predict: -> calibrated P(win) in [0,1]
"""
from __future__ import annotations

import numpy as np

from bot.ml.features_pit import FEATURE_COLUMNS, to_vector
from bot.ml.models import model_zoo, CalibratedModel, IsotonicCalibrator
from bot.ml.registry import ModelRegistry
from bot.ml.validation import (purged_walk_forward, bucket_expectancy, calibration_table,
                               auc, brier, slice_report)

_PRIOR = 0.42                 # base ORB hit-rate when no model is trained yet
MODEL_NAME = "signal_winprob"
MIN_AUC = 0.52                # below this the model has no real edge — keep the prior
_reg = ModelRegistry()


def feat(c) -> list[float]:
    """Fallback PRE-TRADE vector from the candidate alone (no bar frame available). Only a thin
    subset of the schema is derivable — prefer passing the full PIT snapshot from the scan."""
    h = int(c.generated_at[11:13]) if c.generated_at else 12
    d = {"side_long": 1.0 if c.side.value == "long" else 0.0, "rr": float(c.rr),
         "regime_A": 1.0 if c.regime == "A" else 0.0, "regime_B": 1.0 if c.regime == "B" else 0.0,
         "regime_C": 1.0 if c.regime == "C" else 0.0, "regime_D": 1.0 if c.regime == "D" else 0.0,
         "hour_sin": float(np.sin(2 * np.pi * h / 24.0)), "hour_cos": float(np.cos(2 * np.pi * h / 24.0))}
    return list(to_vector(d))


def train_and_promote(sym: str = "QQQ", n_splits: int = 5, embargo: int = 5,
                      auto_promote: bool = True, tf: str = "5m") -> dict:
    """ADAPT: dataset -> model-zoo purged walk-forward -> calibrate best -> gate -> promote.
    sym="ALL" trains the POOLED multi-symbol set (symbol one-hot features carry identity).
    tf = training timeframe (1m/3m/5m/15m/30m/1h/2h/4h — multi-TF training 2026-07-05).
    auto_promote=False (AITP-001 governance / continuous training): a gate-passing challenger is
    REGISTERED but NOT made champion — it waits for manual approval on the Training Lab.
    Every run's report is persisted (bot.ml.registry.save_report) for the training dashboard."""
    rep = _train_impl(sym, n_splits, embargo, auto_promote, tf)
    try:
        from bot.ml.registry import save_report
        save_report("ml", f"{sym}" + ("" if tf == "5m" else f"@{tf}"), rep)
    except Exception:
        pass
    return rep


def _train_impl(sym: str, n_splits: int, embargo: int, auto_promote: bool, tf: str = "5m") -> dict:
    from bot.ml.dataset import build, build_pooled, to_xy
    from bot.strategy.orb_candidates import STRATEGY_VERSION
    df = build_pooled(tf=tf) if sym.upper() == "ALL" else build(sym, tf=tf)
    if len(df) < 80:
        return {"error": f"only {len(df)} samples — not enough to validate honestly"}
    X, y, net_r, _ = to_xy(df)

    # 1) model zoo through PURGED walk-forward (embargo kills boundary leakage)
    zoo = model_zoo()
    results, oos = {}, {}
    for name, factory in zoo.items():
        wf = purged_walk_forward(X, y, factory, n_splits=n_splits, embargo=embargo)
        results[name] = {"oos_auc": wf["oos_auc"], "oos_brier": wf["oos_brier"], "folds": wf["folds"]}
        oos[name] = wf
    best = max(results, key=lambda k: (results[k]["oos_auc"] if results[k]["oos_auc"] == results[k]["oos_auc"] else -1))
    wf = oos[best]
    report = {"sym": sym, "tf": tf, "samples": len(df), "win_rate": round(float(y.mean()), 3),
              "strategy_version": STRATEGY_VERSION, "zoo": results, "best": best,
              "oos_auc": results[best]["oos_auc"], "oos_brier": results[best]["oos_brier"]}

    # 2) hard gates — a non-predictive or non-monotone model must never go live
    if not (wf["oos_auc"] == wf["oos_auc"] and wf["oos_auc"] > MIN_AUC):
        return {**report, "promote": False,
                "reason": f"OOS AUC <= {MIN_AUC} (no real predictive edge) — model NOT deployed"}
    base_brier = float(np.mean((y.mean() - y) ** 2))          # always-predict-base-rate coin
    if not (wf["oos_brier"] == wf["oos_brier"] and wf["oos_brier"] < base_brier):
        return {**report, "promote": False,
                "reason": f"OOS Brier {wf['oos_brier']:.4f} does not beat the base rate {base_brier:.4f}"}
    # calibrate on POOLED OOS predictions, then check the expectancy-by-bucket hard rule
    calib = IsotonicCalibrator().fit(wf["oos_p"], wf["oos_y"])
    p_cal = np.clip(calib.transform(wf["oos_p"]), 0, 1)
    buckets = bucket_expectancy(p_cal, net_r[wf["oos_idx"]])
    report["buckets"] = buckets
    # LEAKAGE FIX (user 2026-07-05): the DISPLAYED calibration table must not judge the calibrator
    # on the rows it was fit on — fit on the first 70% of OOS predictions (time order), tabulate
    # on the last 30%. (The bucket gate is rank-safe: isotonic is monotone, ordering unchanged.)
    order = np.argsort(wf["oos_idx"])
    cut = int(0.7 * len(order))
    if len(order) - cut >= 30:
        cal_h = IsotonicCalibrator().fit(wf["oos_p"][order[:cut]], wf["oos_y"][order[:cut]])
        report["calibration"] = calibration_table(
            wf["oos_y"][order[cut:]], np.clip(cal_h.transform(wf["oos_p"][order[cut:]]), 0, 1))
        report["calibration_note"] = "honest split: fit on first 70% of OOS, table on last 30%"
    else:
        report["calibration"] = calibration_table(wf["oos_y"], p_cal)
        report["calibration_note"] = "in-sample calibration table (too few OOS rows to split)"
    if not buckets["monotone_ok"]:
        return {**report, "promote": False,
                "reason": "high-confidence trades do not out-earn low-confidence OOS — model not useful"}
    # PER-SLICE GATE (MLP-001 §5, enforced in promotion 2026-07-05): no slice with enough samples
    # may INVERT (its high-confidence half earning materially less than its low half) — a model
    # that only works on one symbol/side/year must not become the champion for all of them.
    oidx = wf["oos_idx"]
    slices = {"side": np.where(df["side_long"].to_numpy(float)[oidx] > 0, "long", "short")
              if "side_long" in df.columns else df["side"].to_numpy()[oidx],
              "year": df["ts"].dt.year.to_numpy()[oidx].astype(str)}
    if "symbol" in df.columns and df["symbol"].nunique() > 1:
        slices["symbol"] = df["symbol"].to_numpy()[oidx]
    sl = slice_report(p_cal, wf["oos_y"], net_r[oidx], slices, min_n=80)
    report["slice_gates"] = sl
    if not sl["all_ok"]:
        bad = [k for k, v in sl["slices"].items() if not v["ok"]]
        return {**report, "promote": False,
                "reason": f"slice gate: inverted expectancy in {bad} — model not uniform enough to deploy"}

    # 3) champion-challenger duel on the frozen last-30% holdout. LEAKAGE FIX (user 2026-07-05):
    # the duel model trains on the FIRST 70% ONLY — retraining on ALL data and then scoring the
    # holdout graded the challenger on rows it had seen (inflated ch_auc). Raw probabilities are
    # used for AUC (isotonic is rank-preserving, the calibrator cannot change AUC).
    k = int(len(X) * 0.7)
    duel = zoo[best]().fit(X[:k], y[:k])
    ch_auc = auc(y[k:], duel.predict_proba(X[k:]))
    champ, meta = _reg.champion(MODEL_NAME)
    cm_auc = auc(y[k:], champ.predict_proba(X[k:])) if champ is not None else float("-inf")
    # the DEPLOYED challenger still trains on all data (best live model) + the OOS calibrator
    challenger = CalibratedModel(zoo[best]().fit(X, y), calib)
    promote = champ is None or (ch_auc == ch_auc and ch_auc >= cm_auc)
    report.update({"challenger_auc": round(float(ch_auc), 3),
                   "champion_auc": (round(float(cm_auc), 3) if cm_auc == cm_auc and cm_auc != float("-inf") else None),
                   "promote": bool(promote)})
    if promote:
        version = f"{sym}{'' if tf == '5m' else '@' + tf}-{best}-auc{results[best]['oos_auc']}"
        _reg.register(challenger, MODEL_NAME, version,
                      {"oos_auc": results[best]["oos_auc"], "oos_brier": results[best]["oos_brier"],
                       "holdout_auc": round(float(ch_auc), 3), "buckets": buckets,
                       "gates_passed": True},
                      champion=bool(auto_promote), features=list(FEATURE_COLUMNS),
                      strategy_version=STRATEGY_VERSION)
        report["version"] = version
        report["pending_approval"] = not auto_promote     # AITP: manual promotion on the dashboard
    return report


def _schema_ok(meta) -> bool:
    """Never score with a model whose trained feature schema no longer matches the live schema."""
    return meta is None or meta.features is None or list(meta.features) == list(FEATURE_COLUMNS)


def predict_candidate(c, feats: dict | None = None) -> float:
    """PREDICT: calibrated P(win) from the champion (or the prior). `feats` = the PIT snapshot the
    scan computed at the signal bar (train/live parity); without it a thin candidate-only vector
    is used. Attaches the confidence to the candidate."""
    model, meta = _reg.champion(MODEL_NAME)
    if model is None or not _schema_ok(meta):
        return _PRIOR
    try:
        x = to_vector(feats) if feats else np.array(feat(c), float)
        p = float(np.atleast_1d(model.predict_proba(x.reshape(1, -1)))[0])
        c.confidence = round(p, 3)
        return c.confidence
    except Exception:
        return _PRIOR


def explain_last_champion(feats: dict) -> dict | None:
    """Trade-level explanation from the live champion for a PIT snapshot (dashboard/journal)."""
    model, meta = _reg.champion(MODEL_NAME)
    if model is None or not _schema_ok(meta):
        return None
    from bot.ml.explain import explain_candidate
    return explain_candidate(model, to_vector(feats), list(FEATURE_COLUMNS))


if __name__ == "__main__":
    import sys
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    sym = args[0] if args else "QQQ"
    auto = "--no-promote" not in sys.argv          # continuous/governed runs pass --no-promote
    tf = next((a.split("=", 1)[1] for a in sys.argv[1:] if a.startswith("--tf=")), "5m")
    print(f"ADAPT - train_and_promote({sym}, tf={tf}, auto_promote={auto}):")
    r = train_and_promote(sym, auto_promote=auto, tf=tf)
    for k, v in r.items():
        if k not in ("calibration",):
            print(f"  {k}: {v}")
    print("\npipeline OK")
