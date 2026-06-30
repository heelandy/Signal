# Evidence.docx → Implementation Traceability

Honest map of every Evidence.docx section to where (if anywhere) it is implemented. Status:
**DONE** = built + tested · **PARTIAL** = core built, pieces missing · **PLANNED** = in
REMAINING_FEATURES.md, not built · **REFERENCE** = research context, not code.

> Note: Evidence.docx was NOT split into the separate controlled docs Botreview suggested
> (RESEARCH_EVIDENCE / MICROSTRUCTURE_ENTRY_MODEL / …). Instead its **content was implemented into
> `bot/` code** and its plan captured in `BUILD_PLAN.md`. This table is the index.

## Part 1 — Research landscape (the strategy-families half)
| Evidence section | Where | Status |
|---|---|---|
| Executive summary, canonical evidence map, strategy-families table | `BUILD_PLAN.md` §Evidence (context) | REFERENCE |
| Data-source survey (French/AQR/Databento/…) | `bot/market_data/` (Databento path only) | REFERENCE / PARTIAL |
| Overfitting methodology (walk-forward, CSCV, Deflated-Sharpe, SPA) | engine research gauntlet + `bot/tests` | PARTIAL (gauntlet yes; DSR/CSCV not in bot) |

## Part 2 — Order-flow / early-entry model (the microstructure half)
| Evidence section | Where | Status |
|---|---|---|
| Early-entry model (location / live evidence / unused space) | `bot/orderflow/score.py` + ORB candidate | PARTIAL |
| Queue imbalance `QI` | `bot/orderflow/features.py` `book_bbo` | **DONE** (QI–microprice corr +0.96 verified) |
| Microprice `Δμ` | `features.py` `book_bbo` (micro, dmu) | **DONE** |
| Aggressive-trade imbalance `ATI` | `features.py` `trade_features` | **DONE** |
| Cumulative delta `CD` / `zCD` | `features.py` (delta, cum_delta, zcd) | **DONE** |
| Order-flow imbalance `OFI` (Cont et al., event-level) | — | PLANNED (§B) |
| Add/cancel imbalance `ACI` | — | PLANNED (§B) |
| Multi-level `MLOFI` | — | PLANNED (§B) |
| Velocity / acceleration | `score.py` accepts `vel`, not computed | PARTIAL |
| Liquidity-sweep detector | — | PLANNED (§B) |
| Intrabar direction score (0–100) | `bot/orderflow/score.py` `score_row` | **DONE** (with the features we compute) |
| Persistence layer (event-time) | `score.py` state machine `persist` | PARTIAL |
| Signal state machine (FLAT→ARMED→ENTER→ACTIVE→EARLY_FAILURE→LOCKOUT) | `score.py` `DirectionStateMachine` | **DONE** |
| Early-failure exit | `score.py` (EARLY_FAILURE state) | PARTIAL (state yes; live wiring no) |
| Multi-timeframe fusion (regime/setup/trigger/exec) | `bot/strategy/regime.py` (regime layer) | PARTIAL |
| Stop/TP (structural + hard) | engine + `risk.py` (`cap4`, struct stop) | DONE (for ORB) |
| Streaming architecture (feed→book→features→SM→exec→reconcile) | `bot/orchestrator.py` (skeleton) | PARTIAL (live loop PLANNED §G) |
| Storage formats (PCAP/DBN/Parquet/append-log) | `bot/journal.py` (JSONL) | PARTIAL |
| Databento historical + live code | `bot/market_data/databento_feed.py` | DONE (historical); live stub |
| Alpaca stream/exec code | `bot/brokers/alpaca_broker.py` | DONE (orders); data-stream PLANNED |
| Roadmap phases 1–3 | `REMAINING_FEATURES.md` §B | PLANNED |

## Part 3 — System architecture (the second, two-engine half)
| Evidence section | Where | Status |
|---|---|---|
| Overall architecture (2 alpha engines, 1 risk, 1 exec, 1 DB) | `bot/` package shape | PARTIAL |
| Trading universe (ETFs/futures/stocks) | `bot/config.py` + per-symbol point values | PARTIAL |
| **Strategy A Setup 1 — opening-range continuation** | `bot/strategy/orb_candidates.py` (= validated ORB+F61) | **DONE** |
| Strategy A Setup 2 — trend pullback | — | PLANNED |
| Strategy B — VWAP mean-reversion | `regime.py` references it; not built | PLANNED (needs own validation) |
| Day-Trade Regime Selector (trend vs range) | `bot/strategy/regime.py` | **DONE** |
| Day-Trade Risk Engine (0.25%/trade, 0.75% daily, 3/day, 2-loss) | `bot/risk.py` | **DONE** |
| Trading-window enforcement | — | PLANNED (§D) |
| News/event lockout | `bot/news_lockout.py` | **DONE** (needs event source wired) |
| Long-term ETF trend/momentum engine | — | PLANNED (out of MVP) |
| Individual-stock extension | — | PLANNED (out of MVP) |
| Shared Signal Object (JSON) | `bot/contracts.py` `TradeCandidate` | **DONE** |
| Execution engine (marketable limit + bracket + OCO + reconcile) | `bot/brokers/alpaca_broker.py` (bracket) | PARTIAL (OCO/partial-fill/reconcile PLANNED §A) |
| Data requirements (1m OHLCV, quotes, VWAP, halts) | `bot/market_data/` + engine | PARTIAL |
| Technology stack (Postgres/Timescale/Redis/FastAPI/Docker) | Python/pandas/duckdb only | PARTIAL (DB/API/Redis PLANNED §E/§F) |
| Required DB tables (orders/fills/positions/risk_snapshots/…) | `journal.jsonl` only | PLANNED (§E) |
| Validation standards + acceptance gates | engine gauntlet + `bot/tests` (17) | PARTIAL |
| Deployment sequence (research→sim→paper→shadow→live) | `bot/orchestrator.py` mode gate (SHADOW done, LIVE locked) | PARTIAL |
| ML / continuous-learning (advisory) | `bot/ml/predictor.py` (baseline) | PARTIAL |

## Summary
- **Fully implemented (DONE):** the validated edge (ORB+F61), the contracts/shared-signal object,
  risk engine, regime selector, news-lockout, the core order-flow features (QI/microprice/ATI/CD) +
  intrabar score + state machine, Databento/Alpaca adapters, journal.
- **Biggest NOT-yet pieces:** event-level OFI/ACI/MLOFI/sweep features, the live streaming loop, OMS
  (OCO/partial-fill/reconciliation), DB persistence + FastAPI, Strategy B (mean-reversion) and the
  long-term ETF engine, and full DSR/CSCV validation. All tracked in `REMAINING_FEATURES.md`.
