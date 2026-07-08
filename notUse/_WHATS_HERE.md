# notUse/ — moved for your review (nothing deleted)

Files not used by the current HIGHSTRIKE pipeline. Review and delete what you don't want.

## Old "Price Prediction Base" project (superseded)
- `app.py` — old Streamlit price-prediction UI
- `price_prediction.py` — old generic price predictor
- `make_nq_sample.py` — old sample-trade generator
- `notebook.ipynb`, `Untitled-1/3/5/7.ipynb` — old exploration notebooks
- `README.md` — old project readme (a fresh HIGHSTRIKE README is now in the root)

## Old sample / output artifacts
- `nq_sample_trades.csv`, `sample_data.csv`, `predictions.csv`
- `validate_output.txt`, `validate_output2.txt`, `validation_result.txt`
- `tmp_validate_eval.py`
- `tradovate-positions-...csv` (empty)

## Live-fills tooling — NOT used yet, KEEP for Phase 8 (going live)
- `fills.py` and `hs_validation.py` — identical Tradovate "Fills" → round-trip-trades
  converters (FIFO matching). When you trade live, these convert broker fills into the
  canonical trade schema that `hs_validate.py` ingests. Don't delete — just not used now.

## Databento batch leftovers (the data is already ingested)
- `metadata.json`, `manifest.json`, `condition.json` — the ES batch's metadata
- `GLBX-20260608-3FW3T7PQGJ1HR/` — the batch folder; contains a redundant NQ **1h** CSV
  (we resample our own from the 1m, so it's not needed) + the same metadata.
