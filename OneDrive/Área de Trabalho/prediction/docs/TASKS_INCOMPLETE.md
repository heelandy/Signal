# Partial & incomplete tasks — living checklist (updated 2026-07-05)

Status of every feature requested in the strategy/platform docs vs implementation. Update on every
move. Scope rule: only STACK/AUTO Pines + BOT receive code changes by default.

Legend: ✅ done · 🟡 partial · ❌ not started · ⏸ deferred by user

## Entry standard / strategy rules

| Item | Status | Notes |
|---|---|---|
| Canonical ARMED→WATCH→FILL on all surfaces | ✅ | STACK TV-compiled; AUTO compile pending |
| Cooldown / stale-range / two-entry / hard-invalidation | ✅ | A/B validated, adopted |
| Per-asset Layer-1 context (equities ON / futures OFF) | ✅ | |
| Entry-parameter sweep (best-combination search) | ✅ | SPY candidate (cd0/stale12/retest0.25, OOS +0.753 vs +0.572) awaits gauntlet |
| VWAP-reversal detectors (RSI/MACD div, slope div, capitulation, absorption) | ✅ features | in the 59-col schema; expectancy gauntlet as filters ❌ |
| AUTO TP1 scale-out | 🟡 | still TP2-bracket only |
| OPTIONS/V1/MTF on the new standard | ⏸ | scope rule |

## Pullback deep-research — ⏸ ALL DEFERRED BY USER ("do the pullback last")

min-depth · impulse-midpoint · VWAP-retest variant · %OR-width depth · tighter extension threshold ·
pullback timeout · relative-volume confirm · side risk budget · gap rules · microstructure retest.

## ML platform (MLP-001)

| Item | Status | Notes |
|---|---|---|
| PIT feature store (59 features incl. reversal + l2_*) | ✅ | train/live parity |
| Purged WF + calibration + gates + pooled ALL | ✅ | |
| Rejected-setup labels | ✅ | 126k rows across QQQ/SPY/NQ/ES |
| Multi-head models (tp2/stop/expected-R/no-trade) | ✅ built | none passed gates yet (tp2 AUC 0.641, IC 0.117 — closest) |
| No-trade model | ✅ built | AUC 0.546 vs 0.55 gate — retrain with reversal+L2 features |
| Per-symbol/side/session calibration | ✅ | GroupCalibrator (wire into pipeline champion path when a model passes) |
| Per-slice validation gates | ✅ helper | `slice_report` — enforce in pipeline promotion next |
| NN similarity clusters | ✅ | OOS spread-holds gate; auto-serves when it passes |
| Ensemble decision layer | ✅ | `ai_decision` on every live proposal |
| ML/NN explanations on live signals | ✅ | `ml_explain` + heads on proposals (render in main dashboard UI 🟡) |
| L2/L3 depth data → features | ✅ pipeline | register path / drag-drop; awaiting your real depth files |
| Live similarity scoring on proposals | ❌ | needs live 64-bar sequence builder |
| Threshold-usage study (P(win) cutoff expectancy lift) | ❌ | |
| Transformer / TFT / MoE | ❌ | after baselines pass gates |

## Platform / governance (AITP-001)

| Item | Status | Notes |
|---|---|---|
| Data QA · rule freeze · approval ladder (+ live stage) · manual promotion · continuous training · Training Lab | ✅ | |
| Backtest report matrix (year/regime/DOW/hour/side) | ✅ | `/api/training/report_matrix` |
| Cost stress (2× slip / latency ticks / 90% partial fills) | ✅ | **ES negative at 2× slip — no live sizing until execution measured** |
| Replay-parity report | ✅ | 100% exact, 4 symbols |
| Unified audit trail | ✅ | `BOT/data/audit.jsonl` + `/api/audit` |
| Post-trade learning queue → training rows | ✅ | `live_labels` (PIT snapshots ride with decisions from now on) |
| Risk lockouts (weekly loss, streak, correlated buckets) | ✅ | + daily/trailing/kill/news from before |
| Strategy-module registry (asset class × style contract) | ✅ | 4 implemented, 4 spec_only |
| Paper→live path documented + double live gate | ✅ | docs/PAPER_TO_LIVE.md |
| Scalping/swing module research | ❌ | spec_only stubs registered |
| CI pipeline + requirements.txt + repo hygiene | ❌ | see docs/ENGINEERING_AUDIT.md |
| AITP phases 6–8 | 🟡 | phase 6 unlocked (approve + paper); 7–8 blocked on paper results by design |
