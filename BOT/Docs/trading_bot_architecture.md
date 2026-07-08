# Trading Bot — Reference Architecture & Detailed Layer Usage

**Version 1.0 · July 2026 · Companion to the `tradingbot` scaffold (Layers 1, 4, 8 implemented and smoke-tested)**

---

## Overview

A production-grade trading bot is a one-directional data pipeline. Each layer consumes typed messages from the layer above and publishes typed messages to the layer below. No shared mutable state, no back-channels.

```
┌─ 1. DATA INGESTION ──── provider adapters, normalization
├─ 2. DATA STORE ──────── time-series DB, bar/tick history
├─ 3. FEATURE LAYER ───── indicators, regime metrics, session context
├─ 4. SIGNAL ENGINE ───── strategies, gating, dedupe
├─ 5. RISK MANAGER ────── sizing, circuit breakers, exposure caps
├─ 6. EXECUTION / OMS ─── order routing, lifecycle, fills
├─ 7. PORTFOLIO STATE ─── positions, P&L, reconciliation
├─ 8. TRANSPORT ───────── dashboard, alerts, webhooks
├─ 9. BACKTEST / REPLAY ─ same engine, historical bars
└─ 10. OBSERVABILITY ──── logging, metrics, health, kill switch
```

---

## Layer 1 — Data Ingestion

**What it is.** One adapter per data provider (Alpaca websocket, Yahoo polling, Databento, IBKR, Tradovate). Each adapter converts native payloads into a single normalized `Bar` (or `Tick`) schema and pushes onto a shared async queue.

**Detailed use.**
- Isolates provider quirks — timestamp conventions, symbol formats, delayed vs realtime, rate limits — so nothing downstream changes when feeds are swapped or added.
- Reconnect with exponential backoff; a feed drop is routine, not fatal.
- Gap detection: if bar N+2 arrives without N+1, backfill via the provider's REST history endpoint before releasing bars downstream.
- Tag every bar with its provider for audit and reconciliation.
- **Bar-close gating**: strategies must only ever see closed bars. If a feed delivers intra-bar updates, the adapter (not the engine) buffers until close.
- Multi-feed reconciliation: when two providers cover one symbol, merge on `(symbol, bar_open_time)`. Designate primary; secondary is failover/confirmation only. Never let two feeds independently drive the same strategy.

## Layer 2 — Data Store

**What it is.** Time-series database (TimescaleDB hypertable) for bars, plus tables for emitted signals and fills. Raw provider data is immutable; everything else is derived.

**Detailed use.**
- **Warm-start**: on restart, rehydrate each strategy's rolling window from the last N stored bars instead of waiting for the live feed to refill it. Restart becomes boring.
- Serves the backtester and the dashboard's history view.
- Signal + fill tables give the audit trail for slippage analysis (signal price vs fill price) and post-hoc validation.
- Bars are mandatory; ticks optional (storage cost vs marginal value — for structure-based systems, bars suffice).

## Layer 3 — Feature Layer

**What it is.** Computes shared indicators (EMA, ATR, ADX, VWAP), regime metrics (trend/range classification, volatility percentile, VIX context), and session context (RTH/ETH, time-of-day window, day-of-week) once per bar.

**Detailed use.**
- Eliminates redundant computation — five strategies asking for ATR(14) hit one cached value.
- **This is where regime gating lives.** Strategies query "is this a trending regime?" rather than each implementing its own ADX threshold. Centralizing the regime call means one place to tune it and consistent behavior across strategies.
- Session context enforces trading-window discipline (e.g., 9:50–11:00 ET scalp window) as a feature every strategy can gate on.

## Layer 4 — Signal Engine

**What it is.** The orchestrator. Consumes closed bars, maintains bounded rolling windows per (symbol, timeframe), runs every registered `Strategy`, dedupes, and publishes typed `Signal` objects to a pub/sub bus.

**Detailed use.**
- Strategies are pure functions of `(window, own_state)` — no I/O, no globals. This is what makes them unit-testable and guarantees identical behavior live vs replay.
- `Signal` carries symbol, side, kind (ENTRY/EXIT/ALERT), price, timeframe, conviction (0–1), a human-readable reason, and structured metadata. A signal must be actionable by a human or by Layer 6 without further queries.
- Dedupe suppresses double-fires; key on bar-open-time (not wall-clock) so replay behaves identically.
- Strategy exceptions are caught per-strategy: one broken strategy never takes down the engine.

## Layer 5 — Risk Manager

**What it is.** A mandatory gate between signal and order. Nothing reaches execution without passing it. It can veto, resize, or delay any signal.

