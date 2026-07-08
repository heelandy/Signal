# Engineering audit — full ROOT folder (senior-engineer review, 2026-07-04)

Scope: everything under `prediction/`. Verdict up front: **the core is genuinely solid** — one
validated rule engine as the single source of truth, 100% contract↔engine parity, honest ML
gates, governance enforced in code. The main risks are **repo hygiene** (research sprawl, data in
the working tree, OneDrive), **single-process state**, and **futures execution economics** (ES
dies under stress-level slippage).

## Inventory

| Area | Size | Assessment |
|---|---|---|
| `BOT/bot` | 76 py files, ~10.5k LOC | production bot: strategy/risk/ML/NN/api — well-layered, contracts-first |
| `engine/` | 4 files, ~1.2k LOC | the backtest truth — compact, but `hs_backtest.py` is becoming a god-module |
| `research/` | **110 scripts, ~12.8k LOC** | sprawl: one-off F-studies mixed with load-bearing tools (ab/sweep/report/parity) |
| `production/` | 6 Pine, ~3.8k LOC | STACK/AUTO/OPTIONS + V1s; only STACK compile-verified recently |
| `pipeline/` | 6 files | ingestion/resample/QA — clean |
| `data/` | **3.9 GB in the repo folder** | parquet store + DuckDB views — fine locally, wrong place long-term |
| `notUse/` | 31 MB | dead code + a Databento OHLCV drop — delete or archive |
| `.venv/` | in-tree | conventional but heavy inside a OneDrive-synced folder |

## Top findings (ranked)

1. **OneDrive is syncing your trading system** (`Área de Trabalho` = Desktop under OneDrive).
   3.9 GB of parquet + SQLite + a venv under a file-sync daemon risks lock contention (SQLite
   tracker writes!), partial syncs, and silent conflict copies. **Move the repo (or at least
   `data/`, `BOT/data/`, `.venv/`) outside OneDrive**; keep OneDrive for docs only.
2. **ES economics fail the stress test**: base +0.087R/trade flips to **−0.098R at 2× slip** and
   −0.06 at 2-tick latency (backtest_matrix.json). NQ halves (+0.155→+0.076). Action: ES stays
   research-only until measured paper execution beats the stress case; NQ needs slippage-aware
   sizing. Equities are robust (+0.449→+0.393 QQQ worst-case).
3. **Single-process, in-memory server state**: `_state`, `_latest`, `_train_state`, `_cont` are
   process-local; a restart loses kill-switch state, run history, continuous-training arm state.
   Acceptable for research; before paper-with-money-consequences, persist `_state` (kill switch,
   paper toggle) to disk next to approvals and rehydrate on startup.
4. **Research sprawl**: 110 scripts, no lifecycle. The four load-bearing ones (ab_entry_standard,
   sweep_entry_params, backtest_report, replay_parity) live beside ~100 one-off studies. Action:
   `research/tools/` (kept, tested) vs `research/archive/` (frozen); RESEARCH_NOTES.md already
   indexes findings.
5. **`hs_backtest.py` god-module**: `_orb_signals` now carries 20+ params and the watch/reject
   machinery inline. It works and is tested, but the next feature should trigger extraction of a
   `SignalConfig` dataclass + a small state-machine class shared with the FSM semantics.
6. **SQLite under concurrent writers**: tracker + journal write from the scan thread while
   training subprocesses read. Currently fine (WAL-less, short transactions) but add
   `PRAGMA journal_mode=WAL` and busy_timeout before paper scale-up.
7. **Tests are good where they exist** (119 green; FSM, ML platform, risk, structure velocity)
   but there is no CI. A pre-commit `pytest -q` hook or a GitHub Action (repo has a remote)
   would catch schema drift the moment it happens.
8. **Schema evolution is handled but implicit**: FEATURE_COLUMNS grew 39→45→59 today; old model
   artifacts become unscoreable (by design) and old dataset caches degrade to NaN (by design).
   Add a `SCHEMA_VERSION` constant and stamp it into datasets/registry to make drift auditable.
9. **Secrets/config**: tokens via env (`WEBHOOK_TOKEN`, Alpaca keys) — good; `API_REQUIRE_AUTH`
   defaults OFF (localhost-bound). Fine for local research; flip it on the day the server binds
   beyond 127.0.0.1.
10. **Pine surfaces drift risk**: OPTIONS/V1/MTF are intentionally frozen (scope rule), but they
    now DISPLAY different state semantics than STACK/AUTO. The changelog flags it; consider a
    header comment in the frozen files pointing at ENTRY_STANDARD.md.

## Optimizations (cheap, high value)

- `_orb_signals` python loop dominates sweep/backtest time (~10-20s/run on futures). A numba/
  vectorized rewrite would cut the 54-combo sweep from ~30 min to ~3; only worth it if sweeps
  become routine.
- `families.scan` recomputes `prepare()` per scan cycle (60s) — cache the state frame per symbol
  and append only new bars (the 1m direction feed already caches).
- Continuous training re-replays full history each cycle: incremental dataset append (only new
  sessions) would make 1h cycles cheap.
- DuckDB for the tracker analytics instead of pandas-over-SQLite when decision counts grow.

## Delivery discipline (what to change in the process)

1. **Commit cadence**: the working tree carries a large uncommitted change set (entry standard +
   ML platform + governance). Commit in reviewable slices now that tests are green; tag
   `orb-standard-2026.07`.
2. **CI gate**: pytest + the parity report on push.
3. **Data lifecycle**: reports/ grows unbounded (every training run writes JSON) — add a 90-day
   retention sweep.
4. **One venv requirement file**: `pip freeze` drifted (torch/xgboost/lightgbm added ad hoc) —
   write `requirements.txt` from the current venv so the environment is reproducible.
5. **Runbook docs are good** (ENTRY_STANDARD, ML_NN_PLATFORM, PAPER_TO_LIVE, TASKS_INCOMPLETE) —
   keep them the single index; retire stale duplicates under `docs/bot-review/` as they age.
