
# Risk Rule Library
**Status:** ✅ Regenerated
**Module ID:** RRL-001
**Version:** 1.0

> Official Risk Rule Library for the Trading OS.

# Purpose

This document is the authoritative catalog of all risk rules enforced by the Trading OS. Every trade, strategy, account, and portfolio must comply with these rules before execution.

# Core Principles

- Capital preservation before profit
- Risk Engine has final authority
- Rules are deterministic
- Rules are versioned and auditable
- Replay → Paper → Live validation required

# Rule Categories

## Account Rules
- Maximum daily loss
- Maximum total drawdown
- Trailing drawdown
- Buying power validation
- Margin validation

## Position Rules
- Maximum position size
- Maximum open positions
- Position concentration
- Correlation limits

## Trade Rules
- Maximum risk per trade
- Minimum risk-to-reward ratio
- Stop-loss required
- Position sizing validation

## Portfolio Rules
- Total portfolio exposure
- Sector exposure
- Asset allocation
- Cross-account exposure

## News Rules
- High-impact news restrictions
- Scheduled event protection
- Volatility safeguards

## Evaluation Account Rules
- Static drawdown
- Trailing drawdown
- Consistency rule
- Green-day preservation rule
- Daily profit targets
- Maximum loss lockout

## User-Defined Rules
- Custom risk profiles
- Trading schedules
- Symbol restrictions
- Strategy restrictions

# Rule Lifecycle

DESIGNED
IMPLEMENTED
VALIDATED
ACTIVE
DEPRECATED
RETIRED

# Rule Metadata

Each rule contains:
- Rule ID
- Name
- Description
- Trigger
- Threshold
- Severity
- Enforcement Action
- Applicable Accounts
- Version History

# Enforcement Actions

- Warning
- Reduce position size
- Reject trade
- Pause strategy
- Pause account
- Activate kill switch

# Regeneration Status

✅ Regenerated

Official Risk Rule Library for the Trading OS.
