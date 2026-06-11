# validatedResearch/ — passed the research gate, NOT yet in production

Configs that cleared the validation discipline (signal-level + walk-forward, both sides >0, lower-CI >0,
robust across NQ/QQQ/SPY) but are **not yet adopted** — they still need the engineering step (Pine port
reconciled bar-for-bar vs the Python harness) and a user go-ahead before moving to `production/`.

| File | What it is | Status / blocker |
|------|-----------|------------------|
| **`HIGHSTRIKE_ORB_STACK.pine`** ⭐ | **The unified, fully-upgraded file — supersedes STRUCTURE + ASIA.** One script with a **Session switch** (US RTH / Asia-Tokyo / Custom) on the trade-day clock, the structure gate + VWAP-cap, PLUS the two graduated exit/risk upgrades: **structure-anchored stop** (F25b — rest at the last HH/HL swing, ~½ the risk, +0.74→+1.00R) and a **trail exit** (F27b — ATR chandelier, 2ATR default for futures). MTF-style dashboard with explicit **Entry / Stop loss** rows. Both stop & exit are inputs (structure-stop + trail are the recommended defaults; OR-edge + scale-to-TP kept as options). | ✅ Reconcile settled offline (F28: edge invariant to the pivot tie-rule). ⚠️ **PENDING:** TradingView compile check + a **forward paper-test** of fills (esp. Asia). Run on NQ1!/MNQ1! (CME trade-day). |
| `HIGHSTRIKE_ORB_STRUCTURE.pine` | The walk-forward-validated **5m stack**: TF-adaptive trend gate (HH/HL `st_state` structure ≤5m, EMA ≥15m) + VWAP-extension cap (k=2.0). Research Findings 20 + 21: additive, exp ~2× production, DD cut 2-6×, positive every year on NQ+QQQ+SPY, OOS holds. | ✅ TradingView compile OK. ⚠️ **PENDING:** bar-for-bar reconcile of the ported `st_state` machine vs `hs_harness.py` (Phase-1 toolchain) — until that passes, live ≠ backtest. Minor: cap uses current-bar VWAP vs the backtest's prior-bar VWAP (F16: immaterial, confirm in reconcile). |
| `HIGHSTRIKE_ORB_ASIA.pine` | The **Asia-session sibling** of STRUCTURE (Finding 22): same stack on the **Tokyo-open OR (19:00-20:00 ET)** for **NQ/MNQ only**, with trade-day (18:00-ET) coordinates so the session crossing midnight stays contiguous. Walk-forward on NQ 5m: +0.50R, PF 2.78, positive every year (17/17), OOS holds, survives 2× slippage. The production breakout + a fade both LOSE in Asia — only the structure stack works. | ⚠️ **PENDING:** same `st_state` reconcile as STRUCTURE, **plus** a forward-paper-test of fill quality — Asia liquidity is thinner, ES corroborates the direction but dies under 2× slippage, so slippage is the live risk. Run on a CME futures chart (NQ1!/MNQ1!) so `time("D")` resets at the 18:00-ET Globex reopen. |

STRUCTURE + ASIA are kept for reference but **STACK supersedes both** (it merges them and adds the graduated stop/exit).

Evidence lives in `../research/RESEARCH_NOTES.md` (Findings 16, 20-28) and the harnesses `orb_hhhl_walkforward.py`,
`orb_hhhl_vwapcap.py`, `orb_stack_walkforward.py`, `orb_asia.py`, `orb_asia_walkforward.py`, `orb_struct_robust.py`,
`orb_exit_levers.py`, `orb_stop_walkforward.py`, `orb_exit_mgmt.py`, `orb_exit_walkforward.py`, `orb_xinstrument.py`,
`orb_prop_eval.py`, `orb_pivot_impact.py`, and `../qa/pivot_check.py` (all in `../research/` unless noted).
