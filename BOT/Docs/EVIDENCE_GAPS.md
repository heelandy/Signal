# Evidence.docx → build cross-check (what's missing)

Read of `BOT/Evidence.docx` (1,970 paras) mapped against the code, 2026-06-30. Legend:
✅ built · ⚠️ partial · ❌ missing · 🟰 intentional evidence-based deviation (our own research beat the doc's *starting* recommendation — the doc says its constants are "recommended starting points, not proven final parameters").

## Phase 1 — intrabar microstructure (MNQ/NQ)
| Deliverable | Status | Where / note |
|---|---|---|
| Deterministic replay engine | ✅ | engine + bot replay |
| In-memory book builder | ✅ | `orderflow/` (MBO L3) |
| Feature engine, event-time persistence | ✅ | QI, Δμ, ATI, CD, d_VWAP |
| **Labeling suite 100/250/500ms / 1s** | ❌ | F63 tested 1m–30m only; **no sub-second labeling pipeline** |
| Walk-forward report (AUC/Brier/net edge) | ✅ | `ml/validation.py` |
| **Stop/go: OOS lift in 2 adjacent horizons** | ⛔ FAILED gate | **F63: order flow NOT predictive** → microstructure correctly did NOT graduate. Not a missing build — a met-and-failed gate. |

## Phase 2 — queue mechanics + execution
| Deliverable | Status | Note |
|---|---|---|
| L3 sweep detector | ✅ | `orderflow/` |
| Add/cancel imbalance module | ⚠️ | ACI/MLOFI present; explicit add/cancel-rate module partial |
| Structural stop logic | ✅ | `_levels` struct stop (F25b) |
| **Fill-quality / adverse-selection simulator** | ❌ | replay broker exists, no microstructure fill-quality sim |
| Regime-conditioned threshold calibration | ⚠️ | regime exists; per-regime threshold calibration partial |
| Contract-roll + session-state | ✅ | continuous-contract build + session windows |

## Phase 3 — cross-asset bot
| Deliverable | Status | Note |
|---|---|---|
| OPRA / IV / Greeks | ✅ | `options/` |
| Broker integration + kill switch | ✅ (out of scope) | execution is reference only — **signal engine, you trade manually** |
| **White's Reality Check / SPA** | ❌ | only Deflated/Probabilistic Sharpe built |
| **CSCV / CPCV / PBO (overfit diagnostics)** | ❌ | the doc's central methodological ask |
| Signal-state machine (lockouts/blackout/kill) | ✅ | states + `news_lockout.py` + kill switch |
| Production observability dashboard | 📄 | deferred — single-user local |
| Cross-asset feature fusion | ⚠️ | market context (SPY/VIX), not full fusion |
| **Monthly retraining / recalibration job** | ❌ | `ml/pipeline.py` exists, no scheduler |
| Strategy governance pack | 📄 | deferred |

## Day-trade strategies (§3–4)
| Item | Status | Note |
|---|---|---|
| Setup 1 — opening-range continuation | ✅ | the core edge (F62 + the stack) |
| Setup 2 — trend pullback | ⚠️ | `strategy/extra.py` has it; **not in the live 4-family scan** |
| Strategy B — VWAP mean-reversion | 🟰 | built but DISABLED — F62/F18/F53 found MR **negative** (info-only) |
| **Regime selector (trend_score / range_score 0–100, ≥70 to enable)** | ❌ | not built as explicit scores; partly moot (MR is dead) but the scoring gate itself is absent |
| Multi-timeframe 60/15/5/1m | ⚠️ | 5m core; MTF dashboard in Pine; 1m execution-refine not in BOT |

## Risk engine (§5)
| Rule | Status |
|---|---|
| Position sizing risk$ ÷ |entry−stop| | ✅ `risk.py` |
| 0.20–0.35% / trade, 0.75–1.0% daily, ≤3 trades/day, stop after 2 losses | ✅ defaults |
| Reject: daily-loss, trailing-DD, RR<1.5R, stale data, consecutive losses, max-open | ✅ |
| **Reject: spread too wide** | ❌ (no spread feed in the live proposal) |
| Reject: stop too small (noise) / too large (ATR) | ⚠️ stop is ATR-clamped at construction; no explicit noise-floor reject |
| **Reject: per-symbol exposure** | ⚠️ only max-open-positions |
| **Reject: news imminent** | ⚠️ `news_lockout.py` exists, **not wired into `decide()`** |
| Reject: signal after window | ⚠️ enforced in the scan's session cutoffs, not in `decide()` |
| "use ACTUAL fill price, not expected" | n/a (manual fills) — but the **live-vs-backtest scorecard** now measures realised R vs the modelled edge |

## Profit-management & windows — intentional deviations 🟰
- Doc Setup 1 TP: **TP1=1R/40%, TP2=2R/40%, runner 20% trailing**. Ours (F64, validated on NQ/QQQ/SPY): **TP1=1.5R, TP2=4R, do NOT trail** (trailing loses under honest fills). We kept our backtested numbers over the doc's starting model.
- Doc windows (trend 9:35–11:30 + 13:30–15:30, MR 10:00–14:30): we use the ORB session windows + `entry_delay=60` (F38) — evidence-tuned to our own tests.

## Long-term engine (§6)
| Item | Status |
|---|---|
| ETF trend-momentum (0.2·r3 + 0.3·r6 + 0.5·r12, 200-day filter) | ✅ `strategy/extra.py` + `portfolio.py` (inverse-vol weights) |
| **Monthly rebalance scheduler + dashboard surface** | ❌ function exists, no job/UI |

## The honest top of the list (what actually matters)
1. **Multiple-testing / overfit correction (White RC · SPA · CSCV/CPCV · PBO).** The doc's *central* lesson; we ran many F-tests, and DSR alone is thin. Highest-value methodological gap — it tells us how much of the edge is real vs the factor zoo.
2. **Live-vs-backtest scorecard** — ✅ now built (taken R vs the F64 reference, by grade). The doc's "use actual fills" check, made concrete.
3. Wire **news-imminent** + **stale/spread** rejects into the live proposal (data exists, not surfaced as a hard flag).
4. Sub-second microstructure labeling + 150ms early-failure — the doc's "if you do one thing," but F63 already shows order flow isn't predictive at minute horizon; needs sub-second data and likely won't change the verdict → **low ROI**.
5. Regime selector scores + monthly ETF rebalance job — out of the day-trade signal scope → **low priority**.
