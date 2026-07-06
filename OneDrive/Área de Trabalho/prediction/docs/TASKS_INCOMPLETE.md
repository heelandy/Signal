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
| Entry-parameter sweep (best-combination search) | ✅ | per-asset champions adopted (all 7/7 gauntlet); `--tf` pass-through for the 15m lineage |
| VWAP-reversal detectors (RSI/MACD div, slope div, capitulation, absorption) | ✅ features | in the 59-col schema; expectancy gauntlet as filters ❌ |
| AUTO TP1 scale-out | ✅ | "Scale 50% @ TP1 → BE → TP2" exit mode — TV compile pending |
| Target-geometry study (ultimate goal WR85/PF1.8/45t-$4) | ✅ | run kind `geometry`; **no cell meets goal yet** — see DEVELOPMENT_PLAN §0 |
| Futures high-WR search (NQ ≥75% ask) | ✅ research | run kind `nqwr` + `nq_scratch.py`: NQ hits 75-81% WR only at 2×ATR stops and PF ≤ 0.91 — profitable ≥75% needs the loser-veto model (~24% of losers) |
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
| Live similarity scoring on proposals | ✅ | families.py live 64-bar scoring; clusters PROMOTED (first live model) |
| Threshold-usage study (P(win) cutoff expectancy lift) | ✅ | button 10; verdict so far: no reliable top-bucket lift |
| Transformer / TFT / MoE | ✅ built | in the NN zoo; none past gates yet |
| **P(win)/heads/no-trade champion past gates** | ❌ | **the blocker** — best AUC per sym 0.50–0.55, Brier never beats base rate; identical data → identical result each cycle (cont-training now skips unchanged data). Needs NEW data: L2 sync, live labels, 15m lineage |

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
| Scalping/swing module research | 🟡 | swing 1d/1w triple-barrier datasets build; swing rules + gauntlet next; scalp blocked on L2 |
| CI pipeline + requirements.txt | ✅ | GitHub Actions pytest + 88 pins |
| Repo hygiene | 🟡 | tracker WAL+busy_timeout ✅ · 90-day report retention ✅ · **OneDrive move ❌ (user's hands — Webull token in BOT/conf is cloud-synced)** · research/→tools split ❌ |
| Continuous training skip-unchanged-data | ✅ | dataset signature per cycle; ml/nn run only when rows/span move |
| AITP phases 6–8 | 🟡 | phase 6 unlocked (approve + paper); 7–8 blocked on paper results by design |
