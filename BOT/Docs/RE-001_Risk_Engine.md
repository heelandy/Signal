# Risk Engine
**Status:** ✅ Regenerated
**Module ID:** RE-001
**Version:** 1.0

> Official regenerated specification for the Trading OS Risk Engine.

# Purpose

The Risk Engine is the highest authority for capital protection. Every trade, regardless of source, must pass through this engine before execution.

# Responsibilities

- Validate every trade
- Enforce user risk rules
- Enforce prop firm rules
- Calculate position size
- Protect capital
- Monitor account health
- Monitor portfolio exposure
- Block unsafe trades
- Activate kill switches
- Publish risk decisions

# Core Philosophy

Risk cannot be bypassed.

No module, ML model, LLM, strategy, automation, broker adapter, or user workflow may submit a live trade without Risk Engine approval.

# Architecture

```text
Trade Candidate
      │
Portfolio Intelligence
      │
══════════════════════════════
        RISK ENGINE
══════════════════════════════
Account Risk
Trade Risk
Portfolio Risk
Market Risk
News Risk
Broker Risk
Prop Firm Rules
Capital Preservation
Kill Switch Manager
Position Sizing
══════════════════════════════
      │
Risk Decision
      │
Execution Core
```

# Validation Pipeline

1. Capability Registry
2. Trading mode
3. Account status
4. Buying power
5. Daily loss limit
6. Maximum drawdown
7. Position sizing
8. Portfolio exposure
9. Correlation limits
10. Market conditions
11. News restrictions
12. Broker health
13. Kill switches
14. Final approval

# Risk Budgets

- Per Trade
- Daily
- Weekly
- Monthly
- Quarterly
- Yearly
- Lifetime

# Supported Assets

- Stocks
- ETFs
- Futures (NQ, MNQ, ES, MES, YM, MYM, RTY, CL, GC, etc.)
- Options
- Forex
- Crypto

# Position Sizing

Inputs:
- Account balance
- Risk %
- Dollar risk
- ATR
- Stop distance
- Tick size/value
- Contract specifications
- Instrument type

Outputs:
- Shares
- Contracts
- Lots
- Position value

# Capital Preservation

Supports:
- Daily stop
- Weekly stop
- Profit lock
- Trailing equity protection
- "40% of previous green day" protection rule
- Consecutive loss protection

# Prop Firm Support

Configurable templates:
- Daily loss
- Trailing drawdown
- Static drawdown
- Max contracts
- Consistency rules
- Payout rules
- Evaluation/Funded modes

# Kill Switches

- Daily loss
- Maximum drawdown
- Broker disconnected
- Bad market data
- High latency
- Market halt
- Emergency stop
- Manual stop
- System health failure

# States

PENDING
VALIDATING
APPROVED
REJECTED
BLOCKED
EMERGENCY_STOP

# Database Tables

- risk_rules
- risk_profiles
- risk_decisions
- risk_budgets
- daily_loss_limits
- capital_preservation_rules
- kill_switch_events

# Events Published

- risk.approved
- risk.rejected
- risk.warning
- risk.kill_switch
- risk.limit_reached

# Performance Targets

Validation: <5 ms
Deterministic execution
No blocking database operations
No ML training
No LLM execution

# Security Rules

- Cannot be bypassed
- Every decision audited
- Broker truth respected
- Live mode required
- Trace ID on every decision

# Future Implementations

- Dynamic volatility budgets
- Adaptive position sizing
- Portfolio VaR
- Stress testing
- Scenario analysis
- Institutional hedging
- Cross-account optimization

# Relationships

Depends on:
- Trading OS Core
- Portfolio Intelligence
- Account Management
- Capability Registry

Provides decisions to:
- Execution Core
- Order Manager
- Position Management

# Regeneration Status

✅ Regenerated
Official source of truth for the Risk Engine.
