# validatedResearch/ — passed the research gate, NOT yet in production

Configs that cleared the validation discipline (signal-level + walk-forward, both sides >0, lower-CI >0,
robust across NQ/QQQ/SPY) but are **not yet adopted** — they still need the engineering step (Pine port
reconciled bar-for-bar vs the Python harness) and a user go-ahead before moving to `production/`.

| File | What it is | Status / blocker |
|------|-----------|------------------|
| `HIGHSTRIKE_ORB_STRUCTURE.pine` | The walk-forward-validated **5m stack**: TF-adaptive trend gate (HH/HL `st_state` structure ≤5m, EMA ≥15m) + VWAP-extension cap (k=2.0). Research Findings 20 + 21: additive, exp ~2× production, DD cut 2-6×, positive every year on NQ+QQQ+SPY, OOS holds. | ⚠️ **PENDING:** (1) TradingView compile check; (2) bar-for-bar reconcile of the ported `st_state` machine vs `hs_harness.py` (Phase-1 toolchain) — until that passes, live ≠ backtest. Minor: cap uses current-bar VWAP vs the backtest's prior-bar VWAP (F16: immaterial, confirm in reconcile). |

Evidence lives in `../research/RESEARCH_NOTES.md` (Findings 16, 20, 21) and the harnesses
`../research/orb_hhhl_walkforward.py`, `../research/orb_hhhl_vwapcap.py`, `../research/orb_stack_walkforward.py`.
