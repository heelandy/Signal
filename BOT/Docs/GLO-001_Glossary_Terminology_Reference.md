
# Glossary & Terminology Reference
**Status:** ✅ Regenerated
**Module ID:** GLO-001
**Version:** 1.0

> Official glossary for the Trading OS.

# Purpose

This glossary establishes a single, authoritative definition for terminology used throughout the Trading OS documentation, implementation, testing, and operations.

# Core Terms

## Market Truth
The canonical normalized market state produced after reconciling all approved market data providers.

## Security DNA
A continuously evolving behavioral profile describing how an individual instrument typically behaves across market regimes.

## Replay
Deterministic reconstruction of historical trading sessions using archived Market Truth and historical system state.

## Paper Trading
Real-time simulation using live market data without risking capital.

## Live Trading
Execution of real orders through a connected brokerage after all validation gates have been satisfied.

## Capability Registry
Central authority that determines whether a feature is available in Development, Replay, Paper, or Live environments.

## Risk Engine
Highest authority responsible for approving or rejecting every trading action.

## Capital Preservation Engine
Protective subsystem responsible for enforcing drawdown limits, evaluation account rules, and capital protection policies.

## Execution Core
Subsystem responsible for converting approved trade decisions into broker-ready execution requests.

## Trading Knowledge Brain
Long-term institutional memory storing validated knowledge, research findings, lessons learned, and historical relationships.

## AI Research Lab
Isolated experimentation environment where new strategies, models, and ideas are validated before production.

## Champion / Challenger
Framework that compares production logic against experimental alternatives using replay and paper trading.

## Opening Range Matrix
Framework tracking Opening Range Blocks across multiple timeframes.

## Global Market Intelligence
Macro-economic and cross-asset context supplied to trading decisions.

## Decision Intelligence
Engine responsible for explaining why every trade was accepted, rejected, modified, or exited.

## Replay Validation
Mandatory verification stage before Paper Trading.

## Paper Validation
Mandatory verification stage before Live Trading.

## Market Opportunity Queue
Priority queue containing validated trading opportunities awaiting risk review.

## Broker Truth
The broker's order and position state, considered authoritative during reconciliation.

# Abbreviations

- ADR – Architecture Decision Record
- API – Application Programming Interface
- CI/CD – Continuous Integration / Continuous Delivery
- ML – Machine Learning
- LLM – Large Language Model
- OMS – Order Management System
- RBAC – Role-Based Access Control
- RPO – Recovery Point Objective
- RTO – Recovery Time Objective
- R:R – Risk-to-Reward Ratio

# Regeneration Status

✅ Regenerated

Official terminology reference for the Trading OS.
