# STATUS — single source of truth
*(updated 2026-07-11 · maintained under `docs/REMEDIATION_PLAN.md` Phase 0.6 — update on every landed phase)*

> **Remediation scoreboard (2026-07-12): Phases 0–7 + R + E + P1 (complete) + U (complete) ALL
> LANDED — suite 256 green, every fix red-first-tested, the operator console LIVE on :8000**
> (Mission Control renders the honest verdict: READINESS BLOCKED on data QA — the frozen-span
> waiver made visible). Open: P1.3 ML program (gated on fills + crash root-cause), TV bar-replay
> of the parity goldens (user — writes `parity_tv.json`), the 07.7 paper re-approval click
> (user), commit (parked). Forward gates running; fills expected from Monday's open.
> Deltas: `docs/REMEDIATION_DELTA.md`.

## Right now

- **Strategy version:** `orb-standard-2026.07.7` (close-confirm / watch-state, F78 pullback rules)
- **Mode:** PAPER · live **HARD-LOCKED** (`config/LIVE_APPROVED.lock` absent — double gate) · kill switch OFF
- **Paper autotrade:** **OFF** — Phase 5 landed 2026-07-11, so decision 0.5's condition is met:
  the toggle may be re-armed (user action) and every order it places now goes through the
  ExecutionService (risk on real account state → persistent OMS → fills → reconciliation).
  Shadow tracking runs regardless of this toggle. ⚠ restart the worker/server first — the
  running processes predate the Phase 1–5 code.
- **Clean forward record:** judged from the **2026-07-10 open**; ML / mining / Boss-workers
  **PARKED**; the 7DTE condor is the only band-pass study.
- **Feature freeze:** ACTIVE (no new strategies/indicators/dashboards/AI features —
  REMEDIATION_PLAN ground rule 6; watch-only research exempt).

## Trusted evidence

