# BOT — Front-End Visualization & User-Interaction Proposal

The bot back-end is an auditable pipeline (`Candidate → MarketTruth → Risk → Order → Broker →
Journal`). The front-end's job is to make that pipeline **observable and controllable** without ever
letting the UI place trades directly — every action goes back through the risk gate and broker
adapter. The UI is a window and a set of buttons onto the existing contracts; it adds no trading logic.

## Principles
- **Read-mostly.** The UI shows state; trading happens server-side through the risk gate.
- **One contract language.** Every panel renders the canonical objects (`TradeCandidate`,
  `RiskDecision`, `OrderEvent`, `PositionState`, `JournalEntry`, `SourceHealthState`).
- **Mode is always visible** (REPLAY / PAPER / SHADOW / LIVE) with a colour and a lock icon; LIVE
  needs the readiness lock and a typed confirmation.
- **Fail-closed UI.** If the feed is stale or the bot is unhealthy, controls grey out.

## Recommended stack
- **Backend API**: FastAPI over the existing `bot/` modules (REMAINING_FEATURES §F) — REST for
  state, WebSocket for the live tape/score/positions.
- **Frontend**: reuse the existing **Next.js/TypeScript `web/`** app (it already has auth, billing,
  admin, a journal surface) — add a "Bot" section. Charts: **TradingView Lightweight Charts** (matches
  the Pine look) + Recharts for equity/metrics.
- **Live push**: WebSocket channel per instrument (candles, order-flow score, position, health).

## Screens (proposed)

### 1. Live Trade Board  *(the main screen — mirrors the STACK dashboard)*
- Price chart (Lightweight Charts) with: OR high/low, entry/stop/TP1/TP2 lines, **FILL marker + time**
  (exactly the simplified Pine look), session shading.
- Per-side **state chip**: WAIT / ARMED / FILLED / NEAR TP1 / TP1 / TP2 / STOP (the user's colour legend).
- Trade-plan panel: GRADE, ENTRY, STOP, TP1, TP2, R:R, suggested qty, regime, session.
- **Order-flow strip** (when MBO live): intrabar direction score 0–100 gauge, QI / microprice Δμ /
  ATI / cumulative-delta sparklines, signal state (FLAT→ARMED→ENTER→…).

### 2. Candidates & Risk Feed
- Streaming list of every `TradeCandidate` with its `RiskDecision` (approved / rejected / blocked +
  reason code). Rejected candidates shown too (greyed) — the "why we didn't trade" log.
- Filter by symbol / setup / reason. Click a row → full evidence JSON.

### 3. Positions & Orders
- Open positions (broker truth vs internal — flag mismatches in red), live P&L in R and $.
- Order ledger with the state machine timeline (created→submitted→accepted→filled…), fills, slippage
  vs plan. Manual **cancel / flatten** buttons (routed through the broker adapter, audited).

### 4. Performance & Journal
- Equity curve, drawdown, expectancy (R), win %, profit factor, exit mix, per-session / per-symbol
  breakdown — straight from `Journal.metrics()`.
- Paper-vs-theoretical comparison (Evidence stage 3): expected fill vs paper fill vs market, latency.
- Trade journal table (reuse `web/account/journal`), each linked to its candidate→risk→orders.

### 5. Health & Controls  *(ops)*
- Health tiles: market-data freshness, source health, broker connection, DB, kill-switch — from
  `Orchestrator.health()`. Red = fail-closed (controls disabled).
- **Kill switch** (big red), **pause new entries**, **flatten all**, mode selector (REPLAY/PAPER/
  SHADOW/LIVE with the LIVE confirmation gate), per-account funded-eval limits.
- Pre-market checklist + EOD report.

### 6. Replay / Backtest Explorer
- Run a replay over a symbol/date-range, scrub the equity curve, step through trades, see each
  candidate's plan + outcome on the chart. (Drives `bot/replay.py`.)

### 7. Settings
- Risk limits (risk %/trade, daily-loss, trailing-DD, max trades/day) — write to `RiskLimits`.
- Strategy toggles (sessions, `dir_seq`, exit mode), instrument universe, news-lockout calendar.
- Broker keys status (never display secrets — show connected/which account, masked).

## User-interaction list (what the user can DO)
1. Watch live candidates, risk decisions, positions, P&L, and the order-flow score in real time.
2. Switch mode (replay → paper → shadow → live) with a hard LIVE confirmation.
3. Hit the kill switch / pause entries / flatten all (audited, fail-closed).
4. Approve or veto a candidate manually (optional "review-before-send" mode) — still re-checked by risk.
5. Adjust risk limits, strategy toggles, and the instrument universe.
6. Run and scrub replays/backtests; export the journal.
7. Acknowledge incidents and read the pre-market / EOD reports.

## Build order (front-end)
1. FastAPI read-only endpoints (`/health`, `/candidates`, `/positions`, `/journal/metrics`) + WS tape.
2. Screen 5 (Health & Controls) + Screen 1 (Live Board) — see + stop.
3. Screen 2/3 (Candidates/Risk, Positions/Orders).
4. Screen 4 (Performance/Journal) reusing `web/`.
5. Screen 6 (Replay Explorer) + Screen 7 (Settings).
6. Order-flow strip on Screen 1 once the MBO live engine (§B) streams.

Nothing here can place a trade the risk gate didn't approve — the UI is an observation/command
surface over the same contracts the bot already enforces.
