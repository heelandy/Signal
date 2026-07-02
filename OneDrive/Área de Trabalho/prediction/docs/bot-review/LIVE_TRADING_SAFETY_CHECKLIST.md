# Live Trading Safety Checklist — bot review 2026-07-02

Status legend: ✅ verified in this review (code + test) · ⚠ verified with conditions · ❌ open —
must be closed before ever creating `LIVE_APPROVED.lock`.

| # | Control | Status | Evidence |
|---|---|---|---|
| 1 | **Paper mode verified** | ✅ | `AlpacaBroker(paper=True)` default from `ALPACA_PAPER=true`; `_paper_broker()` hardcodes `paper=True`; toggle refuses when `ALPACA_PAPER=false` (`test_paper_autotrade_toggle_requires_paper_mode`). `start.ps1` defaults `BOT_MODE=paper`. |
| 2 | **Live mode disabled by default** | ✅ | Four independent gates: `settings.live_allowed` requires `BOT_MODE=live` **and** `config/LIVE_APPROVED.lock`; `risk.decide` → `LIVE_LOCKED`; `Orchestrator.__post_init__` raises; `AlpacaBroker.__init__` raises on live without the lock. Test: `test_live_locked_by_default`. |
| 3 | **Kill switch verified** | ✅ | `/api/control/kill` arm always available, disarm token-gated (HS-H6); blocks webhook orders (`test_kill_switch_blocks_webhook`), ticket orders, the scan loop, and `risk.decide` (Account.kill_switch → first-checked block). |
| 4 | **Daily-loss limit verified** | ✅ | `risk.decide` blocks at −0.75 % equity (`test_risk_blocks[dailyloss]`); Pine EVAL daily halt with early-halt buffer; prop engine daily floor. |
| 5 | **Stale-data gate verified** | ✅ (new) | `live.source_health` (market-truth QA + 15-min bar age) → `SOURCE_HEALTH_CRITICAL` block; paper autotrade skips stale feeds. Tests: 3 (fresh passes, stale/dirty/empty blocked). |
| 6 | **Reconciliation verified** | ⚠ | `oms.reconcile` — broker truth wins, mismatch → `MISMATCH` phase (tested); `bot.reconcile` poller exists. **Condition:** mismatch currently pauses the symbol, it does not auto-trip the kill switch, and no scheduled poller runs in the server loop — wire `reconcile_once` into `_scan_loop` + kill-on-mismatch before live. |
| 7 | **Duplicate-order prevention verified** | ✅ (new) | Webhook + manual ticket idempotency dedup; deterministic `client_order_id` to Alpaca (broker dedup across restarts); OMS ignores duplicate fill events. Tests: 6. **Condition:** in-process key set resets on restart — Alpaca covered by client_order_id; persist the key set before using non-Alpaca bridges. |
| 8 | **Secrets verified** | ⚠ | `.env` ignored; template placeholder-only; no keys in code; API/webhook token constant-time. **Condition:** the previously committed Webull token is still in git history — ROTATE it (and ideally rewrite history) before treating the repo as clean. |
| 9 | **Monitoring verified** | ⚠ | `/api/health`, capability registry, scan error surface, provider status panel exist. **Condition:** `health.source_healthy` is hardcoded `true` at the endpoint (display only — the real gate is per-scan); no alerting/paging exists. Add real health aggregation + an external alert before live. |
| 10 | **Emergency-close process verified** | ✅ | `/api/flatten` → `close_all_positions(cancel_orders=True)`; webhook `exit/close` events flatten; Pine session-end + eval-halt flatten with broker-held brackets as the dead-pipe fallback. Exits are never blocked by entry gates. |

## Pre-live gate (all must be true before creating `LIVE_APPROVED.lock`)

1. Webull token rotated; history cleaned or repo access restricted.
2. TradingView compile + ≥2-week forward paper test of the edited STACK/AUTO scripts (HS-H4).
3. Broker fill stream wired to OMS + restart-recovery test on the paper account.
4. Reconcile poller scheduled + mismatch trips the kill switch automatically.
5. Early-close calendar + news lockout feed wired (HS-M8/M9).
6. `API_REQUIRE_AUTH=true` set; server still bound to localhost or behind an authenticated proxy.
7. Scorecard gate green: live tracked grade-A expectancy consistent with the backtest reference
   (`/api/scorecard`, ≥12 closed taken trades — now conservative after HS-H5).
8. Maximum live order size configured (risk gate `max_contracts` / notional cap reviewed for the
   live account size) and a written emergency runbook (kill → flatten → broker portal fallback).
