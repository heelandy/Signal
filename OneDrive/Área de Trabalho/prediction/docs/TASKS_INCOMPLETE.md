# Partial & incomplete tasks — living checklist (updated 2026-07-06)

Status of every feature requested in the strategy/platform docs vs implementation. Update on every
move. Scope rule: only STACK/AUTO Pines + BOT receive code changes by default.

Legend: ✅ done · 🟡 partial · ❌ not started · ⏸ deferred by user

## Entry standard / strategy rules

| Item | Status | Notes |
|---|---|---|
| Canonical ARMED→WATCH→FILL on all surfaces | ✅ | rule 07.7 (F78) — STACK + AUTO TV compile pending |
| Cooldown / stale-range / two-entry / hard-invalidation | ✅ | A/B validated, adopted |
| Per-asset Layer-1 context (equities ON / futures OFF) | ✅ | |
| Entry-parameter sweep (best-combination search) | ✅ | per-asset champions adopted (all 7/7 gauntlet); `--tf` pass-through for the 15m lineage |
| VWAP-reversal detectors (RSI/MACD div, slope div, capitulation, absorption) | ✅ | in the 59-col schema; expectancy gauntlet as filters RUN (v6, `reversal_filters.py`): NO detector qualifies as a hard veto on any symbol (veto cohorts positive OOS) — they stay model features |
| AUTO TP1 scale-out | ✅ | "Scale 50% @ TP1 → BE → TP2" exit mode — TV compile pending |
| Target-geometry study (ultimate goal WR85/PF1.8/45t-$4) | ✅ | run kind `geometry`; **no cell meets goal yet** — see DEVELOPMENT_PLAN §0 |
| Futures high-WR search (NQ ≥75% ask) | ✅ research | run kind `nqwr` + `nq_scratch.py`: NQ hits 75-81% WR only at 2×ATR stops and PF ≤ 0.91 — profitable ≥75% needs the loser-veto model (~24% of losers) |
| OPTIONS/V1/MTF on the new standard | ⏸ | scope rule |

## Pullback deep-research — ✅ CLOSED 2026-07-06 (F78, the "purple" block → rule 07.7)

All ten items cohort-tested vs the live-identical base (`research/pullback_deep.py`):

| Item | Verdict |
|---|---|
| Impulse-midpoint retest | ✅ tested — **ADOPTED NQ/MNQ** (+13.5R, better DD) |
| Extension threshold (chase sweep) | ✅ tested — **ADOPTED NQ/MNQ 1.0→1.5** (+20.7R, same DD); tighter (0.5/0.75) loses |
| Pullback timeout | ✅ tested — confirmed 8 = local optimum (4 and 16 both lose) |
| min-depth (ATR) | ✅ tested — no-op at 15m (zero trade diff) — stays 0.05 |
| VWAP-retest variant | ✅ tested — REJECTED (blocked cohort +0.305×26 on NQ) |
| %OR-width depth | ✅ tested — REJECTED (drops winners, admits losers) |
| Relative-volume confirm | ✅ tested — REJECTED every symbol (QQQ 158→115R, NQ 258→58R at 1.2×) |
| Side risk budget | ✅ tested — REJECTED (NQ's 3rd entry after two losses WINS +0.191×141) |
| Gap rules | ✅ tested — REJECTED (every blocked-day cohort positive) |
| Microstructure (reclaim) retest | ✅ tested — REJECTED (lost cohort +0.559×12) |

All ten items are COMPLETE — a REJECTED verdict is a finished study (the gate costs money),
not an open task. Re-testing them requires NEW data or a NEW rule version, nothing else.

Combined NQ verify: **257.6→283.8R, PF 1.36, DD unchanged**. QQQ/SPY/ES byte-identical
(refined pullback still forfeits more than it saves there — chase stays 0).

## ML platform (MLP-001)

| Item | Status | Notes |
|---|---|---|
| PIT feature store (59 features incl. reversal + l2_*) | ✅ | train/live parity |
| Purged WF + calibration + gates + pooled ALL | ✅ | |
| Rejected-setup labels | ✅ | 126k rows across QQQ/SPY/NQ/ES |
| Multi-head models (tp2/stop/expected-R/no-trade) | ✅ built | none passed gates yet (tp2 AUC 0.641, IC 0.117 — closest) |
| No-trade model | ✅ built | AUC 0.546 vs 0.55 gate — retrain with reversal+L2 features |
| Per-symbol/side/session calibration | ✅ | GroupCalibrator (wire into pipeline champion path when a model passes) |
| Per-slice validation gates | ✅ | `slice_report` ENFORCED in promotion (`pipeline.py`: any inverted symbol/side/year slice → promote=False) |
| NN similarity clusters | ✅ | OOS spread-holds gate; auto-serves when it passes |
| Ensemble decision layer | ✅ | `ai_decision` on every live proposal |
| ML/NN explanations on live signals | ✅ | `ml_explain` + heads on proposals AND rendered on the main dashboard (2026-07-06): hover P(win) → "why" top for/against drivers; hover eR → all four head reads |
| L2/L3 depth data → features | ✅ pipeline | 2026-07-06 misconfig sweep on the REAL Databento files (D:\XNAS-…): 4 sources relabeled NQ→QQQ (XNAS ITCH is the Nasdaq equities book — files verified QQQ-only), 10 unregistered files (May 26–Jun 8, OVERLAPPING the bar store) registered, synthesis now symbol-filtered (full-venue files can't contaminate) + duckdb memory-capped (spills, no more OOM). Store rebuilt clean; QQQ dataset re-joined; further overlap needs the bar-store refresh past Jun 9 |
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
| Scalping/swing module research | 🟡 | SWING DONE: equities QQQ pullback + NQ breakout both 7/7 gauntlet → lineages swing-1d-0.1 / swing-fut-1d-0.1 (approvable, in the duel). SCALP still blocked on L2 bar-store overlap (external data — your depth files vs bar refresh) |
| CI pipeline + requirements.txt | ✅ | GitHub Actions pytest + 88 pins |
| Repo hygiene | 🟡 | tracker WAL+busy_timeout ✅ · 90-day report retention ✅ · **OneDrive move ❌ (user's hands — Webull token in BOT/conf is cloud-synced)** · production→research import REMOVED ✅ (zone engine promoted to `bot.strategy.liquidity_zones`, shim left for research drivers, 2026-07-06) · wholesale research/→tools file split CLOSED won't-do (133 studies cross-referenced by F-numbers + run kinds; moving them breaks references for zero functional gain) |
| Continuous training skip-unchanged-data | ✅ | dataset signature per cycle; ml/nn run only when rows/span move |
| Boss/Workers assembly (WR 75-85 · PF≥1.7 · DD≤10%) | 🟡 | infrastructure LIVE 2026-07-07 (Boss + workers + evolution engine + ladders ×5, F80/F81); **no worker in band yet** — Q closest (OOS in band + 2× stress, IS era blocks); E/G OBSOLETE; paper data is the unlock |
| AITP phases 6–8 | 🟡 | phase 6 unlocked (approve + paper) · **7–8 AUTO-ADVANCE WIRED (2026-07-06, `bot/phase78.py` + `/api/phase78` + hourly tick)**: the paper study evaluates itself (≥60 trades AND ≥8 wks AND scorecard green AND no grade inversion) + phase-7 hardening checks + execution-quality vs 2× stress → 'live' stage advances automatically when all green; LIVE_APPROVED.lock stays manual (double gate); ES excluded. Waiting only on paper data accruing |
