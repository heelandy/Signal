# qa/ — data QA + Python↔Pine reconcile

Verification tooling. **Run from the repo ROOT.** These import the shared library (`../engine`) via a
`sys.path` bootstrap at the top of each file.

| Script | Role |
|--------|------|
| `hs_qa.py`        | Reusable data-QA suite (coverage, gap scan, dupes, OHLC integrity, modal interval) over the built artifacts. |
| `hs_qa_data.py`   | Quick QA pass on a raw drop (`data/raw/glbx-*.csv` by default). |
| `hs_reconcile.py` | Phase-1 Python↔Pine diff: re-runs the harness on a TradingView "Export chart data" CSV (from `../research/hs_recon_export.pine`) and logs per-column state mismatches → `data/reconcile_mismatches.csv`. This is the gate for porting `st_state` into Pine (see `../validatedResearch/`). |
