# Database Architecture
**Status:** ✅ Regenerated
**Module ID:** DBA-001
**Version:** 1.0

> Official regenerated specification for the Trading OS Database Architecture.

# Purpose

The Database Architecture defines the persistent storage layer for the Trading OS. It stores operational data, historical records, configuration, learning artifacts, and audit history while ensuring consistency, scalability, and high performance.

# Responsibilities

- Persist all operational data
- Maintain transactional integrity
- Support replay and historical analysis
- Provide ML-ready datasets
- Preserve complete audit history
- Version critical entities
- Support future horizontal scaling

# Core Philosophy

PostgreSQL stores authoritative operational data.

Redis stores temporary high-speed state.

The Data Lake stores long-term historical and research data.

# Architecture

```text
Application Layer
        │
══════════════════════════════
 DATABASE ARCHITECTURE
══════════════════════════════
PostgreSQL
Redis
Object Storage
Data Lake
══════════════════════════════
        │
Trading OS Modules
```

# Schema Groups

- Core Platform
- Users & Profiles
- Accounts
- Brokers
- Instruments
- Market Data
- Feature Store
- Strategies
- Trade Candidates
- Risk
- Orders
- Positions
- Journal
- Machine Learning
- Performance
- Knowledge
- Configuration
- Audit
- Incidents

# Core Tables

## Platform
- users
- roles
- permissions
- sessions
- api_keys

## Trading
- trading_accounts
- brokers
- instruments
- symbols
- orders
- order_events
- fills
- positions

## Market

- market_ticks
- market_candles
- market_truth_candles
- feature_snapshots
- opening_ranges

## Strategy

- strategies
- strategy_versions
- trade_candidates
- opportunity_queue

## Risk

- risk_rules
- risk_decisions
- risk_budgets
- capital_preservation_rules

## Learning

- trade_journals
- learning_labels
- ml_models
- model_versions
- experiments
- knowledge_objects

## Performance

- strategy_performance
- portfolio_performance
- execution_performance
- ml_performance

## Governance

- capability_registry
- configuration_history
- audit_logs
- incidents

# Design Rules

- UUID primary keys
- UTC timestamps
- Soft delete where appropriate
- Immutable audit history
- Version critical entities
- Foreign key integrity
- Indexed lookup fields

# Performance Targets

- Optimized indexes
- Partition historical tables
- Read replicas (future)
- Connection pooling
- Efficient pagination

# Security

- Least-privilege access
- Encrypted secrets
- Row ownership validation
- Complete audit trail
- Backup and recovery procedures

# Future Implementations

- Table partitioning
- Multi-region replication
- Time-series optimization
- Data compression
- Archive automation

# Relationships

Provides persistence for every Trading OS module.

Works with:
- Data Lake
- API Layer
- Trading Knowledge Brain
- Machine Learning Platform

# Regeneration Status

✅ Regenerated

Official source of truth for the Database Architecture.
