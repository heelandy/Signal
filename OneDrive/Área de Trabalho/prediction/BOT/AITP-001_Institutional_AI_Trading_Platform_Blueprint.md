# AITP-001 - Institutional AI Trading Platform Blueprint

**Status:** Draft architecture  
**Scope:** Trading-only platform for equities, futures, and options  
**Current posture:** Research, backtest, replay, and approval workflow only  
**Live trading:** Explicitly out of scope until future manual approval after paper validation

## 1. Purpose

This document defines the target architecture for an institutional-grade AI trading platform focused only on:

- Equities
- Futures
  - NQ
  - MNQ
  - GC
  - ES
- Options

The platform must not live trade immediately. The first production goal is a controlled research-to-paper pipeline where every strategy is reviewed, backtested, risk-approved, and manually approved before any paper order can be sent.

The AI layer is advisory. It must never replace the rule engine.

Core principle:

```text
Rules decide whether a trade is eligible.
Machine learning scores setup quality.
Neural networks recognize historical pattern similarity.
Risk management grants or blocks permission.
Execution acts only after every required approval is present.
```

## 2. Non-Negotiable Trading Gates

No strategy may paper trade until all of these are complete:

1. Historical data has been reviewed and validated.
2. Backtesting has been completed.
3. Strategy sustainability has been proven.
4. Profitability has been evaluated.
5. Risk management rules have been approved.
6. The user manually approves the strategy for paper trading.

No strategy may move beyond paper trading without a separate manual approval.

The approval workflow must be enforceable in code and visible in the dashboard.

## 3. Operating Modes

The platform has five modes:

| Mode | Purpose | Orders allowed |
|---|---|---|
| Research | Explore rules, features, and labels | No |
| Backtest | Historical event simulation | No broker orders |
| Replay | Historical bars through production pipeline | Simulated only |
| Paper | Broker paper account only | Yes, if manually approved |
| Live | Future mode only | Disabled until separate approval |

The initial implementation must keep live trading locked.

Paper mode requires:

- Strategy status: `paper_approved`
- Asset class status: `paper_enabled`
- Risk profile status: `approved`
- Data source status: `healthy`
- User approval record: present
- Kill switch: off
- Broker: paper account only

## 4. Asset Class Structure

The platform must separate strategies by asset class and trading style.

### 4.1 Equities

Supported styles:

- Scalping
- Day trading
- Options-linked equity signals
- Swing trading

Primary examples:

- SPY
- QQQ
- IWM
- DIA
- NVDA
- TSLA
- AAPL
- MSFT
- AMZN
- META
- AMD

Equity-specific concerns:

- Session gaps
- Opening range behavior
- Corporate actions
- Split adjustments
- Borrow/short availability
- Spread and liquidity filters
- Pattern day trader constraints
- Options translation for eligible tickers

### 4.2 Futures

Supported contracts:

- NQ
- MNQ
- GC
- ES

Supported styles:

- Scalping
- Day trading
- Swing trading
- Options-linked futures research, if later approved

Futures-specific concerns:

- Contract rolls
- Continuous contract construction
- Tick value and point value
- Session templates
- Asia, London, and RTH sessions
- Higher overnight liquidity risk
- Prop-firm trailing drawdown rules
- Exchange holidays and early closes

### 4.3 Options

Supported styles:

- Options trading
- Day trading options
- Swing options
- Options overlays on equity signals

Option structures:

- Long call
- Long put
- Debit spread
- Credit spread
- Future expansion: iron condor, calendar spread, diagonal spread

Options-specific concerns:

- Expiration
- DTE
- IV
- Greeks
- Bid/ask spread
- Open interest
- Volume
- Assignment risk
- Exercise risk
- 0DTE risk
- Multi-leg execution quality

## 5. Trading Style Subcategories

Every asset class must support these subcategories, even if a given strategy is initially disabled.

### 5.1 Scalping

Purpose:

- Fast intraday entries.
- Short hold time.
- Tight risk.
- High sensitivity to slippage.

Required validations:

