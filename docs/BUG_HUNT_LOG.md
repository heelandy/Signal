# BUG HUNT LOG
*(one line per lead/find: verdict · severity · test id · scenario. Plan: docs/BUG_HUNT_PLAN.md)*

## Pre-hunt finds (surfaced during the live-persister build, 2026-07-12)

- **CONFIRMED · MED · `hs_resample` fails on READ-ONLY partition dirs (the real root cause).**
  The persister's hive refresh failed deterministically for QQQ/SPY/ES/GC (NQ fine) with
  `WinError 5 Access denied` on `data/bars/sym=X/tf=15m/session=full/year=YYYY`. NOT a lock:
  the dirs are empty and a fresh python can write files INTO them — but they carry the Windows
  **read-only attribute** (git/backup artifact on the original historical build), and
  `shutil.rmtree`'s `rmdir` refuses a read-only directory. NQ resampled only because an earlier
  successful run had already rewritten its dirs (fresh = no read-only bit). Diagnosis chain
  (instructive — three wrong hypotheses before the right one): scan-loop lock (kill switch didn't
  help) → stack duckdb glob-reads (stopping the stack didn't help) → orphaned mp child (killing
  it didn't help) → **read-only attribute** (`os.stat().st_mode & S_IWRITE` == 0; chmod-retry
  rmtree succeeds). FIX: `pipeline/hs_resample.py` rmtree now clears the read-only bit and retries
  per-path (`onexc`/`onerror` handler). This latent bug would have blocked the EOD persist beat's
  first real refresh. TODO Wave-3: a test that sets S_IREAD on a scratch partition and asserts
  resample still rewrites it.
- **CONFIRMED · low · `_spawn_post` parent-death** — a Popen'd cmd.exe chain launched by a
  one-shot `python -m ...` parent was killed when the parent exited (Windows). FIX: same as above
  (detached single child). This is the same class as the boot-drill's worker-death find.
- **CONFIRMED · low · overlapping-resample self-race (operator error, but a real lesson)** — while
  manually clearing hives I launched TWO concurrent resample loops over the same symbols; they
  locked EACH OTHER out (WinError 5), not just the scan. LESSON for the auto path: resample must
  be single-flight. The `_spawn_post` runner is already single-flight per invocation, but the EOD
  beat could in principle overlap a manual run — Wave-3 TODO: a lockfile (`data/.resample.lock`)
  so no two resamples ever run at once. Manual refreshes must never launch a second job while one
  is live.

- **CONFIRMED · LOW · orphaned multiprocessing child survives worker stop** — after stop.ps1
  killed the worker (PID 36900), a `spawn_main(parent_pid=36900) --multiprocessing-fork` child
  (59220) kept running. This CORRECTS the boot-drill's earlier note that a same-second worker
  "twin" is fully benign: it's a mp spawn child, and it can ORPHAN when its parent is killed,
  surviving as a stray process. Not the hive-lock cause (killing it didn't unblock resample), but
  a real leak. Wave-5 TODO: the worker's shutdown/crash path should reap its mp children (atexit
  or a process-group kill); the single-instance mutex covers duplicate LAUNCHES, not orphaned
  CHILDREN.

- **FIXED · med · orphaned/hidden children not reaped by stop.ps1** (follow-through on the orphan
  find). stop.ps1 killed the worker BY NAME, leaving its multiprocessing-fork children and
  pipeline/training subprocesses alive (one held hive handles). FIX: stop.ps1 now `taskkill /T`
  the worker+API roots (whole child tree) + sweeps BOT-marked leftover python (mp-fork, hs_*,
  bot.ml/nn, nightly_battery, gauntlet, evolve); production port only. run_worker reaps
  `multiprocessing.active_children()` on every exit path (Ctrl-C/crash/normal). Verified: both
  scripts parse; the specific orphan class can no longer survive a stop.

## Pine/Python parity (P1.2) — correlation audit 2026-07-12

- STACK Pine is version-stamped `orb-standard-2026.07.7`; AUTO preset "Matches BOT asset_config
  exactly". ENTRY RULES correlate with the current implementation. Lookahead: Pine already uses
  `lookahead=barmerge.lookahead_off` on all daily externals — never had the Phase-1 bug. The
  Phase 2/3 fixes are BACKTEST-SCORING changes (EOD order, gap fills, MFE/MAE, economics) that
  Pine does not perform — N/A to the indicator. OPEN (unchanged, user step): bar-by-bar signal
  parity — the 1m-structure vs chart-TF difference + the OB port need a TV compile + bar-replay
  diff against `tests/goldens/parity_signals.json`, writing `reports/parity_tv.json` (the last red
  LIVE predicate). Not a defect; a verification the harness cannot self-run.

## Wave 1 — Execution & risk (the money path) — 2026-07-12

