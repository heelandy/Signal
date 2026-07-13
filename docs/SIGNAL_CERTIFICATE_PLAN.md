# SIGNAL CERTIFICATE & TRUST-COMPLETION PLAN
*(2026-07-12 · docs-first per the standing process rule · authority for the trust layer that sits
ABOVE `docs/REMEDIATION_PLAN.md`: the remediation repaired correctness; this plan makes every
actionable signal PROVABLE. Freeze intact — this is design; no strategy/indicator/AI is added.
Live stays hard-locked. Every code step it later spawns is red-first-tested.)*

## 0. What "trust" means here (the one distinction)

**100% confidence = every required process was executed, passed, and recorded correctly — NOT that
the trade will profit.** A perfectly certified signal can still lose; markets are uncertain. The
governing rule:

> **No valid Signal Certificate ⇒ no actionable signal, no "ENTER" alert, and no order.**
> **UNKNOWN is treated exactly like BLOCKED** (an unprovable gate is a failed gate — the OMS's
> `ACCOUNT_STATE_UNPROVEN` principle, generalized to the whole firing path).

Today the pieces exist but are scattered: the scanner emits a *proposal*; risk, profitability,
approvals, and broker truth live in separate places; nothing binds them into one immutable proof.
This plan unifies them.

## 1. The signal lifecycle — stop calling every candidate a "signal"

```
SETUP ─► CERTIFIED SIGNAL ─► ORDER READY ─► SUBMITTED ─► FILLED & PROTECTED ─► RECONCILED
```
| Stage | Meaning | Colour |
|---|---|---|
| **SETUP** | something may be developing — informational only | gray (CONTEXT) |
| **CERTIFIED SIGNAL** | data + entry logic + profitability evidence passed | — |
| **ORDER READY** | account + risk + broker checks passed → **the only stage that is green "ENTER"** | green |
| SUBMITTED | order sent, idempotency claimed | blue |
| FILLED & PROTECTED | broker confirmed fill **and** working protective legs | blue |
| RECONCILED | internal record == broker record | green |

The **pattern advisory** (`bot/strategy/pattern_advisory.py`, built 2026-07-12) is exactly the
**SETUP tier** — it shows CONTEXT/WATCH-ONLY and only QQQ/SPY can pass, never NQ/ES/GC. It is NOT the
certificate; it is the honest pre-certificate view. Good foundation, correct semantics.

## 2. The Signal Certificate — one immutable artifact per actionable signal

Persisted **before** any alert is sent; the alert carries its id + hash. Contents:

- `signal_id`, `candidate_id`, `correlation_id`
- strategy version + **config hash**, code/commit (git worktree id)
- symbol · side · timeframe · session · **closed** signal-bar timestamp
- data provider + data age + **data-QA verdict**
- **feature-snapshot hash** (PIT)
- entry-state transition history (the full developing→…→fired path)
- **every passed AND failed gate**
- exact `entry_group_id` + **profitability-evidence id**
- entry · stop · targets · R:R
- account snapshot + risk decision + quantity calc & source
- **approval/evidence-manifest hash**
- ML status: a valid score **or an explicit abstention** (never a silent prior)
- creation time · expiration time · **certificate hash**

## 3. The nine mandatory gates (block on false OR unknown)

