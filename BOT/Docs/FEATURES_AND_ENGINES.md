# BOT — Features & Engines (master list)

Consolidated from the BOT spec docs (MMR-001 registry, ORM-001, FEE-001, the engine specs) +
example.txt + Evidence.docx, mapped to what's built. **Scope reminder: this is a SIGNAL ENGINE — it
analyses and emits signals to the dashboard; it does not place trades.**

Status: ✅ built+tested · ⚠️ partial · 📄 spec-only (documented, not built) · ⛔ out of scope (execution).

## ENGINES (by MMR layer)

### Market layer
| Engine | Doc | Status | Where |
|---|---|---|---|
| Market Data | MDE-001 | ⚠️ | `market_data/` (Databento local + API; multi-provider Alpaca/Yahoo/Webull/TV) |
| Market Truth | MTE/MTA | ✅ | `market_truth.py` (fail-closed stale/gap/dup/bad-OHLC) |
| Feature Engineering | FEE-001 | ✅ | `features.py` (RSI/MACD/ROC, ATR%/expansion/BB/Keltner, rel-vol, VWAP-dist, EMA slopes, ADX) |
| Market Intelligence (+context) | MIE/GMI | ✅ | `market_intel.py` (SPY/VIX → regime risk-on/off) + `strategy/regime.py` |
| **Opening Range Matrix** | ORM-001 | ✅ | engine `_orb_signals` + `strategy/families.py` (ORB, states, breakout) |
| News Intelligence / Reaction | NIH/NRE | ⚠️ | `news_lockout.py` (lockout); reaction in macro repo |

### Strategy layer
| Engine | Doc | Status | Where |
|---|---|---|---|
| Strategy Decision | SDE-001 | ✅ | `strategy/families.py` (the 4 families, per-asset) |
| Entry Intelligence | EIE-001 | ✅ | ORB close-confirm + F61 dir-seq |
| Exit Intelligence | XIE-001 | ✅ | `options/exit_plan.py` (TP1 1.5R / TP2 4R, F64) |
| Market Opportunity Queue | MOQ-001 | ✅ | `strategy/opportunity.py` (EV rank) |
| Decision Explainability | DIE-001 | ✅ | `strategy/opportunity.py` `explain()` |
| Trading Strategy Library | TSL-001 | ✅ | breakout (core) + trend/SMC (equity) + meanrev (negative) + extra |

### Risk layer
| Engine | Doc | Status | Where |
|---|---|---|---|
| Risk | RE/RRL | ✅ | `risk.py` (sizing, daily-loss, trailing-DD, kill-switch) |
| Capital Preservation / Prop-firm | CPE/PFR | ✅ | `prop.py` (eval profiles: target/daily-loss/trailing-DD/min-days/consistency/green-day protection) |
| Portfolio Intelligence | PIE-001 | ✅ | `portfolio.py` (exposure/heat/cluster/rebalance) — not yet enforced live |

### Execution layer — ⛔ OUT OF SCOPE (signal engine; you trade manually)
Broker Framework / Execution Core / OMS / Position Mgmt (BF/EC/OMS/PME) exist as `brokers/` +
`execution/oms.py` + `reconcile.py` but are **optional reference**, not the product.

### Learning layer
| Engine | Doc | Status | Where |
|---|---|---|---|
| ML Platform (+registry/champion-challenger/validation) | MLP/ML-001..008 | ✅ | `ml/pipeline.py`,`registry.py`,`validation.py` — honest/idle (no predictive edge, F62/F63) |
| Performance Intelligence / Learning | PFI/PLE | ✅ | `performance.py` + `journal.py` |
| Trade Lifecycle Journal | TLJ-001 | ✅ | `journal.py` + `store.py` (SQLite) |
| Knowledge Brain | TKB-001 | 📄 | — |

### Platform / infra
| Engine | Doc | Status |
|---|---|---|
| Trading OS Core / Capability Registry / Event Bus | TOS/RCR/EVT | ✅ `platform.py` (event bus + capability registry, 16 modules) |
| API + Dashboard | API/APIREF | ✅ `api/server.py` + dashboard (Live Signals, auto-scan, market context, take/skip) |
| Security / IAM | SEC/SDNA | ✅ `security.py` (token verify + secret redaction) + token guards |
| Observability / Ops / DR | OMP/MOR/DRP | 📄 (needs deploy env) |

## FEATURES (FEE-001 / ORM-001 / example.txt / Evidence)

| Group | Features | Status |
|---|---|---|
| Price | OHLC, body, wicks, range, body-ratio, gap | ✅ (engine) |
| Trend | EMA 9/21/50/200, slopes, ADX, lin-reg slope | ✅ |
| Volatility | ATR, ATR%, ATR-expansion, realized vol, BB & Keltner width | ✅ (`features.py`) |
| Structure (SMC) | HH/HL/LH/LL, BOS, CHoCH, st_state, swing len/angle | ✅ (st_state) |
| Liquidity (SMC) | order blocks, FVG, equal highs/lows, **liquidity sweeps** | ⚠️ (OB ✅, sweeps ✅ in MBO) |
| **ORB** | OR high/low, **range width, ATR-ratio, breakout dir, retest, vol-confirm, VWAP-align, trend-align, sweep** | ✅ (`families.py`) |
| Volume | volume, rel-volume, volume-spike, VWAP-dist | ✅ (`features.py`; buy/sell-delta in MBO) |
| **Order-flow (L3 MBO)** | **QI, microprice Δμ, ATI, OFI, ACI, MLOFI, cum-delta zCD, sweep detector** | ✅ (`orderflow/`) — NOT predictive (F63) |
| Time/Session | session, hour, day, **opening range per session (Asia/London/RTH)**, kill-zone | ✅ |
| Momentum | RSI, ROC, MACD (+hist), accel/decel | ✅ (`features.py`) |
| Market context | SPY trend, VIX, regime risk-on/off | ✅ (`market_intel.py`) |
| Options | Black-Scholes, **Δ/Γ/Θ/V/ρ, IV solve**, naked/debit/credit | ✅ (`options/`) |
| News | FOMC/CPI/PPI/NFP/earnings lockout | ⚠️ (`news_lockout.py`, no live calendar) |

## ORB STATES (ORM-001, used by the scan)
BUILDING → COMPLETE → INSIDE_RANGE → BREAKOUT_UP/DOWN → (RETESTING) → CONFIRMED / FAILED / INVALIDATED.

## SESSIONS (futures = 3; equity = 1)
- **Asia / Tokyo**: OR 19:00–20:00 ET (validated F22). **London**: OR 03:00–03:30 ET (F29). **RTH**: OR
  09:30–10:00 ET (F62). Futures scan all three; equities scan RTH. Gold (GC) = US-morning, **unverified**.

See `REMAINING.md` for what's left and `RESEARCH_NOTES.md` (F1–F64) for the validated edges.
