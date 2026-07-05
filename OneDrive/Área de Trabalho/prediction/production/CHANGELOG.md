# production/ — change log

Structured record of changes to the live Pine set. Newest first. See `../research/RESEARCH_NOTES.md`
for the F-number research behind each item.

---

## 2026-07-05 (v3) — 07.2 VERIFIED: parity 100% · similarity clusters PROMOTED (first live model) · QQQ + NQ gauntlet adoptions · triples lose to pairs · auto-reload launcher · CI

* **07.2 verification chain** (research/verify_072.py — parity → matrix → similarity → 8 combos →
  sweep): parity **100% all four symbols**; cost stress — QQQ +0.424 / SPY +0.448 robust,
  NQ +0.189 holds 2× slip (+0.112), **ES still negative at 2× slip (stays barred)**.
* **SIMILARITY CLUSTERS PROMOTED** — OOS winner-vs-loser spread held → the first model live:
  every proposal now carries its nearest-pattern-cluster read; it votes in the ensemble.
* **DIR-fast 8 combos (incl. the 3 triples)**: no triple beats the adopted pairs — equities
  STRUCT(+VWAP), futures MID+VWAP confirmed.
* **Gauntlet adoptions (both 7/7)**: QQQ cd5/stale12/retest0.25 (OOS +0.419 vs +0.374, PF 1.66,
  DD −6.2 vs −9.1R) and NQ/MNQ cd0/stale12/retest0.25 (OOS +0.117 vs +0.109, DD −9.8 vs −11.1R).
  Both trade FEWER times (quality over volume) — revert per-asset overrides to restore volume.
  Sweep/gauntlet defaults now honor per-asset overrides (SPY baseline was understated).
* **Ops**: `BOT/run_server.bat` (uvicorn --reload = new code runs on save), BOT_CONT_TRAINING=1
  auto-arms continuous training on boot, /api/health carries strategy_version,
  `requirements.txt` (88 pins), GitHub Actions pytest workflow.

---

## 2026-07-05 (v2) — RULE orb-standard-2026.07.2: INSTANT FILL when aligned · frozen bias superseded · grade ladder v2 · DIR-fast A/B · crypto weekends · VWAP plot · security fix

⚠️ STACK changed again — **TradingView compile-check needed**. **121 tests green.**

* **INSTANT FILL (user rule)**: when the arming pair is aligned AND price is beyond the mid, the
  strong full-body breakout candle FILLS IMMEDIATELY — the F59c next-candle wait now applies only
  to UNALIGNED setups (engine `instant_aligned`, STACK `instant_fill` input, default ON).
  **Per-asset A/B on the rebuilds**: NQ +0.163→+0.189 avg R on MORE trades (clear win), QQQ/SPY
  total-R neutral, **ES +0.090→+0.057 (worse)** → `Asset.instant_fill=False` for ES (keeps the
  continuation wait); on an ES TV chart turn the input OFF (tooltip says so).
* **Frozen OR-mid day bias SUPERSEDED by the live mid** on mid-armed assets (user screenshots:
  'OR-mid: short day' blocked a live-aligned long). STACK: bias applies only on the STRUCT+VWAP
  (B) pair; BOT mirrors via ctx_mode.
* **GRADE LADDER v2 (user)**: ORMID arms → +VWAP = B → +STRUCT = A → +SLOPE = A+ (cumulative);
  no VWAP = C. STACK `f_grade` + BOT live grade updated.
* **DIR-FAST pairs test run + adopted**: futures arm from MID+VWAP (NQ OOS +0.213 vs +0.104 struct,
  dataset avg +0.155→+0.163; ES +0.153, +0.087→+0.090); equities keep STRUCT+VWAP (QQQ +0.374,
  SPY +0.753). STACK `ctx_source` Auto picks per instrument; dashboards show DIR-A (arming read)
  + DIR-B (fallback composite). 8 possible ORMID-anchored combinations documented; kind=pairs
  re-runs the test.
* **Crypto weekends**: the weekend block no longer applies to `syminfo.type == "crypto"` (BTCUSD
  showed 'RANGE - weekend' and could never arm). **Session VWAP now plottable** (`show_vwap`, on).
* **Kelly**: quarter-Kelly advisory multiple on every proposal (P(win) + realized payoff per
  symbol); main dashboard gained AI verdict + expected-R + ¼K columns.
* **Transformer + MoE** added to the NN zoo (tiny encoder / 3-GRU gated experts) — same gates.
* **Swing datasets live**: tf=1d/1w now build triple-barrier daily/weekly candidates
  (QQQ 1d: 1,484 rows, +0.268R avg) — trainable through the same pipeline.
* **Threshold study** (kind=threshold): current pooled model shows NO reliable top-bucket lift
  (honest negative). **L2 registration**: whole-FOLDER auto-scan + ZIP auto-extract (streamed
  in memory, never written to disk).
* **SECURITY (code review)**: `/api/training/run` symbol was interpolated into a `python -c`
  string — command-injection fixed (argv-passed + whitelist); symbol validated everywhere.
* Training Lab: ET timestamps everywhere, run start-time + elapsed in the status pill, loud
  404 guidance ("restart the server"), per-panel HOW-IT-WORKS guide, approval panel now shows
  WHAT is being approved (rules + evidence + stage meanings), threshold/pairs run buttons.

---

## 2026-07-05 (late) — RULE orb-standard-2026.07.1: pullback refinements ADOPTED · SPY gauntlet-adopted params · FULL GAUNTLET on the UI · multi-TF training · candidate full-detail views

⚠️ STACK + AUTO changed (refinement inputs + watch machine) — **TradingView compile-check needed**
on both. Rule version bumped to **orb-standard-2026.07.1** → datasets/models/approvals re-key
(fresh ladder approvals required — correct governance). **121 tests green.**

* **PULLBACK REFINEMENTS (deep-research doc, un-deferred by user)** in FSM + engine + STACK/AUTO:
  retest TARGET modes (OR edge / impulse midpoint / VWAP), MIN retrace from the extension extreme
  (0.05 ATR anti-spike), pullback TIMEOUT (8 bars → RANGE), relative-VOLUME confirmation on the
  trigger bar (default OFF until gauntleted). Engine params: `retest_mode, min_pullback_atr,
  pullback_timeout, vol_confirm_x`; Pine inputs mirror them.
* **SPY sweep candidate PASSED THE FULL GAUNTLET (7/7)** — cooldown 0 · stale 12 · retest 0.25:
  OOS +0.753 vs default +0.572 avg R, PF 2.40 vs 1.97, win 47.5% vs 40.9%, maxDD −6.1 vs −6.5R,
  survives 2× slip, years consistent, sides clean → **ADOPTED as per-asset overrides**
  (`Asset.cooldown_bars/stale_bars/retest_atr`; BOT reads them everywhere; on a SPY TV chart set
  the three inputs manually). Sweep→gauntlet→adopt pipeline now the standard promotion path.
