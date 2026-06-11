# HIGHSTRIKE ORB — Automation Setup (full step-by-step)

End-to-end guide to run `production/HIGHSTRIKE_ORB_AUTO.pine` on autopilot into a **paper** account, then live.
No prior webhook experience assumed. The script is the automation twin of the validated STACK
(structure gate + VWAP cap + structure stop + ATR trail, RTH / Asia / London / Auto), with a
**provider-agnostic webhook layer**: everything is configured by inputs, so when your webhook URL,
API token, or account IDs arrive you plug them in — no code edits.

> ⚠️ **PAPER FIRST, ALWAYS.** Do every step below on a paper/demo account and run it ≥ 2 weeks,
> reconciling every fill, before a single real dollar. This is also the project's last open adoption
> gate (forward paper-test of fills). Automation fails silently (a missed webhook, a stale stop) —
> paper is how you find those bugs cheaply.

---

## 0 · How it works (read this first)

```
   TradingView (cloud)  ── runs HIGHSTRIKE_ORB_AUTO on live data, 24/7, even if your PC is off
        │  fires an alert the instant price touches the OR level (calc_on_every_tick = intrabar)
        ▼  HTTPS webhook (a JSON message)
   Bridge  (TradersPost / PickMyTrade / your relay)  ── translates the JSON into a broker API order
        │  REST API call
        ▼
   Broker account(s)  (Tradovate/MNQ · Alpaca/shares · prop-firm eval)  ── fills + holds the stop
```

- **TradingView is the brain.** It decides *when* to trade (the validated stack) and fires alerts.
- **The bridge is the translator.** Pick its JSON format with the **`Webhook format`** input.
- **The broker executes** and holds the initial stop you sent with the entry.

### The five messages the script can emit
| Message | Channel | When | Purpose |
|---|---|---|---|
| **ARMED** | `alert()` | setup ready, before the touch | heads-up (text → phone/Discord, or JSON for a relay) |
| **ENTRY** | order fill | resting stop-entry fills | entry + qty + **initial structure SL** (+ TP in bracket mode) |
| **TRAIL SYNC** | `alert()` (optional, OFF) | chandelier ratchets ≥ N ticks | `event:stop_update` JSON so a relay/PMT can move the broker stop |
| **EXIT** | order fill | trail/stop/TP fills in TV | flatten (market) at the broker |
| **SESSION END / EVAL HALT** | order fill | session cutoff / daily-loss halt | flatten — nothing held across sessions |