- Tick or 1-minute data quality.
- Spread/slippage model.
- Latency assumptions.
- Stop-first same-bar logic.
- High sample-size backtests.
- Robustness to 2x costs.

Paper approval rule:

Scalping cannot paper trade until slippage and execution quality have been measured in replay and paper simulation.

### 5.2 Day Trading

Purpose:

- Intraday setups.
- No overnight exposure unless explicitly allowed.
- Primary home for OR/VWAP/structure/DIR-fast systems.

Required validations:

- Session-specific backtests.
- Side-specific performance.
- Regime-specific performance.
- EOD flatten behavior.
- Risk limits per day.

Paper approval rule:

Day trading strategies must prove positive expectancy, acceptable drawdown, and stable performance across multiple market regimes.

### 5.3 Options Trading

Purpose:

- Translate eligible underlying signals into option structures.
- Manage options risk separately from underlying signal risk.

Required validations:

- Option chain availability.
- Bid/ask spread filters.
- IV and Greeks.
- Structure-specific payoff.
- Assignment/exercise safeguards.
- Multi-leg order handling.

Paper approval rule:

Options strategies cannot paper trade until option pricing, spread constraints, and exit logic are validated.

### 5.4 Swing Trading

Purpose:

- Multi-day holding periods.
- Broader regime and trend logic.
- Lower frequency, larger signal horizon.

Required validations:

- Overnight gap risk.
- News and event risk.
- Position sizing by volatility.
- Portfolio exposure.
- Correlation limits.

Paper approval rule:

Swing strategies require portfolio-level risk approval before paper execution.

## 6. Strategy Module Contract

Every strategy module must expose the same sections and outputs.

Required module sections:

- Market context
- Setup rules
- Entry logic
- Pullback logic
- Exit logic
- Stop loss logic
- Profit target logic
- Risk rules
- Trade limits
- Performance tracking
- ML/NN learning labels
- Paper trading approval requirements

Required module outputs:

```text
StrategyCandidate
RiskInputs
FeatureSnapshot
RuleDecision
MLScoreRequest
NNPatternRequest
ExecutionPlan
ExplanationBundle
LearningLabels
```

Required rule verdicts:

- `eligible`
- `watch`
- `blocked_by_rule`
- `blocked_by_data`
- `blocked_by_risk`
- `expired`
- `invalidated`

Required metadata:

- asset_class
- symbol
- trading_style
- strategy_id
- strategy_version
- rule_version
- session
- timeframe
- generated_at
- approval_state

## 7. Target System Architecture

```text
Historical and live market data
        |
        v
Data pipeline and validation
        |
        v
Historical database and feature store
        |
        v
Rule-based strategy modules
        |
        v
Strategy signal generator
        |
        v
ML setup-quality scorer
        |
        v
NN pattern-recognition scorer
        |
        v
Risk engine
        |
        v
Approval workflow
        |
        v
Replay / paper execution engine
        |
        v
Trade journal and audit logs
        |
        v
Post-trade learning queue
        |
        v
Scheduled retraining and model review
```

Hard separation:

- Rule engine creates eligible candidates.
- AI only scores candidates and context.
- Risk engine can always block.
- Execution cannot bypass risk or approval.

## 8. Core Components

### 8.1 Data Pipeline

Responsibilities:

- Ingest raw historical data.
- Normalize timestamps.
- Validate OHLCV integrity.
- Build continuous futures contracts.
- Resample timeframes.
- Mark sessions.
- Attach macro, volatility, and news context.
- Persist immutable raw data and derived data.

Minimum quality checks:

- Missing bars
- Duplicate bars
- Out-of-order timestamps
- Bad OHLC
- Zero or abnormal volume
- Session boundary errors
- Roll adjustment correctness
- Equity split adjustment correctness
- Early-close handling

### 8.2 Historical Database

Responsibilities:

- Store raw bars.
- Store resampled bars.
- Store strategy candidates.
- Store backtest trades.
- Store replay trades.
- Store paper trades.
- Store feature snapshots.
- Store labels.
- Store model predictions.

