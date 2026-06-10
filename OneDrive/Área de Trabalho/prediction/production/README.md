# production/ — frozen, deployed Pine scripts

The live HIGHSTRIKE Pine set. **Do not change entry/exit logic here ad-hoc.** Per the all-scripts-consistency
rule, any adopted entry-logic change must be applied to ALL of these + the Python engine and re-validated
on QQQ AND NQ first (see `../research/RESEARCH_NOTES.md`).

| File | Role |
|------|------|
| `HIGHSTRIKE_ORB_V1_INDICATOR.pine` | ORB visual indicator — OR, breakout signals, regime, SL/TP plan, dashboard (mirrors the strategy) |
| `HIGHSTRIKE_ORB_V1_STRATEGY.pine`  | ORB strategy — resting-stop entries, scale_be exits, EOD-flat, eval guardrails |
| `HIGHSTRIKE_ORB_AUTO.pine`         | ORB automation strategy — single-bracket + webhook JSON for a broker bridge |
| `HIGHSTRIKE_ORB_OPTIONS.pine`      | ORB → options translation (strike/spread picker from the ORB levels) |
| `HIGHSTRIKE_ORB_MTF_SIGNALS.pine`  | 5m + 15m ORB breakout display on any chart TF (confluence awareness) |

(Legacy `HIGHSTRIKE_V44_STRATEGY.pine` + `hs_recon_export.pine` live in `../research/` — V44's entry had no
edge; it's kept for the reconcile only.)

The Python engine (`../hs_*.py`) is the shared logic-of-record and lives at the project root (it's imported by
the research sweeps and reads `../data/` relative to the root — do not move it without rewiring imports/paths).

Promotion path: `research/` (exploratory) → `validatedResearch/` (passed the walk-forward) → here (reconciled
vs the harness + propagated to all scripts + adopted).