* **FULL GAUNTLET on the Training Lab**: parameter form (prefilled by clicking any sweep row) →
  `kind=gauntlet` run → verdict + 7 checks + candidate-vs-default table + a full-detail expander
  recording EVERYTHING used (data span/bars/timeframe, IS/OOS split dates, fill rules, cost
  model, per-side results). `research/gauntlet.py`, `/api/training/gauntlet`.
* **Candidate full details everywhere**: sweep report carries a `used` block (span, windows, grid,
  fixed rules, costs); sweep rows click → detail box + gauntlet prefill; training-run rows click →
  full raw report expander.
* **MULTI-TIMEFRAME TRAINING**: dataset/ML/NN accept `--tf=` (1m/3m/5m/15m/30m/1h/2h/4h — 3m/2h/1w
  resampled causally, 1m from the continuous store); Training Lab timeframe selector; per-TF
  dataset stores + report/version tags (`QQQ@15m`). **1d/1w return an explicit "swing module
  (spec_only)" error** — the ORB day replay needs intraday bars; daily/weekly training ships with
  the swing module.
* Runner accepts sanitized extra args (`--tf`, gauntlet params) from the web.

---

## 2026-07-05 — AITP/MLP phase 2: multi-head ML · rejects no-trade model · ensemble verdicts · L2/L3 depth pipeline · reversal detectors · report matrix + cost stress · parity · unified audit · paper→live path

No Pine changes (BOT/platform only). **121 tests green.** Full detail: `docs/TASKS_INCOMPLETE.md`,
`docs/ENGINEERING_AUDIT.md`, `docs/PAPER_TO_LIVE.md`.

* **Sweep verdicts**: SPY candidate combo (ctx ON · cooldown 0 · stale 12 · retest 0.25) beats the
  default OUT-OF-SAMPLE (+0.753 vs +0.572 avg R) — flagged for gauntlet, NOT adopted; QQQ/NQ/ES
  best-IS combos failed OOS → defaults kept (anti-curve-fit gate worked).
* **Multi-head ML** (`bot/ml/heads.py`, kind=heads): tp2_prob (OOS AUC **0.641**), stop_prob
  (0.541), expected_r (rank-IC **0.117**), no_trade on the **126k pooled rejects** (0.546 vs 0.55
  gate) — all correctly gated out, none deployed; the closest signals yet.
* **Rejects everywhere**: QQQ 22.6k + SPY 24.4k + NQ 38.4k + ES 40.8k blocked setups with first-
  failing-gate reasons + hypothetical outcomes (missed_winner/loser).
* **Ensemble decision layer** (`bot/ml/ensemble.py`): every live proposal now carries
  `ai_decision` (risk_blocked / approved_low/high_ai_confidence + reasons), `heads`, `ml_explain`.
* **Reversal detectors** (user spec — `bot/strategy/reversals.py`): RSI level+divergence, MACD
  histogram/shrink/divergence, VWAP slope-momentum divergence, capitulation wick, absorption —
  8 causal features in the schema (now **59 columns** incl. 6 `l2_*`), unit-tested for causality.
* **L2/L3 depth pipeline** (`bot/ml/l2_features.py`): register a PATH on any disk (nothing
  copied — DuckDB reads csv/csv.zst/parquet in place; Databento MBP/MBO/trades auto-detected)
  → per-minute l2_* features into the FeatureStore, joined onto candidates at their signal
  minute. Training Lab: path box + DRAG-AND-DROP zone (dropped files synthesize in memory,
  raw never written). Epoch units auto-detected (ns/µs/ms/s).
* **Risk lockouts**: weekly-loss (2%), correlated-exposure buckets (NQ+QQQ = one nasdaq bet,
  ES+SPY = spx, GC+GLD = gold) added to daily/trailing/streak/kill/news.
* **Unified audit trail** (`bot/audit.py` → `BOT/data/audit.jsonl`, `/api/audit` + panel):
  approvals, model registrations/promotions, paper toggle, kill switch, mode changes, training
  runs, continuous start/stop, L2 registrations.
* **Report matrix + cost stress** (kind=report): slices by year/regime/DOW/hour/side + stress
  (2× slip, 1-2 tick latency, 90% partial fills). **ES flips NEGATIVE at 2× slip (+0.087→−0.098)**
  → ES barred from live sizing until measured execution beats the stress; NQ halves; QQQ/SPY robust.
* **Replay parity** (kind=parity): contract candidates ≡ engine trades — **100.0% exact on all
  4 symbols (2,073/2,073)**.
* **Post-trade learning queue**: PIT snapshots now ride with tracked decisions; `live_labels`
  builds training rows (taken + missed outcomes) into the FeatureStore.
* **Paper→live**: approval ladder extended with a **live** stage; live mode now needs BOTH the
  LIVE_APPROVED.lock file AND the 'live' approval (double gate). Full path: docs/PAPER_TO_LIVE.md.
* **Strategy-module registry** (`bot/strategy/modules.py`, `/api/strategy/modules`): AITP module
  contract for equities/futures/options day-ORB (implemented) + scalping/swing specs (planned).
* **Engineering audit** (`docs/ENGINEERING_AUDIT.md`): top risks — OneDrive syncing 3.9GB of
  data+venv+SQLite, ES stress economics, single-process server state, 110-script research sprawl;
  ranked with actions.

---

## 2026-07-04 (late) — AITP/MLP phase 1: data QA · pooled training · rejected-setup labels · approval gates · continuous training (web-controlled)

STACK compile confirmed on TradingView by the user. Scope rule active: only STACK/AUTO + BOT are
updated; OPTIONS/V1/MTF untouched. Pullback deep-research refinements deliberately deferred (user:
"do the pullback last").

* **Data QA (AITP step 1)**: fixed `engine/hs_db.py` per-view timestamp detection (ts_utc futures /
  ts_et equities — the report no longer crashes on QQQ/SPY); new `pipeline/hs_data_qa.py` DuckDB
  report (dupes, bad candles, calendar gaps, bars/day completeness) — ALL 5 SYMBOLS CLEAN
  (~1.25M RTH 5m bars checked). Served at `/api/training/dataqa` + a Training Lab panel.
* **Pooled multi-symbol training (MLP-001)**: 6 symbol-identity features added to the PIT schema
  (45 total: sym_* one-hots + is_futures), `dataset.build_pooled()` + `bot.ml.pipeline ALL` and
  pooled NN sequences (`bot.nn.train ALL`) — chronologically interleaved so purged walk-forward
  stays honest. NQ/ES datasets now reflect their adopted layer3-only entry (ctx grade-only).
* **Rejected-setup capture (MLP-001 §2)**: `_orb_signals(collect_rejects=...)` records every bar
  where the breakout trigger fired but a gate blocked (first failing gate: context/no_watch/
  cooldown/range/pullback_wait/chase/dir_seq/or_mid_bias/narrow_or/wick_or_weak_body) +
  `dataset.build_rejects()` adds PIT features and a first-touch HYPOTHETICAL outcome →
  missed_winner/missed_loser labels, stored per symbol in the FeatureStore.