Initial storage:

- DuckDB and Parquet for research and backtests.
- SQLite for local bot state.

Future storage:

- Postgres or TimescaleDB for multi-process production.

### 8.3 Backtesting Engine

Responsibilities:

- Replay historical bars causally.
- Generate candidates from rule modules.
- Apply realistic fills.
- Apply costs, slippage, and commissions.
- Apply risk rules.
- Produce trade-level and portfolio-level metrics.

Required backtest outputs:

- Net R
- Gross R
- Win rate
- Profit factor
- Expectancy
- Max drawdown
- MFE
- MAE
- Hold time
- Side breakdown
- Session breakdown
- Regime breakdown
- Year breakdown
- Cost sensitivity
- Slippage stress

### 8.4 Replay Engine

Responsibilities:

- Run historical data through the production pipeline.
- Use the same strategy code as paper mode.
- Verify live/backtest parity.
- Generate audit trails.
- Validate dashboards and explanations.

Replay must catch:

- Repaint behavior
- Bar-close violations
- Intrabar assumptions
- Duplicate signals
- State-machine drift
- Risk-engine bypasses

### 8.5 Paper Trading Engine

Responsibilities:

- Submit paper orders only after approval.
- Use broker paper account only.
- Record fills.
- Track slippage.
- Compare paper results to backtest expectations.
- Feed outcomes into the learning queue.

Paper mode must block if:

- Strategy not manually approved.
- Data feed unhealthy.
- Risk rules fail.
- Kill switch active.
- Broker account is not paper.
- Strategy drawdown exceeds paper limits.

### 8.6 Risk Engine

Responsibilities:

- Protect capital first.
- Size positions.
- Block unsafe trades.
- Enforce daily limits.
- Enforce strategy limits.
- Enforce portfolio limits.

Risk gates:

- Max risk per trade
- Max trades per day
- Max daily loss
- Max trailing drawdown
- Max concurrent positions
- Max correlated exposure
- Min R:R
- Stop distance sanity
- Spread too wide
- Stale data
- News lockout
- Session lockout
- Strategy drawdown lockout
- Manual kill switch

### 8.7 Strategy Registry

Responsibilities:

- Register every strategy module.
- Track asset class and trading style.
- Track approval state.
- Track version history.
- Track enabled/disabled status.

Strategy states:

- `draft`
- `research_ready`
- `backtest_ready`
- `backtest_passed`
- `sustainability_passed`
- `risk_approved`
- `paper_approved`
- `paper_active`
- `paper_paused`
- `retired`

### 8.8 Model Registry

Responsibilities:

- Register ML and NN models.
- Track feature schemas.
- Track training windows.
- Track validation results.
- Track champion/challenger status.
- Track model approvals.

Model states:

- `draft`
- `trained`
- `validated`
- `paper_candidate`
- `paper_active`
- `rejected`
- `retired`

No model can score paper trades unless:

- Feature schema matches.
- Strategy version matches.
- Validation metrics pass.
- Calibration is reviewed.
- Model is approved for advisory paper use.

### 8.9 Trade Journal

Responsibilities:

- Store every candidate.
- Store every decision.
- Store every blocked trade.
- Store every paper order.
- Store every fill.
- Store every explanation.
- Store post-trade labels.

The journal is the source for continuous learning.

### 8.10 Audit Logs

Responsibilities:

- Create immutable records of all decisions.
- Record approvals.
- Record model promotions.
- Record risk overrides.
- Record configuration changes.
- Record broker events.

Audit log rule:

Every trade must be explainable after the fact from stored records alone.

## 9. AI, ML, and NN Plan

### 9.1 AI Governance

AI is advisory only.

AI cannot:

- Create trades without rules.
- Override invalid setups.
- Override risk blocks.
- Override stale data blocks.
- Override missing approval.
- Move a strategy to paper trading.
- Move a strategy to live trading.

AI can:

- Score setup quality.
- Detect similarity to past winning/losing setups.
- Rank candidates.
- Recommend size reductions.
- Explain historical analogs.
- Identify weak strategy cohorts.
- Suggest research priorities.