| Gate | Must prove | Block when | Today (grounded) |
|---|---|---|---|
| **Runtime** | correct strategy/config/code version | version unknown/mismatch | champion-version guard exists; no per-fire config-hash yet |
| **Data** | provider healthy, fresh, right session/grain | stale/incomplete/damaged | `pipeline/hs_data_qa.py` + `source_health` exist; not bound per-fire |
| **Causality** | closed-bar, PIT features only | lookahead / forming bar | PIT harness + `merge_asof(allow_exact_matches=False)` + bug-hunt armor ✓ |
| **Entry logic** | complete state-machine transition | any condition missing | `orb_state.OrbSideState` FSM exists; not asserted at fire time (see T3) |
| **Profitability** | exact entry group has valid evidence | entry type unproven/removed | `entry_matrix` + removals exist; **grades all `—`, group-id mismatched** (T2) |
| **Risk** | fresh broker account + all limits pass | account-truth unknown / limit breached | `risk.decide` + `account_truth` (fail-closed) ✓; feed-health hardcoded (T3) |
| **Execution** | broker reachable, schema valid, idempotency ready | submission state unprovable | ExecutionService = the one broker door ✓ (Phase 5) |
| **ML** | compatible model + full inputs, or abstain | silent fallback / stale model | champion is 07.4, live is 07.7 → **must abstain** until rebuilt (T5) |
| **Audit** | certificate saved + hash verified | persistence fails | not built yet — the certificate store is new |

> **CERTIFICATE + `certify_and_fire()` LANDED 2026-07-12 (`bot/signal_certificate.py`, 22 tests).**
> The nine gates run; **UNKNOWN==BLOCKED** (missing proof blocks like an explicit failure); the
> certificate is **persisted (audit gate) BEFORE any alert**, the alert carries its hash; a blocked
> candidate produces an auditable BLOCKED cert and NO alert / NO order; ML abstain is fine but a
> silent fallback (scored on incomplete inputs) blocks; identical inputs → identical decision. It
> orchestrates the existing services (risk.decide / approval / removals / evidence_manifest /
> entry_group_id) — no new strategy logic. **REMAINING:** wire the live scan / manual / webhook
> sources to route through it (the sources currently emit proposals directly); populate ctx from the
> real scan/broker/data state; expiry enforcement.

## 4. The one firing door — `certify_and_fire()`

Analogue of ExecutionService (the one *order* door): **one central path every Python signal source
must call to become actionable.** It runs the 9 gates, builds + persists the certificate, and only
then emits the alert / hands ORDER READY to the ExecutionService. Sources that must route through it:
the live scan, manual ticket, TV webhook (Pine stays deferred → **non-actionable** until it can enter
this path). No source may alert "ENTER" or submit without a certificate.

## 5. The five completion tracks

Each track: **grounded current status → what remains → definition of done.** Verified code findings
are marked ✔ (checked against the tree 2026-07-12).

### T1 — Immutable evidence + fingerprint semantics  *(the keystone — unblocks everything)*
> **KEYSTONE LANDED 2026-07-12 (suite 362 → 367).** `pipeline/hs_data_qa.py` now emits an
> **`evidence_fingerprint`** over a frozen `EVIDENCE_CUTOFF` (data ≤ cutoff — immutable across daily
> appends) alongside the operational `store_fingerprint`. `approval._staleness` compares the FROZEN
> fingerprint (legacy records keep the old store-compare). `bot/evidence_manifest.py` builds the
> immutable manifest (version · commit · evidence-fp · cutoff · spans · engine/sim version · costs ·
> report/dataset hashes · QA · waiver) and `approve()` pins it to every paper/live record. Tests:
> `test_evidence_manifest.py` (4) + `test_t1_daily_bar_append_does_not_invalidate_approval` — a daily
> append no longer marks a fresh approval stale. STATUS.md autotrade conflict reconciled (ARMED).
> **REMAINING (ops/user, not code contract):** regenerate the evidence pack from the snapshot ·
> refuse pre-remediation artifacts on current endpoints · re-issue the 07.7 paper approval so it
> carries the new manifest · data-universe: NQ/ES/GC excluded via traded-book scoping (advisory
> already marks them CONTEXT) — give each its own readiness gate in T3.

**Status.** Approval pins a store fingerprint and auto-invalidates on change
(`approval.py:_staleness`). ✔ **BUG:** it pins the **whole current store** fingerprint
(`evidence("").get("store_fingerprint")`), and the new live-bar persister appends bars **daily** →
the store fingerprint changes every EOD → **a fresh approval goes STALE the next day even though no
historical evidence changed.** This is a direct collision between the persister (built 2026-07-12)
and the approval model.