* **Approval workflow (AITP governance)**: `bot/approval.py` — research → replay → paper ladder
  per strategy version, manual + revocable, with auto-collected evidence (data-QA ok, A/B report,
  run count). The PAPER AUTOTRADE toggle is now HARD-BLOCKED without a paper approval (verified
  live). Model promotion: `--no-promote` runs register gate-passing challengers as PENDING;
  `/api/training/approve_model` (+ dashboard button) makes them champion — no automatic
  replacement.
* **Continuous training (web-controlled)**: background worker on the API server cycles
  dataset → ML → NN per symbol (QQQ/SPY/NQ/ES/ALL) on an interval (1h–daily), always
  `--no-promote`; start/stop + interval from the Training Lab; per-job history with rc + tails.
* Training Lab additions: run kinds 0·Data QA / 1b·Rejects, ALL/GC symbols, continuous panel,
  approval ladder panel, pending-models panel with Promote buttons, data-QA table.
* Tests: approval ladder, engine reject-reasons (deterministic tape), symbol one-hots —
  **116 green**.
* **ENTRY-PARAMETER SWEEP (separate training, user request)**: `research/sweep_entry_params.py` —
  54-combo grid over the direction/entry knobs (ctx gate × cooldown × stale × retest), ranked on
  the first 70% of history (min 60 IS trades), JUDGED on the last 30% next to the adopted default;
  a best-IS combo is only a CANDIDATE if it also beats the default OOS (anti-curve-fit verdict).
  Run kind `sweep` on the Training Lab + `/api/training/sweep` panel; merges per-symbol so runs
  accumulate. First QQQ result: best-IS (cooldown 0) ties the default OOS → **keep default**.
* **ONE-CLICK APPROVAL (user request)**: `/api/approval/approve_paper_all` + the big
  "✓ APPROVE strategy + enable PAPER trade" button on /training — walks research → replay → paper
  with audit notes, then arms paper autotrade (still refuses without Alpaca paper keys; live
  remains hard-locked). Verified live: blocked → approved → toggle ON → revoke re-blocks.
* `docs/TASKS_INCOMPLETE.md` — living checklist of partial/incomplete items across all spec docs
  (pullback refinements ⏸ deferred by user to last).

---

## 2026-07-04 — CANONICAL ENTRY STANDARD (ARMED→WATCH→FILL) across STACK/AUTO/OPTIONS + BOT + engine · PULLBACK mode · ML/NN platform

⚠️ Needs a **TradingView compile-check** on STACK/AUTO/OPTIONS + a forward paper session. ⚠️ The
Layer-1 context gate + live watch/cooldown/stale/retest CHANGE the entry vs the validated plain-ORB
config — **A/B on the data drive before trusting old backtest numbers** (every knob reverts
individually: Pine "Entry standard" inputs / `EntryStandard` fields, `ctx_gate=False` restores the
old arming). Full spec: `docs/ENTRY_STANDARD.md`; ML/NN: `docs/ML_NN_PLATFORM.md`.

* **One entry state machine on every surface** (strategy docs 2026-07-04, "Known Bug Fix"): the
  canonical ordering is **context arms → OR mid watches → OR high/low fills**. Old surfaces showed
  WATCH below the mid and called ready-to-fill ARMED — reversed vs the docs; standardized now.
  States everywhere: WAIT → ARMED (Structure+VWAP aligned, 1m-fed) → WATCH (confirmed
  directional-body close beyond OR mid) → FILLED → …, plus COOLDOWN / PULLBACK / RANGE / LOCKED /
  INVALID. New "Entry standard" input group on all 3 Pines (ctx_gate, watch_gate, cooldown 3,
  stale 24, retest 0.5 ATR; chase 1.0 added to AUTO/OPTIONS).
* **PULLBACK mode (new)**: price extends > chase·ATR past the OR level pre-fill → do NOT chase;
  fills blocked until an OR-edge retest within retest·ATR, then the normal fill rules re-check.
  Formalizes the old silent no-chase guard into a visible state + explicit retest requirement.
* **Cooldown rule (new)**: watch cancel at the mid → N-bar cooldown, fresh mid close required
  (kills mid-chop churn). **Range/stale rule (new)**: watch too old without a fill → RANGE, stand
  down until the mid is lost. **Two-entry limit** surfaces as LOCKED.
* **Python twin rebuilt** (`BOT/bot/strategy/orb_state.py` `OrbSideState` + `EntryStandard` — the
  shared knob set), engine grew the same causal machinery
  (`hs_backtest._orb_signals(watch_live, cooldown_bars, stale_bars, retest_atr)`), BOT scan/replay
  route through it (`orb_candidates.run_backtest()` = the ONE canonical call,
  `STRATEGY_VERSION = orb-standard-2026.07`). Layer-2 slope grade (A+..D from the combined slope
  engine) attached to every proposal + carried as an ML feature.
* **ML platform** (`BOT/bot/ml/`): point-in-time feature engine (39 features, causal, train/live
  parity — the live scan attaches the same snapshot the trainer uses), labeled dataset builder →
  FeatureStore parquet, model zoo (numpy logit + sklearn LogReg/RF/HistGB + LightGBM + XGBoost),
  isotonic/Platt calibration on pooled OOS predictions, PURGED walk-forward with embargo,
  hard promotion gates (AUC>0.52, Brier beats base rate, high-conf bucket must out-earn low-conf
  in expected R), champion-challenger + registry with feature-schema + rule-version pinning,
  SHAP/linear/perturbation explainability.
* **NN platform** (`BOT/bot/nn/`): causal 64-bar × 11-channel sequence dataset (shorts mirrored),
  NumpyMLP + torch MLP/1D-CNN/GRU/LSTM/CNN-GRU zoo, same purged validation + gates + registry.
* **Honest first results (QQQ, 312 candidates under the standard)**: best tabular OOS AUC 0.535
  (xgb) fails the Brier gate; best NN 0.487 fails the AUC gate → **nothing deployed, prior stays
  live** — the gates doing their job on a thin sample. Next: pool NQ/ES/QQQ/SPY + add rejected
  setups as no-trade labels (`docs/ML_NN_PLATFORM.md` §results).
* Tests: `BOT/tests/test_orb_state.py` rewritten to the canonical spec (38 tests) +
  `BOT/tests/test_ml_platform.py` (causality, leakage, gates, calibration, registry schema,
  NN causality) — **113 tests green**.
