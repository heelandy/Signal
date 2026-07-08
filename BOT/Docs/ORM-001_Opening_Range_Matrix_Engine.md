# Opening Range Matrix Engine
**Status:** ✅ Regenerated
**Module ID:** ORM-001
**Version:** 1.0

> Official regenerated specification for the Trading OS Opening Range Matrix Engine.

# Purpose

The Opening Range Matrix Engine continuously tracks Opening Range Blocks (ORB) across multiple timeframes and markets, providing a standardized framework for breakout, retest, continuation, and failure analysis.

# Responsibilities

- Calculate ORB on every configured timeframe
- Monitor ORB breakouts and retests
- Measure OR width and volatility
- Publish ORB state to downstream modules
- Maintain historical ORB statistics
- Support replay, paper, and live trading

# Core Philosophy

Every timeframe has its own Opening Range.

The Trading OS continuously monitors all active Opening Ranges simultaneously.

# Supported Timeframes

- 1 Minute
- 3 Minute
- 5 Minute
- 15 Minute
- 30 Minute
- 1 Hour
- 4 Hour
- Daily
- Weekly
- Monthly

# Architecture

```text
Market Truth Engine
        │
══════════════════════════════
 OPENING RANGE MATRIX ENGINE
══════════════════════════════
ORB Builder
Range Validator
Breakout Detector
Retest Detector
Width Analyzer
Strength Scorer
Historical Analyzer
══════════════════════════════
        │
ORB Matrix
        │
Market Intelligence
Strategy Engine
ML Platform
```

# ORB States

- BUILDING
- COMPLETE
- INSIDE_RANGE
- BREAKOUT_UP
- BREAKOUT_DOWN
- RETESTING
- CONFIRMED
- FAILED
- INVALIDATED

# ORB Features

- Opening High
- Opening Low
- Range Width
- ATR Ratio
- Breakout Direction
- Retest Quality
- Volume Confirmation
- VWAP Alignment
- Trend Alignment
- Liquidity Sweep Detection

# Outputs

- ORB Matrix
- Breakout Confidence
- Retest Confidence
- Historical Success Metrics
- ML Feature Snapshot

# Events

- orb.created
- orb.updated
- orb.breakout
- orb.retest
- orb.failed
- orb.invalidated

# Database Tables

- opening_ranges
- orb_events
- orb_statistics
- orb_history
- orb_feature_snapshots

# Performance Targets

- Real-time updates
- Incremental calculations
- Identical logic in replay and live modes
- Low-latency event publishing

# Security

- Consumes Market Truth only
- No direct trading decisions
- Fully auditable

# Future Implementations

- Adaptive ORB windows
- Session-specific ORBs
- Cross-timeframe ORB confluence
- ML-based ORB quality scoring
- Institutional opening auction analysis

# Relationships

Depends on:
- Market Truth Engine
- Feature Engineering Engine

Provides:
- Market Intelligence Engine
- Strategy Decision Engine
- Machine Learning Platform
- Performance Intelligence Engine

# Regeneration Status

✅ Regenerated

Official source of truth for the Opening Range Matrix Engine.