**Detailed use.**
- **Position sizing**: fixed-fractional, volatility-adjusted (ATR-based stop distance → contract count), or fixed-contract for futures eval accounts.
- **Exposure caps**: max concurrent positions, per-symbol cap, aggregate directional exposure, correlated-position limits (long NQ + long QQQ is one bet, not two).
- **Circuit breakers (cascading)**: consecutive-loss stand-down, daily loss limit halt, macro-context stand-down (V18 pattern), feed-quality stand-down.
- **Prop-eval math**: trailing drawdown distance, daily loss buffer, and minimum-days logic live here — this layer is the difference between passing an eval and blowing it.

## Layer 6 — Execution / OMS

**What it is.** Broker adapters plus an order state machine: `pending → submitted → partial → filled | cancelled | rejected`.

**Detailed use.**
- **Idempotent submission**: client-generated order IDs so a network retry never doubles an order.
- Bracket management: entry + stop + TP1/TP2 as an atomic unit; TP1 fill moves stop to breakeven, etc.
- Slippage capture: record signal price vs fill price per trade; feed into validation as realized cost.
- **Kill switch**: one command flattens all positions and cancels all working orders. Test it before you need it.
- Signal-only deployments skip this layer entirely (human executes) — the correct starting posture; execution is the easiest layer to write and the most expensive to write early.

## Layer 7 — Portfolio State

**What it is.** Single source of truth for open positions, average price, realized/unrealized P&L.

**Detailed use.**
- **Broker is truth, local state is a cache.** Reconcile on every fill AND on a timer.
- Any divergence between local and broker state is a critical alert (page immediately), never a log line.
- Feeds Layer 5 — exposure caps are meaningless without accurate current exposure.

## Layer 8 — Transport / Notification

**What it is.** WebSocket/SSE push to the dashboard; out-of-band alerts (Telegram, ntfy, email) for signals and faults.

**Detailed use.**
- The dashboard is a bus consumer, never in the critical path — per-subscriber bounded queues so a dead browser tab cannot stall the engine.
- Bind to the Tailscale interface for remote home-lab access; never expose publicly.
- Alert severity routing: "signal fired" = informational; "feed dead / breaker tripped / reconcile mismatch" = act-now channel.

## Layer 9 — Backtest / Replay

**What it is.** A replay provider streams historical bars through the identical engine, feature layer, risk manager, and simulated execution.

**Detailed use.**
- The entire justification for the normalized-Bar boundary: **zero live/backtest code drift**. If backtester and live engine are different codebases, backtest results describe a system you are not running.
- Plug in walk-forward splits, Monte Carlo bootstrap on trade sequence, regime-stratified performance (ADX/VIX/time-of-day), and slippage stress testing.
- Simulated fills should model spread + slippage pessimistically; optimistic fill models are the most common source of live-vs-backtest divergence.

## Layer 10 — Observability

**What it is.** Structured logging, Prometheus metrics, `/health` endpoint, watchdogs, supervised process management.

**Detailed use.**
- Key metrics: bars/sec per provider, inbox queue depth, signals emitted, WS client count, breaker states, feed lag.
- **Feed-lag watchdog**: no bar within N× expected interval ⇒ feed-dead alert + optional risk stand-down.
- Queue-depth alarm: engine falling behind its feed is a capacity problem you want to see before it becomes a correctness problem.
- systemd/Docker restart policy + Layer 2 warm-start = restarts are non-events.
- Grafana dashboards on the Prometheus metrics for the home-lab monitoring stack.

---

## Cross-Cutting Rules

1. **One-directional flow.** A layer consumes only from above, publishes only below.
2. **Typed messages on queues**, no shared mutable state between layers.
3. **Config via environment/YAML**; secrets never in code or git.
4. **One asyncio event loop** until profiling proves otherwise; provider SDKs that demand their own loop get a daemon thread + threadsafe bridge.
5. **Every layer independently restartable** without corrupting the others.

## Build Order (De-Risked)

| Phase | Layers | Outcome |
|-------|--------|---------|
| 1 | 1 → 4 → 8 | Signals on a live dashboard (done — scaffold built & smoke-tested) |
| 2 | 9 (+2) | Validated edge via replay against historical data |
| 3 | 3 + 5 | Regime gating + risk management on validated strategies |
| 4 | 10 | Production monitoring before real capital |
| 5 | 6 + 7 | Execution last — only after the signal layer has proven itself |

Execution first is the classic failure mode: a perfectly engineered OMS routing orders from an unvalidated strategy is just an expensive random number generator.
