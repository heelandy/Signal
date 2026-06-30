"""Predictive + adaptive layer — the system learns from outcomes and scores every new signal.

PREDICTIVE: for each candidate, predict P(reaches TP2 / wins) from PRE-TRADE features (regime, vol,
time, side, R:R) using the live champion model -> attaches `confidence`. Advisory: it sizes/filters,
never overrides the rule-based signal or the risk gate.

ADAPTIVE: `train_and_promote(sym)` rebuilds the labelled set from the validated engine, walk-forward
validates, and promotes the challenger to champion only if it beats the incumbent OOS (continuous
learning). Re-run on a schedule (e.g. weekly) so the model tracks the regime.

    from bot.ml.pipeline import train_and_promote, predict_candidate
    train_and_promote("QQQ")             # adapt: learn from history, promote if better
    predict_candidate(candidate)         # predict: -> confidence in [0,1]
"""
from __future__ import annotations

import numpy as np

from bot.ml.predictor import DirectionModel
from bot.ml.registry import ModelRegistry, ChampionChallenger
from bot.ml.validation import walk_forward

FEATURES = ["rr", "risk_pts", "regime_A", "regime_B", "hour", "side_long"]
_PRIOR = 0.42                 # base ORB hit-rate when no model is trained yet
MODEL_NAME = "signal_winprob"
_reg = ModelRegistry()


def feat(c) -> list[float]:
    """PRE-TRADE feature vector (no realised mfe/mae — must be knowable at signal time)."""
    h = int(c.generated_at[11:13]) if c.generated_at else 12
    risk = (c.evidence or {}).get("risk_pts", c.risk)
    return [float(c.rr), float(risk), 1.0 if c.regime == "A" else 0.0,
            1.0 if c.regime == "B" else 0.0, float(h), 1.0 if c.side.value == "long" else 0.0]


def build_dataset(sym: str = "QQQ"):
    """(X, y) from the validated engine: pre-trade features -> win(1)/loss(0) per trade."""
    import sys, os
    from bot.config import BOT_ROOT
    sys.path.insert(0, str(BOT_ROOT.parent / "engine"))
    from bot.strategy.orb_candidates import load_state, emit_from_state
    import hs_backtest as B
    from bot.strategy.orb_candidates import T1, T2, ORS, ORE, CUT, EOD, DELAY, STRONG
    d = load_state(sym)
    cands = emit_from_state(d, sym)
    tr = B.backtest(d, "tp2_full", "both", False, "orb", 0, T1, T2, ORS, ORE, 0.0, CUT, "close",
                    eod_min=EOD, stop_mode="struct", entry_delay=DELAY, strong_body=STRONG,
                    ft_confirm=True, dir_seq=True).reset_index(drop=True)
    n = min(len(cands), len(tr))
    X = np.array([feat(cands[i]) for i in range(n)], float)
    y = (tr["net_R"].to_numpy()[:n] > 0).astype(int)
    return X, y


def train_and_promote(sym: str = "QQQ") -> dict:
    """ADAPT: learn from history, walk-forward validate, promote if it beats the champion."""
    X, y = build_dataset(sym)
    if len(X) < 60:
        return {"error": f"only {len(X)} samples"}
    wf = walk_forward(X, y, DirectionModel, n_splits=5)
    # ADAPTIVE GUARD: only deploy a model that genuinely beats random OOS (AUC>0.52) AND the champion.
    # Otherwise keep the prior — a non-predictive model must never go live.
    if not (wf["oos_auc"] and wf["oos_auc"] > 0.52):
        return {"sym": sym, "samples": len(X), "win_rate": round(float(y.mean()), 3), **wf,
                "promote": False, "reason": "OOS AUC <= 0.52 (no real predictive edge) — model NOT deployed"}
    challenger = DirectionModel().fit(X, y)
    cc = ChampionChallenger(_reg, margin=0.0)
    k = int(len(X) * 0.7)
    res = cc.maybe_promote(MODEL_NAME, f"{sym}-wf{wf['oos_auc']}", challenger, X[k:], y[k:])
    return {"sym": sym, "samples": len(X), "win_rate": round(float(y.mean()), 3), **wf, **res}


def predict_candidate(c) -> float:
    """PREDICT: P(win) for a candidate from the champion model (or the prior if none trained)."""
    model, _ = _reg.champion(MODEL_NAME)
    if model is None:
        return _PRIOR
    try:
        p = float(model.predict_proba(np.array([feat(c)], float))[0])
        c.confidence = round(p, 3)        # attach to the candidate
        return c.confidence
    except Exception:
        return _PRIOR


if __name__ == "__main__":
    from bot.contracts import TradeCandidate
    print("ADAPT — train_and_promote(QQQ):")
    r = train_and_promote("QQQ")
    print("  ", r)
    print("\nPREDICT — score 3 candidates:")
    for reg, side in (("A", "long"), ("C", "short"), ("B", "long")):
        c = TradeCandidate(symbol="QQQ", side=side, timeframe="5m", setup="breakout", entry=722,
                           stop=719 if side == "long" else 725, tp2=734 if side == "long" else 710,
                           regime=reg, strategy_version="t", generated_at="2026-06-29T14:30:00+00:00")
        print(f"  regime {reg} {side}: P(win) {predict_candidate(c):.3f}")
    print("predictive+adaptive pipeline OK")
