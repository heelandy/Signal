# FEATURE INVENTORY + ONE-BY-ONE TEST PLAN
*(2026-07-06 · rule orb-standard-2026.07.4 · companion to TASKS_INCOMPLETE.md / BOT_FEATURE_AUDIT.md)*

Every feature from the dashboard through the Training Lab, each with its test procedure and
status. Legend: ✅ verified (date) · 🤖 covered by the pytest suite (123 tests) · 🔲 needs the
manual pass below · ⚠ known caveat.

**How to run the pass**: go section by section, one feature per row, in order. Each row says
exactly what to click/run and what you must see. Anything that deviates = a bug; file it with
the row ID (e.g. "D3 failed: …").

---

## 1 · DASHBOARD (/)

| ID | Feature | Test procedure | Expect | Status |
|---|---|---|---|---|
| D1 | Account overview | open / | equity, buying power render | 🔲 |
| D2 | Live Market tabs | click Indices/Futures/Forex/Crypto | quotes fill, no console errors | 🔲 |
| D3 | Signal table (grades, dir_fast, state) | SCAN NOW during RTH | rows appear with grade A+/A/B/C badges, signal_state, dir_fast read | ✅ 07-06 (scan replayed, 4 proposals) |
| D4 | Heads / AI decision / kelly on signals | hover AI badge on a row | expected-R, verdict reasons, quarter-kelly show | ✅ 07-05 |
| D5 | nn_seq on proposals | inspect a proposal JSON (/api/signals) | `nn_seq: null` until an NN champion exists | ✅ 07-05 (plumbing) |
| D6 | Options play pricing + GATE column | SHOW OPTIONS PLAY | naked/debit/credit rows, GATE column: naked PASS green ◄ VALIDATED, debit/credit FAIL red | ✅ 07-06 (live curl) |
| D7 | Exit plan (recommended=NAKED) | /api/exit_plan or signal detail | recommended always "naked", rationale cites the replay | ✅ 07-06 |
| D8 | Contract greeks | pick a signal → contract panel | BS greeks for the strike render | 🔲 |
| D9 | Bot Strategies panel (modules + duel) | open / | ORB rows + 4 duel modules with ⚡ options expressions + status | ✅ 07-06 (JS checked; visual 🔲) |
| D10 | Sessions panel | open / | Asia/London/RTH windows + status dots | 🔲 |
| D11 | Equity curve + scorecard | after ≥1 resolved tracked trade | curve draws; scorecard n/exp_R vs backtest ref | ✅ 07-06 (scorecard live) |
| D12 | Study panel (MFE/MAE first-touch) | after resolved trades | stop-vs-TP percentages | 🔲 |
| D13 | Candidates / journal | /api/candidates | tracked signals with outcomes (NQ 30021.75 recovered today) | ✅ 07-06 |
| D14 | Paper autotrade toggle + WHY | flip toggle without approval | exact blocker text (approval/keys/hours) in the panel | ✅ 07-05 |
| D15 | Paper log | after paper orders | grade-sized orders listed | 🔲 (needs paper session) |
| D16 | Kill switch | toggle on | scans pause, /api/status healthy=false, persists across restart | 🤖 + restart ✅ 07-05 |
| D17 | Mode switch live-block | POST /api/control/mode live | blocked without lock file + 'live' approval | 🤖 |
| D18 | WS tape flow score | open / during market | 0-100 flow gauge updates ~2s | 🔲 |
| D19 | Multi-TF direction | signal row dir_fast/mtf | per-TF arrows at 1m speed | 🔲 |
| D20 | Alerts/notifications | new tradeable signal while page open | toast fires | 🔲 |

## 2 · TRAINING LAB (/training)

