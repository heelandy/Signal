# Trading Bot Complete Review

Review date: 2026-07-02 · Branch `claude/trading-bot-review-pq637q`
Scope: full repository under `OneDrive/Área de Trabalho/prediction/` (HIGHSTRIKE ORB system).
Companion documents: `FILE_REVIEW_MANIFEST.md`, `CHANGE_IMPLEMENTATION_LOG.md`,
`PERFORMANCE_REPORT.md`, `BACKTEST_INTEGRITY_REPORT.md`, `LIVE_TRADING_SAFETY_CHECKLIST.md`.

## 1. Executive Summary

HIGHSTRIKE is an Opening-Range-Breakout day-trading system: a Python research/backtest engine
(16 y of NQ/ES/GC futures + QQQ/SPY 1-minute data), a set of production TradingView Pine scripts
(indicator + webhook-automation strategy), and a Python "signal engine" bot (`BOT/bot`) that scans
live data, grades signals, translates them to options structures, and can place **paper** bracket
orders on Alpaca. Live trading is deliberately hard-locked (`BOT_MODE=live` **and** a manually
created `LIVE_APPROVED.lock` file, enforced in `config.py`, `risk.py`, `orchestrator.py`,
`alpaca_broker.py` — four independent layers).

Overall the codebase is unusually disciplined for a retail bot: canonical contracts with
fail-closed validation, a stop-first backtest fill model, costs and slippage modeled, bootstrap-CI
gauntlets, walk-forward habit, and a research log (`RESEARCH_NOTES.md`) tracing every production
default to a finding number.

The review found **2 critical** and **7 high** issues — all fixed or mitigated in this branch:
the worst were a **live Webull access token committed to git**, and **no duplicate-order
prevention on the TradingView-webhook / manual-ticket order paths**. The stale-data gate existed
(`market_truth.py`) but was **not wired in** — the live scanner hardcoded `source_healthy=True`.
The Pine automation strategy could fire close-confirm entries **intrabar** (live ≠ backtest).
All fixes are covered by 24 new regression tests (45/45 pass). Measured performance work cut the
per-scan state computation by ~26–33 % with bit-identical outputs.

## 2. Repository Inventory

339 tracked files. Modules: `BOT/bot` (the bot, 57 files), `BOT/tests`, `engine/` (backtest +
state harness), `pipeline/` (data build), `qa/` (data + Pine reconcile QA), `production/` (6 Pine),
`validatedResearch/` (2 Pine), `research/` (96 research scripts — research-only),
`BOT/*.md` (122 design docs), `notUse/` (excluded). Full per-file detail, review depth, and
exclusions: `FILE_REVIEW_MANIFEST.md`.

## 3. Architecture

```mermaid
flowchart TB
  subgraph DATA["Market data"]
    Y[yfinance] --> RT
    AL[Alpaca IEX] --> RT
    WB[Webull OpenAPI] --> RT
    TS[TradeStation v3] --> RT
    DBL[Databento Live] --> LP[latest_price]
    RT[providers.get_bars router\nnormalize -> ts_et OHLCV]
    DBH[Databento historical] --> PIPE
    PIPE[pipeline: continuous front-month,\nratio back-adjust, resample, VIX] --> DUCK[(data/ parquet + DuckDB views)]
  end

  subgraph RESEARCH["Research / backtest (offline)"]
    DUCK --> HAR[engine/hs_harness.compute_state\npivots, HH/HL st_state, OB/FVG, macro regime]
    HAR --> BT[engine/hs_backtest\n_orb_signals + event-driven sim, costs]
    BT --> VAL[hs_validate: bootstrap CI, PF,\nregime windows, slippage stress]
    BT --> RSCH[research/* sweeps -> RESEARCH_NOTES F-xx]
  end

  subgraph LIVEBOT["Signal engine (BOT) — replay/paper; live LOCKED"]
    RT --> MT[market_truth.assess + live.source_health\nSTALE-DATA GATE fail-closed]
    MT --> FAM[strategy/families.scan\n4 families, per-asset config, grades]
    FAM --> ML[ml.pipeline P-win advisory]
    FAM --> OF[orderflow.confirm advisory]
    FAM --> RISK[risk.decide — highest authority\nkill/stale/daily-loss/DD/caps/sizing]
    RISK --> OPT[options translate + exit plan]
    RISK --> ORC[orchestrator / api.server]
    ORC -->|replay| RB[ReplayBroker deterministic fills]
    ORC -->|paper| AB[AlpacaBroker paper bracket]
    ORC -->|live| LOCK{{BOT_MODE=live + LIVE_APPROVED.lock\nelse HARD BLOCK}}
    AB --> OMS[execution.oms state machine\nOCO, partial fills, dup-fill guard]
    OMS --> REC[reconcile: broker truth wins -> MISMATCH]
    ORC --> J[journal.jsonl + store.sqlite + tracker.db]
    J --> DASH[FastAPI /api/* + dashboard.html + WS tape]
  end

  subgraph PINE["TradingView (visualization + alerts)"]
    STACK[HIGHSTRIKE_ORB_STACK indicator\n3-session ORB + gates + grades] --> ALERTS[alerts]
    AUTO[HIGHSTRIKE_ORB_AUTO strategy] --> WH[webhook JSON]
  end
  WH --> WHE[/POST /webhook/tradingview\ntoken (constant-time) + idempotency dedup/]
  WHE --> RISK
  KILL[POST /api/control/kill\narm always, disarm token-gated] -.blocks.-> ORC
```

