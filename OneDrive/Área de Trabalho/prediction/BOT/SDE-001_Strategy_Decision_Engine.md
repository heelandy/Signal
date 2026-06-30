# Strategy Decision Engine
**Status:** ✅ Regenerated
**Module ID:** SDE-001
**Version:** 1.0

> Official regenerated specification for the Trading OS Strategy Decision Engine.

# Purpose

The Strategy Decision Engine evaluates all enabled trading strategies against current market conditions and produces ranked trade candidates. It is responsible for deciding **whether a setup exists**, but it does not approve risk or execute trades.

# Responsibilities

- Scan all enabled strategies
- Evaluate strategy conditions
- Score trade opportunities
- Rank trade candidates
- Apply strategy-specific filters
- Generate candidate explanations
- Publish approved trade candidates for Risk Engine evaluation

# Core Philosophy

Strategies should compete for capital.

Only the highest-quality opportunities should progress to the Risk Engine.

# Architecture

```text
Market Intelligence Engine
Security Intelligence Engine
Feature Engineering Engine
Opening Range Matrix
Global Market Intelligence
        │
═══════════════════════════════════
      STRATEGY DECISION ENGINE
═══════════════════════════════════
Strategy Registry
Condition Evaluator
Confluence Engine
Confidence Calculator
Opportunity Ranking
Candidate Generator
Explanation Builder
═══════════════════════════════════
        │
Trade Candidate Queue
        │
Risk Engine
```

# Supported Strategy Types

- ORB Breakout
- ORB Retest
- Trend Continuation
- Liquidity Sweep
- VWAP Reclaim
- Pullback
- Range Breakout
- Mean Reversion
- Momentum
- User-defined strategies

# Candidate Lifecycle

DISCOVERED

EVALUATING

QUALIFIED

RANKED

QUEUED

SUBMITTED_TO_RISK

REJECTED

EXPIRED

# Strategy Inputs

- Market Regime
- Trend
- Volume
- Volatility
- Liquidity
- ORB
- Session
- News Risk
- Security DNA
- Portfolio Exposure
- Global Market Context

# Outputs

- Trade Candidate
- Strategy Score
- Confidence Score
- Explanation
- Candidate Rank
- Opportunity Metadata

# Events

- candidate.created
- candidate.updated
- candidate.expired
- candidate.rejected
- strategy.signal

# Database Tables

- strategies
- strategy_versions
- strategy_rules
- trade_candidates
- candidate_scores
- opportunity_queue

# Performance Targets

- Continuous scanning
- Incremental evaluation
- Low-latency candidate generation
- Replay identical to live

# Security

- Cannot bypass Risk Engine
- Cannot submit broker orders
- Fully auditable
- Uses Market Truth only

# Future Implementations

- ML-assisted candidate ranking
- Adaptive strategy weighting
- Dynamic strategy activation
- Cross-strategy optimization
- Portfolio-aware strategy prioritization

# Relationships

Depends on:
- Market Intelligence Engine
- Feature Engineering Engine
- Opening Range Matrix
- Security Intelligence Engine
- Global Market Intelligence

Provides:
- Risk Engine
- Opportunity Queue
- AI Research Lab
- Performance Intelligence

# Regeneration Status

✅ Regenerated

Official source of truth for the Strategy Decision Engine.
