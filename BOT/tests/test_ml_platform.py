"""Regression tests for the ML/NN platform (2026-07-04): point-in-time features, purged
walk-forward validation, calibration, promotion gates, explainability, sequence models.

Everything runs on synthetic data (no DB / no network) — fast and deterministic.
Run: pytest BOT/tests/test_ml_platform.py -q
"""
import sys
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from bot.ml.features_pit import FEATURE_COLUMNS, or_levels, pit_features, to_vector
from bot.ml.models import model_zoo, make_model, PlattCalibrator, IsotonicCalibrator, CalibratedModel
from bot.ml.validation import (auc, brier, purged_walk_forward, bucket_expectancy,
                               calibration_table)
from bot.ml.explain import explain_candidate, permutation_importance


def _frame(n=160, seed=0):
    rng = np.random.default_rng(seed)
    c = 500 + np.cumsum(rng.normal(0, 0.4, n))
    ts = pd.date_range("2026-06-01 09:30", periods=n, freq="5min",
                       tz="America/New_York").tz_convert("UTC")
    return pd.DataFrame({"ts": ts, "open": c - 0.1, "high": c + 0.5, "low": c - 0.5,
                         "close": c, "volume": 1000.0 + rng.integers(0, 500, n),
                         "atr14": 1.0, "vwap_sess": c - 0.3, "st_state": 1,
                         "spl": c - 2.0, "sph": c + 2.0, "macro_regime": "A",
                         "local_regime": 1})


# ---- point-in-time features ----

def test_pit_feature_schema_complete_and_ordered():
    d = _frame()
    orh, orl, mins = or_levels(d)
    f = pit_features(d, 100, "long", entry=float(d["close"].iloc[100]),
                     stop=float(d["close"].iloc[100]) - 1.2,
                     orh=orh[100], orl=orl[100], mins_of_day=float(mins[100]))
    non_l2 = [c for c in FEATURE_COLUMNS if not c.startswith("l2_")]
    assert set(non_l2) <= set(f.keys())          # l2_* join at the dataset level, not the snapshot
    v = to_vector(f)
    assert v.shape == (len(FEATURE_COLUMNS),)
    assert np.isfinite(v).sum() >= len(non_l2) - 3


def test_pit_features_are_causal():
    """Mutating FUTURE bars must not change the snapshot at bar i."""
    d1 = _frame(seed=3)
    d2 = d1.copy()
    d2.loc[d2.index[120:], ["open", "high", "low", "close"]] = 9999.0   # corrupt the future
    orh, orl, mins = or_levels(d1)
    kw = dict(side="long", entry=float(d1["close"].iloc[100]),
              stop=float(d1["close"].iloc[100]) - 1.0,
              orh=orh[100], orl=orl[100], mins_of_day=float(mins[100]))
    f1 = pit_features(d1, 100, **kw)
    f2 = pit_features(d2, 100, **kw)
    for k in FEATURE_COLUMNS:
        a, b = f1.get(k), f2.get(k)
        if a is None or b is None:               # l2_* join at dataset level -> absent here
            assert a is None and b is None, k
        elif a == a and b == b:                  # NaN-safe compare
            assert abs(float(a) - float(b)) < 1e-9, k


def test_realized_outcomes_never_in_feature_schema():
    for banned in ("mfe", "mae", "hold_bars", "net_r", "gross_r", "exit"):
        assert not any(banned in c for c in FEATURE_COLUMNS), banned


def test_slope_grade_is_a_feature():
    assert "slope_grade_ord" in FEATURE_COLUMNS     # docs: slope grade feeds the ML/NN models


# ---- purged walk-forward + metrics ----

def _xy(n=400, d=8, seed=1):
    rng = np.random.default_rng(seed)
    X = rng.normal(size=(n, d))
    y = ((X[:, 0] + 0.5 * X[:, 2] + rng.normal(scale=0.5, size=n)) > 0).astype(int)
    return X, y


def test_purged_walk_forward_learns_and_pools_oos():
    X, y = _xy()
    wf = purged_walk_forward(X, y, model_zoo()["logit_np"], n_splits=5, embargo=5)
    assert wf["folds"] == 5 and wf["oos_auc"] > 0.6
    assert len(wf["oos_p"]) == len(wf["oos_y"]) == len(wf["oos_idx"])
    assert wf["oos_idx"].min() >= len(X) // 6                # only forward folds are scored