Environment separation: research (`research/`, `engine/` CLI) is import-shared with the bot only
through `hs_harness`/`hs_backtest` (deep-reviewed, causal). Backtest (`ReplayBroker`) and paper
(`AlpacaBroker(paper=True)`) implement the same broker surface; live is fail-closed behind the
double lock. One coupling to know about: `families.py` does `sys.path.insert` of `engine/` and
calls the *backtest* signal generator for live scanning — by design (live == validated engine),
but it means an engine change instantly changes live signals; regression tests now pin its
behavior.

Startup order: `run.ps1`/`start.ps1` → uvicorn `bot.api.server` → background `_scan_loop` thread
(60 s) → scan → shadow-track → optional paper autotrade → outcome tracking. Kill-switch flow:
`/api/control/kill` → `_state` → checked before webhook/ticket/scan actions and inside
`risk.decide` (Account.kill_switch). Failure recovery: broker `_retry` on transient network errors
only; `is_market_open` cached fallback; reconcile → MISMATCH pauses the symbol.

## 4. Market-Data Review

* Router normalizes every provider to `ts_et` (tz-aware ET), OHLCV float/int, sorted, dedup-na;
  provider label carried in `attrs` and per-proposal (`source`, `price_source`).
* Timezones: all session math is done in `America/New_York` on tz-aware timestamps; DuckDB session
  timezone pinned in SQL (`SET TimeZone`), so results don't depend on machine locale. DST is
  handled by tz-conversion (ET wall clock), including the CME 18:00 trade-day roll (verified in
  `_orb_signals` trade-day coordinates and both Pine scripts).
* `market_truth.assess` checks duplicates, out-of-order, gaps (session-aware), bad OHLC, and
  staleness — **fail-closed** (empty = unhealthy). Previously not wired into the live scan
  (HS-H1, fixed): `live.source_health()` now computes `data age = now − last bar ts` and any
  feed older than `MAX_BAR_AGE_MIN` (15 min) or failing bar QA marks the account
  `source_healthy=False`, which `risk.decide` turns into a `SOURCE_HEALTH_CRITICAL` block. The
  paper autotrader also skips stale-feed signals.
* Mixed-time inputs: `latest_price` (real-time) is used for *display* price only; entry/stop/TP
  come from the same bar frame that produced the signal, so one decision uses one effective
  market time. Historical prices are back-adjusted via an explicit `adj_factor` column — raw
  prices retained for level logic, adjusted for momentum (correct approach, documented in
  `hs_build_continuous.py`).
* Futures rollover: volume-crossover, monotonic forward-only, keyed on `instrument_id` (immune to
  the 10-year symbol-code collision), ratio back-adjustment at each boundary, `is_roll` flagged,
  roll schedule persisted. Verified logic line-by-line; validation prints dups/gaps/negative
  prices.
* Remaining gaps (documented, MEDIUM/LOW): no corporate-action handling for single stocks (only
  ETFs/futures are traded; Databento XNAS 1m is unadjusted — QQQ/SPY splits are rare but a split
  would need a rebuild); Yahoo `fast_info` price carries no timestamp (freshness unknown — used
  for display only); no bid/ask feed, so spread/crossed/locked-market checks are not possible
  pre-trade (bracket orders + limit entries mitigate).

