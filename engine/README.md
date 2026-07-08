# engine/ — shared Python library (the logic-of-record)

The core modules every backtest / research script imports. Kept as flat modules on `sys.path` (no package),
imported as `import hs_db, hs_harness as H, hs_backtest as B, hs_validate as V`.

| Module | Role |
|--------|------|
| `hs_harness.py`  | Port of the V44 chart logic — per-bar state machine (indicators, structure/st_state, pivots, macro/local regime, triggers). `compute_state(df, P)` is the entry point. |
| `hs_backtest.py` | Event-driven ORB/V44 backtest engine. Entry modes (`stop`/`retest`/`fade`/`sweepgo`/`rebreak`), exits (`scale_be`/`tp2_full`/`trail`), costs, off-by-default research toggles (`vwap_cap`, `skip_mask`, …). |
| `hs_db.py`       | DuckDB storage layer over `../data/` (continuous-1m views + the hive-partitioned `bars`). `connect()`, `bars(con, tf, session, sym)`. |
| `hs_validate.py` | Validation stats — expectancy + bootstrap CI, PF, maxDD, regime/year stratification. |

**Run from the repo ROOT** (e.g. `python engine/hs_db.py "SELECT …"`) so the `data/` relative paths resolve.
Research scripts in `../research/` add this folder to `sys.path`; QA scripts in `../qa/` do the same.