* **A/B RUN + ADOPTED (2026-07-04 evening, `research/ab_entry_standard.py`, 2018–2026)**:
  Layer 3 (watch/cooldown/stale/pullback) improves ALL FOUR instruments → ON everywhere
  (QQQ +0.273→+0.340, SPY +0.183→+0.242, NQ +0.140→+0.155, ES +0.073→+0.087 avg R vs baseline).
  The Layer-1 context hard gate LIFTS equities (QQQ +0.340→+0.449 avg R PF 1.70 maxDD −14.2→−9.1R;
  SPY +0.242→+0.329) but HURTS futures (NQ +0.155→+0.109, ES +0.087→+0.041) → **context is now
  PER ASSET**: `Asset.ctx_gate` (equities ON / futures OFF) + the `ctx_auto` input in STACK/AUTO
  (auto by `syminfo.type`). OPTIONS/V1/MTF NOT touched (user scope rule: only STACK/AUTO + BOT
  are updated by default) — on futures charts toggle OPTIONS' manual ctx_gate OFF.
* **TRAINING LAB dashboard** (same local server): `/training` page + `/api/training/*` endpoints
  (run dataset/ML/NN/A-B as subprocesses with live logs, model-zoo AUC/Brier charts vs the gates,
  bucket expectancy, calibration table, A/B panel, model registry, run history). Every
  `train_and_promote` run now persists its report to `BOT/data/ml/reports/` (registry
  `save_report`). Sidebar link "Training Lab" added to the main dashboard.

---

## 2026-07-03 — STRUC velocity: gap-aware CHoCH (all 8 structure machines) + multi-TF rolling direction engine (BOT)

⚠️ Needs a **TradingView compile-check** on STACK/AUTO/OPTIONS/V1_STRATEGY + a forward session
(mechanical, mirrored edits). ⚠️ The gap-aware flip CHANGES the engine trend gate vs the validated
backtest — **A/B on the data drive (`choch_gap_aware=False` reverts) before trusting old numbers.**

Root cause of the "structure needs ~15 closed 1m bars to flip" lag: the old CHoCH rule required a
CROSSING bar (previous close still on the old side of the last swing). In a fast move the swing
reference itself steps toward price via each newly confirmed pivot, so the crossing bar never
exists — st_state stayed wrong for 41 bars on the diagnostic dump tape, oscillating 0↔1 as
leftover HH/HL pairs re-claimed UP.

* **Gap-aware CHoCH** (engine `hs_harness.py` `choch_gap_aware=True` + the chart AND f_struct_1m
  machines of STACK, AUTO, OPTIONS, V1_STRATEGY = 8 machines): flip whenever price CLOSES beyond
  the last swing against the trend (once-only via the prev-state guard) + a claim guard (UP only
  with close ≥ last swing low; DOWN only with close ≤ last swing high — mirrored). Verified:
  41→0 violations on the diagnostic tape; bit-identical to the old rule on clean trending
  zigzags both directions (`BOT/tests/test_structure_velocity.py`).
* **Multi-TF ROLLING direction engine** (`BOT/bot/strategy/direction_engine.py`, user research
  2026-07-02): one 1m array, every TF re-scored on EVERY completed 1m bar from its own window
  (2M/5M/15M/30M/1H/4H = 2/5/15/30/60/240×1m); `D = 0.30·S + 0.20·P + 0.20·E + 0.15·B + 0.15·M`,
  bands ±0.12/±0.30/±0.65, RANGE override; ROLLING + clock-aligned CONFIRMED states side by side;
  IMMEDIATE 2-bar read refreshed by the live last trade between minute closes. Wired: every
  proposal carries `mtf_direction`; new `/api/direction?symbol=` endpoint for a 10–15 s dashboard
  poll (1m frame cached ~45 s, live price fetched per call). **DETECTION layer only — `dir_fast`
  + the confirmed 1m st_state stay untouched as the backup/validated gate** per user instruction;
  entries stay on the 2-bar cadence. 84/84 tests pass (13 new: stale-tape reproduction, gap-aware
  equivalence + invariants, the research file's pullback example, mirror symmetry, RANGE
  override, live-price scope, clock-aligned confirmation).
* **WATCH-before-ARMED promotion** (user spec follow-up): price must PASS the OR mid with clear
  direction before a side can arm — a confirmed FULL-BODY close beyond the mid toward a side puts
  that side on **WATCH** (the visible stage between WAIT and ARMED), and the watch follows the
  LIVE mid bias (cross back = that side drops to WAIT, the mirror side promotes). Shipped: BOT FSM
  (`OrbSideState`: WAITING→WATCH promotion + live-bias demotion, `on_bar(open_px=…)` directional-
  body check) and the STACK + OPTIONS dashboards (`l_watch`/`s_watch` latches; OPTIONS gained the
  WATCH label + orange color). AUTO/V1_STRATEGY have no state display but already enforce the
  mid-pass in their arm conditions (`not l_below_mid`). The mid GATE itself was already in place —
  arming always required the confirmed close beyond the mid. Entry behavior unchanged (display +
  FSM stage only). Suite 88/88.

---

## 2026-07-02 — Regime blocks REMOVED (Block RANGE + Block REGIME B) across all 5 Pine (user directive)

Defaults flipped OFF so the system no longer blocks those cohorts:
- **Block RANGE regime** `block_range` true→**false** (all 5 Pine). Chop-regime days are no longer blocked at the
  local-regime layer — note the vol-expansion filter (`min_or_width`, ON) still screens narrow-OR days, so most
  chop is still filtered at the OR level.
- **Block REGIME B** `block_b_ses` "London only"→**"Off"** (STACK/AUTO/OPTIONS) and `block_b` true→**false**
  (INDICATOR/STRATEGY). Regime B now trades in ALL sessions incl. London. Tradeoff (F31/F31f): regime B carries a
  validated edge (~2.4× trades, OOS ≥ IS) but London gets riskier unblocked at TIGHT daily limits (eval blow-up
  0→13% on the tight profile) — watch the daily-loss guard on London days.
- BOT: already permissive (`families.prepare` sets macro_allow_trades=True, local_regime=0) — no change needed.
- Toggles kept (reversible); still needs the standard TV compile-check. (Engine research backtest still models the
  gate via `local_regime != 2` — flip that too only if you want research baselines to match the unblocked live config.)

## 2026-07-02 — Zone state machine + 1-minute direction feed, ALL 5 production Pine + BOT (staleness fix)

⚠️ Needs a **TradingView compile-check** on all 5 + a forward session before sizing (mechanical, mirrored edits).

Fixes the state-staleness bug (dashboard showed LONG ARMED @730 with price at 719, below the OR low
and the proposed stop) and the "5m structure says Bullish while price dumped" lag. Propagated per the
all-scripts-consistency rule to STACK, AUTO, OPTIONS, V1_STRATEGY, V1_INDICATOR + the BOT engine:

