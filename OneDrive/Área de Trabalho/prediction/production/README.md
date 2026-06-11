# production/ — frozen, deployed Pine scripts

The live HIGHSTRIKE Pine set. **Do not change entry/exit logic here ad-hoc.** Per the all-scripts-consistency
rule, any adopted entry-logic change must be applied to ALL of these + the Python engine and re-validated
on QQQ AND NQ first (see `../research/RESEARCH_NOTES.md`).

| File | Role |
|------|------|
| `HIGHSTRIKE_ORB_STACK.pine`        | **PRIMARY indicator** — the unified validated 5m stack: structure gate + VWAP cap + structure stop + ATR trail, RTH/Asia/London + Auto session mode, MTF dashboard |
| `HIGHSTRIKE_ORB_AUTO.pine`         | **Automation twin of the STACK** — same engine as a strategy + provider-agnostic webhook JSON (TradersPost / PickMyTrade / Generic relay / custom template, multi-account fields). Plug in URL/token/accounts when available — see `../docs/AUTOMATION_SETUP.md` |
| `HIGHSTRIKE_ORB_V1_INDICATOR.pine` | Legacy V1 visual indicator — OR, breakout signals, regime, SL/TP plan (structure-stop + trail available, off by default) |
| `HIGHSTRIKE_ORB_V1_STRATEGY.pine`  | Legacy V1 strategy — resting-stop entries, scale_be exits, EOD-flat, eval guardrails (⚠ stack upgrades NOT yet propagated) |
| `HIGHSTRIKE_ORB_OPTIONS.pine`      | Stack-engine options translator — SPY/QQQ, RTH only, 0DTE entry / max 4-DTE hold, naked BUY call/put at 1-2 ITM/OTM (strike ladder), debit spread capped @TP1, credit spread short @structure stop, trail = exit signal |
| `HIGHSTRIKE_ORB_MTF_SIGNALS.pine`  | 5m + 15m ORB breakout display on any chart TF (confluence awareness) |

(Legacy `HIGHSTRIKE_V44_STRATEGY.pine` + `hs_recon_export.pine` live in `../research/` — V44's entry had no
edge; it's kept for the reconcile only.)

The Python engine (`../hs_*.py`) is the shared logic-of-record and lives at the project root (it's imported by
the research sweeps and reads `../data/` relative to the root — do not move it without rewiring imports/paths).

Promotion path: `research/` (exploratory) → `validatedResearch/` (passed the walk-forward) → here (reconciled
vs the harness + propagated to all scripts + adopted).