| ID | Feature | Test procedure | Expect | Status |
|---|---|---|---|---|
| T1 | Run buttons 0–13 (dataqa…nqwr) | click each with QQQ/5m | job streams to run log, report lands in its panel; "unknown kind" NEVER (else restart hint shows) | ✅ 07-05/06 (all kinds exercised via CLI/API) |
| T2 | TF selector pass-through | dataset/ml/nn/heads/sweep with 15m | `--tf=15m` in the command line of the run log | ✅ 07-05 (sweep 15m loader) |
| T3 | Continuous training start/stop + history | Start; watch history | cycles log per symbol; SKIPS when dataset unchanged ("dataset unchanged — ml/nn skipped") | ✅ 07-05 (skip observed) |
| T4 | Skip-signature includes L2 | after an L2 sync, next cycle | does NOT skip (l2 mtimes in signature) | ✅ 07-06 (code path) 🔲 live confirm |
| T5 | Approval ladder + version dropdown | select each lineage | stages render inside the card, WHAT-you-approve details per lineage | ✅ 07-06 (fit CSS + versions live) |
| T6 | One-click APPROVE+paper+learning | click on a test lineage | ladder approved + paper armed (or exact blocker) + continuous training "started/already running" + joins duel | ✅ 07-06 (endpoint) 🔲 UI click |
| T7 | Revoke cascades | revoke replay | paper falls with it; paper autotrade disarms next cycle | 🤖 |
| T8 | STRATEGY DUEL panel | open /training | 4 modules, ⚡ options line, IN THE DUEL vs awaiting; fits the card | ✅ 07-06 (live /api/duel) |
| T9 | Duel daily tick | next completed daily bar | open positions appear for approved modules; resolve over days | 🔲 (needs bar-store refresh) |
| T10 | Pending models + promote | after a gate-passing run | model listed with metrics; Promote makes it champion | 🤖 (no gate-passer yet — blocked on data) |
| T11 | L2 register file/folder + dedupe | re-register same folder | "folder scanned: N registered", duplicates are no-ops | ✅ 07-06 |
| T12 | L2 SYNC ALL + progress + errors | click with pending sources | per-file progress, errors listed, store APPEND-MERGES days | ✅ 07-06 (12 files, 8 QQQ days) |
| T13 | Post-sync AUTO-TRAIN + retrain button | after sync completes | "AUTO-TRAINING: ml QQQ" in panel → datasets rebuilt → ml/nn run | ✅ 07-06 (observed end-to-end) |
| T14 | Drag-drop synthesize | drop a small csv | in-memory synthesis, rows reported, raw never saved | 🔲 |
| T15 | Reports click-to-view | click a report row | raw JSON renders | 🔲 |
| T16 | Gauntlet form + sweep prefill | click a sweep row → gauntlet | params prefill; 7 checks render with full "used" detail | ✅ 07-05 |
| T17 | Audit trail panel | any state change | audit rows append (approvals, syncs, toggles) | 🤖 |
| T18 | Report matrix + cost stress | button 8 | per-year/regime/DOW slices + 2x-slip warnings | ✅ 07-05 |
| T19 | Replay parity | button 9 | 100% match, 4 symbols | ✅ 07-06 (07.4: 100% ×4) |

## 3 · STRATEGY ENGINE (canonical entry — engine + BOT + Pine)

| ID | Feature | Test procedure | Expect | Status |
|---|---|---|---|---|
| E1 | FSM states (WAIT→ARMED→WATCH→FILL + PULLBACK/COOLDOWN/RANGE/LOCKED/INVALID) | pytest + chart why-strings | states + first-failing-gate text | 🤖 + ✅ (user charts) |
| E2 | A∨B∨C arming (futures) / Struct+VWAP (equities) | dashboard DIR-fast row | "A: MID ∨B∨C ← ARMS (any engine)" on futures | ✅ 07-06 (user chart) |
| E3 | DIR-fast C (slope strong) | B-row C▲/▼ STRONG marker | matches |S|≥0.30 | ✅ 07-05 (self-test vs engine) |
| E4 | Instant fill (ES exempt) | NQ aligned strong-body break | fills same candle; ES waits | 🤖 (A/B validated) |
| E5 | Watch machine + cooldown + stale + two-entry | pytest + sweeps | gauntlet-adopted per asset | 🤖 |
| E6 | Chase-cap 1.0 + pullback retest | **blocker_edge.py** (this study) | cohort verdict decides keep/relax | ⚠ see §5 |
| E7 | Narrow-OR vol-expansion 2.4 | **blocker_edge.py** | cohort verdict | ⚠ see §5 |
| E8 | SPY stand-down | A/B 07-05 | removing it collapses every symbol — KEEPER | ✅ 07-05 |
| E9 | Macro regime B/D blocks | pytest + dashboard Macro row | regime + block reason | 🤖 |
| E10 | Hard invalidation + reclaim | chart INVALID → reclaim | resets to WAITING | ✅ (user charts) |
| E11 | Grade ladder v2 (C/B/A/A+) | dashboard GRADE row | +VWAP=B +STRUCT=A +SLOPE=A+ | ✅ 07-05 |
| E12 | Crypto weekend exemption | BTCUSD chart on weekend | can arm | ✅ 07-05 |
| E13 | Live≠backtest parity of gates | **NEW: after §5 verdict** | run_backtest carries the SAME gates live enforces | 🔲 **the open item** |