* **ORB zone state machine** (mirrored long/short, confirmed closes only): pending side HARD-
  INVALIDATED on a confirmed close beyond the OPPOSITE OR edge or a pre-entry tag of its own stop
  (entry/stop/TP cleared; resting orders cancelled via strategy.cancel in the strategies); WATCH
  (order pulled) on the wrong side of OR mid; re-arm only after the breakout edge is RECLAIMED on a
  confirmed close + a completely new confirmation (hysteresis). STACK shows INVALID/WATCH states.
* **1-minute direction feed** (`fast_dir`, default ON; STACK/AUTO/OPTIONS/V1_STRATEGY — V1_INDICATOR
  has no structure gate): the identical swing machine runs in the 1m context via request.security
  (lookahead_off) — the trend gate + DIR-fast Struct/Slope arrows flip at 1m speed on ANY chart TF,
  each context keeping its own auto pivot lookback (futures 3 / equity 5 = 3-5 MINUTE confirms).
  Stop anchors stay on chart-TF swings. STACK DIR-fast OR arrow now shows the LIVE zone, not the
  frozen 10:00 day bias. OPTIONS + V1_INDICATOR also gained the HS-H4 confirmed-bar close-confirm
  gate they were missing (parity with STACK/AUTO).
* **Entries cap 0 = UNLIMITED** (STACK manual mode + AUTO) per user; the state machine still forces
  a fresh confirmed break per entry and hard-blocks an INVALID side.
* **BOT**: `bot/strategy/orb_state.py` (mirrored FSM + ER/persistence/slope math), proposals carry
  `or_high/or_low`, `signal_state` (active|watch|invalid) and `dir_fast` votes; paper autotrade +
  shadow tracker skip invalid signals; `families.scan(bars_1m=…)` aligns the 1m st_state causally
  onto the 5m frame (Python twin of the fast feed) for the gate + grade. 65/65 tests pass
  (mirror-symmetry, invalidation tables, causality of the 1m alignment, flip-speed timing).
* ⚠ VALIDATION: the 1m-fed trend gate is a behavior change vs the chart-TF backtest — run the
  gauntlet (gate = st_state on 1m bars) + forward-paper before sizing; `fast_dir` OFF reverts.

---

## 2026-07-02 — Fast-direction study: auto structure speed (lb 3/5) + OR-mid chart line, all 5 Pine + BOT

⚠️ Needs a **TradingView compile-check** on all 5 (mechanical edits; `var bool or_bull = na` bool-na fix already applied).

Direction-hunt CONVERGENCE (see `memory/highstrike-fast-direction.md`): ~33 direction/prediction detectors tested
(momentum, OLS/robust/Kalman slope, persistence±ε, efficiency, Hurst, HH/HL, CUSUM, Mann–Kendall, t-significance,
regime-z, EHMA, Markov, microprice, lead-lag, XGBoost/LightGBM/NN/HMM) — **ALL redundant, curve-fit-inconsistent,
or worse-than-follow.** The corrected F58: the confirmed HH/HL structure gate ~DOUBLES exp (trending-day selection)
and no fast/predictive read replaces it — direction is FOLLOWABLE, not forecastable. Propagated the two validated
outputs:
- **Auto structure speed** — `auto_lb` toggle + `int eff_lb = futures 3 / equity 5`, pivots use `eff_lb`. NQ keeps
  the full edge at lb=3 with more + EARLIER breakout entries (catches the move sooner); QQQ needs lb=5 (lb=3 fails
  its gauntlet); SPY ~tied. All 5 Pine + BOT (`asset_config.struct_lb()`, wired into `families.prepare` +
  `orb_candidates.load_state`). BOT smoke-tested (NQ/ES/GC=3, QQQ/SPY=5).
- **OR-mid equilibrium line** on the chart (all 5 Pine), colored lime/red by which half the OR closed in (the
  premium/discount bias axis) — per user request to SEE OR-mid on the chart. Plus STACK dashboard visibility:
  per-side block reasons (`WAIT · OR-mid: short day` / `narrow OR` / `trend gate`…), a `DIR·fast` row (OR-mid +
  VWAP + 12-bar regression slope = continuous awareness read), grade `—` when a side is directionally blocked.

FILL-MODE finding (`research/orb_fillmode.py`, NOT auto-applied): **stop-entry ≥ close-confirm everywhere**, decisive
on equities (QQQ +0.214→+0.473, SPY +0.553→+0.718), ~tied on NQ; retest dead. Close-confirm (user's strong-body
spec) is free on NQ but costs ~0.16-0.26R on QQQ/SPY → consider defaulting OPTIONS to stop-entry (`brk_confirm` toggle, user's call).

## 2026-07-01 — OR-mid BIAS (graduated) + asset-aware max-stop propagated to ALL 5 Pine + BOT

⚠️ Needs a **TradingView compile-check** on INDICATOR / STRATEGY / OPTIONS / AUTO (STACK already checked).
All-scripts-consistency: the two newest validated items are now in every Pine file and the BOT engine.

- **OR-mid bias (`ormid_bias`, default ON)** — GRADUATED (`research/orb_mid_bias.py`): trade only WITH the
  opening-range's closing-half bias — OR closed UPPER half (close > OR-mid) ⇒ day biased LONG (block
  shorts); lower half ⇒ biased SHORT (block longs). Additive edge: NQ +0.17→+0.29, QQQ +0.39→+0.48,
  SPY +0.35→+0.56 (all PASS the gauntlet); the dropped counter-bias trades are the LOSERS; survives 3× slip;
  fixes NQ year-consistency (10/17→13/17). = the ICT premium/discount / equilibrium concept, done as a filter.
  Each file captures `or_mid`/`or_bull` at OR close and gates `gate_long` (req or_bull) / `gate_short`.
  Also wired into the engine (`_orb_signals`/`backtest` `or_mid_bias=`) + BOT breakout family (LIVE).
- **Asset-aware max-stop (`auto_slmax`, default ON → equity 1.5 / futures 2.5 ATR)** — arm-timing graduate,
  `eff_sl_max` now feeds every stop calc (was flat 2.5). Equities take a tighter reversal cap; futures keep room.
- **BOT breakout family gate `none`→`trend`** (bugfix) — a LONG now fires only in an HH/HL uptrend, SHORT
  only in a downtrend (was firing longs in clear downtrends; the Pine was already correct).

NOTE: delay-0 is effectively already the V1/OPTIONS/AUTO behaviour (they never had the F38 60-min delay);
the chase-cap + vol-expansion filter remain STACK-only for now (optional add later).

## 2026-07-01 — STACK: arm-timing + tight-equity-stop propagated (user-directed)

⚠️ Needs a **TradingView compile-check** on STACK. Propagated the graduated findings from the
arm-timing test (`research/orb_arm_timing.py`, `smc_cluster.py` closed the SMC branch as
ORB-redundant) into `HIGHSTRIKE_ORB_STACK.pine`, matching the engine + BOT:

- **Arm delay 60 → 0** (`entry_delay` default). Arm at the OR close so you catch the move near the
  level instead of waiting the hour. Arm-timing: delay-0 ≈ delay-60 per-trade on NQ (+0.170 vs
  +0.173), slightly under 60 on QQQ/SPY, but earlier entries + more trades (user-directed trade-off).
  Set 60 to restore the F38/F39 skip-first-hour.
- **Chase-cap 0.0 → 1.0** (`chase_max` default). Enter within 1 ATR of the level, else the setup
  stays live for the RETEST — early but no chasing. Keeps NQ exp (+0.169), cuts DD (−40.8→−31.4R),
  improves QQQ (+0.266→+0.392). (A *tight* 0.25-0.5 cap is still bad — old F57; 1.0 is the loose one.)
- **Asset-aware max-stop** (new `auto_slmax`, default ON → equity/ETF **1.5** ATR, futures **2.5**).
  A tight 1.5-ATR cap lifts QQQ +0.266→+0.392 / SPY +0.286→+0.351 and caps reversals sooner;
  futures keep 2.5 (tight whipsaws them — NQ 1.5 fails the CI gate). `eff_sl_max` feeds the stop calc.

Vol-expansion (min_or_width 2.4, filter on), the HH/HL structure gate, grade, and asset-aware
min-stop were already in the STACK. NOT yet propagated to the other 4 Pine files (INDICATOR /
STRATEGY / OPTIONS / AUTO) — STACK only, per the request.

## 2026-06-29 — marker-placement fix (all event markers) + DIRECTION-SEQUENCE gate (F61, user-directed)

⚠️ Needs a **TradingView compile-check** on STACK / OPTIONS / AUTO. Two things from the user's
screenshots — the recurring "FILL FILL / TP2 on the wrong side / markers floating off the lines":

- **Marker placement (the actual recurring bug).** The F56/F58/F59 "fix" only ever moved the FILL
  label to its price; every OTHER marker still drew at the candle high/low (`location.above/belowbar`),
  so it floated off its line and stacked. Now anchored AT the real price via `label.new(..., yloc.price)`:
  STACK TP1/TP2/STOP/EXT (STOP captures the actual fill price `l_stop_px`/`s_stop_px`), OPTIONS
  CALL/PUT/EXT/EXIT (at the entry level / exit price), AUTO BUY/SELL (at the entry level). Display only.
- **Direction-sequence gate (F60, `research/orb_dir_seq.py`).** User rule (example.txt / Evidence
  early-entry): a long fires only while price is PUSHING UP — close>close[1] AND close[1]>close[2]
  (101→102→103); short mirror. New `dir_seq` input (STACK, default **ON**) + engine `dir_seq` param.
  VALIDATED: on the **wick/touch fill** it's a real graduate — NQ +0.151→+0.261R (PF 1.26→1.47),
  QQQ +0.276→+0.448, SPY +0.257→+0.383; yrs+ 13/17·9/9·8/9, OOS holds, survives 2× slip. On the
  **close-confirm fill** (shipped default) it's ~neutral (strong-body + continuation already imply it),
  so it's safe-on everywhere. The **no-chase guard was re-tested and stays OFF** (F57/F60: forcing
  near-zone entries costs edge — the late confirmed entries are the winners; the fill price is already
  honest/gap-aware). `dir_seq` PROPAGATED to all 5 (STACK/OPTIONS/AUTO/V1_INDICATOR/V1_STRATEGY),
  default ON — STACK fires `... and seq_l/seq_s`; AUTO/V1_STRATEGY gate the entry/arm; OPTIONS/
  V1_INDICATOR gate the fire. STILL PENDING: a single TV compile-check across the set.

## 2026-06-23 — Session default → "Auto (Asia + London + RTH by clock)" (user)

STACK + AUTO session preset default flipped to **Auto** (runs all three OR cycles per trade-day by the clock).
⚠️ AUTO is the live-order twin — on Auto it will arm/enter across Asia (19:00-20:00 OR), London (03:00-03:30),
and RTH (09:30-10:00). Switch AUTO back to a single session if you only want one session traded live. OPTIONS
left RTH-only (no Auto mode by design — 0DTE translator). Needs a TV compile-check with the F59x changes.

## 2026-06-23 — next-candle CONTINUATION confirm (F59c, user-directed) — validated, improves QQQ/SPY

⚠️ Needs a **TradingView compile-check** on all five. User flagged a long FILL that fired on a breakout candle
which immediately reversed into a downtrend. Fix = a 2-candle confirmation: the breakout candle qualifies (strong
full-body close beyond the OR, F59b), then the NEXT candle must CONTINUE the trend (higher close long / lower
close short) before the fill. New `wait_ft` input (default ON, all 5). Indicators fill on the continuation candle;
AUTO/V1_STRATEGY market-enter on it. Engine got `strong_body` + `ft_confirm` params (default off) so it's testable
and stays in parity. Validated (RESEARCH_NOTES F59c) on TREND + close-confirm + strong0.25: QQQ +0.283→+0.304,
SPY +0.232→**+0.344** (PF 1.66), ~neutral NQ — cuts ~13% of trades, all pass the CI gate, filters the pop-and-
reverse entries.

## 2026-06-23 — USER FILL RULE: clear-trend gate ON + STRONG close-confirm (F59b); reverses F58 gate-default

⚠️ Needs a **TradingView compile-check** on all five. User's explicit entry rule (3rd restatement): a long fills
only DURING A CLEAR UPTREND when a STRONG full-body candle CLOSES above the OR high (short mirrors). Two stacked
requirements, both now enforced:
- **Trend gate back ON (reverses the F58 default).** STACK/AUTO/OPTIONS `trend_mode` default → "Auto (structure
  ≤5m / EMA ≥15m)" (V1 pair were already gate-on). Kept ON as the user's *entry setup* (clean-trend breakouts
  only) — F58's finding still stands that the gate doesn't *add* expectancy net of honest fills, but the user's
  discretionary rule governs the entry. Tested OK: TREND + close-confirm = NQ +0.215R (PF 1.36, CIlo +0.110,
  better than plain), QQQ +0.287, SPY +0.176 — all pass the CI gate.
- **STRONG-close filter** (new `strong_body` input, default **0.25**). Close-confirm now also requires the bar to
  be the right colour (bullish long / bearish short) AND body |close−open| ≥ `strong_body`·(high−low) — rejects
  dojis / long-wick rejection candles. F59b sweep: 0.25 is the validated sweet spot (NQ +0.215→+0.233, QQQ +0.306,
  both best); heavier (0.4-0.6) keeps cutting trades and lowers the edge (0.5: NQ +0.150, SPY fails CI). Raise it
  for a visually stronger candle at a known edge cost.

## 2026-06-23 — full-body CLOSE-confirm entry (F59, user-directed) + FILL marker at the fill price

