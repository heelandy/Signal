# FRESH AUDIT vs PROJECT — claim-by-claim adjudication (2026-07-12)

*(no code changes this round — every claim verified against the current tree, live artifacts and
the running process; measured values quoted. Companion docs: `SIGNAL_CERTIFICATE_PLAN.md` (the
build plan whose REMAINING list this audit independently re-derives), `BUG_HUNT_LOG.md`.)*

## The 3 test warnings (operator question)

All three are **third-party deprecation notices, not defects** — no behavior change, nothing red:

| # | Warning | Source | Meaning |
|---|---|---|---|
| 1 | `on_event is deprecated, use lifespan` | `bot/api/server.py:951` (our registration) | FastAPI is retiring `@app.on_event("startup")`; the code already carries a migration NOTE. Cosmetic until FastAPI removes it. |
| 2 | same, from `fastapi/applications.py` | library side of the SAME registration | One cause, warned twice (our decorator + the library's internal call). |
| 3 | `Using httpx with starlette.testclient is deprecated; install httpx2` | starlette 1.3.1, **test-only** | The test client still works with httpx; starlette wants its successor lib. Runtime server code never touches this. |

## Headline: the audit's central verdict is CORRECT and matches our own accounting

> "The strongest finding so far is an integration gap, not missing modules."

**AGREED — and independently confirmed.** `certify_and_fire` has **zero production callers**
(grep: only `bot/signal_certificate.py` itself + tests). `data/certificates.db` **does not
exist** — zero certificates ever created in production. The plan's own REMAINING list said
exactly this when the modules landed; the audit re-derives it from the outside. The next
`ACTION: ENTER` on the dashboard is NOT yet backed by a certificate.

## Snapshot claims — measured

| Audit claim | Measured (2026-07-12) | Verdict |
|---|---|---|
| Signal certificates in production: zero | `data/certificates.db` does not exist | **CONFIRMED** |
| Broker fills 0/60, orders 0 | `exec_orders: 0 · exec_fills: 0` | **CONFIRMED** |
| Paper approval is a legacy pre-predicate record | 07.7 paper approval `2026-07-07T01:50`, `evidence=NO`, `manifest=NO` — **all 28 approvals on file are legacy** | **CONFIRMED** |
| dataqa.json predates the fingerprint code | `evidence_fingerprint=None`, `evidence_cutoff=None` (generated 07-12 08:21, by the OLD code) | **CONFIRMED** |
| Matrix artifact predates the T2 builder | 2,740 rows, **0** with `entry_group_id` | **CONFIRMED** |
| Tracker: 45 rows, lineage predominantly legacy | 45 rows, state = `legacy` × 45 | **CONFIRMED** |
| "Only 12 of 45 tracker rows contain features" | **42/45 carry a `pit_features` snapshot** | **DISCREPANCY** — measured 42, not 12 (their count may use full-column coverage; either way the corpus is thin and 0 rows are broker-measured, so the conclusion stands) |
| Running API not serving the latest source | live `/api/readiness` on :8000 has **no `objectives` key** — the T3 split exists in source (test green) but the process predates it | **CONFIRMED — ops restart needed (user-managed)** |
| Champion 07.4 incompatible with 07.7; ML should abstain | version guard blocks serving (`pipeline.py:180-193`) — but see finding 7 | **CONFIRMED with refinement** |

## Area-by-area adjudication

### 1. Integration gap — CONFIRMED (see headline)

### 2. "Exit fills are not ingested correctly" — **STALE: FIXED earlier today** (core), sub-claims OPEN

The audit snapshot predates this session's T4 fix. As of today's code:
- `_map_order` legs carry `id/status/filled_qty/avg_fill_price/updated_at` (`alpaca_broker.py:196`)
- `poll_fills` ingests a FILLED bracket leg as the offsetting fill against the ENTRY order
  (cumulative-delta, `leg:{id}:{qty}` fill ids)
- `_finalize_symbol_entries` finalizes the ENTRY's decision by symbol at net 0 — never the
  closing order's candidate
- The "manual closing-fill test" criticism was **valid and is resolved**: the strict-xfail pins
  were flipped into real broker-child-ingestion regression tests
  (`test_t4_bracket_exit_finalizes_the_entry` — nested-leg close + idempotent re-poll). Suite 402.

So the listed consequences (book never at zero, missing realized P&L, wrong loss gates,
label_final unreachable, reconcile halt after broker close) are **closed for the bracket-leg
path**. **STILL TRUE (confirmed open):**
- Webhook `exit`/`close` calls `b.flatten()` directly (`server.py:2053`) — Alpaca `flatten()` =
  `close_all_positions(cancel_orders=True)`: it **closes the entire account, not the ticker**,
  and bypasses the ExecutionService (no OMS record of the exit).
- `/api/order/cancel` (`server.py:2077`) and `/api/flatten` (`server.py:2085`) also go
  broker-direct. (Webhook ENTRY correctly routes through the service.)

### 3. "Frozen evidence not immutable or approved" — CONFIRMED (artifacts + 4 design findings)

- **Artifacts predate the controls** — measured above. Regeneration + a non-legacy manifest-pinned
  07.7 re-approval are OPS steps (approval click is the operator's by design).
- **Fingerprint hashes count/min/max/volume-sum, not row content** (`hs_data_qa.py`): TRUE. It
  catches append/truncate/volume edits but a price-only mutation with an equal volume sum would
  pass. Valid hardening: row-content/source-file hashes (audit completion step 3). Accepted.
- **`manifest_hash` excludes report/dataset hashes** (`evidence_manifest.py:98`): TRUE and
  **deliberate** — those files change on every daily operational append, and T1's whole point is
  that an append must not re-identify the evidence (the docstring documents this). The audit's
  residual risk is real though, and it collapses to the previous bullet: make the *fingerprint*
  content-based and the exclusion becomes safe. One fix, both findings.
- **`-dirty` is identity-less** (`evidence_manifest.py:34`): TRUE — two different uncommitted
  trees share `HEAD-dirty`. Resolution = audit completion step 1 (commit a clean release) plus,
  later, a diff-hash suffix.
- **Manifest failure silently ignored while approval succeeds** (`approval.py:177-182`): TRUE —
  `build_manifest` is best-effort in `approve()`. Should be fail-closed when it becomes load-bearing.
- **Staleness compares only the evidence fingerprint** (`approval.py:120-140`): TRUE — engine/
  simulator/cost changes don't auto-invalidate. Widening to a `manifest_hash` compare (which
  already includes code/engine/sim/costs) is the natural fix once approvals carry manifests.

### 4. "Matrix does not control entries" — CONFIRMED in full

Every sub-claim verified: artifact 0/2740 group ids; `matrix()` groups by
`DIMS=(symbol,side,session,family,grade,regime)` — `entry_group_id` stamped but **not** the join
key (`entry_matrix.py:30`); shadow loader has **no strategy-version filter**
(`entry_matrix.py:48-50`); paper attribution picks the **latest prior order with no symbol
match** (`entry_matrix.py:88-95` — concurrent QQQ+SPY round trips WOULD cross-attribute; worse
than the audit words it); corrupt inputs → silent empty (`except: pass`, `entry_matrix.py:105`);
`/api/entry_matrix?floor=` lets the caller lower the sample floor (`server.py:1069`); **the
firing path never queries the matrix** — profitability is enforced only inside the (unwired)
certificate. All = the plan's T2-REMAINING identity-join work, now with an external confirmation.

### 5. "Console can show a false ENTER" — CONFIRMED

`entryState()` (`dashboard.html:1105`) declares FIRED from `tradeable`/`signal_state`; `ACTION:
ENTER` (`dashboard.html:1131`) requires none of: risk_ok, source_healthy, skip_reco, BOSS,
approval validity, reconciliation, certificate, profitability. The backend already computes
several of these per proposal (`live.py:277+`). The fix direction is exactly the audit's step 9 =
the plan's T3-REMAINING: **backend produces the final operator action; UI renders it** — the
natural carrier is the certificate verdict once `certify_and_fire` is wired. Plus the ops fact:
the running :8000 serves no `objectives` (stale process — restart is the operator's).

### 6. "Final label lineage not enforced in training" — CONFIRMED

`build_live_labels` selects `WHERE outcome NOT IN ('open')` — **no lifecycle-state check**
(`live_labels.py:30-33`); `attach_live_journal` filters `taken==1` + features + tf + lineage
separation but **`taken` ≠ broker-filled** (`dataset.py:49-51`) — theoretical shadow outcomes
can enter the corpus. The new `entry_filled`/`label_final` states are written by execution but
**not yet consumed** by the label builder (plan T4-REMAINING: `label_final` required for
execution-grade training). Current data limits the blast radius (45 rows, all `legacy`-state,
0 broker fills) but the gate must exist before fills arrive.

### 7. "Production ML remains blocked" — CONFIRMED, one sharp refinement accepted

The audit's sharpest point is right: `predict_candidate` returns the hardcoded prior
`_PRIOR = 0.42` when no compatible champion exists (`pipeline.py:196-202`), and `live.py:202 →
272` passes that into `decide_ensemble(ml_p=conf ...)` **as if it were a model vote**. The
version guard correctly refuses to SERVE the 07.4 champion — but the fallback is not an honest
downstream ABSTAIN: the ensemble cannot distinguish "the model says 0.42" from "there is no
model". The certificate's ml gate already encodes the right semantics (silent fallback = BLOCK);
the serving path and UI need the same honesty (`ML: ABSTAIN — NO COMPATIBLE MODEL`, `ml_p=None`).
Also TRUE: training functions aren't independently QA-gated (only intake orchestration checks),
futures QA red yet training reports exist for those datasets, no 07.7 champion, continuous
training disabled, drift/rollback/final-holdout governance incomplete — all match plan
T5-REMAINING.

### Areas the audit marks correct — agreed

Idempotency (dated, DB-backed), pending-state-before-submit, submit-time approval recheck,
SUBMIT_UNKNOWN never blind-retried, centralized risk off broker truth, kill-switch persistence,
QQQ/SPY QA green / futures honestly damaged-context, advisory honestly labeled, old champion
version-blocked, live physically hard-locked, Pine parity excluded as agreed.

## Required completion order — accepted as the execution sequence

The audit's 12 steps map 1:1 onto the plan's REMAINING list and sharpen the ORDER (commit-clean
release first, regenerate artifacts second, manifest-mandatory third, re-approval fourth, THEN
the identity chain, matrix gate, certificate wiring, backend-authoritative action, label_final
gate, and the 60-fill/56-day accumulation). Steps 1 (commit + restart + runtime-hash proof), 2
(regenerate), 4 (re-approve 07.7) and 11 (burn-in) are **operator-owned**; the rest are build
work already documented as REMAINING. No disagreement with the sequence.

## Bottom line

Of the audit's 7 negative findings: **6 CONFIRMED** (integration gap, frozen-evidence gaps,
matrix-not-a-gate, false-ENTER surface, label-lineage gap, ML-blocked + 0.42 refinement),
**1 STALE** (exit-fill ingestion core — fixed earlier today with live-path regression tests;
its webhook/flatten/cancel sub-claims remain confirmed-open), and **1 factual discrepancy**
(feature coverage: measured 42/45, not 12/45 — conclusion unaffected). The audit and the
project's own REMAINING list now describe the same gap from two directions: **the modules are
built and tested; the production wiring that makes them the ONLY path is the remaining work.**
