
# Database Schema Reference
**Status:** ✅ Regenerated
**Module ID:** DBS-001
**Version:** 1.0

> Official Database Schema Reference for the Trading OS.

# Purpose

This document serves as the authoritative reference for the Trading OS database schema. It defines schema organization, naming conventions, table groups, relationships, indexing standards, and migration policies.

# Database Technologies

- PostgreSQL (authoritative operational database)
- Redis (cache and ephemeral state)
- Object Storage (artifacts and media)
- Data Lake (historical archives)

# Schema Organization

## Identity
- users
- roles
- permissions
- sessions
- api_keys

## Accounts
- trading_accounts
- broker_accounts
- account_balances
- account_snapshots

## Market
- symbols
- instruments
- market_ticks
- market_candles
- market_truth
- opening_ranges

## Trading
- trade_candidates
- risk_decisions
- orders
- order_events
- fills
- positions
- executions

## Portfolio
- portfolios
- allocations
- exposure_history

## Learning
- trade_journals
- performance_metrics
- ml_models
- experiments
- knowledge_objects

## Governance
- capability_registry
- configuration_history
- audit_logs
- incidents

# Naming Standards

- snake_case table names
- UUID primary keys
- created_at / updated_at timestamps
- UTC for all time fields
- Foreign keys explicitly named

# Relationship Rules

- Enforce referential integrity
- Soft deletes only where appropriate
- Immutable audit history
- Version critical business entities

# Indexing Guidelines

- Primary keys indexed
- Foreign keys indexed
- Frequently filtered columns indexed
- Composite indexes for common query patterns
- Partition large historical tables

# Migration Policy

- Version-controlled migrations
- Forward-only in production
- Tested in Replay before deployment
- Rollback strategy documented

# Regeneration Status

✅ Regenerated

Official database schema reference for the Trading OS.
