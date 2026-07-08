# Account Management Engine
**Status:** ✅ Regenerated
**Module ID:** AME-001
**Version:** 1.0

> Official regenerated specification for the Trading OS Account Management Engine.

# Purpose

The Account Management Engine is responsible for managing all trading accounts, balances, account states, prop firm configurations, broker synchronization, and account-specific rules.

# Responsibilities

- Manage multiple trading accounts
- Synchronize balances with brokers
- Support paper, evaluation, funded, and personal accounts
- Track buying power and equity
- Store account-specific rules
- Monitor account status
- Coordinate with Risk Engine and Portfolio Intelligence

# Supported Account Types

- Paper Trading
- Replay
- Personal Brokerage
- Evaluation Account
- Funded Prop Firm
- Retirement Account
- Research Account

# Architecture

```text
              ACCOUNT MANAGEMENT ENGINE

Trading Profiles
        │
Trading Accounts
        │
──────────────────────────────────────
Account Registry
Balance Sync
Buying Power Monitor
Equity Tracker
Account Rules
Broker Sync
Prop Firm Profiles
Account Health
──────────────────────────────────────
        │
Risk Engine
Portfolio Intelligence
Execution Core
```

# Core Features

- Unlimited account support
- Dynamic account size updates
- Automatic broker synchronization
- Manual adjustment history
- Account health monitoring
- Currency support
- Multi-broker compatibility

# Account Status

ACTIVE

PAPER

REPLAY

LIVE

EVALUATION

FUNDED

PAUSED

LOCKED

SUSPENDED

ARCHIVED

# Prop Firm Support

Supports configurable templates for:

- Apex
- Topstep
- Take Profit Trader
- MyFundedFutures
- Bulenox
- Tradeify
- Custom Firms

Rules stored separately from account logic.

# Account Metrics

- Balance
- Equity
- Buying Power
- Available Margin
- Unrealized P/L
- Realized P/L
- Daily P/L
- Weekly P/L
- Monthly P/L
- Lifetime Performance

# Events

- account.created
- account.updated
- account.synced
- account.locked
- account.unlocked
- account.balance_changed
- account.health_changed

# Database Tables

- trading_accounts
- account_balances
- account_rules
- account_history
- broker_accounts
- prop_firm_profiles

# Performance

Synchronization Target:

<100 ms after broker response

Balance updates should propagate immediately to:
- Risk Engine
- Portfolio Intelligence
- Dashboard
- Performance Engine

# Security

- One user owns all accounts
- Encrypted broker credentials
- Full audit trail
- Live account confirmation required
- No cross-account leakage

# Future Implementations

- Cross-account optimization
- Automatic account rotation
- Portfolio allocation across accounts
- Multi-currency accounts
- Tax tracking
- Broker migration assistant

# Relationships

Depends on:
- Broker Framework

Provides services to:
- Risk Engine
- Capital Preservation Engine
- Portfolio Intelligence
- Execution Core
- Performance Intelligence

# Regeneration Status

✅ Regenerated

Official source of truth for the Account Management Engine.
