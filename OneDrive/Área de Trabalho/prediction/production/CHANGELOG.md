# production/ — change log

Structured record of changes to the live Pine set. Newest first. See `../research/RESEARCH_NOTES.md`
for the F-number research behind each item.

---

## 2026-07-06 (v13) — RULE orb-standard-2026.07.6: cooldown/stale/next-candle verdicts (F77)

⚠️ STACK + AUTO changed (stale default + tooltips) — **TradingView compile needed.**

* **User ask: "test against cooldown, stale, next-candle"** — cohorts under the live-identical
  base, combined configs verified before adoption:
  **STALE/RANGE dropped on QQQ/SPY/NQ** (blocked cohorts +0.58/+0.24/+0.18R — standing down cost
  real money), **kept on ES** (cohort negative, DD explodes without it) · **QQQ cooldown 5→0** ·
  **QQQ fills the breakout candle itself** (ft_confirm off — the wait-created trades lose
  −0.54R) · **SPY instant fill OFF** (always waits for continuation: OOS 0.386→**0.620**) ·
  NQ keeps instant (always-wait collapses its OOS) · ES untouched — every ES blocker earns.
* **07.6 canonical (= live · parity 100% ×4 · 123 tests green):**
  QQQ n287 **+0.552R PF 1.88 total +158.4R** OOS +0.718 · SPY n269 +0.442R **total +118.9R
  OOS +0.620** · NQ n1327 +0.194R **total +257.6R** OOS +0.286 · ES n1226 +0.088R (unchanged).
  Day-one of the audit the system earned +74/+67/+225/+107 total R — two rounds of honest
  blocker testing later it earns **+158/+119/+258/+108**.
* **Pines**: stale_n default 24→**0** (ES charts: set 24 — its cohort is negative), wait_ft
  tooltip carries the QQQ-off exception, instant_fill tooltip now says OFF on **ES and SPY**
  charts.
* **AUTO PER-ASSET KNOBS (user: "make them automatic on the script")** — one new toggle
  (`auto_asset`, default ON) in STACK + AUTO applies every cohort-adopted per-asset value by
  SYMBOL, no manual per-chart setup: NQ/MNQ chase 1.0 · ES stale 24 + cooldown 3 · QQQ no
  next-bar wait · instant fill OFF on ES+SPY · RANGE block equities-only · retest ES 0.5 /
  others 0.25. Detection via syminfo.root (futures) / ticker (equities, MES covered). Matches
  BOT asset_config exactly; OFF restores the seven manual inputs (renamed *_in internally).
  Identifier wiring machine-verified (each input renamed once, each derived once).

---

## 2026-07-06 (v12) — RULE orb-standard-2026.07.5: SEVEN live≠backtest divergences closed, LIVE == BACKTEST gate-for-gate (F75/F76)

⚠️ STACK + AUTO defaults changed — **TradingView compile needed.** 07.5 re-keys datasets/models;
approvals reset by design (re-approve on /training).

* **THE AUDIT (user: "fix the blocker, run backtest against the other blockers")** — seven
  divergences found and closed: chase-cap + narrow-OR were LIVE-only; canonical ran DELAY=60
  (live 0), single-entry (live re-arm), no equity bias (live ON), TP1 1.0 (live 1.5); and the
  live scan NEVER applied the macro/regime gates — the SPY stand-down existed only in
  backtest+Pine while paper autotrade would have traded against it. Every prior number described
  a system nobody traded.
* **COHORT-DRIVEN ADOPTIONS (blocker_edge + blocker_edge2)**: chase OFF on QQQ/SPY/ES (the
  chased entries ARE the winners: +0.59/+0.70/+0.16 cohorts), KEPT 1.0 on NQ/MNQ as the DD-halver
  · narrow-OR filter → GRADE-only everywhere (blocked cohorts positive on all four) · equity
  re-entries dropped (max_entries 1: cohorts QQQ −0.093, SPY −0.524; OOS better single), futures
  keep 3 (NQ cohort +0.164) · delay-0 confirmed everywhere · equity frozen OR-mid bias KEPT
  (OOS 0.68 vs 0.396 without) · CHOP-regime block dropped on FUTURES (cohorts +0.19/+0.18,
  OOS up on both), kept on equities · 07.3 bias-supersede regression on "abc" fixed.