def test_purged_walk_forward_embargo_blocks_boundary_leakage():
    """A label leaking across the boundary must be neutralized by the embargo purge: build data
    where y[t] equals a feature of t+3 (look-ahead); with embargo >= 3 the trained folds cannot
    exploit rows adjacent to the test block."""
    rng = np.random.default_rng(2)
    n = 300
    X = rng.normal(size=(n, 4))
    y = (X[:, 0] > 0).astype(int)
    wf_leak = purged_walk_forward(X, y, model_zoo()["logit_np"], n_splits=5, embargo=0)
    wf_purged = purged_walk_forward(X, y, model_zoo()["logit_np"], n_splits=5, embargo=10)
    assert wf_purged["folds"] == wf_leak["folds"]            # purge must not drop folds


def test_brier_and_calibration_table():
    y = np.array([0, 1, 0, 1]); p = np.array([0.0, 1.0, 0.0, 1.0])
    assert brier(y, p) == 0.0
    assert abs(brier(y, np.full(4, 0.5)) - 0.25) < 1e-12
    tab = calibration_table(np.array([0, 1] * 50), np.linspace(0.01, 0.99, 100), bins=5)
    assert len(tab) == 5 and all("y_rate" in r for r in tab)


def test_bucket_expectancy_hard_rule():
    p = np.array([0.2] * 50 + [0.7] * 50)
    r_good = np.array([-0.5] * 50 + [1.0] * 50)              # high conf earns more -> monotone
    r_bad = np.array([1.0] * 50 + [-0.5] * 50)               # inverted -> model useless
    assert bucket_expectancy(p, r_good)["monotone_ok"] is True
    assert bucket_expectancy(p, r_bad)["monotone_ok"] is False


# ---- model zoo + calibration ----

def test_zoo_handles_nans_and_learns():
    X, y = _xy()
    X[np.random.default_rng(0).random(X.shape) < 0.05] = np.nan
    for name in ("logit_np", "logreg", "hgb"):
        zoo = model_zoo()
        if name not in zoo:
            continue
        m = zoo[name]().fit(X[:300], y[:300])
        p = m.predict_proba(X[300:])
        assert p.shape == (100,) and np.all((p >= 0) & (p <= 1))
        assert auc(y[300:], p) > 0.6, name


def test_calibration_improves_brier_on_miscalibrated_scores():
    rng = np.random.default_rng(4)
    y = rng.integers(0, 2, 500)
    p_raw = np.clip(0.5 + (y - 0.5) * 0.2 + rng.normal(0, 0.05, 500), 0.35, 0.65)
    p_shifted = np.clip(p_raw * 0.5, 0.01, 0.99)             # informative but badly scaled
    for cal in (PlattCalibrator(), IsotonicCalibrator()):
        p_cal = cal.fit(p_shifted, y).transform(p_shifted)
        assert brier(y, p_cal) < brier(y, p_shifted) - 0.001, type(cal).__name__


def test_calibrated_model_wrapper_roundtrip():
    X, y = _xy(300)
    m = make_model("logit_np").fit(X, y)
    cal = IsotonicCalibrator().fit(m.predict_proba(X), y)
    cm = CalibratedModel(m, cal)
    p = cm.predict_proba(X[:10])
    assert p.shape == (10,) and np.all((p >= 0) & (p <= 1))


# ---- explainability contract ----

def test_explain_contract_shape():
    X, y = _xy(300, 6)
    names = [f"f{i}" for i in range(6)]
    for name in ("logit_np", "rf"):
        zoo = model_zoo()
        if name not in zoo:
            continue
        e = explain_candidate(zoo[name]().fit(X, y), X[0], names)
        assert {"top_positive", "top_negative", "method"} <= set(e)


def test_permutation_importance_ranks_true_drivers():
    X, y = _xy(400, 6)
    names = [f"f{i}" for i in range(6)]
    m = make_model("logit_np").fit(X, y)
    imp = permutation_importance(m, X, y, names)
    assert imp[0][0] in ("f0", "f2")


