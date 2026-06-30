# BOT — Remaining & Missing Implementation (current, 2026-06-29)

What's built is the auditable signal-provider: 4-family scan (per-asset config) → risk → P(win) →
order-flow → 0DTE options (naked/debit/credit, TP1 1.5R / TP2 4R) → journal + SQLite → dashboard +
TV webhook. Below is everything **still remaining**, grouped by what blocks it.

Legend: 🌐 needs a deploy/runtime environment · 🔬 needs research · 🔌 needs an external account/feed ·
🛠 buildable now · ⚠️ honesty flag.

## A. Deployment / runtime (🌐 — not code, needs hosting)
- [ ] Public HTTPS endpoint for the TV webhook (ngrok / Cloudflare tunnel / cloud VM) — receiver is built, localhost-only.
- [ ] Containerize (Docker) + run the live loop & API server as managed services (systemd/pm2/compose).
- [ ] Monitoring + alerting (Prometheus/Grafana) and centralized logs.
- [ ] Backup/restore + DR for `data/highstrike.db` + `journal.jsonl`.
- [ ] CI/CD (run pytest on push, deploy).

## B. Data (🔌 — needs accounts/feeds)
- [ ] **Databento LIVE feed** (real-time 1m + MBO) — only historical + Yahoo/Alpaca-IEX now. **Live order flow needs this.**
- [ ] Full-volume data (Alpaca **SIP** or Databento) — IEX free feed is a partial-volume subset.
- [ ] Connect the Webull / TradingView **data** adapters (login / unofficial pkg) — built, not wired.
- [ ] SPY equity **MBO** batch (drop-in ready via `run_symbol SPY`) for SPY order flow.

## C. Strategy / research (🔬)
- [ ] ⚠️ **GOLD (GC) edge re-validation** — F30 (+0.44R) does NOT reproduce under the current engine; GC fails every config tried. Currently flagged `unverified` — needs its own research before it's tradeable.
- [ ] Sub-second **event-time OFI** study (the last predictive long-shot) — F63 showed minute-level order flow is NOT predictive; this is the only untested avenue (low odds).
- [ ] Structure/liquidity-based TP targets (only the 4R cap is validated; level-based TP2 untested).
- [ ] Multi-session (Asia / London) for futures in the live loop (exists in Pine, not the bot).
- [ ] Re-validate the trend / SMC filters as standalone edges (F62: equity-only, ~0 additive).

## D. Execution — ⛔ OUT OF SCOPE (the BOT is a SIGNAL ENGINE; you place trades manually)
The bot pulls data → analyses → emits signals to the dashboard. It does **not** place trades. The
Alpaca submit / options-submit / OMS / reconciliation / broker adapters that exist are **optional
reference only** and are NOT on the critical path. No execution work is required for the product.
- (optional) broker adapters / live order routing — only if you ever want assisted execution; not needed.

## E. Predictive / adaptive (🔬 — honest state)
- [ ] ⚠️ **No predictive edge found** (F62 bar features AUC 0.48; F63 order flow IC ≤ 0). The ML layer is wired but correctly refuses to deploy. Making it predictive needs a genuinely predictive feature — none found yet.
- [ ] Schedule the retrain (`train_and_promote`) on a cron so the model adapts automatically (currently manual).
- [ ] Feature expansion (the full example.txt feature set) — only coarse features tried.

## F. UI (🛠)
- [ ] Full multi-screen **Next.js** UI (only the single-page dashboard exists).
- [ ] Surface in the dashboard: per-asset status, P(win), order-flow confirm, the **exit-plan** (`/api/exit_plan`) — some are API-only.
- [ ] Mobile app; proper auth/RBAC (only the optional token guard + webhook token today).

## G. Risk / ops (🛠 / 🔌)
- [ ] News/event **lockout wired to a live calendar** (FOMC/CPI/NFP) — module built, no event source.
- [ ] **Portfolio risk enforced in the live loop** (correlation/heat/concentration — module built, not gated live).
- [ ] Exercise the **live-readiness gate** + go-live checklist before any real-money switch.

## H. Testing (🛠)
- [ ] Integration / E2E tests (live loop, webhook round-trip, options submission against the broker).
- [ ] Larger book-level sample (F63 was 12 days).

---
### Done since the audit (for reference)
4-family registry **with per-asset config** (NQ/QQQ/SPY validated, GC unverified) · live loop
(SPY/QQQ/NQ/GC, P(win)+order-flow+options) · SQLite store · options engine + **exit-plan (TP1 1.5R /
TP2 4R)** + submission · reconciliation poller · multi-provider data (Alpaca/Yahoo + futures) · TV
webhook receiver · predictive+adaptive ML (honest/idle) · F62/F63/F64 research. 21 pytest green.
