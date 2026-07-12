# Remediation Plan — verified audit findings → designed fixes
*(2026-07-11 · status: ACTIVE — approved 2026-07-11, Phase 0 landed same day (item 0.5 pending
user decision) · code changes begin with Phase 1 on approval)*

This is the single tracking document for fixing the 2026-07-11 active-system audit. Every finding
below was **verified against code at the cited line** before being planned (nothing here is taken
from the audit on faith; two of its claims were softened after verification — see §Nuances).
Maintained alongside `TASKS_INCOMPLETE.md` (the living status checklist). When a phase lands, its
status line here flips and the regression-test IDs are recorded next to it.

## Adopted direction (user, 2026-07-11)

> The project does not need more strategies, indicators, dashboards, or AI features right now.
> It needs correctness, integration, and trustworthy evidence.

**The product's two questions (entry-first charter, 2026-07-11).** Everything the system does
supports exactly two questions: **"Is this a high-quality entry right now?"** and **"Has this
exact entry produced reliable profit after costs?"** The remediation exists so both can be
answered from proven data. Entry is the core product; once the foundation is corrected, the first
use of it is Phase E — prune rule 07.7 to the entry types that demonstrably make net money.

New strategy / indicator / dashboard / AI feature development is **frozen** until the P0 chain
completes. The needs and where this plan delivers them:

| # | Need | Where in this plan |
|---|---|---|
| 1 | Trustworthy backtest foundation (PIT joins, exec rules, excursions, gaps, roll adjustment, per-asset + options economics) | Phases 1–3, regenerated in R |
| 2 | Fail-closed data pipeline (freshness, sessions, volume, grain, overlap, instrument identity, manifests) | Phase 4 |
| 3 | One mandatory trading lifecycle for every order source | Phase 5 |
| 4 | Real account-level risk state (P&L, drawdown, exposure, streaks, margin, health) — block when unprovable | Phase 5 §Account truth |
| 5 | Real paper-fill evidence program (fills, slippage, acks, rejections — not shadow outcomes) | Phase 5 §Journal + Phase 6 |
| 6 | Enforced approval/release gates with auto-invalidation | Phase 6 |
| 7 | Persistent OMS + reconciliation with full recovery matrix | Phase 5 |
| 8 | Accurate health + operational safety (backup/restore, one topology, DR tests) | Phase 7 |
| 9 | Pine/Python behavioral parity (compiled, bar-by-bar) | P1.2 — before ML retraining |
| 10 | Stronger automated verification | T-tests per phase + P1.6 CI |
| 11 | Clean ML/NN lineage (version-pure labels, holdout, drift, rollback) | Phase 6 guard + P1.1/P1.3 |
| 12 | One authoritative status document | Phase 0 item 0.6 (`docs/STATUS.md`) |
| 13 | UI as the control + evidence layer (operator console, added 2026-07-11) | Phase U — ships incrementally with Phases 4–7 |
| 14 | Failure-mode register — every named bug pinned to a guard + test (added 2026-07-11) | Appendix A |
| 15 | Entry-first: which exact entries make net money; prune the rest (added 2026-07-11) | Phase E + the two primary views (Phase U) |

End state, in order: repair history → regenerate evidence → unify execution → collect genuine
paper fills → harden ops → prove parity → retrain ML → **only then consider a minimal live pilot.**

## Ground rules (apply to every phase)

1. **Live stays locked.** `LIVE_APPROVED.lock` is untouched for the duration. Nothing in this plan
   changes live-trading capability.
2. **Current backtest numbers are demoted to "indicative".** No expectancy/PF/A-B number produced
   before Phase R (regeneration) may be used as approval evidence. The clean forward record
   (judged from the 2026-07-10 open) is unaffected — it is forward data.
3. **Test-first, every defect.** Each fix starts with a regression test that is RED against the
   current code (proving the test catches the defect), then the fix, then GREEN. A fix without its
   red-first test does not merge.
4. **One phase at a time.** Each phase ends with a verification gate (listed per phase). No
   cherry-picking items across phases — the ordering is a dependency chain.
5. **Fix ≠ recalibration.** Phases 1–4 will move historical numbers (mostly down — the lookahead
   and optimistic exits flattered results). That is expected and is the point. The old-vs-new
   delta is documented in Phase R, not hidden.
6. **Feature freeze.** No new strategies, indicators, dashboards, or AI features while the P0
   chain is open. Watch-only research (studies that observe, wire nothing) is exempt; anything
   touching the live loop or model zoo waits for the chain to close. **The operator console
   (Phase U) is explicitly NOT a frozen feature** — it is the control and evidence layer *of* the
   remediation; UI work outside Phase U's scope (new charts, cosmetic panels) stays frozen.

## Phase overview and dependency order

| Phase | Theme | Why this order |
|---|---|---|
| 0 | Freeze + doc governance | Stop trusting/producing tainted evidence before touching code |
| 1 | Point-in-time correctness (lookahead) | Everything downstream consumes these bars |
| 2 | Simulator correctness | Backtest numbers are inputs to every later gate |
| 3 | Asset economics + futures adjustment | Same reason — cost/feature truth |
| 4 | Fail-closed data pipeline | Regeneration (R) must run on QA-hard data |
| R | Regenerate all evidence | Only valid once 1–4 are green |
| E | Entry Profitability Program (matrix + pruning) | Consumes R's corrected history; concludes with Phase 5's paper fills |
| 5 | One execution path (risk → OMS → fills) | Forward evidence collection depends on it |
| 6 | Phase-7/8 schema + approval predicates | Needs Phase 5's real fills to mean anything |
| 7 | Fail-closed ops (health/watchdog/state) | Independent, but its tests reuse 5/6 plumbing |
| U | Operator console (UI = control + evidence layer) | Cross-cutting — each view ships inside the phase that produces its data (4–7) |
| P1 | Lineage, Pine parity, API security, CI | After the P0 chain |

---

## Phase 0 — Freeze + documentation governance (no code)

**Findings addressed:** stale contradictory status docs (doc-governance audit, 2026-07-10);
README claims stop-entry/all-day results as current ([README.md:14](../README.md)).

| # | Action | Done when |
|---|---|---|
| 0.1 | Stamp deprecation banners on `BOT/Docs/REMAINING.md`, `BOT/Docs/REMAINING_FEATURES.md`, `BOT/Docs/IMPLEMENTATION_STATUS.md`, `docs/bot-review/TASK_LEDGER.md`: "historical snapshot as of <date> — do not use for status; see docs/TASKS_INCOMPLETE.md + docs/REMEDIATION_PLAN.md" | Banners present |
| 0.2 | Correct the two inaccurate rows in `TASKS_INCOMPLETE.md` (news-lockout overstated ✅; add the 2026-07-10 clean-record reset row) | Rows corrected |
| 0.3 | README: retitle the results table "historical (pre-remediation lineage, superseded by Phase R)" and state the active rule is 07.7 close-confirm | README honest |
| 0.4 | Tag every existing report under `BOT/data/ml/reports/` as pre-fix lineage (a `lineage: "pre-remediation"` key or a `_prefix` archive folder) so regenerated reports can never be confused with tainted ones | Old/new reports distinguishable programmatically |
| 0.5 | Decision (user): keep `paper_autotrade` OFF until Phase 5 lands, since its orders bypass the risk gate. Recommended: OFF — the shadow tracker keeps collecting signal outcomes regardless; only broker-fill data pauses | Toggle state decided + noted here |
| 0.6 | Create **`docs/STATUS.md`** — the single authoritative status page: current strategy version · active execution mode · implemented vs scaffold-only · datasets + date ranges · latest valid evidence (with store fingerprints) · open blockers · exact startup procedure · release criteria · list of historical-only documents. Updated on every landed phase; deprecation banners (0.1) point here | STATUS.md exists; every banner references it |

**Gate:** no document in the repo claims pre-fix backtest numbers as current evidence, and
`docs/STATUS.md` answers "what is true right now" without reading code.

---

## Phase 1 — Point-in-time correctness (audit P0.1) — the lookahead

**Verified defect:** [engine/hs_backtest.py:33-58](../engine/hs_backtest.py) `_externals` merges
same-date daily VIX `sma5`, ES `close/e20/e50/adx`, and symbol `htf_bull/htf_bear` onto every
intraday bar (no shift). Consumed by the macro regime at
[engine/hs_harness.py:303-319](../engine/hs_harness.py); inherited by the BOT replay via
[BOT/bot/strategy/orb_candidates.py:123](../BOT/bot/strategy/orb_candidates.py).