- **Phase R landed 2026-07-11 (frozen-span waiver — user's no-refresh decision):** the trusted
  set is now the artifacts stamped `remediation-2026-07-11 · corrected engine · frozen-span
  waiver`: the regenerated A/B (`ab_strategy_version_match` TRUE; QQQ standard **+0.306R** vs
  baseline +0.114R — the equity edge survives honest math; NQ/ES canonical: no honest edge in
  any variant), the entry-matrix backtest cells, all six ML datasets (corrected-lineage labels),
  and the re-baselined live-vs-backtest reference (+0.335R/39.4%). QA freshness stays honestly
  RED — that is the waiver's visible cost. The 415 `pre-remediation` reports remain tagged and
  untrusted. **One manual click open:** the 07.7 paper re-approval with override (see Startup
  section note).
- **Forward shadow scorecard** (`phase78.json`): n=25 closed, −0.515R avg, 12% WR — *theoretical
  shadow outcomes, not broker fills*, straddling the 07-10 reset, 15/25 grade-B data-collection
  entries. A warning, not a verdict.
- **Kept-strategy re-test (2026-07-11, post Phases 1–3):** zero verdict flips — nq-composite
  ALL-7 · futures_volbreak ALL PASS at 5m AND 1m (+0.349R, PF 1.62) · qqq-monday + spy-monday
  ADOPT 7/7 · watch studies unchanged. Canonical ORB is the weakest futures member now:
  NQ +0.047R marginal, **ES −0.068R negative**. Full table: `REMEDIATION_DELTA.md`.
- **Entry Profitability Matrix LIVE (Phase E, 2026-07-11):** `/api/entry_matrix?evidence=
  backtest|shadow|paper|live` — 28 backtest cells on the corrected engine; nominations at
  `/api/entry_matrix/nominations`. **First removal cycle: ES nominated → cohort test → REJECT**
  (OOS 2024+ is +0.167R×125 — full-history negativity hid a working recent regime). No removals
  adopted; `config/entry_removals.json` is the registry, enforced in scan + service.

## Datasets (bars store `data/hs.duckdb`, 5m RTH — spans per dataqa 2026-07-08)

QA is **fail-closed since 2026-07-11 (Phase 4)**. **2026-07-12: live-bar persister landed +
first refresh done — QQQ/SPY are now GREEN (spans → 2026-07-10, fresh).** The persister
(`bot/market_data/live_persist.py`, daily EOD beat) grows the store's forward edge from the
scan's own delayed feeds; the paper/live approval predicate is **traded-book scoped (QQQ/SPY)**,
which is now green. NQ/ES/GC stay honestly RED on LEGACY short-day damage (127/127/636 short days
— fixed numerators over decade denominators; forward accrual can't dilute them; visible in Data
Trust, non-traded). Bug found+fixed en route: `hs_resample` failed on read-only historical
partition dirs (`docs/BUG_HUNT_LOG.md`).

| Symbol | Span | Note |
|---|---|---|
| QQQ | 2018-05-01 → 2026-06-08 | **STALE** (~1 month behind) |
| SPY | 2018-05-01 → 2026-06-08 | **STALE** |
| NQ | 2010-06-07 → 2026-07-07 13:00 | last day partial · 128 short days · 5m rows appended into the 1m store since 2026-06-05 (documented grain exception) |
| ES | 2010-06-07 → 2026-06-08 | **STALE** |
| GC | similar era | edge **unverified** — GC fails engine re-validation. **Short-days verdict (2026-07-11):** modal day = full 78-bar grid (3,454 days) → the 636 short days (15.5%) are genuinely broken history, not a session-profile mismatch; QA's red is honest. Re-ingest GC before it ever matters (it is live-excluded anyway) |

L2/MBO depth: QQQ-only shards (XNAS ITCH); overlap with the bar store limited past ~Jun 9.

## Implemented vs scaffold (verified against code, 2026-07-11)

- **Implemented and wired:** 4-family ORB scan (5m + 15m lineages) · risk gate v1 (`risk.py` —
  real gates, but fed thin Account state) · SQLite store + journal + audit trail · options
  0DTE/7DTE native studies · order-flow package (`bot/orderflow/`) · continuous-training
  endpoints (worker cont-training **disabled** after crashing the scan — `run_worker.bat`) ·
  CI (slim suite, `BOT/tests` only) · watchdog + alerts channel · NN-similarity champion
  (advisory; labeled **07.4** → version-mismatched with 07.7).
- **Implemented but NOT wired / not proven:** news lockout (no calendar source, imported
  nowhere) · `portfolio.py` (only inverse-vol weights used) · Alpaca broker adapter + OMS class
  (paper autotrade bypasses both) · `reconcile_once` (called with a fresh empty OMS) · phase-8
  execution quality (journal schema mismatch → permanently n=0).
- **Scaffold / spec-only:** futures broker adapter · event bus · multi-screen UI · 4 spec_only
  strategy modules.

## Open blockers (fix order = `docs/REMEDIATION_PLAN.md`)

1. ~~Same-day daily-data lookahead~~ **FIXED 2026-07-11 (Phase 1)** — strictly-prior joins in
   engine + live, pinned by `test_pit_no_lookahead.py`. Measured impact (`REMEDIATION_DELTA.md`):
   total R roughly halved on every run; **ES flipped negative**. ⚠ the running worker still has
   the OLD live code in memory — restart the worker to load the parity fix.
2. ~~Paper path bypasses risk → OMS → journal → reconciliation~~ **FIXED 2026-07-11 (Phase 5)** —
   `bot/execution/service.py` is the ONE door for autotrade/manual/webhook: submit-time approval,
   dated idempotency, account truth from broker+fills (unprovable → reject), persistent OMS
   (`execution.db`), fill ingestion + bracket-integrity halt, reconcile-with-teeth, staleness
   sweep, boot recovery. **Paper autotrade may now be re-armed** (decision 0.5's condition is met)
3. ~~Fail-open data QA~~ **FIXED 2026-07-11 (Phase 4)** — freshness/volume/short-day/grain gates
   + fingerprints; intake aborts on step failure or red QA. **The store now honestly fails QA on
   all 5 symbols** (stale spans; GC 15.5% short days) — refreshing the data clears it and is the
   prerequisite for Phase R
4. ~~MNQ economics / unused roll adjustment~~ **FIXED 2026-07-11 (Phase 3)** — contract registry
   (`engine/hs_contracts.py`) + roll-adjusted indicators. Honest canonical numbers: NQ@5m +0.047R ·
   **ES@5m −0.068R (negative at correct costs — removal candidate)** · equities unchanged
5. ~~Simulator exit/excursion defects~~ **FIXED 2026-07-11 (Phase 2)** — last-bar EOD flatten
   (the overnight leak was flattering futures most), gap-aware stops, stop-wins ambiguity,
   side-aware MFE/MAE, 0-start maxDD, day-block bootstrap CI. Pinned by
   `test_simulator_semantics.py`. Cumulative honest numbers now: NQ@5m +0.039R · ES **−0.096R** ·
   QQQ@5m +0.335R (see `REMEDIATION_DELTA.md`)
6. ~~Approvals evidence-blind; phase-8 schema mismatch~~ **FIXED 2026-07-11 (Phase 6)** —
   paper/live approvals require green evidence (snapshot + fingerprint pinned; overrides recorded
   forever; drift → stale → arm checks refuse); phase-8 reads real execution.db fills + a
   reconciliation-clean criterion; the 07.4 champion is version-blocked from serving under 07.7;
   `GET /api/phase78` can no longer advance the live stage. NOTE: the existing 07.7 paper
   approval is honored as a **legacy** record (granted pre-predicates) so fill collection can
   proceed; any NEW approval needs green QA — impossible until the store freshens (by design)
7. ~~Fail-open health/safety state~~ **FIXED 2026-07-11 (Phase 7)** — corrupt runtime state boots
   with the kill switch ON (+alert); `/api/health` + `/api/live` are semantic (scan-heartbeat
   freshness, core-beat failures, broker ping, process identity); watchdog restarts on the
   semantic verdict; worker leaves crash records + holds a single-instance mutex; daily verified
   backups + a real restore drill passed 2026-07-11. Forward gate: one week of zero
   unexplained restarts

## Forward gates — RUNNING (started 2026-07-11 ~23:00 ET)

- **System LIVE under the production topology**: watchdog (semantic check + 90s boot grace) →
  `run_all.bat` → worker (singleton mutex, crash records, `config/worker.log`) + reloadable API
  (reload watch fixed). Autotrade **ARMED** through the ExecutionService; the cross-process
  control channel (`exec_flags` ctl_*) verified end-to-end: API POST → flag → worker sync →
  worker-persisted state.
- **Gate 1 — zero unexplained restarts, 7 days (clock: 2026-07-11 23:00 ET → 2026-07-18).**
  Judged by: any `BOT/data/crash_*.txt` (python deaths), `config/worker.log` tail (non-python
  deaths), `config/watchdog.log` relaunches. Explained = has a crash record or a deliberate
  operator action noted here. The 22:19–23:00 boot drill's restarts were all deliberate.
- **Gate 2 — paper fills accruing.** Armed Saturday; markets closed — first fills expected
  Monday 2026-07-13 09:30 ET (QQQ/SPY, grade-sized, through risk → OMS → fills → reconciliation).
  Judged by: `exec_fills` rows, phase-8 `execution_quality` n>0, matrix paper cells populating.
- **Boot-drill findings (2026-07-11, all fixed same hour):** watchdog boot-storm (no grace → 4
  stacked relaunches) · silent worker death (no log; console close-kill) · single-instance mutex
  read a clobberable GetLastError (`use_last_error=True` fix) · **uvicorn `--reload-include`
  REPLACED the default `*.py` watch — the "reloadable" API never reloaded python all session** ·
  plus: same-second worker "twins" are a multiprocessing spawn child, not duplicates.

## Startup — THE production topology (decided Phase 7, 2026-07-11)

- **Production:** `BOT/run_all.bat` → persistent worker (scan backbone, single-instance mutex,
  crash records, `BOT_CONT_TRAINING=0`) + reloadable API (`run_server.bat`), guarded by
  `watchdog.ps1` (semantic `/api/live` check; relaunches run_all — duplicates are no-ops via
  mutex + port bind).
- `BOT/start.ps1` is **DEV-ONLY** (stamped in the file) — do not point autostart at it.
  **start/stop verified 2026-07-12**: dev cycle on a side port works; `stop.ps1` fixed for the
  split topology — it now stops the WORKER too, only touches the watchdog/worker when stopping
  :8000 (a dev-port stop can no longer kill the production guard), and logs every stop as a
  DELIBERATE (gate-explained) action in `watchdog.log`.
- **UI plan**: `docs/UI_PLAN.md` (2026-07-12) — Phase U blueprint, docs-first; build starts on
  go-ahead. Deferred-items verdicts: htf parity gap = benign/closed (zero canonical consumers);
  GC short days = real data damage, QA honestly red (modal day is a full 78-bar grid); options
  economics = adopts the registry at the sealed 7DTE journal's next reset (documented in
  `engine/hs_contracts.py`).
- Dashboard: http://127.0.0.1:8000 (localhost-bound; API auth currently optional/off — P1.4).
- **Backups:** daily verified snapshot → `BOT/data/backups/` (14 kept). Last tested restore
  drill: **2026-07-11, 10 files, verify ok** (T7.4 re-drills in every suite run).

## Release criteria (enforced from remediation Phase 6)

Paper: QA green on the exact dataset · A/B matches strategy version and postdates the last rule
change · PIT canary green · test-suite marker fresh · store fingerprints match. Live additionally:
≥60 real paper fills over ≥56 days · scorecard green, no grade inversion · zero unresolved
reconciliation failures · Pine/Python parity green · champion model + feature schema match ·
`LIVE_APPROVED.lock` (manual, always).

## Documents

- **Living:** this file · `docs/TASKS_INCOMPLETE.md` (task checklist) · `docs/REMEDIATION_PLAN.md`
  (fix authority + failure-mode register).
- **Historical only (banners stamped 2026-07-11):** `BOT/Docs/REMAINING.md` ·
  `BOT/Docs/REMAINING_FEATURES.md` · `BOT/Docs/IMPLEMENTATION_STATUS.md` ·
  `docs/bot-review/TASK_LEDGER.md`. The README results table is pre-remediation lineage.
