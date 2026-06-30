# Execution Core
**Status:** ✅ Regenerated  
**Module ID:** EC-001  
**Version:** 1.0 (Architecture Regeneration)

> This document is the official regenerated specification for the Execution Core based on the agreed Trading OS architecture. It supersedes earlier discussion notes.

---

# Purpose

The Execution Core is responsible for safely transforming an approved trade candidate into an executed order while enforcing all safety gates. It never creates trading ideas, changes risk rules, or bypasses the Risk Engine.

---

# Responsibilities

- Receive approved trade candidates
- Validate execution prerequisites
- Route trades to Development, Replay, Paper, or Live mode
- Submit orders through the Broker Framework
- Track execution lifecycle
- Record execution telemetry
- Publish execution events
- Hand control to the Position Management Engine after fill

---

# Scope

The Execution Core **does not**:
- Generate signals
- Change strategies
- Override risk decisions
- Retrain ML models
- Allow LLMs to place trades

---

# Inputs

- Approved Trade Candidate
- Risk Decision
- Portfolio Allocation
- Account Information
- Broker Status
- Capability Registry
- Execution Mode

---

# Outputs

- Order Request
- Order Events
- Execution Metrics
- Position Open Event
- Audit Records

---

# Architecture

```text
Strategy Decision Engine
        │
Risk Engine
        │
Portfolio Intelligence
        │
Decision Orchestrator
        │
════════════════════════════
      EXECUTION CORE
════════════════════════════
Execution Validator
Order Builder
Mode Router
Broker Dispatcher
Execution Tracker
Telemetry Collector
════════════════════════════
        │
Broker Framework
```

# Execution Modes

- Development
- Replay
- Paper Trading
- Live Trading

Only one mode may be active for an execution path.

---

# Validation Pipeline

1. Capability Registry
2. Live Mode enabled?
3. Risk approved?
4. Account active?
5. Broker connected?
6. Market open?
7. Instrument tradable?
8. Position sizing valid?
9. Duplicate order check
10. Kill switch check
11. Submit order

Failure at any stage blocks execution.

---

# State Machine

```text
RECEIVED
↓
VALIDATING
↓
READY
↓
SUBMITTING
↓
ACCEPTED
↓
PARTIAL_FILL
↓
FILLED
↓
POSITION_OPEN
↓
COMPLETE

ERROR
REJECTED
CANCELLED
EXPIRED
```

# Error Handling

- Broker timeout
- Order rejection
- Partial fill
- Network interruption
- Duplicate submission
- Position mismatch
- Market halt
- Margin rejection

All errors generate audit events and incident records.

---

# Performance Targets

- Validation: <5 ms
- Internal routing: <2 ms
- Order build: <2 ms
- ML inference is completed before reaching Execution Core.
- Execution Core performs no heavy computation.

---

# Security Rules

- Risk Engine cannot be bypassed.
- LLM cannot submit orders.
- Broker keys remain inside Broker Framework.
- Every execution has a trace ID.
- Every action is audited.

---

# Database Records

- orders
- order_events
- fills
- execution_latency_logs
- audit_logs

---

# Published Events

- order.created
- order.submitted
- order.accepted
- order.partially_filled
- order.filled
- order.rejected
- position.opened

---

# Related Modules

- Trading OS Core
- Decision Orchestrator
- Risk Engine
- Portfolio Intelligence
- Broker Framework
- Order Manager
- Position Management Engine

---

# Future Implementations

- Smart order routing
- Iceberg orders
- TWAP/VWAP execution
- Adaptive execution
- Multi-broker execution
- Institutional execution algorithms

Future implementations must pass Replay, Paper Trading, and User Approval before Live activation.

---

# Regeneration Status

✅ Regenerated from agreed architecture.
This document is now considered the authoritative specification for the Execution Core.