## 4 · ML/NN PLATFORM + GOVERNANCE

| ID | Feature | Test | Expect | Status |
|---|---|---|---|---|
| M1 | PIT features (59) + rejects + multi-TF datasets | dataset builds | rows + spans per tf | 🤖 |
| M2 | Purged WF + embargo + gates + slices | pipeline runs | honest fails until data improves | 🤖 + canaries |
| M3 | Leakage canaries | pytest | shuffled labels ≈ 0.5 AUC | 🤖 ✅ |
| M4 | Calibration honest split + duel-holdout fix | pipeline report fields | calibration_note present | ✅ 07-05 |
| M5 | Similarity clusters live | proposals carry cluster read | promoted, votes in ensemble | ✅ 07-05 |
| M6 | Heads / no-trade / expected-R | heads runs | reports; none past gates yet | 🤖 |
| M7 | L2 features → dataset join | after bar-store refresh past Jun 9 | l2_* non-NaN on new candidates | 🔲 **blocked on bar-store refresh** |
| M8 | Ensemble + kelly + explanations | proposal JSON | ai_decision reasons incl. nn_seq when present | ✅ 07-05/06 |
| M9 | Approval lineages + audit | §2 T5-T7 | per-version records | ✅ 07-06 |
| M10 | Restart recovery + reconcile | restart server with kill on | kill stays on; reconcile every ~10 cycles when paper armed | ✅ 07-05 |
| M11 | Orderflow persistence | data/orderflow_scores.csv grows | minute rows per scan | ✅ 07-05 (self-test) 🔲 live file check |
| M12 | Options leg shadow-recording | tracked signal json | options structure stored | ✅ 07-05 |
| M13 | Scan capture window resilience | (was the NQ miss) | bars_back=12; restart cannot drop a signal | ✅ 07-06 (fix) |

## 5 · BLOCKERS-BY-DESIGN — the edge re-tests (the user's ask)

Run `python research/blocker_edge.py QQQ SPY NQ ES` → `blocker_edge.json`. It measures, under
07.4, the exact cohorts each live blocker removes (chase-cap, narrow-OR) — **and it exposed
that the canonical backtest never carried these two gates at all** (live traded a SUBSET of
every validated number). Decision rule per blocker per symbol:
- blocked cohort avg R **negative** → the blocker EARNS; add the gate to `run_backtest` so the
  canonical numbers match live (rule bump 07.5, datasets re-key, parity re-run);
- blocked cohort avg R **positive** → the blocker COSTS edge → gauntlet a per-asset relax.
Already settled by earlier A/Bs: SPY stand-down (keeper, 07-05) · VWAP arm-gate on futures
(dropped, 07.3) · A∨B∨C (adopted futures, 07.4) · instant-fill (per-asset, ES off).
Results + verdicts: see the study report and CHANGELOG.

## 6 · ORDER OF THE MANUAL PASS
1. §1 D1–D20 top to bottom during one RTH session (30 min).
2. §2 T1–T19 (T9 waits for the daily bar; T10 waits for a gate-passer).
3. §3/§4 rows marked 🔲.
4. §5 verdicts → implement the winner (E13) → 07.5 verification chain (tests + parity + A/B).
File every deviation as: `<row ID> — what you saw vs expected`.