* **07.5 canonical (= live, parity 100% ×4, 123 tests green)**:
  QQQ n170 +0.435R PF 1.66 DD −9.9R OOS **+0.747** · SPY n150 +0.444R PF 1.73 DD −7.1 OOS +0.386
  · NQ n1147 +0.196R **total +224.9R** (was +127) OOS +0.235 · ES n1226 +0.088R total +107.5
  (was +64) OOS +0.167. Every symbol improves on its judge metrics.
* **Pines (STACK + AUTO)**: chase_max default 1.0 → **0.0** (NQ/MNQ charts: set 1.0 for the DD
  halving) · volexp_filter default → **off** (grade-only) · auto max-entries equity 2 → **1**
  (AUTO input default 1; futures charts set 3).
* **SCRIPTS FULLY RE-BASED ON THE NEW RESEARCH (user)** — every stale claim rewritten to
  F75/F76: chase tooltip now states the blocked-cohort evidence + the NQ/MNQ exception ·
  vol-exp tooltip explains the grade-only demotion (graduation was vs plain ORB) · re-entry +
  auto-max-entries tooltips carry the per-asset cohorts (equity 1 / futures 3) · block_range
  gained per-asset guidance (futures OFF / equities ON) · delay tooltip carries the F76
  first-hour re-confirmation · EntryStandard.max_entries default 2 → 1 (BOT reference aligned).
  No "ADOPTED 1.0" / "equity 2" / "default ON" claims remain in either script. 123 tests green.

---

## 2026-07-06 (v10) — OPTIONS MODULE FINISHED: payoff replay verdict = NAKED-ONLY (options-0.1) · one-click approve+learn · STRATEGY DUEL · dashboard banner removed

* **OPTIONS PAYOFF REPLAY (the module's gauntlet — research/options_replay.py)**: every canonical
  QQQ/SPY trade priced through the three 0DTE plays (Black-Scholes entry/exit, per-leg spread +
  commission, IV sensitivity 0.15/0.20/0.30). **NAKED BUY PASSES both** (QQQ +0.268 ret/premium
  PF 2.05 9/9 yrs CIlo +0.157, IV-robust · SPY +0.123 PF 1.5 9/9, marginal at IV .30);
  **debit + credit verticals FAIL everywhere** — capping the 4R tail / selling the breakout
  direction destroys the low-WR big-winner edge. Module `options_day_orb` → gauntlet_pass,
  lineage **options-0.1** (approvable on /training). IV is model-approximated: paper verifies
  real fills before sizing.
* **ONE-CLICK APPROVE + LEARN** — the big button approves the SELECTED lineage's ladder AND arms
  paper autotrade AND starts continuous training AND enters the lineage in the duel.
* **STRATEGY DUEL** (user: "put them against each other") — approved lineages shadow-trade their
  daily rules head-to-head (bot/strategy/duel.py, /api/duel, panel under the approval ladder):
  R-normalized per module, resolved on completed daily bars, no orders. Duel + version dropdown
  now FIT their card (fixed layout, wrapped cells).
* **Dashboard: OPTIONS SIGNAL ENGINE banner removed** (user request) — Account + Live Market
  share the top row; nav link + engine KPI code deleted.
* **123 tests green.** STACK compiled by user ✓ · AUTO compile still pending.
* **OPTIONS CROSS-TEST + OPTIONS-ONLY SEARCH (F74, same day)** — which strategy makes it as
  options: **volbreak → 0DTE naked is the standout** (QQQ +1.01 ret/premium PF 3.30 9/9 yrs
  OOS +1.11, n=1,940; SPY +0.63 PF 2.51 9/9); **swing QQQ @21DTE passes naked AND debit** (the
  only stream carrying a vertical); Connors converts to nothing; **credit spreads fail all five
  streams**. Options-ONLY search: the **variance risk premium** (short daily ATM straddle,
  VIX-priced) passes the numeric gate huge (SPY PF 5.35 win 82% 9/9) but is registered as
  `options_native_vrp` **research_candidate only** — VIX-as-daily-IV likely inflates the short
  side and the tail is unbounded (worst day −7.15×premium); needs real 0DTE chain IV.
* **OPTIONS SHOWN BY GATE (user)** — every surface now presents each structure with the gate it
  passed: live proposals' option plans recommend NAKED always (was regime-based debit default —
  contradicted the replay), each structure carries its PASS/FAIL verdict inline; the DUEL panel
  shows each module's validated expression (⚡ volbreak → 0DTE naked · swing → QQQ 21DTE
  naked+debit · connors → underlying only).