### 9.2 ML Training Pipeline

ML target:

Score rule-eligible setups using tabular, point-in-time features.

Inputs:

- Rule outputs
- OR features
- VWAP features
- Structure features
- DIR-fast features
- Candle features
- Volume features
- Volatility features
- Session features
- News features
- Slippage features
- Risk features

Initial models:

- Logistic Regression
- Random Forest
- XGBoost
- LightGBM
- CatBoost

Targets:

- Win probability
- Stop-first probability
- TP1 probability
- TP2 probability
- Expected R
- Setup quality
- No-trade probability

Required validation:

- Walk-forward validation
- Purged time-series validation
- Embargo
- Side-by-side train/test date windows
- Symbol breakdown
- Side breakdown
- Session breakdown
- Regime breakdown
- Confidence-bucket analysis
- Calibration analysis

Promotion gates:

- OOS performance improves.
- Calibration improves.
- High-confidence bucket outperforms low-confidence bucket.
- No collapse by side, session, or symbol.
- Paper scorecard agrees with backtest.

### 9.3 Neural Network Training Pipeline

NN target:

Recognize whether the current setup resembles past winning or losing setups under similar conditions.

Inputs:

- Fixed-length candle sequences.
- Engineered feature sequences.
- Static context features.
- Strategy state features.

Sequence windows:

- 32 bars
- 64 bars
- 128 bars
- Style-specific windows for scalping, day trading, and swing trading

Models:

- MLP baseline
- 1D CNN
- GRU
- LSTM
- CNN + GRU hybrid
- Transformer encoder
- Temporal Fusion Transformer
- Mixture of Experts by regime and trading style

NN outputs:

- Pattern win similarity
- Pattern loss similarity
- Breakout continuation probability
- Failed-breakout probability
- Pullback-quality score
- Regime-pattern score

NN restrictions:

- Sequence must end at the signal timestamp.
- No future bars in input.
- No realized MFE, MAE, or outcome fields in input.
- NN cannot create trades independently.

### 9.4 Learning Sources

The platform must learn from:

- Historical data
- Backtests
- Replay testing
- Paper trades
- Missed trades
- Winning trades
- Losing trades
- Invalid setups
- Pullbacks
- Breakouts
- Failed breakouts
- Market regimes
- Volatility conditions
- News conditions
- Slippage
- Execution quality

Each learning event must be labeled and linked to:

- Strategy version
- Model version
- Feature schema
- Asset class
- Trading style
- Risk profile
- Outcome

## 10. Database Structure

### 10.1 Core Reference Tables

`assets`

- asset_id
- symbol
- asset_class
- exchange
- tick_size
- point_value
- options_root
- active

`asset_sessions`

- session_id
- asset_id
- session_name
- timezone
- start_time
- end_time
- opening_range_start
- opening_range_end

`strategy_registry`

- strategy_id
- strategy_name
- asset_class
- trading_style
- module_path
- strategy_version
- status
- created_at
- approved_at
- approved_by

`model_registry`

- model_id
- model_name
- model_type
- strategy_id
- feature_schema_id
- training_start
- training_end
- validation_start
- validation_end
- status
- champion
- artifact_path

### 10.2 Market Data Tables

`bars_1m`

- symbol
- timestamp
- open
- high
- low
- close
- volume
- source
- quality_status

`bars_resampled`

- symbol
- timeframe
- session
- timestamp
- open
- high
- low
- close
- volume

`futures_rolls`

- root_symbol
- contract
- roll_date
- adjustment_factor
- method

`option_chains`

- underlying
- timestamp
- expiration
- strike
- right
- bid
- ask
- mid
- iv
- delta
- gamma
- theta
- vega
- volume
- open_interest

### 10.3 Strategy and Trade Tables

`strategy_candidates`

- candidate_id
- strategy_id
- symbol
- asset_class
- trading_style
- side
- timestamp
- entry
- stop
- tp1
- tp2
- rule_status
- approval_state
- json_payload