## 5. Direction-State Engine Review

The direction engine is the HH/HL swing-structure state machine (`hs_harness.compute_state`,
ported to both Pine scripts): pivots (confirmed `lb` bars after the extreme) → tolerance-filtered
swing pairs → `st_state ∈ {0 none, 1 UP, 2 DOWN, 3 RANGE}` with BOS/CHoCH transitions, plus a
fast awareness read (12-bar regression slope + VWAP side + OR-mid bias) on the STACK dashboard.

Verified:
* **Causality** — pivots only appear `lb` bars after the extreme; `sph/spl` update at the confirm
  bar; no negative shifts anywhere in the engine or bot (repo-wide scan; the only forward shifts
  are research label construction — see manifest §2).
* **Symmetry** — up/down formulas are exact mirrors (`s_hh/s_hl` vs `s_ll/s_lh`, CHoCH both ways);
  new tests assert a rising zigzag never prints DOWN and vice versa.
* **Scale invariance** — tolerance is percentage-based; test scales prices ×100 and asserts
  identical states.
* **Neutrality is possible** — flat tape stays 0/3 (tested); a *pure monotonic ramp* prints no
  pivots and therefore stays neutral — this is correct for a swing-structure engine and now
  test-pinned (it never prints the opposite direction).
* **Hysteresis** — structure tolerance %, pivot confirmation lag, `bias_confirm_bars` on the
  master bias, macro-regime persistence (`persist_n`, D immediate, C→A doubled) all damp
  oscillation. One outlier print does not flip a persistent trend (tested).
* Momentum veto normalizes by ATR (`(c-c[5])/atr`), regression slope is a dashboard read only.
* Noise thresholds: ATR-based min-stop floors per instrument class (0.5 futures / 0.75 equity),
  documented tick/cost model per class. No per-tick-size threshold beyond that (acceptable at 5m).
* Divide-by-zero: ATR guards (`atr[i]>0`), `replace(0, nan)` in DMI, `+1e-12` in features; the
  tracker guards zero risk with `or 1e-9` (tested).
* Missing/duplicate observations: `market_truth` blocks them upstream fail-closed.

The orderflow direction score (`orderflow/score.py`) has a defined meaning (weighted, thresholded
contributions in [0,100], opposite evidence scores 0), symmetric by construction, with ARMED→ENTER
persistence (3 consecutive ≥80 events) and an early-failure flip state — verified + self-tested.

## 6. Strategy and Signal Review

Four standing families (`families.py`), each tagged with validation status; only `breakout` is
tradeable-validated (NQ/QQQ/SPY), `meanrev` is explicitly info-only (negative expectancy, F18/F53/F62).
Entry rules: OR break with close-confirm (strong body ≥0.25 range, right color) + next-candle
continuation (F59c) + direction sequence (F61) + trend gate (st_state) + OR-mid bias + no-chase
cap (1 ATR) + vol-expansion grade; session windows per asset (RTH equity; Asia/London/RTH
futures); re-entry re-arms inside the OR up to per-asset `max_entries`. Exits: structure-anchored
stop (F25b) with min/max ATR clamps per class, TP1=1.5R / TP2=4R cap (F64), EOD flat. Long/short
symmetric throughout (verified in `_orb_signals` and both Pines). Duplicate-signal prevention:
`traded_l/s` latches + re-arm rules + per-day caps; deterministic candidate idempotency keys.
Cooldowns/max-trades live in the risk gate (3/day, 2 consecutive losses) and Pine eval throttles.
Overnight: futures sessions flatten at their cutoffs; nothing is held across sessions by design.

Per-strategy determinism: `bot.replay` runs the pipeline twice and asserts identical trade
sequences (determinism verified). Reproducibility: live scan uses the *same* engine entry code as
the backtest — by construction live==backtest logic (fills aside, see §12).

Unvalidated extras (`extra.py`) are suffixed `-UNVALIDATED` and gated off. GOLD is flagged
`unverified` with the failed-reproduction note carried into every proposal.

## 7. ORB and Session Review

* Sessions: RTH 09:30–10:00 OR (trade to 15:00), Asia 19:00–20:00 (to 03:00), London 03:00–03:30
  (to 08:00), all ET; futures use trade-day minutes anchored at 18:00 ET so Asia stays contiguous
  across midnight (`(et-18h) mod 24h` — verified in Python and Pine, including the Sunday-evening
  weekday attribution `time+6h`).
