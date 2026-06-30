
# Trading Strategy Library
**Status:** ✅ Regenerated
**Module ID:** TSL-001
**Version:** 1.0

> Official Trading Strategy Library for the Trading OS.

# Purpose

This document is the authoritative catalog of every trading strategy supported by the Trading OS. It defines strategy classifications, lifecycle, requirements, validation rules, and governance.

# Strategy Principles

- Every strategy is modular.
- Every strategy must pass Replay before Paper.
- Every strategy must pass Paper before Live.
- Every strategy is versioned.
- Every strategy is explainable.
- Every strategy is evaluated by the Risk Engine before execution.

# Strategy Categories

## Trend Following
- EMA Trend
- Market Structure
- Breakout Continuation
- Pullback Continuation

## Momentum
- Opening Range Breakout (ORB)
- VWAP Momentum
- Volume Expansion
- Relative Strength

## Mean Reversion
- VWAP Reversion
- Bollinger Reversion
- Range Rotation

## Structure-Based
- BOS
- CHoCH
- Liquidity Sweep
- Order Block
- Fair Value Gap

## News-Based
- Scheduled News Reaction
- Earnings Reaction
- Macro Event Strategy

## Futures
- NQ
- MNQ
- ES
- MES
- YM
- RTY
- CL
- GC

# Strategy Metadata

Every strategy contains:

- Strategy ID
- Version
- Supported Assets
- Supported Timeframes
- Entry Logic
- Exit Logic
- Risk Rules
- Position Sizing Rules
- ML Compatibility
- Security DNA Compatibility
- Expected Market Regime
- Validation History

# Strategy Lifecycle

DESIGNED

IMPLEMENTED

REPLAY_VALIDATED

PAPER_VALIDATED

LIVE_APPROVED

PRODUCTION

RETIRED

# Validation Requirements

- Replay accuracy
- Paper performance
- Risk validation
- Performance benchmark
- User approval

# Regeneration Status

✅ Regenerated

Official Trading Strategy Library for the Trading OS.