Opened with the three seeded money-path leads. All three CONFIRMED and pinned red-first
(`BOT/tests/test_bughunt_wave1.py`, 5 tests: 3 defect + 2 guard). Suite 261 → 266, all green.

- **CONFIRMED · MED-HIGH · L3 — `_replay_fills` carried a STALE basis across a direction flip.**
  A single fill that reverses net through zero (e.g. long 10 → sell 15 → residual short 5)
  realized the closed part correctly but only reset `avg` when `net==0`; on a flip `net≠0`, so
  the residual kept the OLD average instead of the flip-fill price. The NEXT close then realized
  P&L off a wrong basis — a **$50 error on the 5-lot test tape** (got +75, truth +125). This feeds
  the daily/weekly realized-loss GATES (`account_truth`), so a mis-realized loss could wrongly
  arm or wrongly skip a stand-down. FIX: capture `net_before`; on `net*net_before < 0` set
  `avg = price` (the residual opens at this fill). Test:
  `test_l3_direction_flip_realizes_pnl_off_the_flip_price` (+ partial-reduce guard so the
  no-flip average is untouched). NOTE reachability: paper today is single-entry per side
  (max_open_positions=1, max_entries=1 equity), so a same-symbol reversal fill is not on the
  current live path — but reconciliation/live and any multi-entry future hits it, and the OMS is
  the permanent accounting authority, so it's fixed now with armor.
- **CONFIRMED · LOW-MED · L2 — exec idem key omitted `setup` while its message claimed it.**
  `idem_key` hashed symbol·side·**entry**·session·date·version but NOT setup; the duplicate reason
  string literally reads "same setup, same trade date". Two DIFFERENT setups firing the same
  symbol/side/price on one day collided → the second (legitimate) order dropped as a FALSE
  duplicate. FIX: `setup` added to the key (now truthful to the message; old rows keep their old
  hashes — no migration, future keys only). Test: `test_l2_two_setups_same_price_are_not_false_duplicates`
  (asserts different setups both submit AND same setup still dedups — the guard not weakened).
