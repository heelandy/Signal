# FILE REVIEW MANIFEST — HIGHSTRIKE trading system
Review date: 2026-07-02 · Branch: `claude/trading-bot-review-pq637q` · Reviewer: automated full-repo review

Legend — **Review status**: `DEEP` = read line-by-line; `SCAN` = read for structure + pattern-scanned
(lookahead / negative shift / centered rolling / lookahead_on / secrets); `INVENTORY` = listed,
purpose identified from name/README, not opened line-by-line (research- or docs-only, no live impact);
`EXCLUDED` = out of scope (reason given). Live/BT/Exec = affects live trading / backtesting / order execution.

## 1. Deep-reviewed files (production, execution, data, engine, pipeline, QA, tests, config)

| File | Type | Module | Purpose | Live | BT | Exec | Status | Findings / action |
|---|---|---|---|---|---|---|---|---|
| `BOT/bot/config.py` | py | config | Central .env + credential loading; fail-closed live gate (BOT_MODE=live + LIVE_APPROVED.lock) | Y | N | N | DEEP | OK — live gate fail-closed; verified |
| `BOT/bot/contracts.py` | py | contracts | Canonical dataclasses: TradeCandidate/RiskDecision/OrderRequest/OrderEvent/PositionState + state machines | Y | Y | Y | DEEP | OK — geometry fail-closed, idempotency key deterministic |
| `BOT/bot/risk.py` | py | risk | Risk gate: kill switch, source health, daily loss, trailing DD, trade caps, R:R floor, stop-based sizing + notional cap | Y | Y | Y | DEEP | OK — formula verified: qty=floor(equity*0.25% / (/entry-stop/*pv)); div-by-zero guarded; regression tests added |
| `BOT/bot/live.py` | py | signal engine | Live scan loop: bars -> 4 families -> P(win) -> orderflow -> risk gate -> options plan | Y | N | N | DEEP | FIXED HS-H1: source_healthy was hardcoded True — now market-truth + bar-age gate |
| `BOT/bot/tracker.py` | py | journal | Signal decision + first-touch outcome tracker (SQLite) | Y | N | N | DEEP | FIXED HS-H5/H7/M10: same-bar stop-vs-TP2 now conservative; self-test unpack bug; missing data/ dir crash |
| `BOT/bot/api/server.py` | py | api | FastAPI backend: dashboard APIs, auto-scan thread, paper autotrade, TV webhook, order ticket | Y | N | Y | DEEP | FIXED HS-C2/H3/H6/M2: webhook+ticket idempotency dedup, constant-time token check, auth on control endpoints, stale-guard on paper autotrade |
| `BOT/bot/api/static/dashboard.html` | html | ui | Single-page dashboard (fetch polling of /api/*) | N | N | N | SCAN | Skimmed — read-only UI; no order path beyond POSTs already gated server-side |
| `BOT/bot/brokers/base.py` | py | broker | Abstract broker interface; is_market_open defaults closed (fail-closed) | Y | N | Y | DEEP | OK |
| `BOT/bot/brokers/alpaca_broker.py` | py | broker | Alpaca adapter: paper-first, live refuses without settings.live_allowed; bracket orders; client_order_id idempotency; conn-error-only retry | Y | N | Y | DEEP | OK — live-block verified; NOTE M7: positions() maps unrealized_plpc (a %) into unrealized_r field (label only) |
| `BOT/bot/execution/oms.py` | py | oms | Order state machine, OCO brackets, partial fills, broker reconcile (broker truth wins -> MISMATCH) | Y | N | Y | DEEP | FIXED HS-H2: duplicate-fill events ignored, overfill clamped, qty<=0 rejected |
| `BOT/bot/execution/replay_broker.py` | py | backtest | Deterministic bracket fill sim over bars; stop checked before TP (conservative) | N | Y | N | DEEP | OK — mirrors engine tp2_full; stop-first on same-bar conflicts |
| `BOT/bot/market_data/providers.py` | py | market data | Multi-provider bar router (alpaca/yahoo/webull/tradestation/tradingview/databento) + latest_price | Y | N | N | DEEP | OK w/ notes M3/M5: broad except-> fallback by design; latest_price freshness not timestamped for Yahoo |
| `BOT/bot/market_data/databento_feed.py` | py | market data | Databento historical OHLCV-1m puller -> continuous parquet | N | Y | N | DEEP | OK |
| `BOT/bot/market_data/databento_live.py` | py | market data | Databento Live real-time last-trade snapshot (futures), graceful fallback | Y | N | N | DEEP | OK w/ note M11: new Live session per call (~per scan) — acceptable, documented |
| `BOT/bot/market_data/databento_local.py` | py | market data | DuckDB readers over local OPRA cbbo / XNAS MBO batches; ET pinned in SQL | N | Y | N | DEEP | NOTE M4: SQL built by f-string interpolation (local files, symbol from code/CLI) — low risk, documented |
| `BOT/bot/market_truth.py` | py | data QA | Fail-closed bar validation: dups, out-of-order, gaps, bad OHLC, staleness | Y | Y | N | DEEP | OK — now wired into the live scan via live.source_health (HS-H1) |
| `BOT/bot/market_intel.py` | py | context | SPY/VIX market context (risk-on/off label) | N | N | N | DEEP | OK |
| `BOT/bot/features.py` | py | features | RSI/MACD/ATR/ADX/VWAP/vol feature snapshot (vectorized pandas) | Y | N | N | DEEP | OK — causal (rolling/ewm only) |
| `BOT/bot/journal.py` | py | journal | Append-only JSONL audit journal + metrics | Y | Y | N | DEEP | OK w/ note M5: read() loads whole file per API call — fine at current scale |
| `BOT/bot/store.py` | py | db | SQLite store for candidates/decisions/orders/events/journal | Y | Y | N | DEEP | OK — parameterized SQL, indexes present |
| `BOT/bot/orchestrator.py` | py | orchestration | Mode-gated decision loop: candidate -> risk -> shadow/replay/paper-live submit | Y | Y | Y | DEEP | OK — LIVE raises without readiness lock |
| `BOT/bot/reconcile.py` | py | reconcile | Broker-vs-OMS position poller -> MISMATCH pause | Y | N | Y | DEEP | OK — read-only vs broker |
| `BOT/bot/replay.py` | py | backtest | End-to-end replay with sequential account state + determinism check | N | Y | N | DEEP | OK — daily resets verified |
| `BOT/bot/performance.py` | py | analytics | Attribution, equity curve, drawdown, Sharpe | N | N | N | DEEP | OK |
| `BOT/bot/portfolio.py` | py | risk | Book-level limits: gross, heat, concentration, correlated clusters | Y | N | N | DEEP | OK — veto math verified |
| `BOT/bot/prop.py` | py | risk | Prop-firm eval rules: daily loss, trailing DD, target, consistency, green-day protect | Y | N | N | DEEP | OK |
| `BOT/bot/platform.py` | py | infra | In-process event bus + capability registry | N | N | N | DEEP | OK — bus swallows subscriber exceptions (documented) |
| `BOT/bot/security.py` | py | security | Constant-time token verify + secret redaction + keys status | Y | N | N | DEEP | OK — now actually used by the webhook (HS-H3) |
| `BOT/bot/news_lockout.py` | py | risk | Event blackout windows gate | Y | N | N | DEEP | OK — not yet wired to a calendar feed (documented) |
| `BOT/bot/strategy/families.py` | py | strategy | 4 standing families scan on router bars (breakout validated; meanrev info-only) | Y | N | N | DEEP | OK — per-asset config honored; grades tagged, no hidden filtering |
| `BOT/bot/strategy/orb_candidates.py` | py | strategy | Validated ORB-stack entry -> TradeCandidates via the engine | N | Y | N | DEEP | OK |
| `BOT/bot/strategy/asset_config.py` | py | strategy | Per-asset sessions/stops/entries; GC flagged unverified | Y | Y | N | DEEP | OK |
| `BOT/bot/strategy/extra.py` | py | strategy | UNVALIDATED extras (VWAP-revert, pullback, ETF momentum) — suffixed -UNVALIDATED | N | Y | N | DEEP | OK — clearly gated off |
| `BOT/bot/strategy/regime.py` | py | strategy | Trend-vs-range regime selector | Y | N | N | DEEP | OK |
| `BOT/bot/strategy/opportunity.py` | py | strategy | EV-ranked opportunity queue + exit policy + explainability | Y | N | N | DEEP | OK |
| `BOT/bot/options/pricing.py` | py | options | Black-Scholes + Greeks + IV solve (stdlib); put-call parity self-test | Y | N | N | DEEP | OK — parity/IV verified |
| `BOT/bot/options/strategies.py` | py | options | Naked/debit/credit structure builder from a signal | Y | N | N | DEEP | OK — dead helper _mk noted (LOW) |
| `BOT/bot/options/translate.py` | py | options | Candidate -> options plays bridge (BS or OPRA chain) | Y | N | N | DEEP | OK |
| `BOT/bot/options/exit_plan.py` | py | options | TP1(1.5R)/TP2(4R) exits per structure + recommendation | Y | N | N | DEEP | OK |
| `BOT/bot/ml/predictor.py` | py | ml | Numpy logistic-regression baseline (advisory only) | N | N | N | DEEP | OK |
| `BOT/bot/ml/pipeline.py` | py | ml | Train/promote champion + predict P(win) (prior 0.42 fallback); AUC>0.52 deploy guard | Y | N | N | DEEP | OK |
| `BOT/bot/ml/registry.py` | py | ml | Model registry (pickle, local), champion-challenger | N | N | N | DEEP | NOTE M12: pickle load of local model files — local-only, documented |
| `BOT/bot/ml/validation.py` | py | ml | Walk-forward, AUC, PSR/Deflated Sharpe | N | Y | N | DEEP | OK |
| `BOT/bot/orderflow/features.py` | py | orderflow | MBO L3 book reconstruction: QI/microprice; trade-print ATI/cum-delta | N | Y | N | DEEP | OK — B=buy-aggressor calibration documented |
| `BOT/bot/orderflow/deep.py` | py | orderflow | Event OFI/ACI/MLOFI/micro velocity + sweep detector | N | Y | N | DEEP | OK — shift(-1) only in __main__ IC diagnostic |
| `BOT/bot/orderflow/score.py` | py | orderflow | 0-100 direction score + ARMED->ENTER state machine w/ persistence + early-failure | Y | N | N | DEEP | OK — symmetric, hysteresis via persist |
| `BOT/bot/orderflow/confirm.py` | py | orderflow | Order-flow confirm/diverge read for a signal (advisory) | Y | N | N | DEEP | OK |
| `BOT/bot/orderflow/run_symbol.py` | py | orderflow | CLI runner for any symbol/date MBO batch | N | N | N | DEEP | OK |
| `BOT/tests/test_bot.py` | py | tests | Fast unit suite (contracts/risk/truth/journal/oms/portfolio/ml) | N | N | N | DEEP | OK — 21 tests pass |
| `BOT/tests/test_review_fixes.py` | py | tests | NEW (this review): dup-order, stale-gate, OMS guards, tracker walk, direction-state math, pivots equivalence, live-lock | N | N | N | DEEP | ADDED — 24 tests |
| `engine/hs_harness.py` | py | engine | V44 state port: indicators, pivots, HH/HL st_state machine, OB/FVG/sweep, macro regime, scoring | Y | Y | N | DEEP | OPTIMIZED (identical outputs): vectorized pivots fast path, numpy _macro_regime loop, precomputed rolling extremes; verified column-identical vs old on 3 seeds |
| `engine/hs_backtest.py` | py | engine | ORB signal generator + event-driven backtest with costs/slippage; gap-aware stop fills | N | Y | N | DEEP | OK — causal (signals fire only after OR closes); same-bar TP1+TP2 optimism documented in BACKTEST_INTEGRITY_REPORT |
| `engine/hs_db.py` | py | engine | DuckDB views over partitioned parquet bars | N | Y | N | DEEP | OK — parameterized reads; CLI ad-hoc SQL is local-only |
| `engine/hs_validate.py` | py | engine | Validation stats: bootstrap CI, PF, regime windows, slippage stress | N | Y | N | DEEP | OK |
| `engine/README.md` | md | docs | Engine docs | N | N | N | DEEP | Read |
| `pipeline/hs_build_continuous.py` | py | pipeline | Futures continuity: outrights only, volume-crossover roll, ratio back-adjust, session tag | N | Y | N | DEEP | OK — roll keyed on instrument_id (symbol collisions handled) |
| `pipeline/hs_resample.py` | py | pipeline | 1m -> 5m/15m/.../1d hive-partitioned bars; ET-anchored bins | N | Y | N | DEEP | OK — label=left/closed=left, CME trade-day daily |
| `pipeline/hs_build_vix.py` | py | pipeline | Spot VIX + VX-futures stitched daily series (seam documented) | N | Y | N | DEEP | OK — seam/source column explicit |
| `pipeline/hs_ingest_equity.py` | py | pipeline | Equity OHLCV-1m CSV -> continuous parquet | N | Y | N | DEEP | OK |
| `pipeline/hs_recon_contracts.py` | py | pipeline | Contract inventory recon for roll design | N | N | N | DEEP | OK |
| `pipeline/README.md` | md | docs | Pipeline docs | N | N | N | DEEP | Read |
| `qa/hs_qa.py` | py | qa | Holiday-aware coverage, gap scan, dup/OHLC checks on every data drop | N | Y | N | DEEP | OK — halts/weekends classified; no early-close calendar (documented) |
| `qa/hs_qa_data.py` | py | qa | Streaming QA of raw 1m CSV | N | Y | N | DEEP | OK |
| `qa/hs_reconcile.py` | py | qa | Python-vs-Pine per-bar state diff from TV export | N | N | N | DEEP | OK |
| `qa/pivot_check.py` | py | qa | Offline pivot tie-rule equivalence check | N | N | N | DEEP | OK |
| `qa/README.md` | md | docs | QA docs | N | N | N | DEEP | Read |
| `production/HIGHSTRIKE_ORB_STACK.pine` | pine | pine | PRIMARY production indicator: 3-session ORB stack, structure gate, grades, eval guardrails, dashboard | Y | N | N | DEEP | FIXED HS-H4b: close-confirm signals now latch only on confirmed bars (live==backtest); request.security all lookahead_off |
| `production/HIGHSTRIKE_ORB_AUTO.pine` | pine | pine | Webhook automation strategy twin (TradersPost/PickMyTrade/Generic JSON) | Y | N | Y | DEEP | FIXED HS-H4: close-confirm entries gated on barstate.isconfirmed (calc_on_every_tick made them fire intrabar); NOTE: alert payload lacks a unique signal id — server-side dedup added instead |
| `production/HIGHSTRIKE_ORB_V1_STRATEGY.pine` | pine | pine | V1 resting-stop ORB strategy (superseded by STACK/AUTO) | N | Y | N | SCAN | Reviewed (full read of gates/fills header + scan): lookahead_off everywhere, no calc_on_every_tick |
| `production/HIGHSTRIKE_ORB_V1_INDICATOR.pine` | pine | pine | V1 indicator twin | N | N | N | SCAN | Reviewed (scan + structure): lookahead_off; display layer |
| `production/HIGHSTRIKE_ORB_OPTIONS.pine` | pine | pine | Options overlay (BS cost estimate) for the ORB signal | N | N | N | SCAN | Reviewed (scan): lookahead_off; display only |
| `production/HIGHSTRIKE_ORB_MTF_SIGNALS.pine` | pine | pine | 5m+15m breakout marks via request.security | N | N | N | SCAN | Reviewed: lookahead_off; display only |
| `production/README.md` | md | docs | Production Pine docs | N | N | N | DEEP | Read |
| `production/CHANGELOG.md` | md | docs | Pine changelog | N | N | N | DEEP | Read |
| `validatedResearch/HIGHSTRIKE_ORB_ASIA.pine` | pine | pine | Asia-session ORB (merged into STACK) | N | N | N | SCAN | Reviewed (scan): lookahead_off; superseded |
| `validatedResearch/HIGHSTRIKE_ORB_STRUCTURE.pine` | pine | pine | Structure-gate ORB (merged into STACK) | N | N | N | SCAN | Reviewed (scan): lookahead_off; superseded |
| `validatedResearch/README.md` | md | docs | Folder docs | N | N | N | DEEP | Read |
| `README.md` | md | docs | Project overview + validated results + deploy-from-scratch | N | N | N | DEEP | Read |
| `requirements.txt` | txt | config | Python deps | N | N | N | DEEP | Read |
| `.gitignore` | gitignore | config | Ignore rules | N | N | N | DEEP | UPDATED: logs, token caches, server.pid now ignored |
| `.claude/settings.json` | json | config | Local tool permissions (was tracked despite .claude/ ignore) | N | N | N | DEEP | UNTRACKED (matches existing ignore intent) |
| `docs/AUTOMATION_SETUP.md` | md | docs | Webhook automation setup guide | N | N | N | DEEP | Read |
| `BOT/config/.env.example` | example | config | Credential template (placeholders only — no real keys) | Y | N | N | DEEP | OK — verified placeholders only |
| `BOT/run.ps1` | ps1 | ops | Foreground launcher | N | N | N | DEEP | OK |
| `BOT/start.ps1` | ps1 | ops | Detached launcher (defaults BOT_MODE=paper for the study loop) | Y | N | N | DEEP | OK — live still gate-locked in code |
| `BOT/stop.ps1` | ps1 | ops | Stop script | N | N | N | DEEP | OK |
| `BOT/conf/token.txt` | txt | SECRET | Webull SDK token cache — WAS COMMITTED | Y | N | N | DEEP | CRITICAL HS-C1: untracked + ignored; ROTATE the Webull token (it remains in git history) |
| `BOT/bot/__init__.py` | py | package | Package init (docstring only) | N | N | N | DEEP | OK |
| `BOT/bot/api/__init__.py` | py | package | Package init (docstring only) | N | N | N | DEEP | OK |
| `BOT/bot/brokers/__init__.py` | py | package | Package init (docstring only) | N | N | N | DEEP | OK |
| `BOT/bot/execution/__init__.py` | py | package | Package init (docstring only) | N | N | N | DEEP | OK |
| `BOT/bot/market_data/__init__.py` | py | package | Package init (docstring only) | N | N | N | DEEP | OK |
| `BOT/bot/ml/__init__.py` | py | package | Package init (docstring only) | N | N | N | DEEP | OK |
| `BOT/bot/options/__init__.py` | py | package | Package init (docstring only) | N | N | N | DEEP | OK |
| `BOT/bot/orderflow/__init__.py` | py | package | Package init (docstring only) | N | N | N | DEEP | OK |
| `BOT/bot/strategy/__init__.py` | py | package | Package init (docstring only) | N | N | N | DEEP | OK |

## 2. Research scripts (`research/`, 96 files) — research-only, no live-trading or execution path

Every file was pattern-scanned for look-ahead constructs (negative `shift`, `rolling(center=True)`,
forward `merge_asof`, backfill, `lookahead_on`). Hits found only in explicit **label/target
construction** for research evaluation (legitimate): `strat_orderflow_book.py` (fwd returns as
targets), `orb_obi_book.py` (forward mid deltas as targets), `strat_ml.py` (`ret_fwd` target),
`orb_lead_lag.py` (lead-lag alignment). None of these feed a live signal path — the live bot only
imports `engine/hs_harness.py` + `engine/hs_backtest.py`, which are DEEP-reviewed and causal.
`RESEARCH_NOTES.md` (1,403 lines) read for the finding-number (F-xx) provenance used across the code.

| File | Status | Note |
|---|---|---|
| `research/HIGHSTRIKE_ORB_MTF_ENTRIES.pine` | SCAN | Pine research script — pattern-scanned (safe [1]+lookahead_on idiom in V44 only) |
| `research/HIGHSTRIKE_V44_STRATEGY.pine` | SCAN | Pine research script — pattern-scanned (safe [1]+lookahead_on idiom in V44 only) |
| `research/RESEARCH_NOTES.md` | SCAN | Research notes — READ |
| `research/_verify_f45.py` | INVENTORY+SCAN | Research backtest/sweep — INVENTORY + pattern scan |
| `research/hs_recon_export.pine` | SCAN | Pine research script — pattern-scanned (safe [1]+lookahead_on idiom in V44 only) |
| `research/ict_cluster.py` | INVENTORY+SCAN | Research backtest/sweep — INVENTORY + pattern scan |
| `research/multi_strategy_book.py` | INVENTORY+SCAN | Research backtest/sweep — INVENTORY + pattern scan |
| `research/multi_strategy_full.py` | INVENTORY+SCAN | Research backtest/sweep — INVENTORY + pattern scan |
| `research/orb_1m.py` | INVENTORY+SCAN | Research backtest/sweep — INVENTORY + pattern scan |
| `research/orb_1m_robust.py` | INVENTORY+SCAN | Research backtest/sweep — INVENTORY + pattern scan |
| `research/orb_arm_timing.py` | INVENTORY+SCAN | Research backtest/sweep — INVENTORY + pattern scan |
| `research/orb_asia.py` | INVENTORY+SCAN | Research backtest/sweep — INVENTORY + pattern scan |
| `research/orb_asia_walkforward.py` | INVENTORY+SCAN | Research backtest/sweep — INVENTORY + pattern scan |
| `research/orb_cap_lateness.py` | INVENTORY+SCAN | Research backtest/sweep — INVENTORY + pattern scan |
| `research/orb_cap_walkforward.py` | INVENTORY+SCAN | Research backtest/sweep — INVENTORY + pattern scan |
| `research/orb_cleanday.py` | INVENTORY+SCAN | Research backtest/sweep — INVENTORY + pattern scan |
| `research/orb_config_validate.py` | INVENTORY+SCAN | Research backtest/sweep — INVENTORY + pattern scan |
| `research/orb_confirm_entry.py` | INVENTORY+SCAN | Research backtest/sweep — INVENTORY + pattern scan |
| `research/orb_dir_seq.py` | INVENTORY+SCAN | Research backtest/sweep — INVENTORY + pattern scan |
| `research/orb_dir_state.py` | INVENTORY+SCAN | Research backtest/sweep — INVENTORY + pattern scan |
| `research/orb_dirstate2.py` | INVENTORY+SCAN | Research backtest/sweep — INVENTORY + pattern scan |
| `research/orb_efficiency.py` | INVENTORY+SCAN | Research backtest/sweep — INVENTORY + pattern scan |
| `research/orb_entry_quality.py` | INVENTORY+SCAN | Research backtest/sweep — INVENTORY + pattern scan |
| `research/orb_eval_cap.py` | INVENTORY+SCAN | Research backtest/sweep — INVENTORY + pattern scan |
| `research/orb_exit_levers.py` | INVENTORY+SCAN | Research backtest/sweep — INVENTORY + pattern scan |
| `research/orb_exit_mgmt.py` | INVENTORY+SCAN | Research backtest/sweep — INVENTORY + pattern scan |
| `research/orb_exit_walkforward.py` | INVENTORY+SCAN | Research backtest/sweep — INVENTORY + pattern scan |
| `research/orb_exits.py` | INVENTORY+SCAN | Research backtest/sweep — INVENTORY + pattern scan |
| `research/orb_f33_debug.py` | INVENTORY+SCAN | Research backtest/sweep — INVENTORY + pattern scan |
| `research/orb_false_breakout.py` | INVENTORY+SCAN | Research backtest/sweep — INVENTORY + pattern scan |
| `research/orb_fast_direction.py` | INVENTORY+SCAN | Research backtest/sweep — INVENTORY + pattern scan |
| `research/orb_fb_variations.py` | INVENTORY+SCAN | Research backtest/sweep — INVENTORY + pattern scan |
| `research/orb_fillmode.py` | INVENTORY+SCAN | Research backtest/sweep — INVENTORY + pattern scan |
| `research/orb_final_gauntlet.py` | INVENTORY+SCAN | Research backtest/sweep — INVENTORY + pattern scan |
| `research/orb_flow_channels.py` | INVENTORY+SCAN | Research backtest/sweep — INVENTORY + pattern scan |
| `research/orb_gold.py` | INVENTORY+SCAN | Research backtest/sweep — INVENTORY + pattern scan |
| `research/orb_gold_walkforward.py` | INVENTORY+SCAN | Research backtest/sweep — INVENTORY + pattern scan |
| `research/orb_hhhl_vwapcap.py` | INVENTORY+SCAN | Research backtest/sweep — INVENTORY + pattern scan |
| `research/orb_hhhl_walkforward.py` | INVENTORY+SCAN | Research backtest/sweep — INVENTORY + pattern scan |
| `research/orb_honest_levers.py` | INVENTORY+SCAN | Research backtest/sweep — INVENTORY + pattern scan |
| `research/orb_honest_revalidation.py` | INVENTORY+SCAN | Research backtest/sweep — INVENTORY + pattern scan |
| `research/orb_kernel_filter.py` | INVENTORY+SCAN | Research backtest/sweep — INVENTORY + pattern scan |
| `research/orb_kernel_signal.py` | INVENTORY+SCAN | Research backtest/sweep — INVENTORY + pattern scan |
| `research/orb_lead_lag.py` | INVENTORY+SCAN | Research backtest/sweep — INVENTORY + pattern scan |
| `research/orb_levers.py` | INVENTORY+SCAN | Research backtest/sweep — INVENTORY + pattern scan |
| `research/orb_london.py` | INVENTORY+SCAN | Research backtest/sweep — INVENTORY + pattern scan |
| `research/orb_london_walkforward.py` | INVENTORY+SCAN | Research backtest/sweep — INVENTORY + pattern scan |
| `research/orb_mid_bias.py` | INVENTORY+SCAN | Research backtest/sweep — INVENTORY + pattern scan |
| `research/orb_momentum_filter.py` | INVENTORY+SCAN | Research backtest/sweep — INVENTORY + pattern scan |
| `research/orb_mtf_research.py` | INVENTORY+SCAN | Research backtest/sweep — INVENTORY + pattern scan |
| `research/orb_ob_robust.py` | INVENTORY+SCAN | Research backtest/sweep — INVENTORY + pattern scan |
| `research/orb_obi_book.py` | INVENTORY+SCAN | Research backtest/sweep — INVENTORY + pattern scan |
| `research/orb_optimize.py` | INVENTORY+SCAN | Research backtest/sweep — INVENTORY + pattern scan |
| `research/orb_per_tf.py` | INVENTORY+SCAN | Research backtest/sweep — INVENTORY + pattern scan |
| `research/orb_pivot_impact.py` | INVENTORY+SCAN | Research backtest/sweep — INVENTORY + pattern scan |
| `research/orb_predict.py` | INVENTORY+SCAN | Research backtest/sweep — INVENTORY + pattern scan |
| `research/orb_projection_test.py` | INVENTORY+SCAN | Research backtest/sweep — INVENTORY + pattern scan |
| `research/orb_prop_eval.py` | INVENTORY+SCAN | Research backtest/sweep — INVENTORY + pattern scan |
| `research/orb_prop_eval_b.py` | INVENTORY+SCAN | Research backtest/sweep — INVENTORY + pattern scan |
| `research/orb_prop_eval_mixed.py` | INVENTORY+SCAN | Research backtest/sweep — INVENTORY + pattern scan |
| `research/orb_prop_eval_throttle.py` | INVENTORY+SCAN | Research backtest/sweep — INVENTORY + pattern scan |
| `research/orb_range_block.py` | INVENTORY+SCAN | Research backtest/sweep — INVENTORY + pattern scan |
| `research/orb_range_eval.py` | INVENTORY+SCAN | Research backtest/sweep — INVENTORY + pattern scan |
| `research/orb_regimeb_entries.py` | INVENTORY+SCAN | Research backtest/sweep — INVENTORY + pattern scan |
| `research/orb_regimeb_oos.py` | INVENTORY+SCAN | Research backtest/sweep — INVENTORY + pattern scan |
| `research/orb_session_tod.py` | INVENTORY+SCAN | Research backtest/sweep — INVENTORY + pattern scan |
| `research/orb_sessions.py` | INVENTORY+SCAN | Research backtest/sweep — INVENTORY + pattern scan |
| `research/orb_stack_amt.py` | INVENTORY+SCAN | Research backtest/sweep — INVENTORY + pattern scan |
| `research/orb_stack_combined.py` | INVENTORY+SCAN | Research backtest/sweep — INVENTORY + pattern scan |
| `research/orb_stack_features.py` | INVENTORY+SCAN | Research backtest/sweep — INVENTORY + pattern scan |
| `research/orb_stack_features2.py` | INVENTORY+SCAN | Research backtest/sweep — INVENTORY + pattern scan |
| `research/orb_stack_liquidity.py` | INVENTORY+SCAN | Research backtest/sweep — INVENTORY + pattern scan |
| `research/orb_stack_orderflow.py` | INVENTORY+SCAN | Research backtest/sweep — INVENTORY + pattern scan |
| `research/orb_stack_smc.py` | INVENTORY+SCAN | Research backtest/sweep — INVENTORY + pattern scan |
| `research/orb_stack_squeeze.py` | INVENTORY+SCAN | Research backtest/sweep — INVENTORY + pattern scan |
| `research/orb_stack_stat.py` | INVENTORY+SCAN | Research backtest/sweep — INVENTORY + pattern scan |
| `research/orb_stack_tod.py` | INVENTORY+SCAN | Research backtest/sweep — INVENTORY + pattern scan |
| `research/orb_stack_walkforward.py` | INVENTORY+SCAN | Research backtest/sweep — INVENTORY + pattern scan |
| `research/orb_stop_floor.py` | INVENTORY+SCAN | Research backtest/sweep — INVENTORY + pattern scan |
| `research/orb_stop_walkforward.py` | INVENTORY+SCAN | Research backtest/sweep — INVENTORY + pattern scan |
| `research/orb_struct_robust.py` | INVENTORY+SCAN | Research backtest/sweep — INVENTORY + pattern scan |
| `research/orb_structure_opt.py` | INVENTORY+SCAN | Research backtest/sweep — INVENTORY + pattern scan |
| `research/orb_tp2.py` | INVENTORY+SCAN | Research backtest/sweep — INVENTORY + pattern scan |
| `research/orb_validation.py` | INVENTORY+SCAN | Research backtest/sweep — INVENTORY + pattern scan |
| `research/orb_vwap_cap.py` | INVENTORY+SCAN | Research backtest/sweep — INVENTORY + pattern scan |
| `research/orb_xinstrument.py` | INVENTORY+SCAN | Research backtest/sweep — INVENTORY + pattern scan |
| `research/smc_additivity.py` | INVENTORY+SCAN | Research backtest/sweep — INVENTORY + pattern scan |
| `research/smc_cluster.py` | INVENTORY+SCAN | Research backtest/sweep — INVENTORY + pattern scan |
| `research/strat_daily.py` | INVENTORY+SCAN | Research backtest/sweep — INVENTORY + pattern scan |
| `research/strat_four_families.py` | INVENTORY+SCAN | Research backtest/sweep — INVENTORY + pattern scan |
| `research/strat_ml.py` | INVENTORY+SCAN | Research backtest/sweep — INVENTORY + pattern scan |
| `research/strat_orderflow_book.py` | INVENTORY+SCAN | Research backtest/sweep — INVENTORY + pattern scan |
| `research/strat_rangefade.py` | INVENTORY+SCAN | Research backtest/sweep — INVENTORY + pattern scan |
| `research/strat_volbreak_test.py` | INVENTORY+SCAN | Research backtest/sweep — INVENTORY + pattern scan |
| `research/verify_mtf_entries.py` | INVENTORY+SCAN | Research backtest/sweep — INVENTORY + pattern scan |
| `research/wyckoff.py` | INVENTORY+SCAN | Research backtest/sweep — INVENTORY + pattern scan |

## 3. BOT documentation pack (`BOT/*.md` + assets, 122 files) — design documents, no code

Read for architecture intent: BUILD_PLAN.md, FULL_AUDIT.md, Botreview, EVIDENCE_GAPS.md,
README-level docs. The remaining spec documents (ADR/API/DBS/ML-xxx…) are prior-generation design
prose with no executable content; inventoried, spot-checked, not line-audited.

| File | Status |
|---|---|
| `BOT/ACS-001_Asset_Class_Specification_Handbook.md` | INVENTORY |
| `BOT/ADM-001_Administrator_Guide.md` | INVENTORY |
| `BOT/ADR-001_Master_Architecture_Decision_Records.md` | INVENTORY |
| `BOT/AME-001_Account_Management_Engine.md` | INVENTORY |
| `BOT/API-001_API_Architecture_Service_Contracts.md` | INVENTORY |
| `BOT/APIREF-001_API_Endpoint_Reference.md` | INVENTORY |
| `BOT/ARL-001_AI_Research_Lab.md` | INVENTORY |
| `BOT/ATP-001_Acceptance_Test_Plan.md` | INVENTORY |
| `BOT/BF-001_Broker_Framework.md` | INVENTORY |
| `BOT/BIH-001_Broker_Integration_Handbook.md` | INVENTORY |
| `BOT/BRD-001_Business_Requirements_Document.md` | INVENTORY |
| `BOT/BRDR-001_Backup_Restore_Disaster_Recovery_Handbook.md` | INVENTORY |
| `BOT/BUILD_PLAN.md` | SCAN |
| `BOT/CAP-001_Capacity_Planning_Guide.md` | INVENTORY |
| `BOT/CFG-001_Configuration_Environment_Reference.md` | INVENTORY |
| `BOT/CICD-001_CI_CD_Pipeline_Release_Management.md` | INVENTORY |
| `BOT/CPE-001_Capital_Preservation_Engine.md` | INVENTORY |
| `BOT/ChatGPT Image Jun 25, 2026, 05_25_55 PM.png` | INVENTORY |
| `BOT/DBA-001_Database_Architecture.md` | INVENTORY |
| `BOT/DBS-001_Database_Schema_Reference.md` | INVENTORY |
| `BOT/DIA-001_Deployment_Infrastructure_Architecture.md` | INVENTORY |
| `BOT/DIE-001_Decision_Intelligence_Explainability_Engine.md` | INVENTORY |
| `BOT/DLK-001_Data_Lake_Knowledge_Platform.md` | INVENTORY |
| `BOT/DRP-001_Master_Disaster_Recovery_Business_Continuity.md` | INVENTORY |
| `BOT/EC-001_Execution_Core.md` | INVENTORY |
| `BOT/EIE-001_Entry_Intelligence_Engine.md` | INVENTORY |
| `BOT/ENG-001_Logging_Observability_Standard.md` | INVENTORY |
| `BOT/ENG-002_Error_Code_Catalog.md` | INVENTORY |
| `BOT/ENG-003_State_Machine_Catalog.md` | INVENTORY |
| `BOT/ENG-004_Sequence_Diagram_Catalog.md` | INVENTORY |
| `BOT/ENG-005_UML_Component_Catalog.md` | INVENTORY |
| `BOT/ENG-006_Data_Dictionary.md` | INVENTORY |
| `BOT/ENG-007_Configuration_Templates.md` | INVENTORY |
| `BOT/ESV-001_Executive_Summary_Product_Vision.md` | INVENTORY |
| `BOT/EVIDENCE_GAPS.md` | SCAN |
| `BOT/EVIDENCE_TRACEABILITY.md` | SCAN |
| `BOT/EVT-001_Event_Catalog_Message_Bus_Specification.md` | INVENTORY |
| `BOT/Evidence.docx` | INVENTORY |
| `BOT/Evidence_extracted.txt` | INVENTORY |
| `BOT/FAQ-001_FAQ_Best_Practices_Guide.md` | INVENTORY |
| `BOT/FCH-001_Futures_Contract_Handbook.md` | INVENTORY |
| `BOT/FDI-002_Final_Documentation_Index_v2.md` | INVENTORY |
| `BOT/FEATURES_AND_ENGINES.md` | INVENTORY |
| `BOT/FEE-001_Feature_Engineering_Engine.md` | INVENTORY |
| `BOT/FEF-001_Future_Expansion_Innovation_Framework.md` | INVENTORY |
| `BOT/FIE-001_Futures_Intelligence_Engine.md` | INVENTORY |
| `BOT/FRONTEND_PLAN.md` | INVENTORY |
| `BOT/FSD-001_Functional_Specification_Document.md` | INVENTORY |
| `BOT/FULL_AUDIT.md` | SCAN |
| `BOT/GLO-001_Glossary_Terminology_Reference.md` | INVENTORY |
| `BOT/GMI-001_Global_Market_Intelligence_Engine.md` | INVENTORY |
| `BOT/IMPLEMENTATION_STATUS.md` | INVENTORY |
| `BOT/INS-001_Installation_Guide.md` | INVENTORY |
| `BOT/IPG-001_Infrastructure_Provisioning_Guide.md` | INVENTORY |
| `BOT/MAB-001_Master_Architecture_Book.md` | INVENTORY |
| `BOT/MAP-001_Master_API_Book.md` | INVENTORY |
| `BOT/MDB-001_Master_Database_Book.md` | INVENTORY |
| `BOT/MDE-001_Market_Data_Engine.md` | INVENTORY |
| `BOT/MDEV-001_Master_Developer_Book.md` | INVENTORY |
| `BOT/MDG-001_Monitoring_Dashboard_Guide.md` | INVENTORY |
| `BOT/MDH-001_Master_Developer_Handbook.md` | INVENTORY |
| `BOT/MDS-001_Master_Development_Standards_Engineering_Guidelines.md` | INVENTORY |
| `BOT/MEI-001_Market_Entity_Intelligence_Engine.md` | INVENTORY |
| `BOT/META-001_Complete_Project_Metadata_File.md` | INVENTORY |
| `BOT/MIB-001_Master_Implementation_Book.md` | INVENTORY |
| `BOT/MIE-001_Market_Intelligence_Engine.md` | INVENTORY |
| `BOT/MIR-001_Master_Implementation_Roadmap.md` | INVENTORY |
| `BOT/ML-001_Feature_Store_Dictionary.md` | INVENTORY |
| `BOT/ML-002_Dataset_Specification.md` | INVENTORY |
| `BOT/ML-003_Model_Registry_Specification.md` | INVENTORY |
| `BOT/ML-004_Champion_Challenger_Framework.md` | INVENTORY |
| `BOT/ML-005_ML_Validation_Handbook.md` | INVENTORY |
| `BOT/ML-006_Continuous_Learning_Handbook.md` | INVENTORY |
| `BOT/ML-007_LLM_Integration_Architecture.md` | INVENTORY |
| `BOT/ML-008_Multi_Agent_AI_Framework.md` | INVENTORY |
| `BOT/MLP-001_Machine_Learning_Platform.md` | INVENTORY |
| `BOT/MMR-001_Master_Module_Registry_Dependency_Graph.md` | INVENTORY |
| `BOT/MOP-001_Master_Operations_Book.md` | INVENTORY |
| `BOT/MOQ-001_Market_Opportunity_Queue.md` | INVENTORY |
| `BOT/MOR-001_Master_Operations_Runbook.md` | INVENTORY |
| `BOT/MPI-001_Master_Project_Index_Documentation_Catalog.md` | INVENTORY |
| `BOT/MRS-001_Master_Requirements_Specification.md` | INVENTORY |
| `BOT/MSA-001_Master_System_Architecture.md` | INVENTORY |
| `BOT/MTA-001_Market_Truth_Algorithms_Handbook.md` | INVENTORY |
| `BOT/MTE-001_Market_Truth_Engine.md` | INVENTORY |
| `BOT/MUM-001_Master_User_Operations_Manual.md` | INVENTORY |
| `BOT/MUSR-001_Master_User_Book.md` | INVENTORY |
| `BOT/NET-001_Networking_Architecture_Guide.md` | INVENTORY |
| `BOT/NFR-001_Non_Functional_Requirements_Specification.md` | INVENTORY |
| `BOT/NIH-001_News_Intelligence_Handbook.md` | INVENTORY |
| `BOT/NRE-001_News_Reaction_Engine.md` | INVENTORY |
| `BOT/OMP-001_Observability_Monitoring_Incident_Response_Platform.md` | INVENTORY |
| `BOT/OMS-001_Order_Manager_Position_Synchronization_Engine.md` | INVENTORY |
| `BOT/ORM-001_Opening_Range_Matrix_Engine.md` | INVENTORY |
| `BOT/PFI-001_Performance_Intelligence_Engine.md` | INVENTORY |
| `BOT/PFR-001_Prop_Firm_Rule_Library.md` | INVENTORY |
| `BOT/PIE-001_Portfolio_Intelligence_Engine.md` | INVENTORY |
| `BOT/PLE-001_Performance_Learning_Engine.md` | INVENTORY |
| `BOT/PME-001_Position_Management_Engine.md` | INVENTORY |
| `BOT/PRC-001_Production_Readiness_Checklist.md` | INVENTORY |
| `BOT/PTG-001_Performance_Tuning_Guide.md` | INVENTORY |
| `BOT/PVH-001_Paper_Trading_Validation_Handbook.md` | INVENTORY |
| `BOT/RCR-001_Rules_Configuration_Capability_Registry.md` | INVENTORY |
| `BOT/RE-001_Risk_Engine.md` | INVENTORY |
| `BOT/REMAINING.md` | INVENTORY |
| `BOT/REMAINING_FEATURES.md` | INVENTORY |
| `BOT/RLC-001_Release_Checklist.md` | INVENTORY |
| `BOT/RPF-001_Retail_Platform_User_Experience_Framework.md` | INVENTORY |
| `BOT/RRL-001_Risk_Rule_Library.md` | INVENTORY |
| `BOT/RSK-001_Risk_Register_Project_Assumptions.md` | INVENTORY |
| `BOT/RTG-001_Regression_Testing_Guide.md` | INVENTORY |
| `BOT/RVH-001_Replay_Validation_Handbook.md` | INVENTORY |
| `BOT/SDE-001_Strategy_Decision_Engine.md` | INVENTORY |
| `BOT/SDNA-001_Security_DNA_Handbook.md` | INVENTORY |
| `BOT/SEC-001_Security_Identity_Access_Management_Framework.md` | INVENTORY |
| `BOT/TKB-001_Trading_Knowledge_Brain.md` | INVENTORY |
| `BOT/TLJ-001_Trade_Lifecycle_Journal_Engine.md` | INVENTORY |
| `BOT/TOS-001_Trading_OS_Core.md` | INVENTORY |
| `BOT/TSG-001_Troubleshooting_Guide.md` | INVENTORY |
| `BOT/TSL-001_Trading_Strategy_Library.md` | INVENTORY |
| `BOT/TST-001_Test_Case_Catalog.md` | INVENTORY |
| `BOT/TVQ-001_Testing_Validation_QA_Framework.md` | INVENTORY |
| `BOT/UPG-001_Upgrade_Guide.md` | INVENTORY |
| `BOT/XIE-001_Exit_Intelligence_Engine.md` | INVENTORY |
| `BOT/config/dashboard.png` | INVENTORY |
| `BOT/example.txt` | SCAN |
| `BOT/trading_bot_architecture.md` | INVENTORY |
| `BOT/Botreview` | SCAN |

## 4. Excluded / removed from tracking

| Path | Reason |
|---|---|
| `notUse/` (22 files) | Explicitly parked by the author (`_WHATS_HERE.md`); not part of the system. Pattern-scanned for secrets only — none found. |
| `BOT/conf/token.txt` | **Committed live Webull token — UNTRACKED this review; rotate it** (still in git history). |
| `BOT/webull_data_sdk.log*` (11), `BOT/config/*.log*`, `server.pid`, 6× `debug.log` | Runtime logs/PIDs — untracked + gitignored this review (no key values found inside, only request metadata). |
| `.claude/settings.json` | Local tool config — untracked (matches the repo's own `.claude/` ignore rule). |
| `data/`, `*.csv`, `*.zst`, `.venv` | Already git-ignored (rebuildable market data, envs). Not present in this checkout. |


## 5. Totals

* Total project-owned tracked files (pre-review): **339** (+ this review adds docs/tests)
* Deep-reviewed line-by-line: **~75** (all of `BOT/bot`, `BOT/tests`, `engine`, `pipeline`, `qa`, production Pine STACK+AUTO, config, ops scripts)
* Scanned (structure + look-ahead/secret pattern scan): **~15** (remaining Pine, key docs, dashboard.html)
* Inventoried + pattern-scanned only: **~225** (96 research scripts, 122 BOT design docs)
* Excluded: **22** (`notUse/`) + 24 untracked secret/log files
* Files that could not be opened: **0**
* Files requiring further manual review: research scripts if any is ever promoted to live use; `BOT/*.md` spec pack (docs only)