### Fix design

- **Prior-closed-session join:** shift each daily frame by one row (one *trading* day — row-shift
  on the daily table is inherently exchange-calendar-aware, no calendar library needed) before the
  merge. Day D's intraday bars see day D−1's VIX sma5, ES close/EMAs/ADX, and HTF alignment.
  Implementation shape: `daily["date_avail"] = daily["date"].shift(-1)` … or equivalently shift the
  value columns by 1 and keep the date key; either way the invariant is
  `max(source_date) < bar_date` for every daily-derived column.
- **VIX detail:** `vix_prev5` (close 5 days back) becomes 6 days back relative to the bar's day —
  keep the *spread definition* (sma5 vs close[5]) intact, both legs lagged by one day.
- **Live-parity check:** the live scan computes these context values from *already-closed* daily
  data at scan time — confirm the live path (families/market_context) uses the prior close, so the
  fix makes backtest match live, not the reverse.
- **Semantics doc:** one paragraph in `docs/ENTRY_STANDARD.md` defining feature availability:
  "daily-derived features are available from the next session's first bar."

### Regression tests (written first, RED on current code)

- **T1.1 poison canary** (extends `BOT/tests/test_leakage_canary.py`): synthetic daily series where
  day D's value is a sentinel; assert no intraday bar dated D carries the sentinel through
  `_externals`.
- **T1.2 property test:** for every daily-derived column, the contributing daily row's date < bar
  date, over a real store sample.
- **T1.3 regime-shift test:** a regime flip on day D must first affect gating on day D+1.

**Gate:** T1.1–T1.3 green; a one-page before/after diff of trade counts + expectancy per symbol
(expect: numbers move; record by how much — this quantifies how much lookahead flattered results).

---

## Phase 2 — Simulator correctness (audit P0.2)

**Verified defects** (all in [engine/hs_backtest.py:494-534](../engine/hs_backtest.py) unless noted):

| ID | Defect | Line |
|---|---|---|
| S1 | Exit evaluation starts on bar after entry; entry-bar remainder unexamined | 500 |
| S2 | Stop/TP checked before day-change/EOD flatten | 503-527 |
| S3 | Short MFE/MAE computed with long-side extremes (short MFE understated, MAE ~0) | 502 |
| S4 | Stop exits valued at stop even when price gaps through | 511-526 |
| S5 | Same-bar ambiguity inconsistent: stop-first before TP1, TP2-first after TP1 | 516-526 |
| S6 | `maxdd` misses initial drawdown (equity curve lacks the 0 start) | hs_validate.py:28 |
| S7 | Touch/stop exec modes fill on current-bar high/low while gates use same-bar close | 180-199 |

### Fix design — explicit bar-event ordering policy

Adopted policy, enforced in one place and documented at the top of the backtest module:

1. **Day boundary first.** If `daykey[i] != entry_day`: position should not exist — exit at
   **bar i's open** (gap-aware), flag the trade `eod_leak` for audit. (After the EOD fix this path
   should be rare: short sessions without a ≥15:58 bar.)
2. **EOD bar:** on the first bar with `tod >= eod_min`, flatten at that bar's **close** — evaluate
   intrabar stop/TP on that bar first (a stop during 15:55-16:00 is real), then flatten.
3. **Same-bar ambiguity rule (uniform):** when stop and target are both touched in one bar,
   **stop wins** — before *and* after TP1. Conservative by construction. Additionally emit an
   `ambiguous_bar` count per run so the size of the ambiguity is visible (if it ever exceeds ~2%
   of exits, revisit with intrabar 1m resolution instead of a coin-flip policy).
4. **Gap-aware fills:** long stop fill = `min(open[i], stop)`; short stop = `max(open[i], stop)`.
   Targets stay filled at the target (never better) — asymmetric on purpose (conservative).
5. **Entry bar (S1):** for the canonical close-confirm mode, entry is the bar close — exits from
   the next bar are *correct*; codify with a comment + test. For touch/stop/retest research modes,
   evaluate the entry bar's remainder using rule 3 with the entry price as the reference.
6. **Side-aware excursions (S3):** `mfe = max(mfe, sig*( (h if sig==1 else l) - entry)/risk)`,
   `mae = min(mae, sig*( (l if sig==1 else h) - entry)/risk)`. Note downstream consumers: the
   evolve engine's TP-revision drafts use median MFE — expect its drafts to change for shorts.
7. **maxdd (S6):** prepend 0: `eq = np.concatenate([[0], np.cumsum(r)])`.
8. **Same-bar gate/fill mixing (S7):** in touch-exec research modes, any gate consuming bar i's
   close (arming, reclaim, fade-confirm) may only authorize fills from bar i+1 on. Canonical 07.7
   is unaffected (close exec) — fix applies to the research paths and is labeled as such.
9. **Validation statistics:** replace the plain bootstrap with a **day-level block bootstrap**
   (resample whole trade-days) so serial dependence and regime clustering survive resampling.

### Regression tests

- **T2.1** golden synthetic fixtures, one per defect: gap-through-stop bar, stop+TP2 same bar
  (pre- and post-TP1), short trade with known MFE/MAE, first-two-trades-lose DD, position crossing
  a short session's end, EOD-bar stop.
- **T2.2** determinism: fixed input → byte-identical trade list (protects Phase R comparability).
- **T2.3** policy doc-test: the ordering policy above rendered in the module docstring and asserted
  by the fixture outcomes (docs and code cannot drift).
- **T2.4** trade-day/timezone fixtures: a Sunday futures session groups to the correct trade day;
  an EOD exit lands in the entry's session, never the next; a signal at the ET-vs-UTC date
  boundary carries the exchange-time day (RTH and overnight never merge into one cohort).

**Gate:** T2.x green; before/after expectancy diff appended to this file (per symbol, per exit mode).

---

## Phase 3 — Asset economics + futures adjustment (audit P0.3)

**Verified defects:** all futures priced as MNQ
([engine/hs_backtest.py:395-401](../engine/hs_backtest.py) — equities have a carve-out, NQ/ES/GC
do not); `adj_factor` stored ([pipeline/hs_build_continuous.py:10-12](../pipeline/hs_build_continuous.py))
and carried through resampling, but referenced nowhere in `engine/` — momentum indicators cross
roll jumps on raw prices. `hs_validate.py:20` hardcodes MNQ point value. Research scripts (e.g.
`nq_composite_gauntlet.py`) carry their own copies of the MNQ constants.

### Fix design

- **Contract registry:** `conf/contracts.py` (single source): per symbol → point value, tick size,
  commission/side, default slip ticks, currency; date-effective if a spec ever changes. Seed:
  NQ $20/0.25 · MNQ $2/0.25 · ES $50/0.25 · MES $5/0.25 · GC $100/0.10 · equities $0.01 tick,
  commission-free. Engine, validator, and research scripts import from it — the copies die.
- **Adjusted analytics / raw execution:** the harness computes a parallel `close_adj/high_adj/low_adj`
  (raw × adj_factor) and uses **adjusted** for ATR, EMA, DMI, momentum, and any cross-day return;
  **raw** stays for levels (OR high/low, VWAP, pivots, round numbers) and for fills. This matches
  the documented intent in `hs_build_continuous.py` that was never wired.
- **Slippage honesty note:** slippage remains in ticks per contract from the registry; the 2×-cost
  stress in the platform reuses registry values instead of MNQ constants.
- **Options economics:** the 0DTE/7DTE options paths get their own registry entries — per-contract
  commission + regulatory fees + half-spread from the real chain where available. Options journals
  and studies must not inherit equity-share economics.

### Regression tests

- **T3.1 roll-boundary test:** synthetic series with a known roll jump; assert ATR/EMA show no
  artificial spike vs the adjusted series, and that OR levels still match raw prices.
- **T3.2 economics table test:** one known trade per symbol → expected $ and R cost from the
  registry (catches any future constant drift).

**Gate:** T3.x green; no `PT_VALUE, TICK, ... =` constant tuples left outside the registry
(grep-enforced in the test).

---

## Phase 4 — Fail-closed data pipeline (audit P0.4)