### How the TRAIL works over webhooks (important)
The validated exit is a 2-ATR chandelier trail — but most bridges can't hold a trailing stop. So:
1. The **ENTRY** webhook carries the **initial structure stop** → the broker holds that as the
   catastrophic bracket (you're protected even if the webhook pipe dies mid-trade).
2. TradingView manages the ratcheting trail internally. When the trail is hit, the **EXIT** webhook
   flattens at market. The broker's resting stop is cancelled by the bridge's exit handling.
3. Optional: turn **`Send TRAIL stop updates`** ON to also push `stop_update` JSONs as the trail
   ratchets (only if your bridge/relay supports stop modification — TradersPost does not; leave OFF).

If you can't trust the bridge to process exit webhooks reliably, switch **`Exit`** to
**Fixed TP bracket (broker-held)** — the broker holds SL **and** TP and nothing depends on a
mid-trade webhook. It gives up the run-more upside of the trail but is the most failure-proof mode.

### What it costs (monthly, paper stage)
| Piece | Why | Cost |
|---|---|---|
| TradingView **Essential/Plus or higher** | webhook alerts require a paid plan | ~$15-30/mo |
| Bridge (TradersPost / PickMyTrade) | the translator | free tiers exist; ~$25-50/mo paid |
| Tradovate **demo** (MNQ) / Alpaca **paper** (shares) | broker | free |

---

## 1 · Pick your path (one webhook URL per alert)

One TradingView alert can call **one** webhook URL. Your options:

**A — TradersPost (simplest, shares + futures).** `Webhook format = TradersPost`. TradersPost can
route one strategy to **multiple connected brokers/accounts** on its side, which is the easiest
multi-account setup — the script doesn't need account IDs at all.

**B — PickMyTrade → Tradovate (futures-focused, supports stop-modify).** `Webhook format =
PickMyTrade / Tradovate`, paste your **API token** and **Account ID** into the Webhook inputs.
Their schema also accepts extra flags (e.g. `"duplicate_position_allow":true` for copying to
multiple accounts) — put those in **`Extra raw JSON fields`**. ⚠️ Verify the key names against
PickMyTrade's current docs when your token arrives — the preset is close but providers move.

**C — Generic JSON → your own relay (max flexibility, true multi-account/multi-provider).**
`Webhook format = Generic JSON`. Every payload carries the full plan
(`event, ticker, action, quantity, entryLevel, stopLoss, takeProfit, exitMode, trailAtr, session,
accountIds[], token, sentAt`). Point it at an n8n flow / Cloudflare worker / small Flask app that
fans out to as many providers/accounts as you like. Fill **`Account IDs, comma-separated`** and the
relay receives `accountIds:["acct1","acct2",...]`.

**D — Custom template.** `Webhook format = Custom template` and edit the ENTRY/EXIT template inputs
using `%TICKER% %ACTION% %QTY% %ENTRY% %STOP% %TP% %EVENT%` placeholders — matches any schema
without touching the code.

**Multiple providers at once?** Either path C (one relay fans out), or add the strategy to the
chart **twice** with different `Webhook format` settings and one alert each.

---

## 2 · Create the accounts

1. **TradingView** — plan with webhook alerts (Essential+). Chart **NQ1!** or **MNQ1!**, **5-minute**
   timeframe (the validated config; the trade-day/Asia logic assumes futures' 18:00 ET roll).
2. **Broker paper** — Tradovate demo (futures) or Alpaca paper (shares).
3. **Bridge** — sign up (TradersPost / PickMyTrade), connect the broker's paper account, create a
   strategy/connection, and **copy its Webhook URL**. Keep it secret — anyone with it can place orders.

---

## 3 · Load + configure the strategy

1. Open `production/HIGHSTRIKE_ORB_AUTO.pine` in the Pine Editor → **Add to chart**.
2. **Strategy Tester → ⚙ Properties** (per-instrument costs; header values must be const):
   - **MNQ/NQ futures:** Commission **0.52**/order, Slippage **2** ticks (the defaults).
   - **Shares (QQQ/SPY):** Commission **0**, Slippage **1** tick.
3. **Strategy settings (⚙):**
   - `Session` → start with **US RTH**; once fills reconcile cleanly, switch to **Auto (Asia +
     London + RTH)** for all three validated cycles per day. (Asia/London are futures-only and the
     most slippage-sensitive — paper-verify their fills especially.)
   - `Stop placement` → **Structure swing** · `Exit` → **Trail (ATR chandelier), 2.0** — the
     validated defaults. Switch exit to **Fixed TP bracket** only if the bridge can't do exits.
   - `Fixed qty` → **1** MNQ to start (or 0 + `Risk $ per trade` for risk-based sizing — note the
     structure stop is ~half as wide, so risk-based sizes larger; `Max qty safety cap` bounds it).
   - **Webhook group** → pick the format (Step 1) and paste token / account ID(s) when you have
     them. `Ticker override` lets you send `MNQ` or a front-month code while charting `NQ1!`.
   - `EVAL: prop guardrails` → ON if running a funded-eval account (daily-loss halt flattens and
     stands down for the day).
4. Sanity-check the Strategy Tester on NQ 5m shows the stack's behavior (selective entries — a few
   per week per session — positive expectancy, trail exits letting winners run) before wiring it up.

---

## 4 · Create the alert (the actual automation)

1. Right-click the chart → **Add alert**.
2. **Condition:** the **`HIGHSTRIKE ORB AUTO`** strategy → **"Order fills and alert() function calls."**
   ← critical: this sends BOTH the `alert()` messages (ARMED, trail sync) and the order-fill JSONs.
3. **Expiration: Open-ended.**
4. **Notifications → Webhook URL:** paste the bridge URL. **Message:** leave as
   `{{strategy.order.alert_message}}` — the script supplies the JSON per order; don't overwrite it.
5. If the bridge rejects the plain-text ARMED message: either set `ARMED alert as JSON` ON (relays),
   or create a **second** alert routed to phone/email/Discord for ARMED and keep the webhook alert
   for order fills only.

---

## 5 · Test before trusting it

1. **Manual webhook test:** use the bridge's "send test" (or curl a sample entry JSON) → confirm a
   paper order appears at the broker. Proves the bridge↔broker link.
2. **Dry-run:** watch the dashboard go `OR forming… → ARMED — order resting → IN TRADE`. The VWAP-cap
   row shows when the entry order is pulled because the level is extended (`EXT ⚠ (order pulled)`).
3. **First real signal — check all three agree:** TV Strategy Tester entry ≈ bridge log ≈ broker fill
   **with the initial stop attached**. In trail mode also verify the EXIT webhook flattened the
   position AND the broker's resting stop was cancelled (no orphans).

---

## 6 · Daily reconciliation routine (non-negotiable on paper)

- ☑ Entry filled at/near the OR level (a tick or two of slippage is normal — Asia/London tolerate
  less; that's why they're paper-tested first).
- ☑ The **initial structure stop is live** at the broker the moment the entry fills.
- ☑ Trail exits: TV exit price vs broker market-fill — log the slippage.
- ☑ Flat at each **session cutoff** (RTH 15:58, London 08:00, Asia 03:00 ET) — nothing held over.
- ☑ No duplicate orders, no orphaned stops after exits.
- ☑ TV fills ≈ broker fills ≈ what the Python engine would have done.

Keep a log (date, session, signal, TV fill, broker fill, slippage, result). **Two weeks of clean
logs** is the bar — this doubles as the project's forward paper-test gate.

---

## 7 · Go-live checklist (in order — do not skip)
1. ☑ Strategy Tester behavior on NQ/MNQ 5m matches the engine's stack results.
2. ☑ Bridge↔broker link proven with a manual test order.
3. ☑ Alert live on **paper**, RTH first; runs **2+ weeks** clean (Step 6).
4. ☑ Asia + London cycles paper-verified separately (slippage within 2 ticks).
5. ☑ Latency measured: touch → broker fill is a couple of seconds (10s+ = fix the bridge first).
6. ☑ Only now: point at a **live** account, **1 MNQ**, re-reconcile daily before sizing up.

---

## 8 · Troubleshooting

| Symptom | Likely cause | Fix |
|---|---|---|
| No webhook received | Alert not "Order fills and alert() function calls", or wrong URL | Recreate the alert; recopy the URL |
| Webhook received, no order | JSON schema mismatch / broker not connected | Check bridge logs; switch `Webhook format` or fix via Custom template |
| Order placed, **no stop** | bridge ignored `stopLoss` | Verify bracket support + key names for your bridge |
| Trail exit fired but position still open | bridge didn't process the EXIT webhook | This is the failure the broker-held initial stop bounds; fix the bridge or switch to bracket mode |
| Stop left behind after an exit (orphan) | bridge exit didn't cancel the resting stop | Confirm the bridge's exit/flatten cancels working orders |
| Entry fires at bar close, late | `calc_on_every_tick` off | It's ON in this file — confirm you loaded AUTO, not the V1 strategy |
| Double orders | ARMED routed to the webhook as an order | `ARMED as JSON` OFF + second non-webhook alert for ARMED |
| Stale order 18:00-19:00 ET (Auto) | pre-Asia gap | Guarded in the script (no orders in that hour) — if you see one, you're on an old file |
| Position held past the session | flatten webhook missed | Confirm the bridge processed `session_end`; check alert is open-ended |

---

## 9 · Known limits
- **Entry is market-on-fill** at the bridge → a tick or two of slippage vs the level. Asia/London are
  more slippage-sensitive (validated to 2-3×, but paper-verify YOUR bridge's latency).
- **The trail lives in TradingView**, not at the broker (unless your bridge supports `stop_update`).
  The broker-held initial structure stop bounds the damage of a dead webhook pipe; bracket mode
  removes the dependency entirely.
- **The scale-out exit is not offered here** — partial-close webhooks are bridge-specific; trail
  (validated better) and bracket cover automation.
- **Options are NOT covered** — use `production/HIGHSTRIKE_ORB_OPTIONS.pine` manually.
- **TradingView must keep the alert running** — open-ended expiration, watch your alert count, and
  re-create the alert after every script update (an edited script detaches its alerts!).
