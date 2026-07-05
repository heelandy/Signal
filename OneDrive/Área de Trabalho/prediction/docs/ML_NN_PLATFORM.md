# ML / NN Platform — architecture, gates and current results (2026-07-04)

Rules decide whether a trade is **legal**. ML decides whether the legal trade is **high quality**.
The NN decides whether the setup **resembles past winners**. Risk decides whether the trade is
**allowed**. Models are advisory — they size and filter, they never override the rule engine or
the risk gate, and a model that fails any promotion gate never goes live (the system falls back
to the base-rate prior).

Everything trains against ONE rule version at a time: `bot.strategy.orb_candidates.STRATEGY_VERSION`
(`orb-standard-2026.07` — see [ENTRY_STANDARD.md](ENTRY_STANDARD.md)). The registry pins the rule
version + feature schema to every artifact and refuses to score on a schema mismatch.

---

## Pipeline map

```text
canonical replay (orb_candidates.run_backtest — the ONE backtest call)
        │
        ├── bot/ml/dataset.py      one row per executed candidate:
        │                          PIT features (bot/ml/features_pit.py) + labels
        │                          → FeatureStore parquet keyed by strategy version
        │
        ├── bot/ml/pipeline.py     model zoo → PURGED walk-forward (embargo) → calibrate on
        │                          pooled OOS preds → HARD GATES → champion-challenger → registry
        │
        ├── bot/nn/dataset.py      one [64 bars x 11 channels] causal sequence per candidate
        │                          (shorts mirrored onto the long frame — one pattern language)
        └── bot/nn/train.py        NN zoo → same purged WF → same gates → registry ("nn_winprob")

live scan (families.scan) ── attaches the SAME pit_features snapshot to every signal
        └── live.py ── predict_candidate(c, feats=snapshot) → calibrated P(win) on the proposal
```

## Governance (AITP-001, added 2026-07-04 late)

- **Approval ladder** (`bot/approval.py`): research → replay → paper per strategy version, manual
  + revocable, evidence auto-collected. **Paper autotrade is hard-blocked** without the paper
  approval. Live remains config-locked regardless.
- **Model promotion is manual on governed runs**: `--no-promote` (used by continuous training)
  registers gate-passing challengers as PENDING; you promote from the Training Lab
  (`/api/training/approve_model`). Direct CLI runs still auto-promote for research convenience.
- **Continuous training**: web-controlled worker (Training Lab → Continuous panel, or
  `POST /api/training/continuous?on=1&interval_min=360&syms=QQQ,SPY,NQ,ES,ALL`) cycling
  dataset → ML → NN per symbol, always `--no-promote`, with per-job history.

## Pooling + rejected setups (added 2026-07-04 late)

- `sym="ALL"` trains the **pooled multi-symbol set** (~2,070 candidates vs 312 QQQ-only);
  identity rides in 6 schema features (sym_* one-hots + is_futures; 45 features total).
- `dataset.build_rejects(sym)` captures every **blocked trigger** with its first failing gate
  (context / no_watch / cooldown / range_stale / pullback_wait / chase_guard / dir_seq /
  or_mid_bias / narrow_or / wick_or_weak_body) + a first-touch hypothetical outcome →
  missed_winner / missed_loser labels (stored separately; feeds the future no-trade model).
- Data quality: `pipeline/hs_data_qa.py` — all 5 symbols clean (run `kind=dataqa` to refresh).

## Features (45, point-in-time — `bot/ml/features_pit.py`)

Groups: side/risk geometry · OR geometry (width/ATR, price vs edge & mid, hours since OR close) ·
VWAP (distance, slope, side) · structure (state one-hot, distance to the protective swing) ·
**Layer-2 slope quality** (combined slope engine S, components, persistence, efficiency, grade
ordinal) · candle anatomy (body/wick fractions) · momentum/volatility (ATR-normalized returns,
ATR%, ATR expansion, relative volume) · regime (macro A–D, local trend/range/volatile) ·
session/time (hour sin/cos, weekday).

Guarantees (unit-tested in `BOT/tests/test_ml_platform.py`):
- **Causal** — mutating future bars cannot change a snapshot.
- **No realized outcomes** — mfe/mae/hold-bars are labels only, banned from the schema by test.
- **Train/live parity** — the identical function builds the training rows and the live snapshot.

## Labels (`bot/ml/dataset.py`)