* **DASHBOARD GATE DISPLAY (user: "this needs to show on the dashboard")** — the gate map is now
  ONE source (`bot/options/exit_plan.STRUCTURE_GATES`) consumed everywhere: `/api/options`
  attaches gates + recommended; the SHOW-OPTIONS-PLAY table gained a GATE column with a
  "◄ VALIDATED" marker on naked; the Bot Strategies panel now lists the REAL module lineup from
  /api/duel — each module with its duel status (IN THE DUEL / awaiting approval), running shadow
  R, and its ⚡ gate-passed options expression; the stale hardcoded "Trend/Momentum" row dropped
  (merged into the breakout per v9). **123 tests green.**
* **"NO SIGNAL but price moved 1.5%" (user 2026-07-06) — diagnosed per symbol**: QQQ = the
  CHASE-CAP stood down correctly (gap ran >1 ATR past the OR high, retest never came — F57 by
  design) · SPY = NARROW-OR vol-expansion block (width 1.97 < 2.4 ATR — the dead cohort, by
  design) · **NQ = a real grade-B breakout long (30021.75, ~10:20 ET) fired but was MISSED**:
  the scan captured only the last 4 bars (20-min window) and that window fell inside a server
  reload storm (every code save restarts uvicorn and kills in-flight scans). FIXES: scan window
  widened to 12 bars (1h — the per-bar dedup makes it idempotent, restarts can no longer drop a
  signal); the missed NQ signal was recovered into the tracker (outcome tracking live). NOTES:
  NQ live bars come from Yahoo (15-min delayed) while Webull futures stays unentitled; two
  Jun-30 QQQ phantom candidates at entry=100.0 flagged — no synthetic provider is active today,
  watch for recurrence.
* **BLOCKER-EDGE STUDY (F75, user: "test the blockers to find edge") — MAJOR FINDING**: the
  canonical backtest NEVER carried the chase-cap or the narrow-OR filter (live enforces both) —
  every 07.x number includes trades live refuses. Cohorts under 07.4: the CHASE-CAP blocks the
  BEST equity trades (QQQ cohort +0.591R n127 · SPY +0.698R n132 — live SPY runs +0.113 avg vs
  +0.448 canonical!), while on futures it's ~neutral per-trade but HALVES max-DD; the NARROW-OR
  filter's blocked cohort is positive on every symbol now (the layered entry already does its
  job — the 07-01 graduation was vs plain ORB). RECOMMENDED (pending gauntlet + user sign-off,
  chase was a user rule): equities chase OFF · futures chase kept (DD knob) · narrow-OR →
  grade-only · then run_backtest carries the SAME gates as live = rule 07.5.
* **FEATURE INVENTORY + TEST PLAN** — docs/FEATURE_TEST_PLAN.md: every feature D1–D20 (dashboard),
  T1–T19 (training lab), E1–E13 (engine), M1–M13 (ML/governance) with per-row test procedure,
  expected result and current status; §6 = the ordered manual pass.

---

## 2026-07-06 (v9) — MODULE LADDERS live (swing/volbreak/connors) · L2 store bugs fixed (full re-sync) · zone-bounce + gold CLOSED dead · sweepgo unstable

* **MULTI-LINEAGE APPROVALS** — the ladder now covers every gauntlet-passed module, each with its
  own version key approvable research→replay→paper on /training (version dropdown):
  `swing-1d-0.1` (QQQ pullback 7/7) · `swing-fut-1d-0.1` (NQ breakout 7/7) ·
  `volbreak-1d-0.1` · `connors-1d-0.1`. Endpoints take ?version= (whitelisted).
