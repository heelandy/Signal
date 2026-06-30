
# API Endpoint Reference
**Status:** ✅ Regenerated
**Module ID:** APIREF-001
**Version:** 1.0

> Official API Endpoint Reference for the Trading OS.

# Purpose

This document defines the REST, WebSocket, and internal service endpoints exposed by the Trading OS. It establishes naming conventions, versioning, authentication, request/response standards, and endpoint responsibilities.

# API Design Principles

- Versioned APIs (/v1, /v2, ...)
- Stateless REST endpoints
- JWT authentication
- RBAC authorization
- Idempotent write operations where applicable
- Consistent JSON responses
- UTC timestamps
- Correlation IDs for tracing

# Endpoint Groups

## Authentication

POST /api/v1/auth/login

POST /api/v1/auth/logout

POST /api/v1/auth/refresh

GET /api/v1/auth/profile

## Accounts

GET /api/v1/accounts

GET /api/v1/accounts/{id}

PATCH /api/v1/accounts/{id}

POST /api/v1/accounts/sync

## Market Data

GET /api/v1/market/quote

GET /api/v1/market/candles

GET /api/v1/market/orderbook

GET /api/v1/market/news

## Strategies

GET /api/v1/strategies

POST /api/v1/strategies

PATCH /api/v1/strategies/{id}

POST /api/v1/strategies/{id}/paper

## Risk

GET /api/v1/risk/status

GET /api/v1/risk/rules

POST /api/v1/risk/evaluate

## Orders

POST /api/v1/orders

PATCH /api/v1/orders/{id}

DELETE /api/v1/orders/{id}

GET /api/v1/orders

## Positions

GET /api/v1/positions

GET /api/v1/positions/{id}

POST /api/v1/positions/close

## Portfolio

GET /api/v1/portfolio

GET /api/v1/performance

GET /api/v1/journal

## Machine Learning

GET /api/v1/ml/models

POST /api/v1/ml/train

GET /api/v1/ml/performance

## Administration

GET /api/v1/admin/health

GET /api/v1/admin/incidents

GET /api/v1/admin/configuration

PATCH /api/v1/admin/configuration

# WebSocket Channels

- market.stream
- order.stream
- position.stream
- portfolio.stream
- risk.stream
- incident.stream
- notification.stream

# Standard Response

{
  "success": true,
  "requestId": "...",
  "timestamp": "...",
  "data": {}
}

# Error Response

{
  "success": false,
  "errorCode": "...",
  "message": "...",
  "traceId": "..."
}

# Regeneration Status

✅ Regenerated

Official API endpoint reference for the Trading OS.