⚠️ Needs a **TradingView compile-check** on all five scripts. User: a FILL must require a **full-body candle
close beyond the level**, not a wick that tags it. Tested (RESEARCH_NOTES F59, `execm="close"`): on plain ORB,
honest fills, close-confirm is BETTER on NQ (+0.151→+0.190R, PF 1.26→1.34, CIlo +0.066→+0.096), ≈equal on QQQ,
mildly worse on SPY (+0.257→+0.197, still CIlo>0) — passes the CI gate everywhere, ~5-8% fewer trades. ADOPTED
as the default (the engine already defaulted to execm="close").
- **New `brk_confirm` input** (all 5), default **"Candle close beyond level (full body)"**; "Wick / touch
  (resting stop)" = the prior F58 stop entry. Trigger: `conf_close ? close≥Le : high≥Le` (long; mirror short).
- **Indicators (STACK/OPTIONS/V1_INDICATOR)**: fire on the confirming close; STACK fills at `l_ep = close`,
  risk `l_rk = l_ep − Ls` (honest from the actual fill, both modes). Dashboard ENTRY row shows the real fill
  price + risk-distance when in position.
- **Strategies (AUTO/V1_STRATEGY)**: swap the resting buy/sell-STOP for a **market entry submitted on the
  full-body close** (`stop = conf_close ? na : Le`, gated on `close≥Le`) → fills ~next open, alert/webhook fires
  then; broker still holds the SL+TP bracket. Touch mode keeps the resting stop.
- **FILL marker fix (separate, same day)**: was `plotshape(... belowbar/abovebar)` (drawn at the candle low/high,
  so a long FILL appeared below the OR-high line and adjacent fills stacked into "FILL FILL"). Replaced with a
  label anchored AT the fill price (STACK `l_ep`/`s_ep`; V1 pair `Le`/`Se` or the close) — a LONG FILL now visibly
  sits at/above the OR high, a SHORT at/below the OR low. Display only.

## 2026-06-23 — ⚠️ SIMPLIFICATION: plain ORB is the default; gate / OB / VWAP-cap → off toggles (F58)

⚠️ Needs a **TradingView compile-check** on all five scripts. After the F56 fill fix, the honest re-validation
(`research/orb_honest_revalidation.py` + `orb_honest_levers.py`, RESEARCH_NOTES F58) settled the core question:
with gap-aware fills the **structure/HH-HL trend gate (F20/F21), order-block confluence (F41/F45), and VWAP-cap
(F16) add ~0 net of costs** — the documented "+1–2R / ~2× expectancy" was the F56 stale-fill artifact. The gate
even HURTS SPY and the cap HURTS everywhere (it removes the late-momentum winners, F57). The honest tradeable
edge is a **PLAIN ORB on NQ/QQQ/SPY** (cap4 exit + skip-first-hour + struct/OR stop), exp +0.15–0.28R, PF
1.26–1.52, bootstrap CIlo>0, OOS holds, NQ survives 2× slip. **ES is dead.** Levers that DID survive honest
fills and stay ON: skip-first-hour time gate (F38, real — more skip is better), cap4 exit (F34b, best exit;
trail is the worst), macro + local-regime filters (untouched — they were part of the passing baseline).

Per the all-scripts rule ([[highstrike-all-scripts-consistency]]) the user chose "plain-ORB default, gate/OB/cap
as off toggles":
- **STACK / AUTO / OPTIONS (live set)**: `trend_mode` default → **"Off — plain ORB (F58 default)"** (new option;
  `gate_off` ⇒ `eff_up=eff_down=true`); `cap_on` default **true→false**; STACK `ob_on` default **true→false**.
  Dashboards show the true structure as INFO when the gate is off (STACK regime row, AUTO trend-gate cell);
  OPTIONS `dside` no longer forces a long bias when flat+gate-off ("waiting: no breakout yet").
- **V1_STRATEGY / V1_INDICATOR (legacy)**: the "Off — plain ORB" option/toggle ADDED for consistency, but their
  LEGACY defaults (EMA trend) are KEPT — these are reference scripts; tooltip points to F58.
- **engine `hs_backtest.py`**: unchanged — already defaults ob_confluence=False, vwap_cap=0.0, and takes the trend
  gate via trend_up/down columns (F58's "pure" run set them true). Defaults stay off.

**FILL-marker placement fix (same day, user-reported):** the green/red "FILL" triangle was `plotshape(...
location.belowbar/abovebar)` = drawn at the candle's low/high, so a long FILL appeared well BELOW the OR-high
line even though the buy-stop only triggers when `high ≥ Le = OR high + buffer` (and fills gap-aware at
`max(Le, open) ≥ OR high`). It only LOOKED like a sub-break fill (and adjacent breakout bars stacked into
"FILL FILL"). Replaced with a label anchored AT the fill price — STACK uses the true gap-aware fill `l_ep`/`s_ep`,
V1_INDICATOR/V1_STRATEGY use the level `Le`/`Se`. A LONG FILL now visibly sits at/above the OR high, a SHORT at/
below the OR low. Logic unchanged (it already enforced the rule); this is display only. AUTO (broker fills) /
OPTIONS (own display) have no FILL triangle.

## 2026-06-22 — ⚠️ FILL-REALISM FIX (F56/F57): stale-level + same-bar-TP inflation removed

⚠️ Needs a **TradingView compile-check** on STACK. The user flagged that fills inflate the stack; investigation
(RESEARCH_NOTES F56) found the gated-stack's documented edge was largely a STALE-FILL ARTIFACT — entries were
recorded at the OR break level while the lagging structure gate fired ~1.8 ATR LATER (price already run). Fixes:
- **Engine `hs_backtest.py`**: entry now fills at the WORSE of {level, bar open} (gap/late-aware); no same-bar TP
  (already scanned from i+1). Added off-by-default `chase_atr` no-chase guard.
- **STACK pine**: (1) management starts the bar AFTER the fill (`if in_long and not long_fire`) → no same-bar
  fill→TP; (2) gap-aware fill (`l_ep = max(Le, open)` / `s_ep = min(Se, open)`); (3) `chase_max` no-chase input
  (default 0 = off).
- **F57 finding**: the no-chase guard HURTS (NQ +0.156→−0.039R) — the late confirmed-momentum entries are the
  winners; the lateness is a feature. Honest stack ≈ +0.15-0.23R (marginal, vs the inflated +1-2R). F20/F21/F41/
  F45 are now SUSPECT and need honest re-validation (RESEARCH_NOTES F56).

## 2026-06-22 — exit default → capped/bracket + ticker-adaptive min-stop (F49/F50/F51)

Needs a **TradingView compile-check** on STACK + AUTO after these edits. Research behind it:
`research/orb_kernel_signal.py` (F49), `orb_cap_lateness.py` (F50), `orb_stop_floor.py` (F51).

### HIGHSTRIKE_ORB_STACK.pine (primary)
- **Default exit Trail → "Full → cap @ TP2 (struct stop)"** (F34b honest/eval-steady graduate). The ATR-chandelier
  trail's headline R/PF is TAIL-INFLATED (a few low-ATR trades blow up the R-denominator — F50/F51; it was made
  default on exactly that unreliable R-comparison, F27b). Trail kept as a toggle.