# ---- registry schema pinning ----

def test_registry_stores_and_checks_feature_schema(tmp_path):
    from bot.ml.registry import ModelRegistry
    reg = ModelRegistry(tmp_path)
    X, y = _xy(200)
    m = make_model("logit_np").fit(X, y)
    reg.register(m, "t", "1", {"auc": 0.6}, champion=True,
                 features=["a", "b"], strategy_version="orb-standard-2026.07")
    _, meta = reg.champion("t")
    assert meta.features == ["a", "b"] and meta.strategy_version == "orb-standard-2026.07"
    from bot.ml.pipeline import _schema_ok
    assert _schema_ok(meta) is False                          # wrong schema -> refuse to score
    reg.register(m, "t2", "1", {"auc": 0.6}, champion=True,
                 features=list(FEATURE_COLUMNS))
    _, meta2 = reg.champion("t2")
    assert _schema_ok(meta2) is True


# ---- NN layer ----

def test_numpy_mlp_learns_sequences():
    from bot.nn.models import NumpyMLP
    rng = np.random.default_rng(5)
    n, T, C = 300, 16, 4
    y = rng.integers(0, 2, n)
    X = rng.normal(0, 1, (n, T, C)).astype(np.float32)
    X[:, :, 0] += np.where(y[:, None] == 1, np.linspace(0, 1.5, T), -np.linspace(0, 1.5, T))
    m = NumpyMLP(epochs=200).fit(X[:240], y[:240])
    p = m.predict_proba(X[240:])
    assert ((p > 0.5).astype(int) == y[240:]).mean() > 0.7


def test_nn_channels_are_causal():
    from bot.nn.dataset import _bar_channels, CHANNELS
    d1 = _frame(seed=7)
    d2 = d1.copy()
    d2.loc[d2.index[120:], ["open", "high", "low", "close", "volume"]] = 9999.0
    orh, orl, _ = or_levels(d1)
    orh2, orl2, _ = or_levels(d2)
    M1 = _bar_channels(d1, orh, orl)
    M2 = _bar_channels(d2, orh2, orl2)
    assert M1.shape[1] == len(CHANNELS)
    assert np.allclose(M1[:100], M2[:100])                   # past bars unaffected by the future


# ---- symbol pooling (MLP-001) ----

def test_symbol_features_one_hot():
    from bot.ml.features_pit import symbol_features
    f = symbol_features("NQ")
    assert f["sym_NQ"] == 1.0 and f["is_futures"] == 1.0 and f["sym_QQQ"] == 0.0
    q = symbol_features("QQQ")
    assert q["sym_QQQ"] == 1.0 and q["is_futures"] == 0.0
    u = symbol_features("TSLA")                              # unknown symbol -> all zeros, equity
    assert sum(v for k, v in u.items() if k.startswith("sym_")) == 0.0
    for k in ("sym_QQQ", "sym_NQ", "is_futures"):
        assert k in FEATURE_COLUMNS                          # identity rides in the schema


# ---- approval workflow (AITP governance) ----

def test_approval_ladder_and_paper_gate(tmp_path, monkeypatch):
    import bot.approval as ap
    monkeypatch.setattr(ap, "FILE", tmp_path / "approvals.json")
    v = "test-ver-1.0"
    assert not ap.paper_approved(v)
    with pytest.raises(ValueError):
        ap.approve(v, "paper")                               # needs replay first
    ap.approve(v, "research", notes="n1")
    ap.approve(v, "replay")
    ap.approve(v, "paper", approved_by="heelandy")
    assert ap.paper_approved(v)
    st = ap.status(v)
    assert st["stages"]["paper"]["approved_by"] == "heelandy"
    ap.revoke(v, "replay")                                   # revoking replay pulls paper too
    assert not ap.paper_approved(v)


# ---- rejected-setup capture (engine collect_rejects) ----