`y_win` (net_R > 0), `y_tp2` (full 4R cap), `y_stop` (~ −1R), plus `net_r / gross_r / mfe_r /
mae_r / hold_bars` for expectancy-by-bucket validation and analysis. Rejected/no-trade situations
are visible through the live journal (risk verdicts + why-strings); extending the dataset with
rejected setups is the next labeling step.

## Models

- **Tabular zoo** (`bot/ml/models.py`): numpy logistic (always), sklearn LogReg / RandomForest /
  HistGB, LightGBM, XGBoost (installed), CatBoost (optional) — one `fit/predict_proba` wrapper,
  train-median NaN imputation.
- **Calibration** (`PlattCalibrator` / `IsotonicCalibrator`): fitted on **pooled out-of-sample**
  walk-forward predictions, never on training fits — "0.72 should mean ~72%".
- **NN zoo** (`bot/nn/models.py`): dependency-free NumpyMLP baseline + torch MLP / 1D-CNN / GRU /
  LSTM / CNN-GRU (CPU wheel installed). Channel standardization on train stats, chronological
  validation tail, early stopping, gradient clipping. Transformer/TFT/MoE stay on the research
  roadmap until these baselines prove out.

## Validation + promotion gates (`bot/ml/validation.py`, applied in both pipelines)

1. **Purged walk-forward** with embargo (boundary samples dropped from training).
2. **OOS AUC > 0.52** — otherwise "no real predictive edge, NOT deployed".
3. **OOS Brier < base-rate coin** — probabilities must beat always-predict-the-win-rate.
4. **Bucket expectancy hard rule** — calibrated high-confidence trades must out-earn
   low-confidence trades in OOS expected R (`monotone_ok`).
5. **Champion-challenger** on a frozen last-30 % holdout; promotion writes metrics, feature
   schema and strategy version to the registry (`bot/ml/registry.py`).

Scheduled retraining = re-run `train_and_promote(sym)` / `train_and_promote_nn(sym)` weekly.
No uncontrolled online learning into live models.

## Explainability (`bot/ml/explain.py`)

Per-candidate `{top_positive, top_negative, method}` via SHAP (tree models, if installed) →
signed linear contributions (logistic) → local perturbation (any model). Global permutation
importance included. `pipeline.explain_last_champion(feats)` serves the dashboard/journal.

## Current honest results (2026-07-04)

| Run | Samples | Best OOS AUC | Brier vs base | Gate verdict |
|---|---:|---|---|---|
| ML QQQ-only | 312 | 0.535 (xgb) | 0.292 / 0.231 | NOT deployed (Brier miss 0.061) |
| NN QQQ-only | 312 | 0.487 (np_mlp) | — | NOT deployed (AUC ≤ 0.52) |
| **ML pooled ALL** | 2,073 | 0.531 (logit) | 0.2417 / 0.2367 | NOT deployed (Brier miss 0.005) |
| **NN pooled ALL** | 2,073 | **0.556 (torch GRU)** | 0.2396 / 0.2367 | NOT deployed (Brier miss **0.003**) |

Pooling worked: every torch sequence model cleared the AUC gate (GRU 0.556, CNN-GRU 0.551, LSTM
0.550) and the Brier miss shrank 20× — the **calibration gate is now the binding constraint**, not
discrimination. The gates keep everything out of production until it's genuinely useful (live
scoring stays on the prior). Next levers, in order:

1. **No-trade class from the rejects store** (~47k labeled blocked setups already built — QQQ 22.6k
   + SPY 24.4k; wick/context/entries-done/range/pullback reasons + missed_winner labels).
2. **Class weights / focal loss + isotonic per-regime** to close the last 0.003 Brier gap.
3. Per-side / per-session / per-regime validation slices (promote only if no slice collapses).
4. Threshold-only usage study: even an uncalibrated 0.556-AUC GRU may add expectancy as a
   top-bucket filter — evaluate expected-R lift at P(win) cutoffs before more architecture work.
5. Only then Transformer / mixture-of-experts.

## How to run

```bash
# labeled dataset + feature store
python -m bot.ml.dataset QQQ
# tabular zoo → gates → (maybe) promote a champion
python -m bot.ml.pipeline QQQ
# sequence dataset + NN zoo
python -m bot.nn.dataset QQQ
python -m bot.nn.train QQQ            # or: python -m bot.nn.train QQQ torch_gru,torch_cnn
# tests
python -m pytest BOT/tests -q
```