**Verified defects:** intake ignores subprocess return codes
([pipeline/intake.py:44-50](../pipeline/intake.py)); QA computes zero-volume + short-day counts but
excludes them from `issues`, and has no freshness check
([pipeline/hs_data_qa.py:56-74](../pipeline/hs_data_qa.py)) — which is why `data_qa_all_ok=true`
coexists with a store ending June 8; equity ingest has no symbol filter
([pipeline/hs_ingest_equity.py:19-21](../pipeline/hs_ingest_equity.py)); 5m rows live in the
nominal-1m store ([pipeline/hs_append_5m.py](../pipeline/hs_append_5m.py) — documented tradeoff,
but grain is unvalidated).

### Fix design

- **Fail-closed orchestration:** `intake.run()` raises on `rc != 0`; `main()` wraps steps in an
  ordered ledger — a failed step aborts everything downstream of it and the intake exits non-zero.
  A `--keep-going` flag exists for manual salvage runs, never default.
- **QA gates become gates:**
  - zero/negative volume above threshold (default: any RTH bar) → issue;
  - short days above threshold (default: >2% of days under 90% expected bars) → issue;
  - **freshness:** span end older than N trading days (default 3; per-symbol override) → issue;
  - **grain:** median + p95 bar spacing must equal the table's nominal tf → issue (this makes the
    5m-in-1m span an *explicit, documented* exception registered in the manifest, or it fails).
- **Duplicate/overlap protection:** ingesting a source file whose span overlaps existing store rows
  requires an explicit `--replace-span`; silent double-append is impossible. This generalizes the
  MBO manifest's removal contract to every ingest path (the L2 misconfig of 2026-07-06 becomes
  structurally unrepeatable).
- **Symbol identity:** `hs_ingest_equity` asserts single-instrument input (symbol column match when
  present; else price-continuity fingerprint — max bar-to-bar jump sanity) before writing.
- **Dataset versioning + source manifests:** every QA pass writes `{store_fingerprint: sha256 over
  (sym, tf, row-count, span, sum(volume))}` into `dataqa.json`, and every ingest records a source
  manifest row (file path, sha256, date span, symbol). Downstream reports and datasets embed the
  fingerprint they were built from. Approval evidence (Phase 6) matches on it.

### Regression tests

- **T4.1** intake step with rc=1 → intake fails, downstream steps not invoked.
- **T4.2** QA fixture with stale span / zero-vol RTH bars / short days / wrong grain → `ok:false`
  with the right issue strings; healthy fixture → `ok:true`.
- **T4.3** two-symbol CSV into `hs_ingest_equity` → hard error.

**Gate:** running QA on the *current* store must FAIL (stale spans, NQ partial last day) — the
failure is the proof the gate works. Refreshing the store clears it.

---

## Phase R — Regenerate all evidence (runs after 1–4, before 5–7 conclusions)

1. Refresh/extend the bar store (user's data pulls where feeds are external), QA green under
   Phase 4 rules.
2. Re-run: canonical backtests per asset/tf, A/B entry-standard report, per-asset champion
   sweeps, geometry study, cost stress — all stamped `strategy 07.7 + remediation lineage +
   store fingerprint`.
3. Rebuild ML datasets and labels from the corrected replay (labels inherit every Phase 1–3 fix);
   archive old datasets as `pre-remediation`.
4. Produce `docs/REMEDIATION_DELTA.md`: old vs new headline numbers per fix class (lookahead,
   exits, economics) — the honest record of how much the defects flattered results.
5. **Re-decide** which lineages still pass the 7-gate gauntlet under corrected numbers. Any
   lineage that only passed on tainted evidence loses its approval (Phase 6 wiring makes that
   automatic; here it is done manually once).

**Gate:** every number quoted anywhere (README, dashboards, approval evidence) traces to a
post-remediation report with a store fingerprint.

---

## Phase E — Entry Profitability Program (user charter 2026-07-11: entry-first)

**The objective, verbatim:** determine exactly which 07.7 entries are profitable — for which
symbols, sides, sessions and market conditions — and remove every entry type that does not hold
up out of sample and in paper fills.

Dependencies: the historical half consumes **Phase R's corrected evidence** (any matrix computed
before R is indicative only, per ground rule 2); the forward half concludes with **Phase 5's
broker paper fills**. The matrix skeleton and classification inventory can be built in parallel
with Phases 4–5.

### E.1 Entry classification — captured at signal time

Every tracked signal carries the classification dimensions: symbol · side · session · entry
family · grade · entry time · breakout distance · OR width · stop distance · volume · trend
alignment · market regime · immediate-vs-pullback · chase distance · strategy version.

Most of these already exist in the 59-column PIT feature schema and the tracker/journal — E.1 is
an **inventory plus the few missing columns** (immediate-vs-pullback flag, chase distance at
fill), not re-instrumentation. P1.1 lineage rules apply: the strategy version on each row is
immutable, never back-stamped.

### E.2 The Entry Profitability Matrix — the main research artifact

Hierarchy: **symbol → side → session → entry type → grade → regime → profitability.** Per cell:
n · win rate · **net** expectancy (win rate × avg win − loss rate × avg loss − commissions −
spread − slippage; costs from the Phase 3 registry) · PF · total R · avg winner / avg loser ·
max DD · consecutive losses · trades/week · measured slippage (paper/live cells) · confidence
interval · sample size.

Rules:
- One API report, recomputed from the journal on demand — never a hand-maintained table.
- Evidence types separated per cell: historical backtest · replay · shadow · paper fills · live
  fills (Phase U rule 3 — never mixed, and the API refuses a mixed query).
- Cells under the sample floor (default n < 30) render **INSUFFICIENT SAMPLE** (Phase U rule 6) —
  a −0.48R cell with n=9 and a CI spanning zero must not look like a verdict.
- Rendered in the **Profitability Lab** view (Phase U).

### E.3 Removal governance — pruning is a rule change, not a dashboard toggle

The matrix **nominates** losing entry groups; it never auto-blocks on sight. This guard is
load-bearing: the F78 pullback study showed several intuitive vetoes FAIL cohort testing — the
blocked cohort was *profitable* (e.g. gap rules, relative-volume confirm). A removal must prove
the blocked cohort actually loses, on both history halves AND out of sample. An adopted removal:

- becomes per-asset config (an entry-type toggle) enforced in the **engine and the
  ExecutionService** — a blocked group can neither fire nor submit; it is not merely hidden;
- bumps the strategy version (07.7 → 07.8 …), which auto-invalidates downstream approvals
  (Phase 6) and forces the A/B evidence to regenerate;
- stays visible as a REMOVED row in the matrix with its evidence link, and its cohort keeps
  accruing shadow data — a wrong removal is detectable and reversible, not silent.

### Tests

- **TE.1** matrix determinism: same journal → identical cells.
- **TE.2** the report API refuses any query that aggregates across evidence types.
- **TE.3** a removed entry group can neither fire in the engine nor submit through the service.
- **TE.4** under-sample cells return INSUFFICIENT SAMPLE — never 0.00R, never green.

**Gate:** matrix live on Phase-R-corrected history with shadow/paper cells accruing; at least one
full removal cycle documented end to end (nomination → cohort test → adopt or reject, with
evidence) — the *process* is the deliverable, whichever way the first verdict goes.

---

## Phase 5 — One execution path (audit P0.5 + P0.6)

**Verified defects:** `_paper_autotrade` calls the broker directly — no `risk.decide()`, no OMS, no
journal fills, no position tracking ([BOT/bot/api/server.py:161-224](../BOT/bot/api/server.py));
idempotency key lacks the trade date (line 211) and is marked placed even on broker ERROR
(line 220 + [alpaca_broker.py:118-119](../BOT/bot/brokers/alpaca_broker.py)); `reconcile_once`
defaults to a fresh empty OMS ([BOT/bot/reconcile.py:24](../BOT/bot/reconcile.py)) and the scan loop
passes none; manual/webhook orders build `Account` from equity+mode+kill-switch only
([server.py:1776-1778](../BOT/bot/api/server.py)) leaving weekly-loss/streak/correlation gates
checking empty defaults ([risk.py:45-54](../BOT/bot/risk.py)).

### Fix design