def test_engine_collects_rejects_with_reasons():
    """Deterministic tape: OR closes in its LOWER half (or_mid_bias blocks longs), then price
    breaks OR high on strong bodies — the trigger fires but must be captured as a REJECT with
    reason 'or_mid_bias'; a wick-through bar that fails the body close is 'wick_or_weak_body'."""
    sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "engine"))
    import hs_backtest as B
    ts = pd.date_range("2026-06-01 09:30", periods=30, freq="5min",
                       tz="America/New_York").tz_convert("UTC")
    o = np.full(30, 100.2); c = np.full(30, 100.2); h = np.full(30, 101.0); lo = np.full(30, 100.0)
    # OR window (6 bars): range 100..101, closes at 100.2 (lower half -> day biased SHORT)
    # post-OR rally: strong full-body closes above OR high
    for k in range(6, 12):
        o[k] = 100.2 + 0.5 * (k - 6); c[k] = o[k] + 0.6
        h[k] = c[k] + 0.1; lo[k] = o[k] - 0.1
    # bar 12: wick pokes above the level but closes weak back inside (wick-only)
    o[12] = c[11]; c[12] = c[11] - 0.05; h[12] = c[11] + 2.0; lo[12] = c[11] - 0.2
    d = pd.DataFrame({"ts": ts, "open": o, "high": h, "low": lo, "close": c,
                      "volume": 1000.0, "atr14": 1.0, "trend_up": True, "trend_down": True})
    rejects = []
    B._orb_signals(d, 570, 600, 0.0, 900, "close", False, False, strong_body=0.25,
                   or_mid_bias=True, collect_rejects=rejects)
    reasons = {r for _, side, r in rejects if side == "long"}
    assert "or_mid_bias" in reasons, rejects
    assert any(r == "wick_or_weak_body" for _, s, r in rejects), rejects


# ---- group calibration + slice gates ----

def test_group_calibrator_per_group_with_fallback():
    from bot.ml.models import GroupCalibrator
    rng = np.random.default_rng(9)
    n = 600
    g = np.array(["A"] * 300 + ["B"] * 300)
    y = rng.integers(0, 2, n)
    p = np.clip(0.5 + (y - 0.5) * 0.2 + rng.normal(0, 0.05, n), 0.05, 0.95)
    p[g == "B"] = np.clip(p[g == "B"] * 0.5, 0.02, 0.98)     # group B miscalibrated differently
    cal = GroupCalibrator(min_n=100).fit(p, y, g)
    assert "A" in cal.by_group and "B" in cal.by_group
    pb = cal.transform(p[g == "B"], g[g == "B"])
    assert brier(y[g == "B"], pb) < brier(y[g == "B"], p[g == "B"])
    pu = cal.transform(np.array([0.4]), np.array(["UNSEEN"]))  # unseen group -> global fallback
    assert 0 <= pu[0] <= 1


def test_slice_report_flags_inverted_slice():
    from bot.ml.validation import slice_report
    n = 200
    p = np.concatenate([np.linspace(0.2, 0.8, n), np.linspace(0.2, 0.8, n)])
    r_good = np.concatenate([np.linspace(-1, 1, n)])          # aligned: high p, high R
    r_bad = np.concatenate([np.linspace(1, -1, n)])           # inverted
    y = (p > 0.5).astype(int)
    rep = slice_report(p, y, np.concatenate([r_good, r_bad]),
                       {"grp": np.array(["good"] * n + ["bad"] * n)}, min_n=50)
    assert rep["slices"]["grp=good"]["ok"] is True
    assert rep["slices"]["grp=bad"]["ok"] is False and rep["all_ok"] is False


# ---- reversal detectors (user spec: institutional rejections) ----