`rule_decisions`

- decision_id
- candidate_id
- eligible
- blocked_reason
- market_context
- setup_rules
- entry_logic
- pullback_logic
- exit_logic
- stop_logic
- target_logic

`risk_decisions`

- risk_decision_id
- candidate_id
- approved
- reason_code
- max_qty
- max_risk
- risk_profile
- decided_at

`orders`

- order_id
- candidate_id
- broker
- account_mode
- symbol
- side
- qty
- order_type
- limit_price
- stop_price
- take_profit
- state

`fills`

- fill_id
- order_id
- timestamp
- qty
- price
- fees
- slippage
- liquidity_flag

`trades`

- trade_id
- candidate_id
- symbol
- side
- opened_at
- closed_at
- entry_price
- exit_price
- net_r
- gross_r
- exit_reason

### 10.4 Learning Tables

`feature_snapshots`

- snapshot_id
- candidate_id
- feature_schema_id
- timestamp
- feature_json

`ml_predictions`

- prediction_id
- candidate_id
- model_id
- raw_score
- calibrated_probability
- expected_r
- no_trade_probability
- explanation_json

`nn_predictions`

- prediction_id
- candidate_id
- model_id
- pattern_win_score
- pattern_loss_score
- regime_pattern_score
- embedding_path
- explanation_json

`learning_labels`

- label_id
- candidate_id
- outcome
- net_r
- mfe_r
- mae_r
- hold_bars
- hit_tp1
- hit_tp2
- stop_first
- failed_breakout
- missed_trade
- invalid_setup

### 10.5 Governance Tables

`approval_records`

- approval_id
- object_type
- object_id
- approval_type
- approved
- approved_by
- approved_at
- notes

`audit_logs`

- audit_id
- timestamp
- actor
- action
- object_type
- object_id
- before_json
- after_json
- reason

`kill_switch_events`

- event_id
- timestamp
- state
- reason
- actor

## 11. Proposed Folder Structure

```text
BOT/
  AITP-001_Institutional_AI_Trading_Platform_Blueprint.md
  bot/
    assets/
      equities/
      futures/
      options/
    strategies/
      equities/
        scalping/
        day_trading/
        options_trading/
        swing_trading/
      futures/
        scalping/
        day_trading/
        swing_trading/
      options/
        day_trading/
        swing_trading/
    strategy_registry/
    data_pipeline/
    feature_store/
    backtest/
    replay/
    paper/
    risk/
    ml/
      datasets/
      features/
      models/
      calibration/
      explainability/
      validation/
    nn/
      datasets/
      models/
      training/
      embeddings/
      validation/
    execution/
    journal/
    audit/
    dashboard/
    approvals/
  tests/
    data/
    strategy/
    risk/
    backtest/
    replay/
    paper/
    ml/
    nn/
    dashboard/
```

Compatibility note:

The current project already has useful modules under `BOT/bot/strategy`, `BOT/bot/ml`, `BOT/bot/execution`, and `engine/`. The future folder structure should be introduced gradually, with adapters around existing code first. Do not duplicate working rule logic.

## 12. Dashboard Plan

The dashboard must include these views:

### 12.1 Live/Paper Trade Monitoring

Shows:

- Current mode
- Paper approval state
- Active candidates
- Active orders
- Open positions
- Risk status
- Kill switch state
- Data source health

### 12.2 Strategy Performance

Shows:

- Strategy expectancy
- Profit factor
- Win rate
- Max drawdown
- Trade count
- Side breakdown
- Session breakdown
- Regime breakdown

### 12.3 Asset Class Performance

Separate pages for:

- Equities
- Futures
- Options

Each page shows:

- PnL by asset
- R by asset
- Drawdown by asset
- Trade frequency
- Approval status

### 12.4 Trading Style Performance

Separate views for:

- Scalping
- Day trading
- Swing trading
- Options trading

Each view shows:

- Active strategies
- Disabled strategies
- Approval stage
- Historical performance
- Paper performance

### 12.5 ML Confidence

Shows:

- Raw model score
- Calibrated probability
- Expected R
- Confidence bucket
- Top positive features
- Top negative features
- Historical bucket performance

### 12.6 NN Confidence

Shows:

- Pattern win score
- Pattern loss score
- Similar historical examples
- Regime match
- Sequence embedding cluster
- Current setup vs past winners

### 12.7 Risk Status

Shows:

- Approved or blocked
- Block reason
- Account risk
- Daily risk
- Strategy risk
- Portfolio risk
- Correlation risk
- News risk
- Stale data risk

### 12.8 Profitability

Shows:

- Net R
- Gross R
- Profit factor
- Expectancy
- Win rate
- Average win
- Average loss
- Payoff ratio
- Drawdown

### 12.9 Model Improvement

Shows:

- Champion model
- Challenger model
- Model version
- Training window
- Validation metrics
- Calibration drift
- Paper performance by model
- Promotion recommendation

### 12.10 Trade Replay

Shows:

- Bar-by-bar replay
- Rule state
- ML score at decision time
- NN score at decision time
- Risk decision
- Execution simulation
- Final outcome

### 12.11 Why Trade Fired / Why Blocked

Every candidate must show:

- Rule eligibility
- Setup reason
- Entry condition
- Pullback condition
- Stop logic
- Target logic
- ML confidence
- NN confidence
- Risk decision
- Final decision
- Block reason, if blocked

## 13. Testing Plan

### 13.1 Data Tests

- Bar schema validation
- Timestamp ordering
- Duplicate detection
- Gap detection
- Bad OHLC detection
- Roll schedule validation
- Session calendar validation
- Option chain sanity checks

### 13.2 Strategy Tests

- Rule eligibility tests
- Entry condition tests
- Pullback tests
- Exit tests
- Stop tests
- Profit target tests
- Invalid setup tests
- No look-ahead tests
- Bar-close confirmation tests

### 13.3 Backtest Tests

- Deterministic replay checksum
- Stop-first same-bar tests
- Cost/slippage tests
- EOD flatten tests
- Multi-session tests
- Strategy version reproducibility

### 13.4 Risk Tests

- Max loss block
- Max trade count block
- Consecutive loss block
- Stale feed block
- Spread block
- News block
- Kill switch block
- Live lock block

### 13.5 ML Tests

- Point-in-time feature tests
- Label alignment tests
- Leakage tests
- Walk-forward split tests
- Calibration tests
- Feature schema compatibility tests
- Model registry tests

### 13.6 NN Tests

- Sequence window tests
- Future-bar exclusion tests
- Shape tests
- Embedding storage tests
- Train/validation split tests
- Determinism tests

### 13.7 Paper Trading Tests

- Manual approval required
- Paper account required
- Broker mode check
- Order deduplication
- Fill recording
- Slippage capture
- Paper-vs-backtest scorecard

### 13.8 Dashboard Tests

- Strategy status visible
- Approval state visible
- Risk block visible
- ML/NN explanation visible
- Trade replay visible
- Performance metrics consistent with database

## 14. Development Roadmap

### Phase 0 - Governance Lock

Deliverables:

- This blueprint approved.
- Live trading disabled.
- Paper approval workflow specified.
- Strategy states defined.
- Database schema drafted.

Exit gate:

- User confirms the platform must remain research/backtest/replay only until manual paper approval.

### Phase 1 - Data and Strategy Inventory

Deliverables:

- Historical data coverage report.
- Data quality report.
- Existing strategy inventory.
- Strategy-of-record for each active strategy.
- Drift report between docs, Pine, Python engine, and bot.

Exit gate:

- Data validated for each asset class.

### Phase 2 - Backtest and Replay Foundation

Deliverables:

- Backtest reports per strategy.
- Replay parity reports.
- Slippage and cost stress.
- Sustainability report.
- Profitability report.

Exit gate:

- Strategy must pass performance and robustness thresholds.

### Phase 3 - Risk and Approval Workflow

Deliverables:

- Strategy approval records.
- Risk rule library.
- Paper trading lock.
- Manual approval UI/API.
- Audit trail for approvals.