- **CONFIRMED · LOW (latent fail-open) · L1 — `risk.decide` sized an unknown symbol at a silent
  $1/pt fallback.** `acct.point_value.get(sym, 1.0)`: equities legitimately trade $1/share and are
  absent by design, but a FUTURES symbol missing from the dict (registry drift — someone adds a
  contract to the watchlist but not to `POINT_VALUE`) would size 20-100x too big. Unreachable on
  today's watchlist (SPY/QQQ/NQ/GC all covered; `_FUTURES_SYMS` == `POINT_VALUE` keys today) — a
  DEFENSE-IN-DEPTH fix. FIX: fail closed — if a symbol is absent from the sizing dict AND
  `asset_config` classifies it futures (or it's in `_FUTURES_SYMS`), REJECT with a sizing-safety
  reason instead of guessing; equities still resolve to $1/share. Mirrors the contract registry's
  fail-loud. Test: `test_l1_futures_symbol_missing_point_value_fails_closed` (+ equity-still-sizes
  guard).

Wave-1 remainder (concurrency / numeric / fuzz) — 2026-07-12, +7 tests, suite 266 → 273:

- **CONFIRMED · MED · ExecutionService sqlite connection was NOT thread-safe.** The service is a
  PROCESS-WIDE singleton (`_broker_cache["exec"]`) called from the scan-beat thread (poll_fills /
  reconcile / staleness beats) AND FastAPI request threads (manual submit L1946, webhook L2039,
  `/api/exec/*` reads, `_replay_fills`) — all sharing ONE connection opened `check_same_thread=False`
  with no serialization. A 12-thread same-candidate submit reproduced hard corruption:
  `InterfaceError('bad parameter or other API misuse')`, `DatabaseError('no more rows available')`,
  `TypeError: NoneType not subscriptable` (cross-thread cursor/txn state clobber). FIX: `self.db`
  is now a **thread-local** connection (each thread its own; WAL shares the file) opened in
  **autocommit** (`isolation_level=None`) — the default deferred-txn mode held a read lock across
  `account_truth`'s SELECTs then upgraded to a write, so N connections DEADLOCKED on upgrade
  ('database is locked', unbreakable by busy_timeout). Autocommit = each write is a short
  self-contained lock; the OMS already writes per-step-durably so no group atomicity is lost.
  Schema created once per file (`_SCHEMA_READY`), not per-thread (that was a CREATE storm). Now
  exactly-one-submits under 12-way contention, zero raises. Tests:
  `test_w1_concurrent_same_candidate_exactly_one_submits`, `_double_poll_never_double_ingests`,
  `_fill_for_unknown_order_creates_no_phantom`.
- **CONFIRMED · LOW · `risk.decide` could RAISE instead of returning a decision.** A subnormally
  tight stop makes risk/unit round to $0.00; the code then built an APPROVED `RiskDecision` with
  `max_risk_dollars=0`, which the contract ctor REJECTS with `ValueError` — an uncaught exception
  on the submit path (submit doesn't wrap `decide`). FIX: guard — if the rounded dollar risk is
  ≤0 the stop is unusable → clean NO_STOP reject; `decide` is now total (never throws on a
  constructible candidate). Tests: `test_w1_decide_never_raises_on_a_subnormal_stop`,
  `_sizing_bounds_are_finite_and_capped_at_extremes`, `_qty_mult_hint_never_sizes_above_the_risk_gate`,
  `_account_too_small_rejects_not_zero_qty`. WAVE 1 CLOSED: 5 confirmed (L1/L2/L3 + thread-safety +
  degenerate-stop), 12 armor tests.

Remaining seeded leads L5 (evidence() perf/import-cycle), L6/L7 (data holes + manifest atomicity),
L8 (except-Exception inventory) — adjudicated in later waves.

## Wave 2 — Engine invariants — 2026-07-12 (+5 tests, suite 273 → 278; 0 new defects, all armor)

- **PROPERTY-ARMOR · mirror-tape symmetry holds.** `tests/test_bughunt_wave2.py`: a tape reflected
  around the OR midpoint (x'=204−x, so the OR range is mirror-invariant) is run through the WHOLE
  ORB pipeline (signal gen + exit engine + economics) in ALL THREE exit modes (scale_be / tp2_full
  / trail). Every long trade has an EXACT short twin — gross_R/net_R/mfe_R/mae_R/risk/hold equal,
  prices mirrored. The short-MFE bug class (S3, fixed in Phase 2) can never silently return. Plus
  universal invariants over a tape batch: exit never precedes entry, net_R ≤ gross_R (costs are a
  tax not a subsidy), hold_bars ≥ 0; determinism under float32 round-trip + index reset.
- **FALSE-ALARM (with proof) · L4 — A/B "standard" (+0.306R) vs canonical (+0.335R) is NOT config
  drift.** The canonical `orb_candidates.run_backtest` uses PER-ASSET `asset_config(sym)` —
  `ft_confirm=a.ft_confirm`, `chase_atr=a.chase_atr` (NQ 1.5 / equities 0), `reentry=True,
  max_entries=a.max_entries`, `block_range=a.block_range` (futures off), `**layer3_kwargs(a)` (per-
  asset retest incl. F78 impulse_mid) — i.e. EXACTLY the live scan's gates (the F75 fix, guarded by
  ONE shared resolver). The A/B `research/ab_entry_standard.run` is a deliberately UNIFORM isolation
  harness (hardcoded ft_confirm=True, single-entry, no per-asset chase/block_range, GLOBAL ES
  Layer-3) whose only job is to isolate the Layer-1 context gate across baseline→layer3_only→
  standard. The two numbers answer DIFFERENT questions; the gap is fully explained by intended
  config differences, not the drift class. NO code defect. DOC HAZARD (noted): the A/B "standard"
  number must never be cited as the live-system expectancy — the canonical run_backtest is the
  live-faithful evidence.

## Wave 3 — Data pipeline & persister chaos — 2026-07-12 (+4 tests, suite 278 → 282; 4 confirmed)

`tests/test_bughunt_wave3.py`. Poison frames through `live_persist.append_bars`:

- **CONFIRMED · MED · W3.1 no continuity/identity guard.** A mis-routed fetch (a WRONG symbol's
  prices) passed every candle-sanity check and would silently corrupt the continuous series — an
  NQ store (~20000) stepping into SPY prices (~550). FIX: refuse an append whose first new close is
  an impossible gap (>5x / <0.2x) from the store's last close — fail closed so QA never blesses a
  corrupted store. (The plan flagged this exact gap: "identity check exists only in the equity
  ingest — does the persister need a continuity guard? probably yes.")
- **CONFIRMED · LOW · W3.2 inf prices bypassed sanity.** `(cols > 0).all()` is True for +inf and
  `pd.to_numeric` doesn't coerce it → an inf bar entered the store. FIX: `np.isfinite` in the filter.
- **CONFIRMED · LOW · W3.3 duplicate timestamps double-appended.** No dedup within the fetched
  frame → a router repeating a bar wrote it twice. FIX: `drop_duplicates(subset="ts_et")`.
- **CONFIRMED · MED · W3.4 / L7 manifest write non-atomic + silent reset.** `_manifest` wrote with
  `write_text` (tearable) and read with a bare `except: m={}` — one torn/corrupt manifest silently
  RESET the whole file, wiping EVERY symbol's provenance and the QA 1m-grain exception with it.
  FIX: atomic tmp+replace write; a present-but-unparseable manifest now FAILS LOUD. L7 CLOSED.

L6 (QQQ/SPY Jul-7 session hole; Yahoo-fallback backfill) — DEFERRED (accepted, not a code defect):
the persister is append-AFTER-LAST by design (grows the forward edge, never backfills mid-store
holes). A one-session interior gap needs a separate targeted backfill; out of scope for the
forward-growth persister; forward QA still clears as the edge advances.

## Wave 4 — Clocks & calendars — 2026-07-12 (+4 tests, suite 282 → 286; 1 confirmed)

`tests/test_bughunt_wave4.py`.

- **CONFIRMED · MED · W4.1 loss gates bucketed fills by UTC date, not the ET trade day.**
  `account_truth` compared `str(at)[:10]` (the broker's UTC `updated_at`) against `today`/`monday`
  in ET. An overnight FUTURES fill after ~20:00 ET has a NEXT-day UTC date, so its realized loss
  fell into the wrong ET day — the daily/weekly loss stand-down could fail to fire (or fire a day
  late). Equity RTH fills (09:30-16:00 ET → same UTC day) were unaffected, which is why it stayed
  hidden. FIX: `_fill_et_date()` converts each fill's timestamp to its ET calendar date (naive
  stamps = already-local for the test fixtures) before bucketing. Tests: overnight fill now counts
  in today's ET daily; helper unit test.
- **ARMOR · `_trade_date` + idem trade-date are ET/DST-safe** (spring-forward 2026-03-08 stable),
  and the **persister session tag is DST-safe** (converts to ET before the RTH window) — both
  correct, now pinned. No defect.

## Wave 5 — Corrupt-file fail-closed matrix — 2026-07-12 (+4 tests, suite 286 → 290; 2 confirmed)

`tests/test_bughunt_wave5.py` (the file-corruption half; kill -9 process drills are a manual owner
step). Bar: a corrupt state file must fail LOUD or SAFE, never silent (runtime_state was already
hardened Phase 7; these are "the rest never got the treatment").

- **CONFIRMED · MED · W5.1 approvals.json corruption failed SILENT.** `approval._load` returned {}
  on a parse error with no signal — trading was blocked (safe) but the operator was never told, and
  a later `approve()` would CLOBBER the unreadable file. FIX: missing = clean first run; corrupt =
  keep the safe empty result BUT fire a critical alert (matches the runtime_state template).
- **CONFIRMED · MED · W5.2 entry_removals.json corruption failed SILENT + fail-OPEN.** `removals.
  _load` returned [] on a parse error — the DANGEROUS direction: an ADOPTED (retired, losing) group
  reads as not-removed and TRADES AGAIN. FIX: corrupt now fires a critical alert (announced, never
  hidden). (No removals are adopted today, so the fail-open window is currently empty — but the
  guard is in place for when one is.)
- **ARMOR · W5.3 execution.db corruption fails LOUD.** A garbage db file raises at
  ExecutionService construction (executescript on the thread-local connection) — never opens on
  non-database bytes. Pinned.

## Wave 6 — API/UI contract sweep — 2026-07-12 (+3 tests, suite 290 → 293; 0 defects, all armor)

`tests/test_bughunt_wave6.py`, via FastAPI TestClient.

- **ARMOR · W6.1 path traversal refused.** `/api/training/report?name=../../..` resolves to
  not-found — `load_report` parent-resolves against REPORTS_DIR. No escape.
- **ARMOR · W6.2 auth gate.** With `API_REQUIRE_AUTH` on, mutating endpoints (`/api/flatten`,
  paper_autotrade, kill DISARM) 401 before the body runs (no side effect); ARMING the kill switch
  stays open (safety is always armable without a token). Correct.
- **ARMOR · W6.3 read endpoints clean.** 12 console/dashboard GETs return 200 + JSON, no raw
  traceback leak, bounded payload. Pinned.

## Wave 7 — Swallow audit & dead wiring (L8) — 2026-07-12 (+1 test, suite 293 → 294; 1 confirmed)

`tests/test_bughunt_wave7.py`. Inventory: ~95 `except Exception: pass` sites across bot/.
Classification of the EXECUTION money path (service.py): most are KEEP (alert-of-alert L83,
tracker-linkage best-effort, broker-down fail-safe in recover) or NARROW (IntegrityError→duplicate,
timeout→SUBMIT_UNKNOWN which already alerts). ONE ALARM:

- **CONFIRMED · LOW-MED · L8 journal.record swallowed silently.** Both `journal.record(rd)` and
  `journal.record(ev)` in `submit()` used bare `except: pass` — a full disk would drop the paper-
  execution AUDIT record without a peep (the OMS in execution.db stays the source of truth, so the
  ORDER is unaffected). FIX: both now fire a `warn` alert naming the loss; the order still submits
  (OMS is truth). Test: a journal that raises OSError still yields `submitted` + an alert + a
  persisted OMS row. The remaining ~93 swallows are KEEP-class best-effort telemetry (alerts,
  beats, manifest, UI) — spot-verified, none on the order-placement path.

## Lead L5 — evidence() perf / import-cycle — 2026-07-12 · FALSE-ALARM (with proof)

The chain `bot.approval → bot.phase78 → bot.ml.entry_matrix → bot.strategy.removals` imports
CLEANLY (direct import test + full-suite collection) — `evidence()`'s `fills_scorecard`/
`reconciliation_clean` imports are LAZY (inside the function), so no module-load cycle exists.
Perf is bounded: `readiness()` caches 20s (`_ready_cache`); `evidence()`'s callers are the approval
UI `status()` + the rare `approve()` + a fingerprint read, not a tight uncached loop; paper fills
are few (`_replay_fills` is "deterministic and cheap"). No defect. FUTURE (not a bug): if paper
fills grow to thousands, memoize `fills_scorecard`.

## Completion pass (exhaustive) — 2026-07-12 (user: "complete at the highest quality, not time-saver")

**1a — corrupt-file matrix, EXHAUSTIVE (every state file).** `tests/test_bughunt_wave5.py` now +4:
- **CONFIRMED · MED · `config.read_json` corrupt-silent (central).** The SHARED loader behind
  boss.json / evolve / phase78 / duel / l2 returned the default on BOTH missing and corrupt — one
  torn state file was invisible across six consumers. FIX: missing = clean default; corrupt = safe
  default + a critical alert. Also pinned: runtime_state corrupt → kill switch ON + alert (Phase-7
  template), latest_scan corrupt → best-effort skip + self-heals (atomic rewrite each scan; fail
  SAFE), tracker DB malformed → callers degrade to n=0 (no stack trace on the status path).

**1b — swallow audit, EXHAUSTIVE (all 255 `except Exception` enumerated by file).** Money-path
files fully classified; the bulk (server UI beats 82, ml/nn/research, per-symbol scan) is KEEP
best-effort telemetry. ONE more money-path ALARM found beyond the journal swallow:
- **CONFIRMED · MED · `AlpacaBroker.recent_orders` swallowed to [].** recover() sets known=None (and
  LEAVES rows for the next pass) only when this broker-truth read RAISES; the swallow returned [],
  so known={} (not None) and recover() would `_fail_release` every PENDING_SUBMIT order as "crash
  before submit" — RELEASING the idem key of a possibly-live order → double-submit risk. FIX:
  recent_orders() now raises; poll_fills already wraps it (retry), recover() now correctly skips a
  broker-down pass. Test: `test_w7_broker_read_failure_during_recover_does_not_fail_release`.
  DEAD-WIRING check: `bot.live` is imported only for GRADE_MULT + scan_watchlist — the legacy
  direct-Alpaca autotrade path is retired (ExecutionService is the one door); no orphan.

**1c — calendar, EXHAUSTIVE.** `tests/test_bughunt_wave4.py` +3: fall-back 2026-11-01 duplicated
01:30 ET hour buckets to ONE ET day (both 05:30Z/06:30Z instants) and the persister keeps BOTH
(distinct UTC, not a dup to collapse); a 13:00-ET half-day flattens on its DATA-driven last bar,
never leaking into the next session. 0 defects — ET-aware helpers already correct; now pinned.

**1d — GET-route sweep, EXHAUSTIVE (all 62 routes).** `test_w6_every_get_route_is_clean...`:
enumerates every GET /api route (safe defaults for the 3 requiring params) and asserts none leaks
a Python traceback, none 500s with a stack trace, none returns an unbounded payload. 0 defects.

**W2 — cross-artifact consistency, oracle recompute.** Two guarantees, both verified:
- STRUCTURAL: the entry matrix, ML dataset and NN dataset ALL derive trades from the SINGLE
  canonical `run_backtest` (import identity asserted); `build_backtest_rows` copies `net_R`
  verbatim (no re-costing). Drift is impossible by construction (the F75 anti-drift design).
- EMPIRICAL: a fresh `run_backtest` on the LIVE QQQ 5m store === the stored matrix artifact,
  **exactly n=193 / sumR=64.69** (store ends 2026-07-10, post-persister, so no forward-growth
  confound). Plus `fills_scorecard` === an independent raw `_replay_fills` recompute (n + total).
  0 drift. Tests: `test_w2_all_backtest_artifacts_share_one_run_backtest`,
  `test_w2_fills_scorecard_equals_raw_exec_fills_replay`.

**Category 4 — ops chaos drills (REAL, dev-port + Edge, production :8000 untouched).**
`tests/test_bughunt_ops.py`:
- **ARMOR · 4a kill -9.** A hard `taskkill /F` of a process holding the single-instance named mutex
  → the OS releases it and a fresh process RE-ACQUIRES (no permanent guard deadlock). execution.db
  (WAL) survives kill -9 mid-life: a committed row is durable and `PRAGMA integrity_check`=ok (no
  torn page). Faithful SIGKILL, unique test mutex (never production's).
- **ARMOR · 4b headless Edge.** Dashboard `/` (155KB DOM) and `/training` (196KB) render with ZERO
  page-JS console errors (extension/tracking-prevention noise excluded). REFERENCE note: the
  dashboard loads chart.js from a CDN (charts degrade offline — soft dep, not a defect).
- **CONFIRMED (armor) · 4c disk-full.** `write_json` and the persister leave the target BYTE-INTACT
  under ENOSPC (tmp+replace never replaces) — no torn state file / half-store.

**Category 2 — generative fuzz + adversarial payloads.**
- **CONFIRMED · MED · W1 fuzz — cumulative filled_qty double-counted partial fills.** `poll_fills`
  ingested `filled_qty` (which is CUMULATIVE broker truth) as the fill qty, so a 10-lot that filled
  partial(5)→full(10) booked rows 5 AND 10 = **net 15 shares** → false reconcile MISMATCH halt /
  wrong P&L. FIX: ingest the DELTA (`filled - already_recorded_for_this_order`); out-of-order lower
  cumulatives are ignored (`delta>0` guard). 25-seed fuzz over random partial/full/dup/out-of-order/
  cancel/unknown interleavings: the book ALWAYS equals the max cumulative reported, never a phantom.
  `tests/test_bughunt_wave1_fuzz.py`.
- **CONFIRMED · MED · W6 — a NaN/inf float 500'd any endpoint.** FastAPI serializes with
  `allow_nan=False`, so one non-finite float (a degenerate ratio, a missing live-data value) raised
  → 500. FIX: app-wide `SafeJSONResponse` recursively maps NaN/±inf → null before serialize; every
  endpoint now returns strict-valid JSON. Adversarial `/api/signals` (NaN/inf/1e308/10KB string/RTL+
  zero-width/`<script>`) → 200, valid JSON, non-finite→null, hostile strings safely JSON-encoded.
  `tests/test_bughunt_wave6.py`.

## Pattern advisory subsystem hunt — 2026-07-12 (+11 tests, 3 confirmed)

`tests/test_bughunt_advisory.py`. Adversarial probes on the new advisory layer (module +
`/api/patterns` + summary):

- **CONFIRMED · MED · ADV1 evidence-gate bypass if the EVIDENCE/ACTIONABLE lists diverge.**
  `_passes` gated only on `evidence == "CERTIFIED"`, not ACTIONABLE membership — so a symbol
  mismarked CERTIFIED (but not in the actionable set) would PASS the gate (a false ENTER prompt on
  a non-actionable asset). FIX: require BOTH `sym in ACTIONABLE` AND `evidence == CERTIFIED`. Now a
  list divergence can never mint a false pass; NQ/ES/GC/unknown never pass (parametrized).
- **CONFIRMED · LOW-MED · ADV2 malformed snapshot crashed the advisory.** `advisory_from_proposals`
  did `p.get(...)` / `"error" in p` on every entry — a non-dict entry (None/str/int) in
  `_latest["signals"]` raised → the endpoint 500'd. FIX: `isinstance(p, dict)` filter; fail safe.
- **CONFIRMED (chained) · ADV3 endpoint 500 on a malformed/NaN snapshot** — same root as ADV2; the
  crash propagated to `/api/patterns`. FIXED by ADV2 + the app-wide SafeJSONResponse (W6) maps the
  NaN/inf fields to null, so the endpoint now returns strict-valid JSON. Adversarial `?sym=` probes
  (traversal/`<script>`/SQL/null-byte/500-char) all return a clean empty advisory, never a pass.

Advisory subsystem: 3 confirmed + fixed, 11 armor tests. Freeze intact (advisory-only, no orders).

## BUG HUNT COMPLETE (exhaustive completion pass) — 2026-07-12

All 8 seeded leads adjudicated + all 7 waves boxed + the user's "complete everything, not a
time-saver" completion pass fully executed (finite enumerations run exhaustively; W2 oracle
recompute on the REAL store; category-4 environment drills run for real on a dev port with headless
Edge). **Suite 261 → 339 (+78 armor tests). 17 confirmed defects fixed, all red-first,
money-path-first, zero regressions.**

Confirmed & fixed (17): L1 sizing fail-open · L2 idem-key false-duplicate · L3 direction-flip P&L ·
W1 OMS thread-safety corruption · W1 decide() degenerate-stop crash · W1-fuzz cumulative-fill
double-count · W3.1 wrong-symbol continuity · W3.2 inf prices · W3.3 dup timestamps · W3.4/L7
manifest atomicity · W4 loss-gate UTC/ET bucketing · W5.1 approvals silent-corrupt · W5.2 removals
silent-corrupt fail-open · W5 read_json central silent-corrupt (boss/evolve/phase78/duel/l2) · L8
journal swallow · L8 recent_orders swallow (recover double-submit risk) · W6 NaN/inf → 500.

FALSE-ALARMS (with proof): L4 (A/B vs canonical = intended config diff; empirically n=193/64.69
identical), L5 (no import cycle, perf bounded). DEFERRED: L6 (interior backfill — out of scope for
the append-after-last persister).

Coverage now EXHAUSTIVE (not sampled): corrupt-file matrix = every state file; swallow audit = all
255 `except Exception` enumerated + every money-path ALARM fixed; calendar = DST spring/fall + half-
days; GET sweep = all 62 routes; W1 state-machine = 25-seed generative fuzz; W6 = adversarial
payloads; ops = real kill -9 (mutex + WAL) + headless-Edge console + disk-full ENOSPC. W2 cross-
artifact = structural (one shared run_backtest) + empirical (real-store recompute exact).
Freeze intact: no new strategies/indicators/params; sealed journals untouched.

## Second hunt — Signal-Certificate / T1-T5 surfaces (post-remediation new code) — 2026-07-12

The first hunt fixed everything the audit named + everything the waves found in the code that
EXISTED then. Since then the Signal-Certificate centerpiece + the T1-T5 tracks LANDED — new
money-path-adjacent code that the exhaustive hunt never saw. Re-ran the full 89-test bug-hunt armor
(all green) then hunted the new surfaces. **Suite 398 → 399 (+1 fix) + 2 strict-xfail deferred-armor.**

- **CONFIRMED · MED (firing door) · certify_and_fire propagated a submit exception AFTER alerting.**
  `alert_fn` was wrapped in try/except but `submit_fn` was NOT — a submit that raises (broker socket
  death, sqlite error) AFTER the "ORDER READY" alert already fired would propagate out of the ONE
  firing door and could kill the caller/scan beat, and the caller would lose the certificate entirely
  (no audit linkage). FIX: wrap `submit_fn` exactly like `alert_fn` — a raise is captured into
  `cert["submit_result"] = {"error": ...}`, never propagated; the OMS remains the order-truth source
  (the cert submit is audit only). Test: `test_certify_and_fire_survives_a_submit_that_raises`
  (red-first: RuntimeError propagated; green: cert returned, fired=True, error captured).

- **CONFIRMED · MED · FIXED · T4 round-trip finalization was unreachable via the live poll path +
  marked the wrong candidate + the internal book NEVER closed on a bracket exit.** Three facets,
  one root: (1) a bracket TP/stop exit is a NESTED LEG of the entry order (`recent_orders` is
  `nested=True`), not a separate matchable order — `poll_fills` never ingested it, so the internal
  book never returned to net 0: `label_final` unreachable AND (worse, found while fixing)
  **`reconcile()` would MISMATCH-HALT on every bracket-closed trade** (internal net≠0 vs broker 0);
  (2) `_map_order` stripped legs to `{"status"}` only — the leg's fill truth (id/qty/price) was
  discarded before the service ever saw it; (3) finalization marked the CLOSING order's candidate,
  not the entry's. Initially logged DEFERRED-as-LOW ("no consumer yet") — WRONG CALL, corrected on
  the user's discipline: error is error; a red test is a bug regardless of current production reach.
  FIX: `_map_order` legs now carry `id/status/filled_qty/avg_fill_price/updated_at` (contract test
  updated in lockstep); `poll_fills` ingests a FILLED leg incrementally (cumulative-delta, same W1
  rule; `leg:{id}:{qty}` fill ids; excluded from the parent's entry-delta sum) as the OFFSETTING
  fill booked against the ENTRY order; when the symbol's book returns to net 0,
  `_finalize_symbol_entries(sym)` finalizes every filled entry's decision BY SYMBOL — never the
  closing order's candidate; the no-downgrade guard keeps late/duplicate polls harmless. The two
  strict-xfail pins were FLIPPED into live-path regression tests
  (`test_t4_bracket_exit_finalizes_the_entry` — nested-leg close + idempotent re-poll;
  `test_t4_close_finalizes_the_entry_not_the_closing_order`) + 2 new broker-contract tests pin the
  enriched leg shape. W1 fuzz (cumulative/dup/out-of-order) all green over the changed delta math.

- **FALSE-ALARM (with proof) · T2 entry_group_id family→category coupling.** `entry_group_id` passes
  `family` into `asset_category(symbol, family)` — suspected false-SPLIT (the same symbol's ORB
  aliases resolving to different categories → different ids, the very defect T2 fixes). VERIFIED not
  a bug: `asset_category` only returns "op" for `options-*` families; for every ORB alias
  (orb@5m/breakout/orb_stack/orb_c/orb) the category is symbol-only, so all aliases collapse to ONE
  id (`test_same_group_same_id_across_legacy_names` pins it). No false-split.

- **NOT A DEFECT (explained) · NQ Asia "not arming" at ~18:45 ET.** Correct behavior, not a bug: the
  futures Asia OR window is 19:00-20:00 ET (`ASIA_FUT = ("asia", 60, 120, 540)` — 60min→19:00,
  120min→20:00 from the 18:00 trade-day base), and a break can only fire AFTER the OR closes (20:00)
  + `entry_delay`. At 18:45 the Asia OR hasn't started forming — nothing should arm. Config matches
  the 19:00-20:00 intent. Tonight NQ Asia builds its OR 19:00-20:00 and is armable after 20:00 ET.

- **VERIFIED (no false-PASS) · the nine certificate gates are consistently fail-closed.** Traced each
  gate for a way to return OK on bad input: UNKNOWN (None) blocks everywhere; case/whitespace
  variants of "certified"/entry-state block (fail-closed); truthy-but-not-True `closed_bar` blocks
  (strict `is not True`); a dict-instead-of-RiskDecision blocks (`getattr(rd,"approved",False)`); ML
  is the only soft gate and only by DESIGN (abstain/unknown = honest pass, stale/incompatible/
  score-without-full-inputs = block). No false-pass path found.

Freeze intact: the one fix is error-handling hardening of the firing door (no new strategy/params);
the T4 gap is DEFERRED not built. Full armor (89) + full suite (399 passed, 2 xfailed) green.

## Third hunt — RTH5F shadow books + T4 leg ingestion (post-landing surfaces) — 2026-07-13

New code since the 2nd pass: the T4 exit-fill fix (leg ingestion + finalize-by-symbol), the
certificate submit-wrap, and the RTH5F/SPY-5F shadow books (`bot/strategy/rth5f_shadow.py` +
scan-loop beat). Hunted money-path-first; 1 confirmed defect, rest armor.

- **CONFIRMED · MED · shadow-book lineage POLLUTED the canonical matrix shadow evidence.**
  `entry_matrix._rows_shadow` selected EVERY resolved tracker decision with NO family/version
  filter — the audit's "loaders do not isolate strategy versions" gap, made concrete by landing
  rth5f: the moment a shadow-book row resolved, it would blend into the CANONICAL shadow cells
  (and so would worker-/trail-/options-native- study rows, which were ALWAYS blendable — a latent
  defect predating rth5f). The ML dataset was already double-protected (feat-notna + version-pure
  + family-prefix exclusion, `dataset.py:48-72`) — the matrix loader had none of it. FIX:
  `SHADOW_BOOK_PREFIXES` exclusion in `_rows_shadow` (mirrors dataset.py's lineage separation).
  Red-first: `tests/test_bughunt_shadow_lineage.py` (seeds core+rth5f+worker+trail rows → only
  core survives).
- **VERIFIED SAFE · ML dataset vs rth5f** — two independent filters exclude shadow-book rows from
  the core corpus: rth5f rows carry no pit_features (`feat0.notna()` drops them) AND version-pure
  (`rth5f-0.1 != orb-standard-2026.07.7`). No leak path.
- **ARMOR · T4 leg ingestion holds under short-side + partial-leg attack** — new pin
  `test_t4_short_entry_bracket_close_and_partial_legs`: SHORT entry + TP leg filling cumulatively
  (1 then 3) ingests deltas on the correct offset side, finalizes only at net 0, and a duplicate
  late poll re-books nothing. No defect found.
- **CONFIRMED · LOW-MED · the fail-closed armor probe found a CRASH — `df.get("volume", 0)`
  returns the INT 0 when the column is missing → `.astype` AttributeError.** Present in the new
  `rth5f_shadow._prep` AND (same idiom, latent) in the CANONICAL `families.prepare`
  (families.py:109) — a volume-less router frame would crash the scan's prepare for that symbol.
  FIX both: explicit column check, missing volume = zeros → VWAP/vol gates fail CLOSED. Pins:
  `test_malformed_inputs_fail_closed` (shadow) + `test_prepare_survives_a_frame_without_volume`
  (canonical). This is why armor probes run against NEW code: the probe was written as a formality
  and caught a live defect in two modules.
- **ARMOR · rth5f fail-closed** — a dead feed returns an error dict into the beat (never raises);
  missing volume blocks at the rvol gate.
- Also verified: autotrade/advisory/autotracker cannot see shadow-book rows (they read
  `_latest["signals"]` which rth5f never enters); `_finalize_symbol_entries` is exec-orders-scoped
  (shadow rows have no orders — untouchable).

THIRD-PASS TALLY: **2 confirmed defects fixed** (matrix shadow-lineage pollution · missing-volume
crash in shadow AND canonical prepare), T4 short/partial-leg armored, ML-dataset leak path
verified closed. Suite 408 → 412. Warnings audit (operator question, "22 warnings"):
ALL third-party deprecations, zero behavioral — FastAPI `on_event` (our registration at
server.py:951 carries the planned lifespan migration note + the library's echo), starlette-httpx
TestClient (test-only), websockets.legacy (alpaca dep), webull SDK `utcnow` (vendor), sklearn
feature-names UserWarning (LGBM canary test). Instance counts vary by test selection (22 vs 27);
unique sites: ~6, none ours except the noted on_event registration.