- **`bot/execution/service.py` — the only door to a broker.** Signature:
  `submit(candidate, source: "autotrade"|"manual"|"webhook") -> ExecutionResult`. Every order
  source calls it; direct `broker.submit` outside the service becomes a test-enforced lint error.
  Flow, transactional per step:
  1. **Account truth:** equity, buying power / margin, and open positions from the broker;
     daily + weekly realized P&L, peak equity / trailing drawdown, trades-taken-today, and
     consecutive-loss streak from the fills table (below); `open_symbols` from *reconciled*
     positions; current feed health, broker health, and reconciliation status attached to the
     Account. If any component is unavailable or stale → **risk-reject with
     `ACCOUNT_STATE_UNPROVEN`** (fail closed — an unprovable limit is a breached limit).
  2. `risk.decide(candidate, account)` — the existing gate, now fed real state.
  3. **Persistent OMS:** orders / order_events / fills tables in the existing SQLite store
     (`store.py`), written before broker submission (state=PENDING_SUBMIT), updated from broker
     events. Restart recovery = load non-terminal orders, poll broker by `client_order_id`.
  4. **Idempotency:** key = `sha1(symbol|side|entry|session|trade_date|strategy_version)`; stored
     with state PENDING before submit; only an ACCEPTED broker response finalizes it. ERROR →
     key released after the order row records the failure (bounded retry allowed next scan).
  5. **Journal — the paper-execution record.** Per order, recorded fields: signal price +
     timestamp · submission and broker-ack times · every partial/complete fill (qty, price) ·
     average fill price · slippage vs signal price · rejections/cancellations · exit fills ·
     realized P&L and R · the reconciliation verdict it closed under. This record — not shadow
     outcomes — is what Phase 6 judges.
- **Fill ingestion:** poll Alpaca open orders + recent closed orders each scan beat (SSE stream is
  a later upgrade); write fills idempotently by broker order id.
- **Reconciliation with teeth:** `reconcile_once(broker, oms)` — `oms` becomes a required argument
  (no empty default); runs at boot and every N minutes; a MISMATCH sets a `halt_submissions` flag
  the ExecutionService honors (fail closed) + fires the alerts channel.
- **Webhook/manual:** `/api/order` and the TV webhook route through the service; their
  hand-rolled Account construction is deleted. Every order/webhook response carries a
  **correlation id + final action** (`rejected | duplicate | shadowed | submitted`) — TradingView
  retries resolve to `duplicate`, never to a second order.
- **Bracket integrity:** after any entry fill, the service verifies the protective legs are
  *working at the broker*; a rejected/missing stop → alert + `halt_submissions` + a CRITICAL row
  in the Reconciliation Center. "Bracket active" is asserted from broker truth, never inferred
  from the submit call having returned.
- **Approval at submit time:** the service re-checks stage approval on every submission
  (multi-tab / cached-page safe) — a revoked approval takes effect on the next order, not the
  next page reload.
- **Order-state staleness monitor:** any non-terminal order older than its staleness budget
  (N× the poll interval) flips to `investigation_required` + alert — no order sits in
  Pending/Submitted/Cancelling forever.

### Regression tests

- **T5.1** autotrade signal → service → risk rejection path (e.g., correlated bucket occupied)
  produces NO broker call (mock broker asserts).
- **T5.2** broker ERROR on submit → key not finalized → retry next cycle; ACCEPTED → key final.
- **T5.3** same signal, same day → dedup; same signal geometry, next day → allowed.
- **T5.4** recovery matrix, one test per scenario: crash-before-submit · crash-after-submit-before-ack ·
  broker timeout where the order was actually accepted (poll by `client_order_id` resolves it, no
  duplicate) · partial fill then restart · cancel/replace sequence · orphaned broker position
  (position with no internal order → halt + alert) · duplicate webhook/button click → one order.
- **T5.5** injected position mismatch → submissions halt until cleared.
- **T5.6** week P&L −2.1% in fills table → weekly-loss gate actually blocks (proves Account is fed).
- **T5.7** entry filled + stop leg rejected (mock) → halt + alert + CRITICAL reconciliation row.
- **T5.8** stale non-terminal order → `investigation_required`; approval revoked between page load
  and submit → next submission refused.

**Gate:** T5.x green; grep-test proves no call site submits to a broker except the service; paper
autotrade re-armed only after this gate (see 0.5).

---

## Phase 6 — Evidence schema + approval predicates (audit P0.7)

**Verified defects:** `phase78.execution_quality` reads `entry/planned_entry/fill_price/avg_fill_price`
([BOT/bot/phase78.py:93](../BOT/bot/phase78.py)) but `JournalEntry` defines `entry_price` only
([BOT/bot/contracts.py:384-403](../BOT/bot/contracts.py)) → execution quality is structurally n=0;
approvals enforce stage order but treat evidence as informational
([BOT/bot/approval.py:42-88](../BOT/bot/approval.py)); model promotion checks nothing
([BOT/bot/ml/registry.py:163-174](../BOT/bot/ml/registry.py)); the serving path accepts a champion
whose `strategy_version` (07.4) mismatches the current rule (07.7).

### Fix design

- **Fill schema:** extend `JournalEntry` with `planned_entry: float|None` and
  `avg_fill_price: float|None` (+ `schema_version` bump; old rows readable — fields default None).
  Phase-5's service writes them; `execution_quality()` reads the real names. No silent fallbacks.
- **Approval predicates:** `approve(version, stage)` **requires** a green evidence snapshot.
  For `paper`: `data_qa_all_ok` (Phase 4 rules) · `ab_strategy_version_match` · backtest/A-B
  reports regenerated *after* the latest rule change (report timestamp > rule-change timestamp) ·
  test-suite marker fresh · no-lookahead canary green (Phase 1) · store fingerprint matches the
  A/B report's. For `live`, additionally: measured paper execution quality with sufficient fills
  (below) · forward paper expectancy within its scorecard band · reconciliation clean (zero
  unresolved mismatches) · Pine/Python parity marker green (P1.2) · champion model + feature
  schema match the strategy version. The snapshot is stored immutably with the approval record
  (who/when/evidence-hash). An `--override` exists, but writes `override: true` into the record —
  visible forever.
- **Auto-invalidation:** any change to strategy version, dataset fingerprint, feature schema,
  config, or the champion model marks dependent downstream approvals **`stale`** — visible on the
  approval screen and refused by every arm check (ExecutionService included) until re-evidenced.
  Approvals for other versions stay valid *for those versions* (already keyed by version).
- **Phase 8 runs on real fills only:** execution-quality and the paper study read the Phase-5
  paper-execution record (broker fills), never shadow outcomes. The existing thresholds stand —
  ≥60 trades AND ≥56 days AND scorecard green AND no grade inversion — **plus zero unresolved
  reconciliation failures** over the study window.
- **Evidence lifecycle states:** every report/dataset carries an explicit backend-advanced
  validity state — `calculated → qa_passed → pit_passed → exec_sim_passed → approved` — one step
  per landed check. "Report exists" never renders as "report valid"; the Strategy Evidence view
  shows the state name, and approval predicates read the state, not the file's existence.
- **Champion/strategy guard:** `predict_candidate` and the NN-similarity serving path refuse a
  champion whose metadata `strategy_version` ≠ current — they fall back to the prior (advisory
  stays advisory, but never version-crossed). `registry.promote()` requires `gates_passed` in the
  model's metadata and records the dataset fingerprint.
- **GET-mutation audit:** inventory all `@app.get` endpoints; any that mutate state (training arm,
  toggles) become POST with the `auth` dependency.

### Regression tests

- **T6.1** journal row with fills → execution_quality n>0; without → "insufficient" (never fake).
- **T6.2** approve(paper) with red evidence → ValueError; with override → recorded as override.
- **T6.3** champion with mismatched strategy_version → serving returns prior + logs once.
- **T6.4** promotion of a model without `gates_passed` → refused.

**Gate:** T6.x green; current 07.7 paper approval re-issued (or explicitly overridden) under the
new predicates once Phase R evidence exists.

---

## Phase 7 — Fail-closed ops (audit P0.8)

**Verified defects:** runtime safety state restores `kill_switch=false` on corrupt JSON, written
non-atomically ([server.py:44-66](../BOT/bot/api/server.py)); `/api/health` hardcodes
`source_healthy: True` and `healthy = not kill_switch` (line 900 — the per-subsystem `beats` are
real, the top-level fields are not); watchdog restarts on any HTTP failure only
([watchdog.ps1:23](../BOT/watchdog.ps1)); 28 restarts logged July 9–10 with no captured cause;
~6 MB unrotated error log.

