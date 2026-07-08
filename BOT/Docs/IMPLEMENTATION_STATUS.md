# BOT — Implementation Status

Maturity per module. `documentation` = spec only · `coded` = exists, untested · `tested` =
has tests / validated · `replay` / `paper` / `live` = proven at that stage. Updated 2026-06-29.

| Module | File(s) | State | Notes |
|--------|---------|-------|-------|
| Config + credentials | `bot/config.py`, `config/.env.example` | **coded** | key-ready; live HARD-LOCKED (needs `config/LIVE_APPROVED.lock`) |
| Local data loader (CBBO + MBO) | `bot/market_data/databento_local.py` | **coded** | verified on the D: data; handles `.zst` AND extracted `.csv` layouts |
| Databento API puller | `bot/market_data/databento_feed.py` | **coded** | historical OHLCV → continuous parquet; live `stream_live` stubbed |
| Canonical contracts | `bot/contracts.py` | **tested** | all 8 objects, enums, state machines, fail-closed, JSON round-trip — self-test passes |
| Strategy → TradeCandidate | `bot/strategy/orb_candidates.py` | **tested** | wraps validated engine ORB + F61; 433 QQQ candidates emitted |
| Market-truth gate | `bot/market_truth.py` | **tested** | fail-closed stale/gap/dup/bad-OHLC; self-test passes |
| Risk gate v1 | `bot/risk.py` | **tested** | `RiskDecision`, Evidence limits, sizing; every block/reject path tested |
| Replay broker + pipeline | `bot/execution/replay_broker.py`, `bot/replay.py` | **tested** | deterministic end-to-end; reconciles to engine (QQQ +0.280 R/trade gross, engine net +0.264, +121 R) |
| Alpaca paper / futures brokers | `bot/brokers/` | documentation | next — see REMAINING_FEATURES.md §A |
| Order-flow direction engine | `bot/orderflow/` (QI/OFI/ATI/CD) | documentation | MBO phase — REMAINING_FEATURES.md §B |
| Journal store / DB | `bot/journal/`, schema | documentation | REMAINING_FEATURES.md §E |

## Pine / engine (running in parallel — see production/CHANGELOG.md)

| Item | State |
|------|-------|
| Marker placement fix (FILL/TP1/TP2/STOP/CALL/PUT at real price) | **done** STACK, OPTIONS, AUTO — needs TV compile-check |
| Direction-sequence gate (F61) | **done + validated** engine + STACK; propagate to OPTIONS/AUTO/V1 next |
| No-chase guard | tested → **left OFF** (costs edge, F57/F61) |

## What's left

The full checklist is in **`REMAINING_FEATURES.md`**. Top of the queue:
1. Alpaca **paper** broker adapter (same interface as ReplayBroker; keys are wired) — §A.
2. Shadow mode + reconcile the replay broker R vs the engine — §G/§I.
3. The **MBO order-flow direction engine** (book builder + QI/OFI/score + state machine) — §B (biggest edge upside).
4. Pine housekeeping: propagate F61 to OPTIONS/AUTO/V1 + TV compile-check — §K.