**What remains.**
- **Separate the two data purposes:** an *immutable research/evidence snapshot* vs the *mutable
  operational store* that receives daily bars. Approval pins the **snapshot**; operational readiness
  checks live-store freshness *separately*.
- **Fingerprint the exact evidence RANGE + cutoff**, not the growing store.
- **Evidence manifest** on every approved run: strategy version · commit/worktree · evidence-store
  fingerprint · symbol/tf/session spans · data cutoff · engine+simulator version · cost assumptions ·
  report hash · dataset hash · generated timestamp · QA result + any waiver.
- **Regenerate every current-facing artifact from that one snapshot:** canonical backtests, A/B
  entry-standard, cost-stress matrix, gauntlet, entry-matrix rows, ML datasets (per-symbol + pooled),
  rejected-entry datasets, live-vs-backtest reference.
- **Refuse pre-remediation artifacts** on current UI/API (archive ok; endpoints must not present them
  as current).
- **Data-universe governance:** QQQ/SPY QA green ✔; NQ/ES/GC QA-red ✔ → repair the histories before
  activating, or **explicitly exclude them from the traded universe with their own readiness gate.**
- **Replace legacy paper approval** with a fingerprinted one — *only after* the immutable-snapshot
  behaviour is fixed.
- **Reconcile `docs/STATUS.md`** (line 4): it shows paper autotrade both off and armed. ✔ conflict.

**Definition of done.** Every number in approvals/operator views resolves to one immutable manifest ·
every current artifact carries strategy version + evidence fingerprint + report hash · zero
current-facing pre-remediation artifacts · daily bar appends never invalidate frozen evidence · all
active symbols pass QA (red ones excluded) · paper approval is non-legacy and pinned to the snapshot.

### T2 — Entry Profitability Matrix + `entry_group_id`
> **FOUNDATION LANDED 2026-07-12.** `bot/strategy/entry_group.py` — one canonical
> `PR-{CAT}-{SESSION}-{TF}-{PATTERN}-{SIDE}-v{n}` id; the legacy names `orb@5m` / `breakout` /
> `orb_stack` all normalize to the same `ORB_C` group (PR1 proved ORB is one pattern), an
> unrecognized family maps to UNKNOWN (never guessed). Wired into all three matrix row-builders
> (backtest / shadow / paper) so a backtest cell and a paper cell for the same group JOIN. Tests:
> `test_signal_certificate_t2.py` (4) incl. the matrix builder stamping the id. **REMAINING:**
> identity-join paper attribution (replace the "latest-prior-order" join — needs T4 fill linkage) ·
> emit the full entry classification from the backtest engine (fills the `—` grades) · true net-R
> with fees/partials · robustness gates (CI/OOS/both-halves/cost-stress/multiple-comparison).

**Status.** `bot/ml/entry_matrix.py` exists; backtest output ~2,740 samples / 28 cells but **every
historical grade is `—`**. Identifiers are **incompatible across paths** ✔: backtest `orb@5m`, live
family `breakout`, execution setup `orb_stack`. Paper attribution ✔ assigns realized P&L to the
**latest order created before** the fill timestamp (`entry_matrix.py:85`), not by identity.

**What remains.**
- **One canonical `entry_group_id`** shared by backtest · scanner · tracker · order · fill · matrix ·
  removals (PR-scheme from `PATTERN_RECOGNITION_V1` §7 is compatible).
- **Capture full entry classification at signal time** (symbol/side/session/tf/version/family/
  immediate-vs-confirm/pullback-vs-direct/re-entry#/grade/regime/entry-time/chase-dist/OR-width/
  stop-dist/vol+trend alignment) — **emitted by the backtest engine**, not reconstructed in the
  matrix builder.
- **Replace paper attribution** with an identity join: `candidate_id → order_id → broker_order_id →
  fill_id`.
- **True net R:** filled qty · partial entries/exits · avg entry/exit · planned risk × filled qty ·
  commission/fees · spread/slippage · entry/exit role · open-vs-closed qty.