* Equities correctly trade **only** RTH (Asia/London levels are never computed from nonexistent
  equity bars — `asset_config.sessions` restricts to `RTH_EQ`; futures carry the 3 sessions).
* OR levels freeze at OR close; signals can only fire after `or_e (+ entry_delay)` — first/last
  bar inclusion is `[or_s, or_e)`, reset at each session's OR start in Auto mode, with an
  18:00–19:00 stale-gap guard so yesterday's RTH levels can't fire pre-Asia. Wick vs close
  confirmation both supported; close-confirm is the default and now confirmed-bar-gated live.
* Previous-day OR is exposed as reference (`/api/orb_levels`, `back=1`).
* Holidays/early closes: the QA layer has a full-holiday NYSE/CME calendar (no early-close
  handling — documented). Trading logic relies on data presence rather than a calendar: on a
  holiday there are simply no bars. Early closes can leave an open position unflattened until the
  next data point — MEDIUM, listed in Remaining Risks.

## 8. Risk-Engine Review

`risk.decide` is a pure, ordered, fail-closed decision service (first failing rule wins):
kill switch → source health → live lock → daily loss (0.75 %) → trailing DD (3 %) → max
trades/day (3) → consecutive losses (2) → max open positions (1) → stop validity → R:R floor
(1.5) → sizing. Portfolio layer adds gross (4×), heat (2 %), name weight (25 %),
correlated-cluster (1.2 %), max positions (5). Prop layer adds eval daily-loss/trailing-DD/
target/consistency/green-day rules with early-halt buffers. All verified against their self-tests
plus the new regression tests. News lockout exists but has no calendar feed wired (MEDIUM).
Risk-reducing exits are never gated (flatten/exit paths bypass entry gates but still respect the
kill switch on new entries only) — verified: webhook `exit` events route to `broker.flatten()`.

## 9. Position-Sizing Review

Formula verified: `risk_dollars = equity × 0.25 %`; `qty = floor(risk_dollars / (|entry−stop| ×
point_value))`; futures capped at `max_contracts=50` with per-symbol point values (NQ 20, MNQ 2,
ES 50, MES 5, GC 100, MGC 10); equities capped at notional ≤ 4× equity — an extremely tight stop
therefore **cannot** create an unbounded position (regression-tested). Zero/negative stop distance
rejects (`NO_STOP`). Options sizing is per-contract with real premium × 100 multiplier and
defined max loss per structure. Grade-weighted sizing (A+ 1.5×, A 1.0×, B 0.4×, C 0) is applied on
top of the base budget with B-skip on ES/SPY (research-derived; advisory sizing only).

## 10. Order-Management Review

Order lifecycle (`contracts.ORDER_TRANSITIONS`) is an explicit fail-closed state machine
(CREATED→VALIDATED→SUBMITTED→ACCEPTED→PARTIALLY_FILLED→FILLED/CANCELLED/REJECTED/EXPIRED/ERROR);
illegal transitions emit ERROR events. OMS handles OCO brackets (fill cancels sibling), partial
fills with correct average-price math, timeouts, and reconcile (broker truth wins → MISMATCH).

Fixed this review (HS-H2): duplicate broker fill events are now ignored once an order is terminal,
overfills are clamped to the remaining quantity, and non-positive fill quantities are rejected —
so a resent fill event can no longer double the internal position (tested).