### Fix design

- **Root-cause first:** before any watchdog change, capture why the server died 28×: wrap the
  worker entry in a top-level crash handler that writes `data/crash_<ts>.txt` (traceback + last
  beats) before exit. One week of crash records precedes symptomatic fixes.
- **Atomic, fail-closed safety state:** reuse the existing atomic-write helper (config.py already
  has the pattern for boss/approvals); on corrupt/unparseable state at boot → `kill_switch=TRUE`
  + alert (never silently default to armed-and-running).
- **Semantic health:** `source_healthy` computed from real feed age (latest bar vs now, per active
  symbol); `broker` from a cached ping when paper features are armed; `healthy` = kill-switch off
  AND scan heartbeat fresh (<3× scan interval) AND no failing beat among the named subsystems:
  market-data freshness · provider connectivity · broker connectivity · scan loop · outcome
  resolver · OMS/reconciliation status · database/storage availability · kill-switch persistence ·
  background-training state. Watchdog checks `healthy==true` + `last_scan_at` freshness, not just
  HTTP 200, and calls a post-restart reconciliation hook (Phase 5's) before considering the
  relaunch successful.
- **Log hygiene:** size-based rotation for the error log + webull SDK logs (they already
  date-rotate); restarts fire the existing alerts channel (`bot/alerts.py`) so 3am deaths page.
- **Backup + tested restore:** scheduled snapshot of `highstrike.db`, journals, approvals, OMS
  tables, and runtime state; a restore script exercised by test (an untested backup is not a
  backup).
- **Single startup topology:** pick ONE production mode — recommendation: the worker+API split
  (`run_all.bat` semantics) with the watchdog pointed at it — document it in `docs/STATUS.md`;
  every other launch script gets a "dev only" header. Restart and disaster-recovery drills run
  against this topology only.
- **Process identity + single instance:** worker and API expose pid / started-at / snapshot age;
  scan and training loops take a single-instance guard (the watchdog's mutex pattern) so an
  abnormal restart can never leave duplicate loops; Mission Control shows *which process*
  produced the data it renders and how old that snapshot is (kills the split-brain
  stale-worker-behind-fresh-API failure).

### Regression tests

- **T7.1** corrupt runtime_state.json → boot with kill_switch true + alert record.
- **T7.2** stale feed (mocked bar age) → `source_healthy:false` → `healthy:false`.
- **T7.3** watchdog simulation: healthy=false with HTTP 200 → restart triggered.
- **T7.4** backup → restore into a scratch location → integrity check green (row counts,
  fingerprints, latest approval record present).

**Gate:** T7.x green; one week with zero unexplained restarts (crash handler proves silence);
one successful restore drill recorded in `docs/STATUS.md`.

---

## Phase U — Operator console (UI as the control + evidence layer; user charter 2026-07-11)

The UI cannot correct lookahead, bad fills, or broken reconciliation — but it must **expose those
problems, block unsafe actions, and guide the operator through the correct workflow**. The current
dashboard and Training Lab evolve from "show information" into an operator console. Phase U is
cross-cutting: each view ships **inside the backend phase that produces its data** (its delivery is
part of that phase's gate — a gate whose truth is invisible in the UI is not landed).

### The main operating flow (rendered as the console's spine)

`DATA TRUST → STRATEGY VALIDATION → PAPER EXECUTION → BROKER RECONCILIATION → APPROVAL → LIVE PILOT`

When a stage fails, the UI **visibly locks every downstream stage** — the operator sees *what* is
blocked and *why*, not a generic error.

### Hard UX rules (apply to every view)

1. **Never display confidence the backend has not proven.** "Unknown" renders as unknown — it
   never defaults to green. No general "healthy" merely because the server responds.
2. **The UI never calculates or overrides risk.** It requests actions; the backend decides. There
   is no visual path around a backend restriction — no "continue anyway" on a critical mismatch.
   Sizing included: the backend returns the authoritative quantity with its calculation trace;
   the UI only explains it (client-side JS never computes a qty that could drift at submission).
3. **Evidence types are never combined.** Historical backtest · replay · shadow outcomes · broker
   paper fills · live fills are distinct series with distinct labels — never one "live performance"
   number, and the word **"live" is never used for shadow outcomes**.
4. **One readiness source.** The console consumes a single backend-computed `/api/readiness`
   (mode, kill switch, per-gate verdicts with verbatim blocking reasons). The UI renders it; it
   never derives readiness client-side.
5. **Four states everywhere: HEALTHY · DEGRADED · BLOCKED · UNKNOWN.** UNKNOWN is never converted
   to green, and any *required* field in UNKNOWN blocks the dependent action.
6. **Missing is never zero.** Absent measurements render as UNKNOWN / NOT MEASURED / INSUFFICIENT
   SAMPLE — never `$0.00` slippage (no data is not perfect execution) or an empty-but-green tile.

### Views — what each shows, and which phase delivers it

**Priority (entry-first charter):** the **Entry Console** ("should I enter now, and why?") and the
**Profitability Lab** ("has this exact entry type actually made money?") are the two primary
views. Everything else supports them.

| View | Ships with | Content (backend source) |
|---|---|---|
| **Mission Control** (evolves `dashboard.html`) | Phase 7 | Answers five questions at a glance: mode (replay/shadow/paper/live) · is trading safe · kill-switch state · what blocks progression · what needs human attention. Renders `/api/readiness` as ✓/✕ lines (e.g. "✕ A/B report belongs to an older strategy version", "✕ Execution-quality fills: 0") |
| **Data Trust** | Phase 4 | Per symbol/tf/session: provider · span · last complete session · expected vs actual bars · missing/short sessions · dupes · bad candles · zero-volume · roll boundaries · checksum · **which backtests/models consume it** · the approval consequence ("Result: strategy approval blocked") |
| **Strategy Evidence** (evolves `training.html`) | Phase 6 (+R) | One evidence card per strategy version: backtest validity (incl. PIT-audit verdict) · dataset hash · Pine compile · parity · A/B version match · shadow forward · paper fills · approval stage. Prevents one version's results being presented as another's evidence |
| **Entry Console** (primary #1; evolves the Signals panel) | states exist today; full console with Phase E | Per candidate, only what the trade decision needs: side · OR levels · trigger · current price · entry/stop/target · risk, reward, R:R — plus the entry state machine rendered honestly: setup developing · armed · waiting for confirmation · entry fired · too extended (do not chase) · waiting for pullback · stale · invalidated · already traded. Every state carries WHY — the exact check that passed/failed ("✕ breakout not confirmed → DO NOT ENTER YET"). The backend already computes these (ARMED→WATCH→FILL, zone state, chase/cooldown/stale rules) — the console *surfaces* them, it never reimplements them |
| **Profitability Lab** (primary #2) | Phase E | The Entry Profitability Matrix (E.2): symbol → side → session → entry type → grade → regime; per cell n, win rate, net expectancy, PF, max DD, CI — per evidence type, never mixed (rule 3); under-sample cells say INSUFFICIENT SAMPLE (rule 6); REMOVED groups stay visible with their evidence |
| **Orders & Fills** | Phase 5 | One traceable timeline per candidate: signal → candidate → risk verdict → submitted → acked → partial/final fills → bracket confirmed → exit → reconciled. A failure shows the exact stage + reason ("BLOCKED AT RISK — daily loss −$412 vs −$375 permitted"), not just "rejected" |
| **Risk cockpit** | Phase 5 | Backend-authoritative Account truth: daily/weekly loss used+remaining · drawdown · trades today · streak · open positions · correlated exposure · buying power · reconciliation state · data freshness · kill switch |
| **Reconciliation Center** | Phase 5 | Dedicated screen (not a status chip): internal vs broker table per position/order/stop; a critical mismatch → red system-wide banner + automatic submission lock (backend flag) + recovery instructions + acknowledge/audit workflow |
| **Models** | Phase 6 + P1.3 | Per model: champion/challenger · label strategy version · dataset hash · feature schema + missing-feature % · trained date · holdout · calibration · drift · approval state · rollback target. A 07.4-labeled model shows **"INCOMPATIBLE WITH CURRENT STRATEGY 07.7 — serving blocked"**, never a silent fallback |
| **Approvals** | Phase 6 | The visible release ladder (Research → Replay → Shadow → Paper → Live pilot → Scale-up); clicking a locked stage enumerates every unmet requirement verbatim from the backend; approve buttons enabled only after the backend confirms all gates |
| **Incidents** | Phase 7 | Restarts (+ last crash reason from the crash records) · failed background jobs · stale heartbeats · provider/broker errors · reconciliation failures · log growth · last backup · last tested restore · whether a restart left unresolved orders/positions |
| **Configuration** | exists | Settings, tokens, toggles — behind `auth` (P1.4) |

### Safer controls (deliberate UX for dangerous actions)

- **Kill switch:** one click, immediate, always available. **Disarm:** authenticated confirmation.
- **Enable paper autotrade:** shows the strategy + evidence summary first (approval state, gate
  verdicts) — armed only if the backend agrees.
- **Live-mode request:** multi-step, typed confirmation — and still subordinate to
  `LIVE_APPROVED.lock` + Phase 6 predicates.
- **Model promotion:** shows lineage + gate results before the confirm.
- **Order cancellation:** shows the broker response *and* the final reconciled state, not just
  "cancelled".

### Interaction states (order actions must be race-proof)

- **Every mutating action:** backend-generated idempotency key · button disabled while pending ·
  an explicit "checking broker status" state · no blind client retry.
- **Uncertain timeout →** `SUBMISSION STATUS UNKNOWN — do not resubmit; broker reconciliation in
  progress.` Never a bare "order failed" (which invites the duplicate).
- **Cancel** renders `CANCEL REQUESTED` until reconciliation confirms; a fill racing the cancel
  shows filled-then-cancel-rejected, never "Cancelled".
- **Partial fills:** requested / filled / remaining / cancelled / **protected** quantities shown
  separately — filled 4 with stop coverage 2 is a visible CRITICAL, not hidden behind "filled".
- **Stale order status:** a non-terminal order past its staleness budget flips to
  `INVESTIGATION REQUIRED` (backend timer, Phase 5) — it never sits looking normally "Pending".
- **Risk-field provenance:** every risk figure shows source + age ("Daily P&L −$230 · broker ·
  8s ago"); a required field at UNKNOWN blocks submission (rule 5). Correlated exposure renders
  as **buckets** (NQ + MNQ + QQQ = one Nasdaq bet), never just a symbol list.
- **Audit timestamps:** operator views use exchange time; audit details show exchange time *and*
  UTC (Phase 2's trade-day tests keep the two from drifting).

### Tests (API-level; browser interaction tests live in P1.6 CI)

- **TU.1** `/api/readiness` enumerates blocking reasons; with any gate red, overall is BLOCKED —
  there is no code path returning a bare green.
- **TU.2** injected reconciliation mismatch → readiness carries the banner flag AND the
  ExecutionService halt flag is set (UI and enforcement come from the same backend state).
- **TU.3** stale Data-Trust verdict → downstream stages (validation → … → live) report locked
  with the upstream cause named.
- **TU.4** every mutating console action requires the `auth` dependency (no unauthenticated
  mutation reachable from a view).

**Gate:** each view lands with its owning phase (its delivery is in that phase's gate); TU.x
green; the console never contradicts `docs/STATUS.md` — both read the same backend truth.

---

## P1 backlog (after the P0 chain — ordered, not yet scheduled)

1. **Label lineage:** add `strategy_version` + `state` (shadow / submitted / accepted / partial /
   filled / cancelled / skipped) columns to the tracker schema
   ([tracker.py:28](../BOT/bot/tracker.py) — currently absent; dataset builder stamps the *current*
   version on old rows at [dataset.py:61-66](../BOT/bot/ml/dataset.py)). Migration backfills from
   journal JSON where recoverable; unrecoverable rows are marked `version:"unknown"` and excluded
   from training.
2. **Pine/Python behavioral parity** (before any ML retraining and before production use):
   TV-compile STACK + AUTO; fixed-bar golden signal sequences exported from the Python engine;
   bar-by-bar diff of entries, watch/cooldown/stale/invalidation/re-entry transitions; resolve or
   explicitly accept the 1m-live vs chart-TF-historical structure difference
   ([ENTRY_STANDARD.md:134](ENTRY_STANDARD.md)); repaint/confirmed-bar tests; alert payloads
   verified against the webhook contract. The existing config-text sync test is necessary but
   **not sufficient** — behavior, not text, is what must match.
3. **ML/NN program** — ML stays advisory until the evidence beneath it is repaired. Preconditions:
   Phase R datasets + version-pure labels (item 1) + enough real, feature-complete paper
   observations (Phase 5). Then: a genuinely untouched final holdout (never seen by model
   selection); champion `strategy_version` matching enforced at serving (Phase 6 guard);
   promotion blocked unless every gate passes with dataset/feature-schema hashes recorded;
   calibration + drift monitoring on the live scorer; one-command champion rollback; continuous
   training re-enabled only after the worker-crash root cause (Phase 7 crash records) is fixed
   ([run_worker.bat:6-9](../BOT/run_worker.bat)). **Serving-time input honesty:** every scored
   proposal carries feature coverage (full vs fallback mode, missing-feature %, stale-feature
   warning, or an explicit abstain) — a confidence number over degraded inputs must look
   different from one over full inputs, on the Models view and on the proposal itself.
   Retraining on today's mixed-lineage labels would amplify the defects — do not shortcut this
   order.
4. **API/browser security + error hygiene:** `auth` required on all mutating endpoints (keep
   localhost bind); a real authenticated session with explicit "session expired" handling —
   dashboards send the token *before* enforcement flips on, so enabling auth can never brick the
   console into silent 401s; origin/CSRF checks on mutations (even localhost — another local page
   must not be able to call them); replace `innerHTML` interpolations in
   `training.html`/`dashboard.html` with `textContent`/element building (stored-XSS via approval
   notes); body-size check before reading uploads; **backend errors normalized, redacted, and
   length-capped before rendering as text** — a raw provider/broker string must never break
   layout, leak secrets, or inject markup. Full trusted-host work only becomes P0 if the service
   is ever exposed beyond localhost.
5. **Persistence/deployment:** schema-version table + migrations for the SQLite store (backup/
   restore and the single topology moved up into Phase 7).
6. **CI expansion:** nightly "full-deps" job (torch/xgboost, full pinned `requirements.txt`);
   store-fixture job exercising real DuckDB/Parquet schemas; provider contract tests
   (Alpaca/Databento response shapes); paper-broker fill-lifecycle + restart/reconciliation suites
   (from T5.x) in CI; a Windows startup smoke test (PowerShell launches the production topology);
   backup/restore test (T7.4) scheduled; browser/API security checks; TV compile/parity artifacts
   attached where automatable. Keep the slim per-push job as the fast gate.

## Appendix A — Failure-mode register (user charter, 2026-07-11)

Two categories: **confirmed** defects already visible in the code, and **likely** bugs that will
appear as UI and backend become more connected. The most dangerous class is not visual — it is the
UI displaying a safe state the backend cannot prove. Every named mode below is pinned to the
guard that prevents it and the test that proves the guard. A failure mode without a test is a
plan bug — add the test, not just the fix.

### The five to prevent first

| # | Failure | Guard | Pinned by |
|---|---|---|---|
| 1 | False-green system health | Phase 7 semantic health + U rules 1/5 | T7.2, TU.1 |
| 2 | Orders bypassing complete risk + reconciliation | Phase 5 ExecutionService | T5.1, T5.6 |
| 3 | Duplicate / lost / orphaned broker orders | Phase 5 OMS + recovery matrix | T5.2, T5.4, T5.5 |
| 4 | Invalid historical evidence presented as approved | Phases 1–3 + evidence lifecycle states (Phase 6) | T1.x, T2.x, T6.2 |
| 5 | Shadow outcomes presented as real paper/live trades | P1.1 lifecycle states + U rule 3 | lineage tests (P1.1) |

### Critical trading & safety

| Failure mode | UI may show | Guard | Pinned by |
|---|---|---|---|
| False-green health | "System healthy" | Phase 7 semantic health; watchdog checks semantics | T7.2, T7.3, TU.1 |
| Risk bypass | "Risk approved" / no warning | Phase 5: every source through the service | T5.1 |
| Duplicate order (retry/double-click/restart) | one order | dated idempotency keys + U interaction states | T5.4 |
| Lost order (broker accepted, unrecorded) | "Order failed" | timeout-but-accepted recovery; `SUBMISSION STATUS UNKNOWN` UX | T5.4 |
| False duplicate (failed attempt marked placed) | "Already submitted" | keys finalized only on ACCEPTED | T5.2 |
| Orphaned broker position | "Flat" | reconciliation vs real OMS → halt | T5.4, T5.5 |
| Missing protective stop | "Bracket active" | bracket-integrity check from broker truth | T5.7 |
| Kill-switch reset after restart | "Kill switch off" | atomic fail-closed state (corrupt → ON) | T7.1 |
| Old approval used | "Paper approved" | auto-invalidation + submit-time recheck | T6.2, T5.8 |
| Wrong quantity | expected risk size | contract registry + backend-authoritative sizing | T3.2 |

### Data & backtest

| Failure mode | Guard | Pinned by |
|---|---|---|
| Lookahead results displayed as validated ("report exists" ≠ valid) | evidence lifecycle states `calculated→…→approved` | T1.1–T1.3, T6.2 |
| Stale data shown current (missing month, partial day, mixed grain, wrong symbol) | Phase 4 freshness/grain/identity gates + Data Trust card | T4.2, T4.3 |
| Session/timezone misgrouping (Sunday session, EOD leak, ET-vs-UTC day) | Phase 2 trade-day policy; exchange-time + UTC in audit views | T2.4 |
| Roll contamination hidden by smooth chart | Phase 3 adjusted analytics; Data Trust shows contract/roll/raw-vs-adjusted | T3.1 |

### Orders & execution

| Failure mode | Guard | Pinned by |
|---|---|---|
| Double-click / blind retry duplication | idempotency + disabled-while-pending + no client retry | T5.4, TU.4 |
| Timeout but broker accepted | `SUBMISSION STATUS UNKNOWN — do not resubmit` + reconciliation | T5.4 |
| Partial fill under-protected | requested/filled/remaining/cancelled/protected shown separately | T5.7 |
| Cancel race (filled before cancel) | `CANCEL REQUESTED` until reconciled | T5.4 (cancel/replace case) |
| Order status stuck forever | staleness monitor → `INVESTIGATION REQUIRED` | T5.8 |

### Risk interface

| Failure mode | Guard | Pinned by |
|---|---|---|
| Risk computed from safe-looking defaults | `ACCOUNT_STATE_UNPROVEN` reject + per-field provenance/age | T5.6 |
| Correlation hidden (NQ+MNQ+QQQ = 3 trades) | bucket gate (risk.py) + bucket view in cockpit | T5.1 |
| UI-computed size drifts from backend | backend returns authoritative qty + trace (U rule 2) | T3.2 |

### Approvals & Phase 8

| Failure mode | Guard | Pinned by |
|---|---|---|
| Approval despite red evidence (JS-only disable) | backend-enforced predicates; buttons follow backend | T6.2, TU.1 |
| Phase 8 stuck at n=0 | fill-schema fix | T6.1 |
| GET request mutates governance state | GET-mutation audit → POST + auth | TU.4 |
| Cached approval in a second tab | submit-time revalidation in the service | T5.8 |

### Labeling, ML & models

| Failure mode | Guard | Pinned by |
|---|---|---|
| Shadow outcomes labeled "live trades" | P1.1 lifecycle states; U rule 3 (word "live" reserved) | P1.1 tests |
| 07.4 champion served under 07.7 | version guard → "MODEL BLOCKED", no silent fallback | T6.3 |
| Silent feature degradation (thin inputs, same confidence) | serving-time coverage/abstain on every score | P1.3 tests |
| Mixed-lineage labels look properly trained | immutable label lineage + dataset/schema hashes | P1.1, T6.4 |

### UI technical & security

| Failure mode | Guard |
|---|---|
| Stored XSS via approval notes / backend strings | P1.4: `textContent` rendering everywhere |
| Enabling auth bricks the dashboard (silent 401s) | P1.4: token sent before enforcement; "session expired" UX |
| Local page calls mutation endpoints | P1.4: origin/CSRF on mutations |
| Large upload exhausts memory | P1.4: size check before read |
| Raw backend error breaks layout / leaks values | P1.4: normalize, redact, cap, render as text |
| Missing value rendered as $0.00 | U rule 6: UNKNOWN / NOT MEASURED, never zero |

### Runtime & deployment

| Failure mode | Guard | Pinned by |
|---|---|---|
| API and worker on different snapshots / stale worker behind fresh API | process identity + snapshot age on Mission Control | Phase 7 |
| Duplicate background loops after abnormal restart | single-instance guards (mutex pattern) | Phase 7 |
| Watchdog satisfied by any HTTP 200 | semantic health check | T7.3 |
| Continuous training crashes the scan worker | crash records → root cause before re-enable | P1.3 precondition |
| Logs fill the disk / corrupt JSON resets controls | rotation + atomic fail-closed state | T7.1 |
| Autostart topology ≠ manual topology | single documented topology, others "dev only" | Phase 7 gate |
| Restart while an order is in flight | restart recovery + post-restart reconciliation | T5.4 |

### Pine / webhook

| Failure mode | Guard | Pinned by |
|---|---|---|
| Pine fires earlier/later than Python (1m vs chart-TF structure) | P1.2 bar-by-bar parity; difference resolved or explicitly accepted | P1.2 goldens |
| TV alert retries create duplicate orders | idempotency; webhook responses return `duplicate` | T5.4 |
| Forming-bar alerts repaint | P1.2 repaint/confirmed-bar tests | P1.2 |
| Pine version ≠ backend version / unapproved version alert | service arm checks per source + version in payload | T5.8 |
| Webhook schema drift | contract test on the webhook payload | P1.6 CI |
| Every webhook response | correlation id + final action (`rejected/duplicate/shadowed/submitted`) | Phase 5 design |

## Explicitly rejected / softened (verified against the audit)

- **5m-in-1m store**: not treated as corruption — the resampler serves correct aggregates by
  construction; it becomes a *registered grain exception* under Phase 4's grain gate instead.
- **`/api/health` "mainly kill switch"**: partially true — the `beats` heartbeats are real
  observability; only the top-level fields are fixed in Phase 7.
- **Same-entry-bar omission**: correct behavior for canonical close-confirm; fixed only for
  touch/stop research modes (Phase 2 item 5).
- **Shadow scorecard (−12.9R / 25)**: real, but 8.5 days of it straddle the 2026-07-10
  clean-record reset and 15/25 are deliberate B-grade data-collection entries — it is a warning,
  not a verdict, and Phase R + Phase 5 make future forward evidence clean.

## Status ledger (update on every landed phase)

| Phase | Status | Landed | Tests | Notes |
|---|---|---|---|---|
| 0 | **landed** | 2026-07-11 | n/a (docs) | 0.1 banners ×4 · 0.2 TASKS rows fixed · 0.3 README demoted · 0.4 415 reports tagged `pre-remediation-2026-07-11` · 0.5 **autotrade OFF until Phase 5** (user decision 2026-07-11) · 0.6 STATUS.md created |
| 1 | **landed** | 2026-07-11 | T1.1–T1.3 (`test_pit_no_lookahead.py`, red-first proven; suite 187 green) | `_externals` + live `families.prepare` → strictly-prior merge_asof. Delta (REMEDIATION_DELTA.md): total R ~halves everywhere, **ES flips negative**; SPY@5m exp +0.442→+0.166. Residual: live htf_bull parity gap documented in ENTRY_STANDARD. **Worker restart needed** to load the live-side fix |
| 2 | **landed** | 2026-07-11 | S1–S7 + T2.2–T2.4 (`test_simulator_semantics.py` ×10, red-first; suite 197 green) | Ordering policy in `backtest()` docstring; last-bar EOD flatten (the eod_min check never fired on 5m — every carried trade exited on next-day prices); gap-aware stops; stop-wins ambiguity + `ambiguous_bars` attr; side-aware MFE/MAE; touch entry-bar remainder; S7 prior-bar gates; maxdd 0-start; day-block bootstrap. Delta: NQ@5m +0.133→+0.039, ES −0.096R (REMEDIATION_DELTA.md §Phase 2) |
| 3 | **landed** | 2026-07-11 | T3.1–T3.3 (`test_contract_economics.py` ×4, red-first; suite 201 green) | `engine/hs_contracts.py` = single economics source; roll-adjusted ATR/EMA/DMI/momo (rescaled to raw units); `SLIP_MULT` stress hook (17 research scripts migrated); composite/census gauntlets on registry costs; option economics registered (sealed journals adopt at next reset). Delta: equities byte-identical; NQ +0.047R, **ES −0.068R still negative at honest costs** |
| 4 | **landed** | 2026-07-11 | T4.1–T4.3 (`test_pipeline_fail_closed.py` ×10, red-first; suite 211 green) | QA gates: freshness (3 bdays) · zero-volume · short-days (2%) · grain (median+p95) + per-symbol fingerprints + `store_fingerprint`/`all_ok`; intake raises on step failure + `qa_gate()` blocks datasets/training on red QA (`--keep-going` = manual salvage); equity ingest identity gate (symbol column / dup-ts / price continuity) + `--replace` overwrite protection + sha256 source manifest; append script fails loud on full overlap. **GATE PROOF: real store now fails QA on all 5 symbols** (QQQ/SPY/ES stale 25 bdays · NQ stale + 3.1% short days · GC 15.5% short days) |
| R | **landed** | 2026-07-11 | suite 243 green | Frozen-span waiver (user: no historical refresh) stamped in every artifact. Regenerated: A/B (live version stamp → `ab_strategy_version_match` TRUE; **QQQ standard +0.306R vs baseline +0.114R — the equity edge survives honest math**; NQ/ES: no honest canonical edge in any variant) · matrix backtest cells · all 6 ML datasets (corrected-lineage labels) · tracker BACKTEST_REF re-baselined (+0.24→+0.335R). NOT re-run by design: champion sweeps/geometry (= new mining, freeze forbids). Kept-strategy re-decision: zero flips (battery + volbreak + census). **Remaining manual click: 07.7 paper re-approval with override (waiver) — converts the legacy record to a fingerprint-pinned one** |
| E | **landed** | 2026-07-11 | TE.1–TE.4 (`test_entry_matrix.py` ×6; suite 243 green) | Matrix live (`/api/entry_matrix`, evidence-singular, INSUFFICIENT-SAMPLE floor, day-block CI, removed-groups visible); backtest cells = corrected engine on the frozen span (pre-R waiver); exec orders now carry session/family/grade dims; removals registry enforced in live scan AND service (shadow keeps accruing; version bump deferred to R — no-refresh world). **First removal cycle documented: ES nominated → cohort test → REJECT (OOS 2024+ = +0.167R×125 — the F78 lesson on cycle one)**. Paper cells fill as fills accrue |
| 5 | **landed** | 2026-07-11 | T5.1–T5.8 (`test_execution_service.py` ×12) + rewired dedup tests; suite 224 green | `bot/execution/service.py` = the ONE door: submit-time approval · dated idempotency (ERROR releases key, TIMEOUT keeps it claimed) · account truth from broker+fills (unprovable → `ACCOUNT_STATE_UNPROVEN`) · risk on real state · persistent OMS (`execution.db`) · fill ingestion + bracket-integrity halt · reconcile-with-teeth (mismatch → `halt_submissions`) · staleness → INVESTIGATION_REQUIRED · boot recovery. Callers wired: autotrade / manual / webhook (hand-rolled Accounts deleted); Alpaca `recent_orders()` added; `reconcile_once` requires a real OMS; orchestrator stamped not-on-live-path. **Gate: only the service submits to a broker (grep-verified). Autotrade may be re-armed per decision 0.5** |
| 6 | **landed** | 2026-07-11 | T6.1–T6.4 (`test_approval_gates.py` ×8, red-first; suite 232 green) | phase-8 execution quality reads the **real** execution.db fills (+ new `reconciliation_clean` readiness criterion); `approve(paper/live)` **enforces** green evidence with an immutable snapshot pinning the store fingerprint (`override=True` recorded forever); fingerprint drift → approval **stale**, refused by `paper_approved()` (legacy pre-predicate records honored until R re-decides — documented); champion **strategy-version guard** at serving (P(win) + similarity: the 07.4 champion no longer serves under 07.7); `registry.promote` requires `gates_passed` + records the fingerprint; GET-mutation audit: **`GET /api/phase78` no longer auto-advances the live stage on a browser refresh** (POST+auth `/api/phase78/advance`), evolve deep-run → POST+auth; JournalEntry gains `planned_entry`/`avg_fill_price` |
| 7 | **landed** | 2026-07-11 | T7.1–T7.4 (`test_ops_fail_closed.py` ×5; suite 237 green) | Corrupt runtime state → boots **kill switch ON** + alert (atomic writes via `write_json`); `_semantic_health()` + `/api/live` (scan-heartbeat freshness <3× cadence, core-beat failures, broker ping, **process identity** pid/role/snapshot-age); watchdog reads the semantic verdict (3× unhealthy → relaunch) and the production topology is **run_all.bat** (start.ps1 stamped dev-only); worker: crash records (`data/crash_*.txt` + alert, thread hook too), single-instance mutex, 5MB log rotation; `bot/backup.py` + daily verified snapshot beat + prune. **Real restore drill 2026-07-11: 10 files → verify ok → restored to scratch.** Forward gate pending: one week of zero unexplained restarts |
| U | **LANDED (steps 0–8 complete)** | 2026-07-12 | console ×6 + hygiene ×2 (suite 256 green) + live screenshot | All 6 endpoints live (`/api/readiness` = the single truth source, 20s cache; exec/orders w/ timelines+qty breakdown; exec/fills w/ open book; risk/state w/ provenance + ACCOUNT_STATE_UNPROVEN blocking payload; removals; incidents w/ gate-1 clock). **OPERATE** (dashboard): sticky Mission Control strip (verbatim gates, ✕/✓), Entry Console (full state machine + WHY + ACTION verdicts), Orders & Fills (lifecycle timelines, req/fill/rem/cxl/PROTECTED, SUBMIT_UNKNOWN banner), Reconciliation Center (CRITICAL halt, no continue-anyway), Risk cockpit (per-field source, bucket exposure). **GOVERN** (training): Profitability Lab (evidence-singular, INSUFFICIENT SAMPLE, removals pipeline), Strategy Evidence + full paper/live predicate panel (overrides flagged forever), Models (MODEL BLOCKED guard rendered), Data Trust (QA cards + consequences), Incidents (crash records, backups, gate-1). **Verified live on :8000: readiness BLOCKED on exactly [data QA] — the honest verdict, screenshotted** |
| P1 | **first pass landed 2026-07-11** | 2026-07-11 | lineage ×2 + parity pin ×1 (suite 246 green) | **P1.1** tracker `strategy_version`+`state` cols, idempotent backfill (json→version, else `unknown`), datasets VERSION-PURE (foreign/unknown rows excluded — the back-stamping defect closed) · **P1.2** parity goldens: deterministic 3-fire behavioral contract pinned (`tests/goldens/parity_signals.json`, incl. day-3 two-fire subtlety); TV compile + bar-replay diff = user step · **P1.4** auth on `signal/decision`+`order/cancel` (kill stays arm-open/disarm-auth), upload size checked BEFORE read, `esc()` + 5 XSS sinks fixed (stored-XSS via approval notes closed), X-API-Token auto-attach in both UIs (enabling auth can't brick the console) · **P1.5** `user_version` stamps on tracker+execution stores · **P1.6** nightly full-deps CI (`nightly.yml`) · **P1.3 GATED by design**: ML retraining waits for version-pure labels (now enforced) + real paper fills + worker-crash root cause; serving-coverage honesty rides with it · **COMPLETION PASS 2026-07-12 (suite 250 green)**: schema versions ENFORCED (newer-store refusal, both DBs) · candidate_id links exec orders → tracker rows, fills upgrade state to `paper_filled` · **paper_study is fills-based** (shadow demoted to labeled ADVISORY) · `approve('live')` enforces the FULL predicate list (fills≥60 · forward-consistent · reconciliation-clean · `parity_tv.json` green) · all 18 remaining backend-string sinks esc()-wrapped + a grep-gate test keeps them closed · broker mapping extracted pure + contract test · Windows CI job added. Remaining partials, accepted with reasons: fill polling (not SSE) is the mechanism at current volumes; per-report lifecycle state machine subsumed by enforced predicates; options wiring deferred to the sealed-journal reset |