* **VOLBREAK + CONNORS RE-CONFIRMED under the current engine** (strat_daily 2026-07-06):
  volbreak k0.3 — NQ +0.094R PF 1.54 **17/17 yrs**, QQQ 9/9, SPY 9/9 (ES/GC fail; slippage
  caveat); Connors RSI-2 — QQQ PF 1.97, SPY PF 2.14, both 7/8 yrs (equities-only, regime
  caveat). Both registered as modules (gauntlet_pass).
* **L2 STORE BUGS (found on the first real post-sync rebuild)** — (1) each file's synthesis
  OVERWROTE the per-symbol store: 51 "synced files" left ONE day of features → saves now
  APPEND-MERGE (dedup by minute); (2) attach_l2 double-merged against the PIT schema's NaN l2_*
  placeholders → l2_*_x/_y suffixes, models saw 100% NaN → placeholders dropped pre-merge;
  (3) the registry held the same 12 disk files as 21 rows (repeated folder scans) → deduped +
  register() is now idempotent by path. Full re-sync of the 12 real sources running; the
  post-sync auto-pipeline retrains with the FIXED join when it lands.
* **RESEARCH CLOSED (F73)**: zone-bounce step 2 FAILS (NQ −0.035R CIlo −0.13 · ES −0.137R —
  zones predict location, fading into them is not an entry; clean-air keeps earning) · GOLD
  FINAL-dead under canonical 07.4 with its own config (n 664, −0.136R, PF 0.83, DD −112R) ·
  sweep-then-go UNSTABLE (QQQ pass→fail, SPY fail→pass across rule versions on n≈100 — 
  watchlist, not adoptable) · trend/momentum family now passes BOTH equities strongly
  (QQQ +0.389 CI +0.208 9/9 · SPY +0.355 8/9) — optional selectivity, still a breakout filter.
