# Master Architecture Decision Records (ADR)
**Status:** ✅ Regenerated
**Module ID:** ADR-001
**Version:** 1.0

> Official Architecture Decision Record index for the Trading OS.

# Purpose

This document records the major architectural decisions that govern the Trading OS. Each decision includes its rationale, consequences, alternatives considered, and current status.

# ADR Format

Every ADR contains:
- Decision ID
- Title
- Status
- Context
- Decision
- Alternatives Considered
- Consequences
- Related Modules
- Version History

# Key Approved Decisions

## ADR-001
Trading OS follows a modular, event-driven architecture.

## ADR-002
Risk Engine is the highest authority for trade approval.

## ADR-003
Market Truth Engine is the single authoritative market feed.

## ADR-004
Broker truth is authoritative for orders and positions.

## ADR-005
Replay → Paper → User Approval → Live is mandatory.

## ADR-006
Machine Learning may assist decisions but cannot bypass Risk Engine.

## ADR-007
LLMs are reserved for explanation, research, and future augmentation—not live execution.

## ADR-008
Capability Registry governs feature maturity and activation.

## ADR-009
Trading Knowledge Brain preserves institutional memory.

## ADR-010
Continuous learning occurs through replay and paper trading before production promotion.

## ADR-011
Retail-first user experience with institutional-grade architecture.

## ADR-012
Every module is independently versioned and regenerated.

# Governance

Architectural changes require:
1. New ADR
2. Impact assessment
3. Documentation update
4. Validation
5. Version increment

# Outputs

- Architecture history
- Decision traceability
- Change governance
- Engineering reference

# Regeneration Status

✅ Regenerated

Official source of truth for Trading OS Architecture Decision Records.
