# Paper → Live: how the BOT trades after approval (2026-07-04)

The execution path after you click approve, and every gate between here and real money.

## The ladder (enforced in code, all manual, all audited)

```text
research ──► replay ──► PAPER ──► LIVE
             │           │          │
             │           │          └─ needs BOTH: LIVE_APPROVED.lock file (config.py hard lock)
             │           │             AND the 'live' approval stage (server /api/control/mode
             │           │             refuses live without either — double gate, AITP phase 8)
             │           └─ paper autotrade HARD-BLOCKED until the 'paper' stage is approved
             │              (one-click button on /training walks research→replay→paper)
             └─ replay-parity report must be green (research/replay_parity.py — currently
                100% on QQQ/SPY/NQ/ES: candidates ≡ engine trades)
```

## How PAPER trading executes (available today)

1. You approve the ladder (Training Lab → "✓ APPROVE strategy + enable PAPER trade").
2. The always-on scanner (`bot.api.server` `_scan_loop`, every 60s) emits rule-valid proposals
   with grade, P(win), heads, ensemble verdict.
3. `_paper_autotrade()` places **grade-sized bracket orders on the Alpaca PAPER account**
   (hardcoded `paper=True` — this code path *cannot* touch a live account): equities QQQ/SPY,
   market entry + stop + TP2 bracket, dedup-keyed, stale-feed and zone-invalid signals skipped.
   The approval gate is re-checked EVERY cycle — a revoke disarms mid-session.
4. Futures paper: TradingView AUTO strategy fires webhooks → `/webhook/tradingview` → risk gate →
   broker adapter in paper mode (or shadow-log when no broker for that mode).
5. Every fill/skip lands in the tracker → first-touch outcomes → **paper-vs-backtest scorecard**
   (`/api/scorecard`) — the exit gate for phase 6.

## What LIVE will require (phase 7–8 — in order)

1. **Green paper scorecard**: taken paper signals realize the backtested per-grade edge over a
   defined window (suggested: ≥60 trades or 8 weeks, whichever later; expectancy within CI of
   backtest; no grade inversion). Served by `/api/scorecard`.
2. **Execution-quality report**: paper slippage + fill latency measured vs the cost-stress
   assumptions (`backtest_matrix.json` — note ES flips negative at 2× slip: ES stays OFF live
   until measured execution beats the stress case).
3. **Production hardening** (phase 7): broker fill stream + reconcile scheduling + restart
   recovery + health alerting (open items in LIVE_TRADING_SAFETY_CHECKLIST.md).
4. **Risk config review**: per-trade 0.25%, daily 0.75%, weekly 2%, trailing 3%, streak lockout,
   correlated buckets — sign-off recorded via the approval notes.
5. **Manual 'live' approval** on the ladder AND creating `LIVE_APPROVED.lock`. Either alone is
   not enough; revoking either kills live mode.
6. First live phase: **minimum size, equities only** (1 share-lot / micro contracts), kill switch
   rehearsed, daily reconcile vs broker statements.

## Kill paths (always available)

- Kill switch (`/api/control/kill`, always allowed to ARM without auth) → blocks all submits.
- Revoke any approval stage → downstream stages fall with it, autotrade disarms next cycle.
- Mode switch back to paper/shadow clears the broker cache instantly.
