# pipeline/ — data ETL (raw → processed store)

Run-once-per-data-drop scripts that turn the raw downloads in `../data/raw/` into the processed DuckDB +
parquet store in `../data/`. **Run from the repo ROOT** so the relative `data/` paths resolve.

| Script | In → Out |
|--------|----------|
| `hs_build_continuous.py` | `data/raw/glbx-*.csv` (futures, mixed contracts) → `data/<sym>_continuous_1m.parquet` + roll schedule |
| `hs_ingest_equity.py`    | `data/raw/xnas-*.csv` (equities) → `data/<sym>_continuous_1m.parquet` |
| `hs_build_vix.py`        | `data/raw/xcbf-*.csv` + `data/raw/2011-2018vix` → `data/vix_daily.parquet` |
| `hs_resample.py`         | `data/<sym>_continuous_1m.parquet` → `data/bars/` (hive: sym/tf/session/year) |
| `hs_recon_contracts.py`  | `data/raw/glbx-*.csv` → `data/hs_outright_inventory.csv` (futures contract inventory) |

Raw-file paths are CLI args with sensible `data/raw/...` defaults; pass a path to override.
