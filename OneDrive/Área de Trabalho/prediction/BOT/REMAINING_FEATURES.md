# BOT — Remaining Features (full development checklist)

What's left to make the BOT complete. Live execution stays **lockable** (fail-closed default), but
it is no longer a development blocker — the user takes discretion on going live. Ordered by the build
sequence in `BUILD_PLAN.md`. ✅ = done this session.

## ✅ Done (the auditable spine)
- Data layer — Databento local loader (CBBO + MBO) + API puller, config/.env, keys wired.
- Canonical contracts (`bot/contracts.py`) — fail-closed, state machines, JSON.
- Strategy → `TradeCandidate` emitter (wraps validated engine ORB + F61).
- Market-truth gate (fail-closed: stale/gap/dup/bad-OHLC).
- Risk gate v1 (`RiskDecision`, Evidence first-live limits, position sizing).
- Replay broker + **deterministic** end-to-end pipeline (`bot/replay.py`): reconciles to the engine (QQQ +0.280 R/trade gross / +0.264 net, +121 R).

---

## A. Execution & brokers
- [ ] `brokers/base.py` — abstract Broker interface (`submit/cancel/replace/positions/account`).
- [ ] **Alpaca paper adapter (equity)** — real order submit + fills via `alpaca-py` (keys ready), same interface as ReplayBroker.
- [ ] Order Management System — OCO/bracket, partial fills, replace/cancel, timeouts, retries, max-slippage limit.
- [ ] Position reconciliation loop — broker truth vs internal; drive the `mismatch`/`emergency` states; pause on disagreement.
- [ ] Alpaca **options** adapter — CALL/PUT + debit/credit verticals (mirror `HIGHSTRIKE_ORB_OPTIONS.pine`), priced off the CBBO chain.
- [ ] Futures adapter (Tradovate or IBKR) for NQ/ES/GC — later phase.
- [ ] Live adapter + flip of the `LIVE_APPROVED.lock` gate.

## B. Order-flow direction engine (MBO phase — Evidence quantified spec)
- [ ] L3 **book builder** from XNAS MBO add/cancel/modify events (incremental, gap-checked).
- [ ] Features: queue imbalance `QI`, microprice `Δμ`, aggressive-trade imbalance `ATI`, order-flow imbalance `OFI/nOFI`, add/cancel `ACI`, multi-level `MLOFI`, cumulative-delta `zCD`, sweep detector, velocity/accel.
- [ ] **Intrabar direction score (0–100)** + event-time persistence layer.
- [ ] Order-flow **signal state machine** (FLAT→ARMED→ENTER→ACTIVE→EARLY_FAILURE/TP/PROTECTIVE→LOCKOUT) + early-failure exit.
- [ ] Wire order-flow as a **confirmation gate** on the candidate (engine param + Pine toggle) and validate (gauntlet). *Note from MBO study: 1-min trade-delta only weakly predicts next-minute (IC ~+0.05) — the edge is in event-time OFI/queue-imbalance, so build the book features, not just delta.*
- [ ] Live NQ MBO via Databento GLBX.MDP3 (`databento_feed.stream_live`).

## C. Strategy expansion
- [ ] VWAP **mean-reversion** strategy (Evidence Strategy B) + **regime selector** (trend vs range; never both).
- [ ] Options strategy translator wired to real chain pricing (replaces Black-Scholes estimate).
- [ ] Multi-session candidate emission (Asia / London) + multi-instrument (SPY, NQ, ES, GC) streams.
- [ ] Rejected-candidate capture (gated/failed breakouts) for diagnostics + the ML layer.

## D. Risk & capital (deepen)
- [ ] Portfolio risk — correlation limits, max concurrent across instruments, portfolio heat.
- [ ] News/event lockout (FOMC/CPI/NFP) — reuse the existing macro catalyst engine.
- [ ] Trading-window enforcement + spread-too-wide check (needs live quote).
- [ ] Multi-account / funded-eval profiles (already modeled in the Pine eval ledger).
- [ ] Options/gamma risk for the 0DTE path.

## E. Persistence & data model
- [ ] DB schema (Postgres/Timescale or SQLite to start): instruments, candles, candidates, risk_decisions, orders, order_events, fills, positions, journal, risk_snapshots, source_health, kill_switch, audit_logs (Evidence §12).
- [ ] Append-only **journal store** (write `JournalEntry` to DB/parquet) + reuse the `web/` journal surface.
- [ ] Feature/event store (raw events + derived features, partitioned).

## F. API & events
- [ ] OpenAPI service (FastAPI): auth, market-data, risk, orders, positions endpoints + auth matrix.
- [ ] Event bus + JSON schemas (`risk.approved`, `order.filled`, `position.synced`, …) with idempotency keys.
- [ ] HMAC ingestion to the existing web app (reuse `engine-ingest-contract`).

## G. Orchestration / runtime
- [ ] **Live event loop** (feed → book → features → state machine → risk → execution → reconcile), one ordered queue per instrument.
- [ ] Mode state machine hard-gating replay → paper → **shadow** → live (shadow = build orders, don't transmit, compare).
- [ ] Session clock + pre-market checklist + EOD report.
- [ ] Kill switch wiring (manual + automatic triggers: stale feed, broker disconnect, daily-loss, mismatch).

## H. Observability / ops
- [ ] Health checks (feed/book/risk/broker/db) → status JSON + dashboard.
- [ ] Structured logging + immutable audit trail.
- [ ] Metrics: signal→order latency, fill rate, paper-vs-theoretical slippage, daily PnL vs theoretical.
- [ ] Incident records + alerting; backup/restore + DR notes.

## I. Testing / validation
- [ ] Pytest suite (lift the per-module `__main__` self-tests into `tests/`).
- [x] Reconcile the replay broker R vs the engine — DONE (was an exit-ordering bug; now matches engine gross within 0.002 R; 11 of 433 trades differ by >0.01 R from level-rounding).
- [ ] Deterministic replay checksum test in CI.
- [ ] Paper-trading validation period + shadow-mode comparison (Evidence stages 3–4).
- [ ] Acceptance gates wired (OOS PF ≥1.2–1.3, no single-symbol/month, survives 2× costs + delayed entry).

## J. ML layer (last — example.txt / Evidence; advisory only, never live authority)
- [ ] Feature engineering pipeline (the example.txt feature set) + labeling (TP1/TP2/stop-first, multi-horizon).
- [ ] Baseline models (XGBoost/LightGBM) → direction / P(target) / confidence / expected move.
- [ ] Champion–challenger + continuous learning + walk-forward / CSCV / Deflated-Sharpe validation.
- [ ] Feeds the prediction → signal engine as a **sizing/filter** layer on top of the rule-based candidate.

## K. Pine / engine (parallel housekeeping)
- [ ] Propagate the F61 `dir_seq` gate to OPTIONS / AUTO / V1_INDICATOR / V1_STRATEGY (all-scripts consistency).
- [ ] TradingView compile-check the marker simplification + F61 across the set.
- [ ] OPTIONS: real-chain pricing from CBBO (replace the Black-Scholes COST estimate).

---

**Suggested next**: A (Alpaca paper adapter) to get the same pipeline submitting real paper orders, then
G (shadow mode) + I (reconcile), then B (the MBO order-flow engine — the biggest edge upside).