- **Ticker-adaptive min-stop floor** (`auto_minstop` ON): futures 0.5 ATR, stocks/funds 0.75 ATR
  (`eff_min_stop = syminfo.type=="futures" ? 0.5 : 0.75`). 0.5 ATR is noise-tight on equities (median QQQ
  structure stop ≈0.57 ATR); 0.75 is expectancy-neutral (F51 sweep). Manual value used when OFF.

### HIGHSTRIKE_ORB_AUTO.pine (real-order twin — kept in lockstep with STACK)
- **Default exit Trail → "Fixed TP bracket (broker-held)"** (= STACK's capped-TP2; webhook now sends bracket
  by default, broker holds SL+TP, survives a dead pipe). Trail kept as a toggle.
- **Same ticker-adaptive min-stop floor** as STACK.

### engine/hs_backtest.py (parity)
- `min_stop_atr_ = 0.75 if EQ else MIN_STOP_ATR` in `backtest()` so the sim's stop floor matches the Pine
  per instrument (verified: NQ min riskATR 0.50, QQQ 0.74). MIN_STOP_ATR constant unchanged (still 0.5 = futures).

### Findings (no code change)
- **F49**: the "Neural Kernel Bands" Buy/Sell signals are DEAD as a standalone entry (~coin-flip accuracy, net-negative
  both follow & fade; the chart look is the label-at-low/high illusion). Not adopted.
- **F50**: order-block port in STACK reconciles faithfully vs the harness (TV compile still pending).

### TODO (not yet done)
- TV compile-check of STACK + AUTO. Propagate the ticker-floor to OPTIONS (always-equity → 0.75) and V1_*.
  Close the F50 order-block TV compile/reconcile.

## 2026-06-15 — uncommitted working tree (review before commit)

Covers everything since the last commit (`47d7181 Options review`). All five touched scripts still
need a **TradingView compile-check**; STACK confirmed compiling. After reload, **set "EVAL: ledger start"
to your eval's first day** on every chart running EVAL (else the ledger counts all history → instant
TARGET ✓ / suppressed signals).

### HIGHSTRIKE_ORB_STACK.pine (primary)
- **EVAL ledger anchor** (`eval_anchor` + `ev_live`): signal-sim PnL before the anchor is ignored — fixes
  the "TARGET ✓ the moment EVAL is enabled" bug. Ledger/halt flags gated on `time >= eval_anchor`.
- **Regime-B block is now session-scoped** (`block_b_ses`: Off / **London only** (default) / All sessions),
  blocking B only during London hours (trade-day `o_now` 540-930 = 03:00-09:30 ET). RTH+Asia trade B. (F31/F31f)
- **Day throttle** (`eval_cap` 5 / `eval_lock` 2): suppresses signals after N/day or N losers; resets daily.
  Free in backtest (F31e). Display layer — AUTO is the real enforcer (throttle not yet in AUTO).
- **cap-4R exit toggle**: new exit mode "Full → cap @ TP2 (struct stop)" — full position to the TP2 R-cap
  (default 4R) on the structure stop, no scale/trail. Walk-forward-graduated (F34b/c). Trail stays default.
- **Event times + chart markers**: ENTRY/STOP/TP1/TP2 dashboard rows show fill/hit time; chart gets TP1/TP2
  diamonds, STOP ✕, eval-TARGET flag.
- **Per-ticker size readout**: ENTRY rows append suggested contracts (`risk_dlr` / stop-dist / `syminfo.pointvalue`),
  auto-adjusting per security.
- **Fix (review)**: in full/cap mode a trade that ticked TP1 then stopped out displayed green "TP1 HIT" — now
  shows "STOP HIT" (`if not l_t1h or is_full`, scoped to the stop branch so a cap win is never mislabeled).

### HIGHSTRIKE_ORB_AUTO.pine (automation twin)
- **EVAL ledger anchor + ev_live re-baseline** of `start_eq`/`peak_eq`/halt flags (mirrors STACK).
- **Regime-B block session-scoped** (`block_b_ses`, identical 540-930 trade-day window) — replaced the old
  all-sessions `block_b` bool.
- **cap-4R**: "Fixed TP bracket (broker-held)" default bumped 2R → **4R** (the graduated cap); tooltip updated.
  Bracket = full position, broker-held struct stop + 4R TP, no trail.
- **Eval-buffer formulas** aligned to STACK (daily/trailing halt `−math.max(limit − eval_buf, 0)`).

### HIGHSTRIKE_ORB_OPTIONS.pine (options translator)
- **Regime-B block session-scoped** (`block_b_ses`) — replaced old `block_b` bool. NOTE: this script's
  `o_now` is **wall-clock**, so London hours = **180-570** (not STACK/AUTO's 540-930). RTH-only ⇒ London-only
  never blocks B here (B trades all RTH). (review fix)
- **Dashboard split + state machine**: TP2, per-side WAIT/ARMED/FILLED/NEAR TP1/TP1/TP2/STOP states,
  STRAT row, Black-Scholes COST estimate row (IV/DTE inputs; ~approximation, no chain access).

### HIGHSTRIKE_ORB_V1_STRATEGY.pine (legacy strategy)
- **EVAL ledger anchor + ev_live**; eval-buffer formulas + `eval_buf` input aligned to AUTO/STACK
  (replaced the old `trail_buf`, added the `math.max(…,0)` clamps).
- **cap-4R**: "Full to TP2" mode already ran at TP2 R = 4 (= the graduated cap); tooltip clarified
  (the "2R/-1R" sublabel is legacy).
- *Still on the old all-sessions `block_b` bool — block_b_ses propagation PENDING (also V1_INDICATOR).*

### README.md
- Minor wording.

### New research scripts (`../research/`, untracked)
F31 regime-B (`orb_regimeb_entries/oos.py`, `orb_prop_eval_b/throttle/mixed.py`), F32 1m
(`orb_1m.py`, `orb_1m_robust.py`), F33 RANGE (`orb_range_block/eval.py`, `orb_f33_debug.py`),
F34 config validation (`orb_config_validate.py`, `orb_cap_walkforward.py`, `orb_eval_cap.py`),
F35 projection feasibility (`orb_projection_test.py`), confirmation entries (`orb_confirm_entry.py`),
gold (`orb_gold.py`, `orb_gold_walkforward.py`).

### Known-pending (not in this commit)
- block_b_ses → V1_STRATEGY + V1_INDICATOR (consistency rule; mind each file's clock convention).
- Day-throttle enforcement → AUTO (currently STACK display-only).
- Forward paper-test of fills (the live-adoption gate).
- Low-pri cleanups: dedupe London 540/930 magic numbers; gate throttle counters by `ev_live`;
  consolidate duplicated research helpers.