- **Evidence filtering:** shadow-only / paper-round-trips-only / live-only / manual-legacy separate.
- **`trades/week` from elapsed calendar time**, not `unique_days/5`.
- **Robustness gates:** min sample · CI · OOS split · both-halves · regime/year stability · cost
  stress · multiple-comparison protection across many cells.
- **Removal governance** tested through the *normalized* group-id across engine, scan, execution.

**Definition of done.** ≥99% rows have valid entry type + grade + version + `entry_group_id` · the
same group has the same id across all evidence types · paper net-R reconciles exactly to the fill
ledger · no silent exception yields a false-empty matrix · under-sample rows stay non-verdicts · an
adopted removal is proven unable to fire/submit yet stays visible for shadow.

### T3 — Operator Console (finish the workflow)
> **READINESS SPLIT LANDED 2026-07-12.** `/api/readiness` now carries `objectives:
> {paper_ready, live_ready, model_ready}`, each `{ready, blocking}`. Paper can be ready at 0/60
> fills, but **live can never read ready (hard-locked by design)** and model readiness reflects the
> champion-version guard (07.4 champion vs 07.7 current → not ready → ML abstains). Test:
> `test_t3_readiness_split_paper_live_model_never_confused`. **REMAINING (some fills-gated):**
> pre-fire state endpoint (per symbol/side FSM state before a fire) · reconciliation COMPARISON
> table (internal vs broker row-by-row) · protection from confirmed working legs · risk-cockpit real
> feed-health + buying-power/DD-room · Strategy Evidence quarantine · real browser acceptance tests.

### T3 — Operator Console (finish the workflow)
**Status.** Endpoints/views exist (`/api/readiness`, Orders & Fills, Risk, Profitability Lab,
Incidents, Reconciliation). First-pass, not a finished operator workflow. The Entry Console reads
`/api/signals` (**post-emission**) ✔ — it cannot show developing/armed/watch/pullback/stale/
invalidated/already-traded before a fire.

**What remains.**
- **A real pre-entry state endpoint:** per symbol·side·session, exact passed/failed gates + next
  permitted action — driven by the `OrbSideState` FSM, not by fired proposals.
- **Split readiness by objective:** `paper_ready` · `live_ready` · `model_ready`. Today
  `/api/readiness` can be OK with 0/60 fills because fill-readiness is non-blocking — fine for paper,
  **must never read as live-ready.**
- **Reconciliation Center truth:** an explicit comparison table — internal vs broker position/order,
  protective stop/target, difference, last-reconcile time, resolution action. "Protected" must come
  from **confirmed working broker legs**, not merely the absence of a `BRACKET_MISSING` event.
- **Risk Cockpit:** real feed-health input (not hardcoded `feed_healthy=True`) · buying power · DD
  used/remaining · daily/weekly room · risk budget remaining · broker/account timestamp · position/
  order freshness · correlation exposure used-vs-allowed.
- **Strategy Evidence** must reject/quarantine old artifacts, not just show approval booleans.
- **Profitability Lab** upgrades *after* T2.
- **Real browser acceptance tests** (beyond the shape tests in `test_operator_console.py`): every
  view leaves loading · no console/network errors · evidence switch works · auth failure shown ·
  reconcile mismatch → system-wide lock · missing data → UNKNOWN · locked actions untriggerable ·
  responsive desktop/tablet · a11y · HTML/XSS with hostile backend strings.

**Definition of done.** Every watched symbol/side shows a pre-entry state + exact reason even with no
fired signal · paper vs live readiness can never be confused · broker/internal mismatches visible
row-by-row · all critical views pass automated browser tests · no current-facing view uses stale/
mixed-lineage evidence.