Duplicate-order prevention across the submission paths (HS-C2, fixed): the TradingView webhook and
the manual `/api/order` ticket now dedupe on an idempotency key (Pine `signalId` if present, else
the candidate's deterministic key; manual tickets key on full geometry + day), and the key rides
to Alpaca as `client_order_id`, so broker-side dedup also holds across process restarts. Network
retries were already safe (retry only on transport errors, idempotent client order id).

## 11. Broker-Integration Review

Alpaca adapter: paper-first construction; **live refuses to construct** without
`settings.live_allowed`; bracket orders (broker holds SL/TP even if the bot dies); retry wrapper
distinguishes transient network errors from API errors; clock cached with last-known fallback;
options submission is dry-run by default (`transmit=False`). Secrets come only from the
git-ignored `.env` (template verified placeholder-only). Futures brokers are config stubs (no
code path). No WebSocket order stream yet — fills are inferred/reconciled by polling (documented;
paper-study acceptable, must be upgraded before live). No live order was placed at any point in
this review; no real credentials exist in this environment.

## 12. Backtesting Review

See `BACKTEST_INTEGRITY_REPORT.md` for the full audit. Headlines: entries fill at the confirm
close (or gap-aware level for stop entries — never better than the open); same-bar stop-vs-target
resolves to the **stop** (conservative) pre-TP1; costs = MNQ $0.52/order + 2-tick slip (futures)
and 1-tick (equities); validation requires bootstrap lower-CI > 0 **and** both sides positive,
per-year, per-regime, slippage-stressed, walk-forward across the research log. Known optimism
(documented): scale mode banks TP1+TP2 in one bar when both are inside it; post-TP1 same-bar
TP2-vs-BE-stop prefers TP2 (no intrabar sequence data). The *tracker* (live scorecard) had the
same post-TP1 optimism — now fixed to stop-first so the live-vs-backtest gate is honest-or-pessimistic.

## 13. Pine Script Review

Six production + two validatedResearch + two research Pine files, all `//@version=6`.
`request.security` is `lookahead_off` everywhere in production (repo-wide scan); the single
`lookahead_on` (research V44) uses the safe `[1]`-offset idiom. No pivot/ZigZag repainting is
presented as real-time: entry logic uses only frozen OR levels + confirmed-pivot state.

Fixed (HS-H4): `HIGHSTRIKE_ORB_AUTO` runs `calc_on_every_tick=true` (needed for touch-mode resting
stops) — but close-confirm conditions read `close` and therefore fired **intrabar** on the live
bar, diverging from the backtest (final closes only). Close-confirm entries are now gated on
`barstate.isconfirmed` (identical history, honest live); the STACK indicator's signal latch got
the same gate so alerts can't fire on a candle that never confirms.

Alert payloads carry ticker/action/qty/entry/stop/TP/event/session/timeframe/`{{timenow}}` +
token/accounts. They do **not** carry a unique signal id (LOW — recommended addition); the server
now dedupes on the candidate's deterministic key regardless, and honors `signalId` if the Pine
adds one. Object counts bounded (`max_labels_count`, arrays trimmed to `ob_keep`, labels deleted
via the `f_setlbl` helper — no leaks). Eval guardrails ledger from an anchor timestamp (prevents
the "whole-history trips the target" bug, handled). Session/timezone math mirrors the Python
engine (verified side-by-side).

Division of labor is correct: Pine = visualization/alerts/lightweight confirmation; Python owns
state, risk, execution, reconciliation, persistence, ML.

## 14. Python Review

* No async misuse: the only async code is the FastAPI websocket, which fetches bars via
  `run_in_executor` (correct). The scan loop is a daemon thread with a broad-catch (reported into
  `_latest["error"]`, not swallowed silently).
* No mutable default arguments; dataclasses use `field(default_factory=…)` throughout.
* Broad `except Exception` appears in provider adapters — intentional fallback design (a failing
  provider must not kill the router); documented rather than removed.
* Datetimes are tz-aware end-to-end (`utcnow_iso`, `ts_et`); no naive-datetime arithmetic found.
* Float vs Decimal: prices round to instrument tick at the broker boundary (`round(...,2)`), R
  math is in floats — acceptable for equity/futures ticks at these magnitudes; the OMS avg-price
  math is exact enough (4 dp). No monetary accumulation crosses precision-critical boundaries.
  Documented as accepted design; no blanket Decimal conversion done (per review rules).
* Resource handling: sqlite connections opened/closed per call (tracker) or held once (store);
  duckdb connections closed; no socket leaks found. `tracker._con()` missing-directory crash
  fixed (HS-M10).
* SQL injection: all user-facing SQL is parameterized; f-string SQL exists only in local-file
  DuckDB readers with code-controlled inputs (documented, MEDIUM-low).

## 15. Database Review

SQLite (`store.py`, `tracker.py`): schema-per-contract with primary keys, `INSERT OR REPLACE`
idempotent writes, JSON blob retained, indexes on the queried columns (`symbol`); a best-effort
`ALTER TABLE` migration adds `mfe_r/mae_r`. DuckDB layer is read-only views over parquet
(lock-free, multi-process safe). Journal is append-only JSONL (audit trail). No destructive
migration paths. Recommended next: an index on `decisions(outcome)` for `track_outcomes`
(LOW — table is small).

## 16. API and Dashboard Review

Read-mostly FastAPI; mutating endpoints are the safety controls and order paths. Fixed this
review: control endpoints (`mode`, `paper_autotrade`, kill **disarm**) now pass the token guard
when `API_REQUIRE_AUTH` is on; kill **arm** deliberately never requires auth (an emergency stop
must not be lockable-out). Webhook token check is constant-time (`hmac.compare_digest` via
`security.verify_token`). Server binds `127.0.0.1` in the launch scripts. Dashboard is a
polling single-page UI over `/api/*` (read-only; Take/Skip posts a decision, orders go through
the gated ticket endpoint). Quotes cached 30 s; websocket tape streams a bar-derived flow score.

## 17. Security Review

* **HS-C1 (fixed/action-required)**: `BOT/conf/token.txt` — a live Webull SDK access token — was
  committed. Untracked + gitignored in this branch, **but it remains in git history: rotate the
  Webull app credentials** (portal → regenerate) and consider a history rewrite before any push
  to a shared remote. Committed SDK/server logs (11 Webull SDK logs, server logs, PID) also
  untracked + ignored; they contained request metadata but no key values (grep-verified).
* `.env` correctly ignored; `.env.example` placeholder-only (verified). `security.redact/mask`
  exist for log hygiene. No hardcoded keys anywhere in code (repo-wide scan).
* API responses never return secrets (`keys_status` masks). Webhook auth constant-time (fixed).
* Rate limits: none on the local API (localhost-bound; MEDIUM if ever exposed — front with a
  reverse proxy + `API_REQUIRE_AUTH=true`).
* Unsafe deserialization: `pickle` for local model registry files only (documented).
* Dependency scan: requirements are minimal (pandas/numpy/duckdb/pyarrow + broker/data SDKs);
  no known-vulnerable pins observed; recommend `pip-audit` in CI (no CI exists yet — see §27).

## 18. Performance Review

Measured (see `PERFORMANCE_REPORT.md`): the per-scan hot path `compute_state` was profiled;
three targeted, output-identical optimizations landed (vectorized pivot fast path, numpy-ified
macro-regime loop, precomputed rolling extremes in the zones loop):

| Metric (best of 3) | Before | After | Δ |
|---|---|---|---|
| `pivots()` 2,000 bars | 6.4 ms | 0.9 ms | −86 % |
| `pivots()` 20,000 bars | 62.5 ms | 3.2 ms | −95 % |
| `compute_state` 2,000 bars (live scan size) | 89.9 ms | 66.7 ms | −26 % |
| `compute_state` 20,000 bars (research size) | 668 ms | 448 ms | −33 % |

Equivalence proof: all 30 state columns identical to the pre-change implementation across three
seeds and both the constant- and adaptive-lookback paths (scripted comparison + permanent
regression test). Remaining bottlenecks documented in the performance report.

## 19. Critical Findings

| ID | File | Problem | Status |
|---|---|---|---|
| HS-C1 | `BOT/conf/token.txt` | Live Webull access token (expiry beyond review date) committed to git; SDK/server logs also committed. Root cause: no ignore rule for `conf/` + logs. Impact: credential exposure to anyone with repo access. | FIXED in-tree (untracked + ignored). **Residual: rotate the token; history rewrite recommended.** |
| HS-C2 | `BOT/bot/api/server.py` (webhook + `/api/order`) | No duplicate-order prevention: every webhook retry / repeated alert / double-clicked ticket built a fresh `OrderRequest` with a fresh UUID idempotency key → duplicate broker orders. Root cause: idempotency key defaulted to the order UUID instead of a deterministic signal key. Repro: POST the same webhook body twice (test `test_repeated_webhook_creates_one_order` — failed before, passes after). | FIXED: process-level dedup + deterministic `client_order_id` to Alpaca. Validated by 4 new tests. |

## 20. High Findings

| ID | File | Problem | Status |
|---|---|---|---|
| HS-H1 | `bot/live.py` | Stale-data gate not enforced: `decide(..., source_healthy=True)` hardcoded; a dead feed could yield APPROVED proposals (and paper orders). | FIXED: `source_health()` (market-truth + 15-min bar-age) wired into the scan, proposals expose `source_healthy`, paper autotrade skips stale. 3 tests. |
| HS-H2 | `bot/execution/oms.py` | Duplicate broker fill events double-applied to the position; overfill unbounded; qty ≤ 0 divided/corrupted state. | FIXED: terminal-state dup guard, overfill clamp, qty validation. 4 tests. |
| HS-H3 | `bot/api/server.py` | Webhook token compared with `!=` (timing side channel) although a constant-time helper existed. | FIXED: `security.verify_token` used in webhook + header auth. |
| HS-H4 | `production/HIGHSTRIKE_ORB_AUTO.pine` (+STACK latch) | `calc_on_every_tick=true` made close-confirm entry conditions evaluate intrabar → live entries the backtest never takes (live ≠ backtest; repaint-class). | FIXED: close-confirm decisions gated on `barstate.isconfirmed` (history identical). Needs a TV compile + forward-paper check (no compiler here). |
| HS-H5 | `bot/tracker.py` `_walk` | Post-TP1 same-bar stop+TP2 scored as TP2 (+4R optimistic) — inflated the live scorecard that gates sizing up. | FIXED: stop-first (conservative) ordering. 2 tests. |
| HS-H6 | `bot/api/server.py` | `POST /api/control/mode`, `/api/control/paper_autotrade`, kill-disarm had no auth even with `API_REQUIRE_AUTH=true`. | FIXED: token-gated (kill **arm** intentionally open). |
| HS-H7 | `bot/tracker.py` self-test | `out, r = _walk(...)` unpack of a 4-tuple → module self-test crashed (and masked regressions). Plus HS-M10: `_con()` crashed on a fresh checkout (no `data/`). | FIXED both. |

## 21. Medium Findings

| ID | Where | Problem / disposition |
|---|---|---|
| HS-M1 | `bot/risk.py` | Equity notional cap uses `max(cap,1)` — a degenerate cap of 0 still allows 1 share. Accepted (1 share is de-minimis); documented. |
| HS-M2 | `bot/api/server.py` | Webhook dedup key is consumed even when the risk gate later rejects — an identical retry after a rejection returns `duplicate` rather than re-evaluating. Deliberate (safer against duplicates); documented behavior. |
| HS-M3 | `providers.latest_price` | Yahoo `fast_info` price has no timestamp — freshness unknowable. Display-only use; documented. |
| HS-M4 | `databento_local.py`, `orderflow/features.py` | SQL via f-string interpolation into DuckDB over local CSVs (symbol/date from code/CLI). Low exploitability; flagged for parameterization if ever exposed. |
| HS-M5 | `journal.py` | `read()` loads the whole JSONL per API call — O(file) per dashboard poll. Fine at current scale; move to the SQLite store when the journal grows. |
| HS-M6 | repo | No CI workflow (tests exist but nothing runs them automatically). Recommended in §27. |
| HS-M7 | `alpaca_broker.positions()` | `unrealized_plpc` (a percentage) stored in the `unrealized_r` field — label/unit mismatch in the dashboard. Cosmetic-data; documented. |
| HS-M8 | `qa/hs_qa.py` | Holiday calendar lacks early-close sessions; an early close leaves EOD-flat logic waiting for bars that never come. Documented; add an early-close calendar before live futures. |
| HS-M9 | `news_lockout.py` | Gate exists but no event-calendar feed wired — FOMC/CPI windows are not actually enforced. |
| HS-M11 | `databento_live.py` | New Live TCP session per price call (per scan). Acceptable at 60 s cadence; pool/stream before tick-level use. |
| HS-M12 | `ml/registry.py` | `pickle.loads` of local model files — local-only trust boundary; documented. |

## 22. Low Findings

* `options/strategies.py` `_mk` helper is dead code.
* `providers.DEFAULT_ORDER` computed at import and unused (call sites use `_default_order()`).
* AUTO Pine alert JSON lacks a unique `signalId` (server honors one if added — recommended).
* `security.keys_status` prints "paper" for Alpaca regardless of `ALPACA_PAPER`.
* `platform.EventBus.publish` swallows subscriber exceptions silently (log counter recommended).
* `.claude/settings.json` was tracked against the repo's own ignore rule (untracked now).
* README results table predates the current default config (grades/OR-mid additions) — refresh.

## 23. Fixes Implemented

See `CHANGE_IMPLEMENTATION_LOG.md` for per-change detail (timestamps, before/after, rollback).
Summary: HS-C1 (untrack secrets/logs + ignore rules), HS-C2 (order dedup + broker client-order-id),
HS-H1 (stale gate), HS-H2 (OMS guards), HS-H3 (constant-time auth), HS-H4 (Pine confirmed-bar
gate, AUTO+STACK), HS-H5/H7/M10 (tracker), HS-H6 (control auth), performance (hs_harness ×3).

## 24. Tests Added

`BOT/tests/test_review_fixes.py` — 24 tests: repeated webhook ⇒ one order; unique signalId
honored; bad token rejected; manual-ticket double-click ⇒ one order (distinct ticket passes);
kill-switch blocks webhook; stale/empty/dirty feed blocks entries (fresh passes); OMS zero/negative
fill, duplicate fill, overfill clamp, partial-fill avg; tracker same-bar conservative outcomes +
zero-risk guard; direction-state up/down/neutral/scale-invariance/outlier tests; pivots fast-path
≡ loop (both tie rules); live locked by default (`LIVE_LOCKED` block); paper-autotrade refuses
non-paper Alpaca; sizing formula + tight-stop notional cap.

## 25. Validation Results

* `pytest BOT/tests -q`: **45 passed, 0 failed** (21 pre-existing + 24 new).
* Module self-tests (17 modules, no network/data needed): all pass, including the previously
  crashing `bot.tracker`.
* Engine equivalence: optimized `compute_state` output **identical** (30 columns, 3 seeds,
  both lb paths) to the pre-change implementation.
* Changed-module import check: `bot.live`, `bot.api.server`, `bot.tracker`, `bot.execution.oms` OK.
* Not run (unavailable in this environment, documented): full 16-y engine backtest (market data
  parquets are git-ignored and absent), TradingView Pine compilation (no compiler), network-based
  provider tests, Alpaca paper round-trip (no credentials — by design of this review).

## 26. Remaining Risks

1. **The committed Webull token exists in git history** until rotated/history-rewritten (owner action).
2. Pine edits (HS-H4) are compile-checked by inspection only — load both scripts in TradingView
   and forward-paper-test ≥2 weeks (the repo's own adoption gate) before trusting fills.
3. No broker fill webhook/stream: paper fills reconcile by polling; upgrade before live.
4. Early-close sessions and news-event lockout are not enforced (HS-M8/M9).
5. Backtest same-bar TP1+TP2 optimism in scale mode remains (documented; the shipped default
   `tp2_full`/cap-4R mode is unaffected pre-TP1 and the tracker is now conservative).
6. In-process dedup set resets on restart — broker `client_order_id` covers restarts for Alpaca,
   but a non-Alpaca bridge (TradersPost/PickMyTrade) relies on the bridge's own dedup.
7. Live trading remains hard-locked — keep it that way until the readiness checklist
   (`LIVE_TRADING_SAFETY_CHECKLIST.md`) is green end-to-end.

## 27. Recommended Next Work

1. Rotate the Webull credentials; optionally `git filter-repo` the token + logs out of history.
2. Add CI (GitHub Actions): `pytest BOT/tests`, `pip-audit`, and a lint pass on push.
3. Add `signalId` (bar time + side + session) to the AUTO Pine webhook JSON.
4. Wire an economic-calendar source into `news_lockout` and early-closes into the QA calendar.
5. Alpaca trade-updates stream → OMS `on_fill` (replace polling), then restart-recovery test
   against the paper account.
6. Persist the dedup key set (SQLite) so webhook dedup survives restarts even for non-Alpaca routes.
7. Refresh README results with the current default stack and the grade system.

## 28. Final Verification Checklist

- [x] Every project-owned file inventoried; review depth recorded per file (manifest)
- [x] Architecture mapped incl. kill-switch, webhook, reconcile flows (Mermaid above)
- [x] Trading logic, direction engine, ORB/session math verified against code
- [x] Look-ahead/repaint scan: repo-wide, production clean; research targets documented
- [x] Backtest fill/cost assumptions audited (see integrity report)
- [x] Risk gate + sizing formulas verified and regression-tested
- [x] Duplicate-order paths closed (webhook, ticket, broker fills) + tested
- [x] Stale-data gate enforced on the signal path + tested
- [x] Secrets removed from tracking; ignore rules added; rotation flagged
- [x] Performance measured before/after; outputs proven identical
- [x] 45/45 tests pass; module self-tests pass
- [x] No live trade executed; no real credentials used; live lock intact
