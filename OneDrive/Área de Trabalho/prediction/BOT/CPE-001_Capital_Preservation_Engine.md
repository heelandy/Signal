# Capital Preservation Engine
**Status:** ✅ Regenerated
**Module ID:** CPE-001
**Version:** 1.0

> Official regenerated specification for the Trading OS Capital Preservation Engine.

# Purpose

The Capital Preservation Engine protects trading capital before profit generation becomes the priority. Its mission is to keep the trader in the game by preventing catastrophic losses and locking in gains according to configurable rules.

# Responsibilities

- Protect daily, weekly, monthly, and lifetime equity
- Lock profits after green days
- Enforce equity-based trading limits
- Monitor drawdowns
- Coordinate with the Risk Engine
- Trigger trading pauses
- Publish preservation events

# Core Philosophy

Capital preservation has priority over profit generation.

No strategy, ML model, automation, or user workflow may bypass preservation rules.

# Architecture

```text
Account Balance
      │
Open Positions
      │
Risk Engine
      │
══════════════════════════════
 CAPITAL PRESERVATION ENGINE
══════════════════════════════
Equity Monitor
Profit Lock Manager
Drawdown Monitor
Daily Protection
Weekly Protection
Monthly Protection
Prop Firm Protection
Recovery Manager
══════════════════════════════
      │
Risk Decision
      │
Execution Core
```

# Protection Rules

- Daily loss limit
- Weekly loss limit
- Monthly loss limit
- Maximum account drawdown
- Trailing equity protection
- Consecutive losing trades protection
- Consecutive losing days protection
- Maximum daily trade count
- Cooling-off period after losses

# Profit Protection

Supported modes:

- Fixed dollar lock
- Percentage lock
- Dynamic equity trailing
- Milestone lock
- User-defined schedule

## Previous Green Day Rule

If enabled:

Yesterday Profit = P

Today's Maximum Allowed Loss = P × Configurable Percentage

Default architecture value discussed:

40% of previous day's realized profit.

Example:

Yesterday: +$1,000

Configured Protection: 40%

Today's Maximum Loss = $400

After reaching -$400:

- No new trades
- Existing protection rules remain active
- User notified
- Event logged

# Account Types

Supports:

- Personal accounts
- Paper accounts
- Evaluation accounts
- Funded prop firm accounts

# Recovery Logic

After protection triggers:

- Pause trading
- Continue monitoring
- Allow paper trading
- Continue AI research
- Preserve learning
- Resume only after configured conditions are met

# Events

- preservation.warning
- preservation.locked
- preservation.resumed
- preservation.limit_hit
- preservation.profit_locked

# Database Tables

- capital_preservation_rules
- equity_snapshots
- preservation_events
- daily_equity_history
- recovery_history

# Performance

Decision latency target:
< 2 ms

# Security

Cannot be disabled during active Live Mode without explicit confirmation.

Every override is audited.

# Future Implementations

- Adaptive equity curve protection
- ML-driven preservation recommendations
- Portfolio-level preservation
- Cross-account preservation
- Volatility-adjusted protection
- Time-of-day protection

# Relationships

Depends on:
- Risk Engine
- Account Management
- Portfolio Intelligence

Provides:
- Execution Core
- Decision Orchestrator
- Performance Intelligence

# Regeneration Status

✅ Regenerated

Official source of truth for the Capital Preservation Engine.
