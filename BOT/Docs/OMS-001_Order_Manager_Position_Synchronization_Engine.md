# Order Manager & Position Synchronization Engine
**Status:** ✅ Regenerated
**Module ID:** OMS-001
**Version:** 1.0

> Official regenerated specification for the Trading OS Order Manager & Position Synchronization Engine.

# Purpose

The Order Manager & Position Synchronization Engine guarantees that the Trading OS and the broker always maintain a consistent view of orders and positions. It manages the complete lifecycle of every order while continuously reconciling broker state.

# Responsibilities

- Create and track orders
- Monitor order lifecycle
- Track fills and partial fills
- Synchronize broker positions
- Detect mismatches
- Resolve synchronization issues
- Publish order and position events

# Core Philosophy

Broker truth always wins.

The Trading OS must never assume its internal state is correct without broker reconciliation.

# Architecture

```text
Execution Core
      │
══════════════════════════════
 ORDER MANAGER & POSITION SYNC
══════════════════════════════
Order Registry
Order Tracker
Fill Tracker
Modify Manager
Cancel Manager
Position Tracker
Broker Reconciliation
Mismatch Detector
══════════════════════════════
      │
Broker Framework
```

# Order States

CREATED

VALIDATED

SUBMITTED

ACCEPTED

PARTIALLY_FILLED

FILLED

MODIFY_PENDING

MODIFIED

CANCEL_PENDING

CANCELLED

REJECTED

EXPIRED

ERROR

# Position States

NO_POSITION

OPENING

OPEN

PARTIAL

REDUCING

CLOSING

CLOSED

MISMATCH

UNKNOWN

EMERGENCY

# Reconciliation

The engine continuously compares:

- Internal position
- Broker position
- Internal orders
- Broker orders

If a mismatch is detected:

- Pause affected workflow
- Request broker refresh
- Resolve discrepancy
- Notify Observability
- Log incident

# Outputs

- Order status
- Position status
- Synchronization status
- Broker reconciliation report

# Events

- order.created
- order.updated
- order.filled
- order.cancelled
- position.synced
- position.mismatch
- reconciliation.completed

# Database Tables

- orders
- order_events
- fills
- positions
- position_events
- position_reconciliations

# Performance Targets

- Near real-time synchronization
- Automatic reconciliation
- Replay identical to live
- Low-latency event processing

# Security

- Broker truth is authoritative
- Full audit logging
- No direct user modification of broker state

# Future Implementations

- Multi-broker synchronization
- Cross-account reconciliation
- Smart fill aggregation
- Institutional allocation support
- Automated recovery workflows

# Relationships

Depends on:
- Broker Framework
- Execution Core

Provides:
- Position Management Engine
- Performance Intelligence
- Trade Lifecycle Journal
- Observability Platform

# Regeneration Status

✅ Regenerated

Official source of truth for the Order Manager & Position Synchronization Engine.
