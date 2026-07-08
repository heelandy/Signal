# Global Market Intelligence Engine
**Status:** ✅ Regenerated
**Module ID:** GMI-001
**Version:** 1.0

> Official regenerated specification for the Trading OS Global Market Intelligence Engine.

# Purpose

The Global Market Intelligence Engine continuously evaluates worldwide macroeconomic, financial, and cross-asset conditions to provide strategic market context for every trading decision.

# Responsibilities

- Monitor macroeconomic indicators
- Track central bank policy
- Analyze treasury markets
- Monitor currencies
- Analyze commodities
- Evaluate volatility regimes
- Track sector rotation
- Measure market breadth
- Build market narrative
- Publish Global Market Score

# Core Philosophy

Technical analysis explains what price is doing.

Global Market Intelligence explains why.

# Architecture

```text
Economic Calendar
News Reaction Engine
Market Data Engine
External Macro Sources
        │
══════════════════════════════
GLOBAL MARKET INTELLIGENCE
══════════════════════════════
Macro Analyzer
Central Bank Monitor
Treasury Analyzer
Currency Engine
Commodity Engine
Volatility Engine
Breadth Analyzer
Sector Rotation
Narrative Builder
Global Score Engine
══════════════════════════════
        │
Market Intelligence Engine
```

# Intelligence Domains

- GDP
- CPI
- PPI
- PCE
- NFP
- Unemployment
- Retail Sales
- PMI
- Consumer Confidence
- Federal Reserve
- Treasury Yields
- DXY
- Gold
- Oil
- VIX
- Market Breadth
- Sector Rotation
- Institutional Flow (future)

# Market Themes

- Risk-On
- Risk-Off
- Inflation
- Disinflation
- Expansion
- Recession
- Soft Landing
- Flight to Safety
- Technology Leadership

# Outputs

- Global Market Score
- Macro Regime
- Market Narrative
- Cross-Asset Context
- Risk Environment
- Confidence Score

# Events

- macro.updated
- narrative.changed
- global_score.updated
- regime.changed

# Database Tables

- macro_snapshots
- central_bank_events
- treasury_history
- sector_rotation_history
- global_market_scores
- market_narratives

# Performance Targets

- Event-driven updates
- Replay identical to live
- Historical macro reconstruction
- Low-latency publication

# Security

- Read-only intelligence module
- Cannot execute trades
- Fully auditable

# Future Implementations

- Institutional flow integration
- Options flow integration
- AI macro forecasting
- Cross-market contagion modeling
- Global economic scenario simulation

# Relationships

Depends on:
- News Reaction Engine
- Market Data Engine

Provides:
- Market Intelligence Engine
- Risk Engine
- Strategy Decision Engine
- Portfolio Intelligence
- Trading Knowledge Brain

# Regeneration Status

✅ Regenerated

Official source of truth for the Global Market Intelligence Engine.
