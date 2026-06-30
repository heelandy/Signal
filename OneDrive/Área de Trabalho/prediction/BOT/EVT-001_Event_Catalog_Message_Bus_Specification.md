
# Event Catalog & Message Bus Specification
**Status:** ✅ Regenerated
**Module ID:** EVT-001
**Version:** 1.0

> Official event catalog and message bus specification for the Trading OS.

# Purpose

This document defines the standard event-driven communication model used throughout the Trading OS. Every module publishes and subscribes to versioned domain events through the central Event Bus.

# Event Design Principles

- Immutable events
- Versioned schemas
- Idempotent consumers
- At-least-once delivery
- Correlation IDs
- Trace IDs
- UTC timestamps

# Standard Event Envelope

- event_id
- event_type
- event_version
- source_module
- timestamp_utc
- correlation_id
- trace_id
- payload

# Event Domains

## Market
- market.tick
- market.candle.closed
- market.truth.updated
- market.session.changed

## Strategy
- strategy.signal.created
- opportunity.queued
- opportunity.expired

## Risk
- risk.approved
- risk.rejected
- capital.rule.triggered

## Execution
- order.submitted
- order.accepted
- order.filled
- order.cancelled
- position.opened
- position.closed

## Learning
- journal.created
- performance.updated
- learning.completed
- model.trained

## Infrastructure
- health.changed
- incident.created
- deployment.completed
- backup.completed

# Consumer Rules

- Events must never modify historical payloads.
- Consumers must tolerate duplicate delivery.
- Failed events move to a dead-letter queue.
- Retry policy is configurable.

# Message Bus Responsibilities

- Routing
- Filtering
- Retry
- Dead-letter handling
- Ordering (where required)
- Observability
- Metrics

# Regeneration Status

✅ Regenerated

Official source of truth for Trading OS event architecture.