Exit gate:

- Risk management rules approved by user.

### Phase 4 - ML Baseline

Deliverables:

- Feature store.
- Label store.
- Logistic baseline.
- Tree model baselines.
- Walk-forward validation.
- Calibration reports.
- ML confidence dashboard.

Exit gate:

- ML proves out-of-sample usefulness as an advisory filter.

### Phase 5 - NN Pattern Layer

Deliverables:

- Sequence dataset builder.
- MLP baseline.
- CNN/GRU/LSTM models.
- Transformer research model.
- NN confidence dashboard.
- Similar historical setup viewer.

Exit gate:

- NN adds stable explanatory or filtering value without overfitting.

### Phase 6 - Paper Trading

Deliverables:

- User manual approval for selected strategies.
- Paper-only broker guard.
- Paper execution logs.
- Paper-vs-backtest scorecard.
- Slippage and fill-quality report.

Exit gate:

- Paper results are consistent with backtest expectations.

### Phase 7 - Production Hardening

Deliverables:

- Full audit logs.
- Health monitoring.
- Alerting.
- Reconciliation.
- Broker fill stream.
- Restart recovery.
- Disaster recovery runbook.

Exit gate:

- System is safe enough to evaluate future live approval.

### Phase 8 - Future Live Review

Deliverables:

- Live readiness checklist.
- Independent risk review.
- Maximum order size approved.
- Emergency process approved.
- Manual live approval record.

Exit gate:

- User manually approves live mode in a separate decision.

## 15. Five-Year Development Plan

### Year 1 - Foundation and Paper Discipline

Goals:

- Complete data validation.
- Complete strategy-of-record review.
- Build feature and label stores.
- Build rule-first backtest and replay reports.
- Add paper approval workflow.
- Paper trade only approved strategies.

Success criteria:

- No live trading.
- Every paper trade has a rule explanation, ML/NN score, risk decision, and audit trail.

### Year 2 - ML/NN Maturity

Goals:

- Add calibrated ML models.
- Add NN sequence models.
- Add model registry and champion/challenger workflow.
- Add model improvement dashboards.
- Expand learning from missed and invalid setups.

Success criteria:

- AI improves filtering or sizing without replacing rules.
- No model is promoted without walk-forward evidence.

### Year 3 - Multi-Asset Expansion

Goals:

- Mature equities, futures, and options modules.
- Add portfolio-level risk.
- Add cross-asset regime features.
- Improve options chain and Greeks integration.
- Expand paper trading across approved strategies.

Success criteria:

- Each asset class has separate performance, risk, and approval reporting.

### Year 4 - Institutional Operations

Goals:

- Add robust production observability.
- Add alerting and incident workflows.
- Add disaster recovery.
- Add formal monthly model reviews.
- Add strategy retirement workflow.

Success criteria:

- The system can be operated like a controlled trading desk process.

### Year 5 - Advanced Intelligence and Governance

Goals:

- Add mixture-of-experts models.
- Add regime-specialized models.
- Add advanced execution-quality modeling.
- Add portfolio optimizer for approved strategies.
- Add formal governance packs for every model and strategy.

Success criteria:

- The platform improves from accumulated evidence while preserving rule authority and capital protection.

## 16. Capital Protection Rules

Capital protection has priority over opportunity.

The platform must always prefer:

- No trade over unclear trade.
- Paper over live.
- Smaller size over larger size.
- Risk block over model confidence.
- Manual approval over automation.
- Auditability over speed.

No strategy may advance unless sustainability, profitability, and risk management have been reviewed.

No strategy may move beyond paper trading without manual approval.

## 17. Final Target State

The final platform is a controlled trading research and paper-trading system where:

- Historical data is validated.
- Rules generate eligible candidates.
- ML scores quality.
- Neural networks recognize pattern similarity.
- Risk grants or blocks permission.
- Paper execution happens only after manual approval.
- Every decision is explainable.
- Every outcome becomes a learning event.
- No live trading occurs without a separate future approval process.

