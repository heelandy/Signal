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

## Waves (pending go-ahead)

_(Wave 1 opens with seeded leads L1–L3; findings appended here.)_