* **123 tests green.**
* **TREND/MOMENTUM FINALIZED (user 2026-07-06)** — verdict: its edge already IS the canonical
  equity entry (the struct_vwap arming gate; canonical QQQ +0.507 / SPY +0.448 beat the family
  replica's +0.389/+0.355 because of the watch machine + per-asset knobs). The separate "trend"
  and "smc" scan families were near-duplicating every equity breakout in the tracker (F58/F62:
  filters, ~0 additive) → both now INFO-ONLY; the breakout family is the one system of record.
* **L2 post-fix verification** — merge fix confirmed: QQQ store 8 days / 7,562 minute-rows,
  NQ 5 days (the "51 files" were 12 real files registered repeatedly). Remaining gap is DATA
  COVERAGE, not code: the depth files span Jun 9–25 while the bar store (and its candidates)
  ends Jun 5–8 → zero overlap to join yet. Next: extend the bar store past Jun 9 (ingest),
  then the auto-pipeline picks the l2_* values up on its own.

---

## 2026-07-05 (v8) — RULE orb-standard-2026.07.4: DIR-FAST C + A∨B∨C arming on futures

⚠️ STACK + AUTO changed again — **TradingView compile needed.** 07.4 re-keys datasets/approvals.

* **DIR-FAST C (user ask: "create the entry rule… it will be Dir fast C")** — built from the
  user's own slope research: C aligned = the COMBINED SLOPE ENGINE strong read, S = 0.50·Sc/ATR +
  0.30·Sm/ATR + 0.20·BP at **|S| ≥ 0.30** toward the side (1m-fed on any chart TF in Pine;
  vectorized `slope_series` in the engine — self-tested identical to `slope_engine` per bar).
* **A∨B∨C arming (user: "DIR-fast can fire when either one is aligned between A, B and C")** —
  a side ARMS when ANY engine aligns: **A** = VWAP side (+ the obligatory OR-mid via the watch
  machine), **B** = swing-structure state, **C** = slope strong. Blocks only when EVERY engine
  disagrees/neutral.
* **A/B → adopted on FUTURES, rejected on equities**: NQ +0.172→+0.173 (identical, −1 trade),
  ES +0.087→+0.090 PF 1.13→1.14 (trims 2 junk trades) — the user rule at zero cost. QQQ
  +0.507→+0.320 / SPY +0.448→+0.208 under any-of-three — the STRUCT+VWAP AND-gate stays the
  equity arm. `ctx_mode="abc"` on NQ/MNQ/ES/GC.
* **Pines**: ctx option "Any engine aligned (A∨B∨C, 07.4)", Auto = equities Struct+VWAP ·
  futures A∨B∨C; dir-C computed from the existing 1m slope feed; dashboard DIR-fast row now
  shows "A … ∨B∨C ← ARMS (any engine)" + a C▲/▼ STRONG marker; why-string "context: no engine
  aligned (A∨B∨C)".
* **Verified: 123 tests green · replay parity 100% ×4 (NQ 710 / ES 711).** Re-approve the
  ladder for 07.4 before paper.
* **BOT live read parity (user: "update the BOT script as well")** — `fast_direction` now carries
  `dir_c` (slope-strong vote) + an `abc` {up/down/read} block, so live proposals show the same
  A∨B∨C read as the STACK dashboard; the arming arrays in the live scan + canonical backtest
  were already switched (families/orb_candidates ctx_mode "abc").
* **POST-SYNC AUTO-PIPELINE (user: "does the dataset and test run automatically?") — now YES**:
  when SYNC ALL finishes, the server automatically runs dataset → ML → NN (--no-promote) for
  every synced symbol; progress shows in the L2 panel ("AUTO-TRAINING: ml QQQ"), gate-passers
  land under Pending models. Manual re-run button "⚙ Rebuild + retrain synced" (endpoint
  /api/data/retrain_synced). Also fixed: the continuous-training skip signature now includes the
  l2 feature-store mtimes — an L2 sync changes column VALUES without changing row counts, so the
  old rows/span signature would have skipped exactly the retrain the sync exists to trigger.

---

## 2026-07-05 (v7) — L2 SYNC FIXED (all 51 were failing) · SWING GAUNTLET: QQQ + NQ PASS 7/7 · NN-seq live scoring · orderflow persistence · options-leg recording · restart recovery

* **L2 Binder Error (user report: 51/51 sync errors)** — DuckDB's CSV sniffer parses Databento's
  ISO `ts_event` straight to TIMESTAMPTZ; dividing a timestamp by 1e9 was the Binder Error.
  `_ts_expr` now PROBES the column type (TIMESTAMPTZ → direct trunc; VARCHAR → cast; int epoch →
  magnitude-based ns/µs/ms/s). Verified on a real 340 MB MBO file (913 minute-rows) — re-sync of
  the full folder re-triggered. NOTE: a `--reload` server restart kills an in-flight sync worker
  (progress is in-memory) — avoid editing `bot/` while a long sync runs.
* **SWING MODULE — first two full-gauntlet passes** (research/swing_gauntlet.py, 7 checks incl.
  2×-cost stress + year consistency): **QQQ pullback-reclaim 7/7** (+0.538R, PF 2.23, OOS +0.687,
  8/9 years) and **NQ 20-day breakout 7/7** (+0.123R, 2×-cost +0.103, 11/17 years — the pullback
  rules fail futures dailies, the breakout variant is the futures setup). SPY 5/7, ES 6/7 — not
  adopted. modules.py → gauntlet_pass; next: swing-1d-0.x approval ladder.
* **NN sequence live scoring wired** — every proposal's 64-bar window now runs through the NN
  champion (`predict_sequence`, champion-gated → None until one passes gates); `nn_seq` rides
  the proposal and votes in the ensemble alongside P(win)/heads/similarity/grade.
* **Orderflow persistence** — `bot/orderflow/persist.py`: minute-deduped flow scores appended per
  scan cycle to `data/orderflow_scores.csv` (data-first; schema join deferred until live history
  exists to backfill an `of_score` feature honestly).
* **Options-leg shadow recording** — every auto-tracked signal now stores its translated option
  structure in the tracker (the standalone options module's future training data).
* **Restart recovery (phase-7 pulled forward)** — kill-switch + paper toggle + paper dedup keys
  persist to `data/runtime_state.json` and restore on boot (mode intentionally NOT restored);
  `reconcile_once` runs every ~10 scan cycles while paper autotrade is armed.
* **Screenshot double-check (user)** — STACK 07.3 confirmed live on chart: A-row "MID▼ ← ARMS
  (obligatory) · VWAP grade C"; the remaining SHORT blocker is the SPY stand-down (validated
  keeper, v6). **123 tests green.**

---

## 2026-07-05 (v6) — RULE orb-standard-2026.07.3: OR_MID-OBLIGATORY arming (futures) · leakage fixes + canaries · swing research PASSES QQQ/SPY · reversal-veto verdict · paper "why" · WR symmetry · BOT audit

⚠️ STACK + AUTO changed — **TradingView compile needed.** ⚠️ 07.3 REVOKES the 07.2 paper approval
(by design) — re-run A/B and re-approve research→replay→paper on /training.

* **07.3 (user, twice: "OR_MID IS OBLIGATORY")** — futures arming = OR-mid side ONLY (watch
  machine); VWAP/STRUCT/SLOPE grade (C/B/A/A+), never block or delay (fixes the NQ short where
  VWAP▲ blocked an armed breakdown). A/B: costs ~nothing on futures (NQ +0.180→+0.172, ES ~flat,
  +4 trades); equities KEEP struct_vwap (it IS their edge: QQQ +0.507 vs +0.314 mid-only, SPY
  +0.448 vs +0.203). ctx_mode="mid" on NQ/MNQ/ES/GC; Pines: ctx gate, dir-A row, tooltips.
  **Verified: 121 tests green · replay parity 100% ×4 (NQ 711 / ES 713 trades).**
* **LEAKAGE (user ask)** — two real leaks fixed in pipeline.py: (1) champion-challenger duel
  retrained the challenger on ALL data incl. the frozen holdout it was scored on → duel model now
  trains on the first 70% only (raw-p AUC; isotonic is rank-preserving); (2) calibration table was
  judged on the rows the calibrator was fit on → honest 70/30 split with note. Plus
  tests/test_leakage_canary.py: shuffled-label null canary (must score ~0.5) + signal canary —
  both PASS, the purged-WF harness itself is leak-free.
* **WIN-RATE SYMMETRY (user ask)** — per side: QQQ 40.6/36.0 (gap 4.6pts), NQ 43.2/36.5 (6.8,
  expectancy symmetric +0.168/+0.178), SPY 42.4/31.6 (**10.8**), ES 42.6/32.5 (**10.2**). Long-
  biased decade explains part; SPY/ES short WR is the watch item — slice gates already block a
  model that only works one side.
* **REVERSAL DETECTORS AS FILTERS (expectancy gauntlet, user ask)** — research/reversal_filters.py:
  NO detector qualifies as a hard veto on any symbol (veto cohorts POSITIVE OOS — a veto would cut
  winners; most detectors never oppose a fresh breakout). They stay MODEL FEATURES.
* **SWING MODULE RESEARCH (user ask)** — research/swing_rules.py (daily EMA20>50 pullback-reclaim,
  1.5ATR/2R/20-bar triple barrier): **QQQ PASS n77 +0.538R PF 2.23 OOS +0.687 · SPY PASS OOS
  +0.689** (IS negative — OOS-driven, verify) · NQ FAIL dd · ES FAIL. modules.py: equities_swing →
  research_pass. Next: full gauntlet + swing-1d-0.x ladder.
* **PAPER "WHY" (user: "don't see where this is doing")** — /api/paper_log now diagnoses the exact
  blocker (keys → toggle → approval-for-CURRENT-version → market hours) and the dashboard paper
  panel shows it; the flow is: approve ladder on /training → flip "Paper autotrade" on / →
  fills land in the paper log + scorecard.
* **SPY STAND-DOWN A/B (user's NQ no-fill screenshots, round 2)** — tested "stand-down as grade"
  under the 07.3 philosophy: REJECTED, the gate stays. OFF collapses every instrument (NQ avg R
  +0.172→+0.023, PF 1.29→1.04, DD −42.6→−75.4R; ES +0.087→−0.051; QQQ +0.507→+0.264; SPY
  +0.448→+0.208). Counter-SPY-trend breakouts ARE the losers — this veto earns ~0.15R/trade.
* **Ops** — stale-server "unknown kind" now says RESTART (dynamic kinds list); sync-all UI 404
  hint; docs/BOT_FEATURE_AUDIT.md (per-file gaps by section).

---

## 2026-07-05 (v5) — NQ 75%-WR search (768 cells) · per-security scoreboard · champion-gate diagnosis · cont-training skips unchanged data · WAL · sweep --tf · retention

* **NQ ≥75% WR (user ask)** — `research/nq_winrate.py` + `nq_scratch.py` (run kind **nqwr**,
  button 13): NQ reaches 75–81% WR only at 2×ATR stops (~136t median) and PF tops at **0.91**;
  BE-move/time-stop/soft-abort all reduce PF (they clip winners more than losses). ES is the
  closest futures cell today (60t stop, TP 0.25×: **76.8% WR, PF 1.12**). Concrete NQ path:
  veto ~24% of losers → ~81% WR / PF 1.2 — the first modest selectivity target for the
  no-trade/L2 stack. Full analysis → DEVELOPMENT_PLAN §0.
* **Champion-gate diagnosis (user: "still no champion")**: 104 reports; every candidate fails
  AUC ≤ 0.52 (SPY 0.496, ES 0.518) or Brier-vs-base-rate (QQQ 0.535 AUC/0.296 Brier vs 0.238
  base; NQ 0.551/0.249 vs 0.242). Same data → same result every cycle: **continuous training
  now skips ml/nn when the rebuilt dataset's rows/span are unchanged** (server `_cont_loop`
  signature check). The gate math is honest — new DATA (L2 sync, live labels, 15m lineage)
  is the only lever, not more retrains.
* **Ops/readiness (ENGINEERING_AUDIT items)**: tracker SQLite **WAL + busy_timeout 5s** (scan
  thread + API + paper autotrade share the DB) · **90-day retention** for timestamped training
  reports at boot · sweep `--tf=` pass-through (15m lineage from the web: TF selector now applies
  to button 5) · Training-Lab buttons **12 Target geometry** and **13 Futures 75% WR**.

---

## 2026-07-05 (v4) — ULTIMATE-GOAL geometry study · L2 Sync-all · bug batch (3m resample, empty dataset, LGBM spam, folder-register UI, approval-card fit)

* **Target-geometry study** (`research/target_geometry.py`, Training-Lab run kind **geometry**):
  measures the user goal *WR 85% · PF 1.8–1.9 · adverse ≤45 ticks futures / $4 equities* against
  the canonical entries. Math: PF = WR·W/((1−WR)·L) ⇒ TP ≈ **0.33× stop**; a driftless random
  walk already wins ~75.4% at that shape, so the entry+model stack must add ~10 WR points after
  costs. Study sweeps TP ∈ {0.25…1.0}×stop, first-touch walk, stop-first ambiguity, EOD flat,
  honest costs; flags `meets_goal` cells. Pursuit plan → DEVELOPMENT_PLAN.md §0.
* **L2 SYNC ALL** — `/api/data/sync_all` + `/api/data/sync_status` + background worker; the L2
  panel shows a SYNC ALL button when ≥2 sources are unsynced, with live per-file progress (built
  for the ~10 registered QQQ MBO files on D:).
* **Bug batch** (all user-reported): tf=3m dataset crash ("duplicate keys" — 1m continuous view
  carried ts **and** ts_et; `_from_continuous()` keeps exactly one) · empty-dataset build now
  prints "0 labeled candidates" instead of KeyError y_win · LGBM "X does not have valid feature
  names" silenced module-wide in models.py · folder registration UI showed "registered undefined"
  (folder responses have `{registered, sources[]}` shape — handled) · approval-ladder table now
  fits its card (fixed layout + word-wrap) · UI routes send Cache-Control no-store (stale-page
  class of bugs closed).
* **pandas 3.0 unit trap** (second sighting — now a convention): datetime64[**us**] series make
  `.astype("int64")` return µs while `Timestamp.value` is ns → searchsorted misses everything.
  Rule: compare `datetime64[ns]` on both sides (`to_numpy("datetime64[ns]")` +
  `.as_unit("ns").to_datetime64()`), never raw int64 epochs. Fixed in target_geometry.py;
  l2_features.py already guards by magnitude.
* **121 tests green** after the batch.

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