### T4 — Label lineage (candidate → order → fill → final label)
> **CORE LANDED 2026-07-12.** `_mark_tracker_filled` now sets **`entry_filled`** on an entry fill and
> **`label_final`** ONLY when the round trip closes (net→0), computed in `poll_fills` from
> `_replay_fills`. A finalized label is never downgraded; a pure shadow row (no exec_orders link) is
> never touched. Tests: `test_signal_certificate_t4.py` (4) — entry≠final, closed→final, shadow
> untouched, no-downgrade. This is the ML-correctness keystone T5 depends on. **REMAINING:** fill
> `role`+`fee` columns (schema bump) · append-only lifecycle-event table · `live_labels.py` field
> retention · dataset versioning + substrate separation · external-signal-without-version → UNKNOWN.

**Status.** ExecutionService stores `candidate_id` and can mark a tracker row `paper_filled` ✔ (one
link closed). Training-label path incomplete. `_mark_tracker_filled` fires on an **entry** fill — a
profitability label must not be final until the round trip **closes**.

**What remains.**
- **One lifecycle contract:** `signal_created → shadow → manually_accepted/skipped → submitted →
  accepted → partially_filled → entry_filled → exit_filled/cancelled/rejected → label_final`.
- **Append-only lifecycle events** over overwriting a single state field.
- `tracker.py:99` — updating a shadow row must also update state + retain a prior-state audit event.
- **External signals lacking a version → mark UNKNOWN and exclude** (never infer the current version).
- `ml/live_labels.py:24` must retain: state/evidence type · candidate/order/broker-order/fill ids ·
  entry+exit prices · qty · fees/slippage · strategy version · store fingerprint · PIT feature hash.
- **Entry fill ≠ final label** — finalize only on a completed, fee-adjusted round trip.
- **Separate training substrates:** historical-replay · shadow-opportunity · manual · broker-paper ·
  live. **Version** `live_outcomes` (stop overwriting v1).
- Tests: shadow→manual · partial→cancel · multi-fill · round-trip · fee-adjusted · restart/recovery ·
  version mismatch · duplicate fill · **no shadow row enters the execution-label dataset.**

**Definition of done.** Every execution label traces to candidate+order+fills · every label has an
explicit evidence type + strategy version · zero shadow outcomes appear as paper executions · only
completed round trips create final execution labels · every dataset has row-level lineage audit.

### T5 — Production ML program  *(last — genuinely blocked on T1–T4)*
> **LEAKAGE FIX LANDED 2026-07-12 (`bot/nn/train.py`).** The NN challenger was `.fit(X, y)` on ALL
> observations then "evaluated" on the last 30% `X[k:]` — data it had trained on → inflated holdout
> AUC → wrongful promotion. Now the **promotion gate** fits on the first 70% ONLY and scores the
> untouched last 30%; the **deployed** model still uses all data. **REMAINING (model itself gated on
> the 60-fill/56-day burn-in):** untouched final holdout · strategy+schema serving guards · registry
> lineage metadata · abstain honesty (prior labelled a prior) · drift monitoring + rollback.

**Status.** Only champion = NN-similarity on 07.4; live is 07.7; version guard blocks the old
champion ✔; broker-paper sample = 0; continuous training disabled. **ML must abstain today.**

**What remains.**
- Wait for corrected labels + real paper outcomes (60 fills/56 days is an *execution-readiness* gate,
  not model sufficiency — require enough +/− obs in every fold and important slice).
- **Untouched final holdout** (excluded from family-selection, HP, calibration, threshold).
- **Fix NN leakage** `nn/train.py:79` (challenger fit on all obs before the 30% eval).
- **Strategy+schema guards on every serving path** (primary P, NN sequence, heads, similarity,
  explanations).
- **Registry metadata:** dataset hash · label-set hash · feature-schema hash · store fingerprint ·
  train range · holdout range · commit · calibration version · approval record.
- **No auto-champion install from similarity training** — same promotion workflow for all.
- **Feature-coverage honesty:** full-input vs fallback score · missing-feature % · stale warning ·
  explicit abstain. A prior like 0.42 is labelled a **prior**, never model confidence.
- **Monitoring:** coverage/abstain rate · calibration/Brier drift · feature drift · expectancy by
  prob bucket · slices · latency/errors. **Immutable champion history + one-command rollback.**