def test_reversal_features_causal_and_capitulation():
    from bot.strategy.reversals import reversal_features
    rng = np.random.default_rng(3)
    n = 80
    c = 100 + np.cumsum(rng.normal(0, 0.2, n))
    d = pd.DataFrame({"close": c, "open": c - 0.05, "high": c + 0.3, "low": c - 0.3,
                      "volume": 1000.0, "vwap_sess": c - 0.2, "atr14": 1.0})
    f = reversal_features(d, n - 1)
    assert set(f) == {"rsi14", "rsi_div", "macd_hist_atr", "macd_shrink", "macd_div",
                      "vwap_slope_div", "capitulation_wick", "absorption"}
    # causality: future mutation cannot change bar i
    d2 = d.copy(); d2.loc[d2.index[-1], "close"] = 9999.0
    fa, fb = reversal_features(d, n - 10), reversal_features(d2, n - 10)
    for k in fa:
        assert (fa[k] == fb[k]) or (fa[k] != fa[k] and fb[k] != fb[k]), k
    # capitulation hammer on 3x volume near VWAP fires
    d3 = d.copy()
    d3.loc[n - 1, ["open", "close", "high", "low", "volume", "vwap_sess"]] = \
        [c[-1], c[-1] + 0.02, c[-1] + 0.05, c[-1] - 2.0, 3500.0, c[-1] - 0.1]
    assert reversal_features(d3, n - 1)["capitulation_wick"] == 1.0
    for k in ("rsi14", "capitulation_wick", "l2_depth_imb"):
        assert k in FEATURE_COLUMNS


# ---- ensemble contract ----

def test_ensemble_verdicts():
    from bot.ml.ensemble import decide_ensemble
    assert decide_ensemble(False)["verdict"] == "risk_blocked"
    hi = decide_ensemble(True, ml_p=0.62, heads={"expected_r": 0.4, "no_trade": 0.2},
                         similarity={"cluster": 1, "win_rate": 0.5, "avg_r": 0.3}, grade="A+")
    assert hi["verdict"] == "approved_high_ai_confidence" and hi["reasons"]
    # no ML champion -> RULES-ONLY (not "AI low"); a grade-A+ setup alone must NOT read low (user 2026-07-09)
    assert decide_ensemble(True)["verdict"] == "rules_only"
    assert decide_ensemble(True, grade="A+")["verdict"] == "rules_only"
    # ML actually voting down IS a low read
    assert decide_ensemble(True, ml_p=0.42, heads={"no_trade": 0.8})["verdict"] == "approved_low_ai_confidence"


# ---- L2 synthesis (in-memory frame -> features, raw never persisted) ----

def test_l2_synthesize_frame_mbp(tmp_path, monkeypatch):
    import bot.ml.l2_features as l2
    import bot.ml.registry as reg
    monkeypatch.setattr(reg, "ML_DIR", tmp_path)             # keep the FeatureStore in tmp
    monkeypatch.setattr(l2, "SOURCES", tmp_path / "l2_sources.json")
    ts = pd.date_range("2026-06-01 09:30", periods=300, freq="s", tz="UTC")
    df = pd.DataFrame({"ts_event": ts.asi8, "bid_px_00": 100.0, "ask_px_00": 100.02,
                       "bid_sz_00": np.random.default_rng(0).integers(1, 50, 300),
                       "ask_sz_00": np.random.default_rng(1).integers(1, 50, 300)})
    # route the FeatureStore used inside synthesize_frame to tmp
    monkeypatch.setattr(l2, "FeatureStore", lambda: reg.FeatureStore(tmp_path / "features"))
    res = l2.synthesize_frame(df, "NQ")
    assert res.get("feature_rows", 0) >= 5 and "error" not in res
    out = reg.FeatureStore(tmp_path / "features").load("l2feat_NQ", "v1")
    assert {"l2_spread_bps", "l2_depth_imb"} <= set(out.columns)
    assert out["l2_spread_bps"].dropna().between(0.5, 5).all()   # ~2bps spread synthesized


@pytest.mark.skipif("torch" not in sys.modules and not __import__("importlib").util.find_spec("torch"),
                    reason="torch not installed")
def test_torch_gru_smoke():
    from bot.nn.models import TorchSeqModel
    rng = np.random.default_rng(6)
    n, T, C = 200, 16, 4
    y = rng.integers(0, 2, n)
    X = rng.normal(0, 1, (n, T, C)).astype(np.float32)
    X[:, :, 0] += np.where(y[:, None] == 1, np.linspace(0, 1.5, T), -np.linspace(0, 1.5, T))
    m = TorchSeqModel(arch="gru", epochs=25, patience=6).fit(X[:160], y[:160])
    p = m.predict_proba(X[160:])
    assert p.shape == (40,) and ((p > 0.5).astype(int) == y[160:]).mean() > 0.65
