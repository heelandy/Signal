
# Prop Firm Rule Library
**Status:** ✅ Regenerated
**Module ID:** PFR-001
**Version:** 1.0

> Official Prop Firm Rule Library for the Trading OS.

# Purpose

This document defines the configurable rule framework used to support evaluation, funded, and challenge accounts from proprietary trading firms. Rules are parameterized so new firms can be added without changing core application logic.

# Design Principles

- Firm-agnostic architecture
- Versioned rule sets
- User-selectable templates
- Custom overrides supported
- Fully auditable
- Enforced by the Risk Engine and Capital Preservation Engine

# Supported Rule Categories

## Account Rules
- Account size
- Buying power
- Leverage
- Margin requirements

## Drawdown Rules
- Static drawdown
- Trailing drawdown
- End-of-day trailing
- Intraday trailing

## Daily Loss Rules
- Maximum daily loss
- Daily lockout
- Daily reset time

## Profit Rules
- Profit target
- Minimum trading days
- Consistency percentage
- Maximum single-day profit percentage

## Position Rules
- Maximum contracts/shares
- Scaling plans
- Overnight holding
- Weekend holding

## News Rules
- Trade during high-impact news
- Hold through news
- Restricted windows

## Evaluation Rules
- Challenge phases
- Verification phases
- Funded account transition
- Payout eligibility

# User-Defined Rules

The Trading OS allows users to:
- Create custom firms
- Import rule templates
- Modify thresholds
- Save versioned profiles

# Enforcement

Possible actions:
- Warning
- Reduce position size
- Reject trade
- Lock account
- Pause trading
- Trigger kill switch

# Validation

Every rule set must pass:
- Replay validation
- Paper validation
- Configuration verification

# Regeneration Status

✅ Regenerated

Official Prop Firm Rule Library for the Trading OS.