- **Re-enable continuous training only after:** worker-crash root cause proven closed · 7-day
  stability gate · isolated process · cannot auto-promote · a failed run cannot touch scan/execution.

**Definition of done.** A current-07.7 model passes untouched holdout + calibration + slice gates ·
registry has full lineage · every serving path blocks incompatible/degraded input · drift + rollback
operationally tested · ML stays advisory (rules + risk retain trade authority).

## 6. Post-signal guarantees (the process doesn't end at the alert)

After submission, auto-verify: broker ack · no duplicate order · requested-vs-filled qty · partial
fills · avg fill + slippage · protective stop/target confirmed working · exit fills + fees · internal
vs broker positions · final realized net R · label finalized against the original certificate.
**If protection or reconciliation cannot be proven:** arm the kill switch · stop further submissions ·
mark the signal **PROCESS FAILED** · critical operator alert · require a clean reconcile before
resuming. (ExecutionService already has the bracket-integrity halt + reconcile-with-teeth — this
extends it to the certificate.)

## 7. Objective acceptance criteria (don't call it trustworthy until ALL pass)

100% of actionable signals have a valid certificate · zero fire when any mandatory gate is false or
unknown · identical inputs → identical certificate decision · 100% candidate→order→fill→label
traceability · zero duplicate submissions across restarts/timeouts · 100% filled entries confirmed
protected or the system halts · zero unresolved reconciliation differences · exact entry profitability
includes costs+qty+completed round trips · stale evidence/versions/models auto-refused · fault tests
pass (stale data · broker timeout · partial fills · corrupt state · missing stops · duplicate webhooks
· restarts) · full paper burn-in ≥60 closed broker-paper trades over 56 days · operator browser tests
prove every view leaves loading + shows the correct blocking reason.

## 8. Dependency order (do NOT reorder)

```
T1 immutable evidence + fingerprints
      └─► T4 fill/label lineage ──► T2 profitability matrix ──► T3 console acceptance
                                                                      └─► paper sample (60/56)
                                                                                └─► T5 ML
```
**Immediate order (before broker fills begin):**
1. Extend fill/label storage: fill role · fees · candidate/order linkage · final-round-trip state (T4 core).
2. Fix paper attribution + normalized `entry_group_id` (T2 core).
3. Separate immutable evidence snapshot from the daily operational store (T1 keystone).
4. Regenerate + fingerprint the evidence pack (T1).
5. Replace the legacy paper approval with a pinned record (T1).
6. Build the Signal Certificate contract + one `certify_and_fire()` path (§2/§4).
7. True pre-fire Entry Console + broker-reconciliation comparison (T3).
8. Add fault-injection + end-to-end tests.
9. Collect + validate the 60-fill/56-day paper record.
10. Rebuild ML only after those labels pass lineage + feature-completeness (T5).

## 9. Alert delivery (decided 2026-07-12)

**Webull CANNOT deliver our certified alerts** — its Alerts are user-set price/volume/indicator
conditions Webull evaluates and pushes to the user's own app/email/SMS; there is no inbound API for
an external system to push a custom message, and a Webull price alert can carry none of the
certificate (gates, `entry_group_id`, hash). **Use the existing channel:** `bot/alerts.py` pushes to
any JSON webhook via `ALERT_WEBHOOK_URL` (Discord/Slack/**ntfy.sh** auto-detected). **The certificate
is persisted first; the alert then carries its id/hash.** ntfy.sh is the zero-code starting point.

## 10. Ground rules (unchanged)

Docs-first, then code · every code step red-first-tested · freeze intact (no new strategy/indicator/
AI; this is correctness + provability only) · live hard-locked · pre-fix numbers are never approval
evidence · sealed journals untouched. This plan is the trust layer; `REMEDIATION_PLAN.md` remains the
correctness authority, `BUG_HUNT_LOG.md` the defect record, `PATTERN_RECOGNITION_V1.md` the advisory
(SETUP tier) design.
