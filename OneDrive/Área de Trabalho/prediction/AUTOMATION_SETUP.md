# HIGHSTRIKE ORB — Automation Setup (paper trading)

Automate `HIGHSTRIKE_ORB_AUTO.pine` via TradingView alerts → a webhook **bridge** → your broker's
**paper** account. The auto file uses a single SL/TP bracket (fully automatable; validated
QQQ 15m 2R ≈ +0.37R/PF 2.0, NQ 15m 2R ≈ +0.31R/PF 1.8).

> **Always start on a PAPER/demo account.** Run it for a couple of weeks and reconcile fills before
> a cent of real money. Automation bugs (double fills, missed cancels, stale stops) lose money fast.

---

## The model
```
TradingView (HIGHSTRIKE_ORB_AUTO strategy)
   │  alerts: ARMED (heads-up) · ENTRY (order-fill JSON) · EXIT/EOD (flatten)
   ▼  webhook
Bridge (TradersPost / PickMyTrade / Tradovate-native)
   ▼  broker order (market entry + SL/TP bracket)
Broker PAPER account (Alpaca · Tradovate demo · etc.)
```
The strategy's resting stop fills in TV when price touches the OR level → TV sends the **ENTRY** JSON
→ the bridge places a market order **plus** the SL/TP bracket from the JSON → the broker manages the
exit. At 15:58 ET the strategy fires the **EXIT/EOD** flatten so nothing is held overnight.

---

## Path A — SPY / QQQ shares  (TradersPost → Alpaca paper)
1. **Alpaca** — create a free account, switch to **Paper**, copy the paper API key/secret.
2. **TradersPost** — create an account, connect the **Alpaca paper** broker, create a **Strategy**,
   copy its **webhook URL**.
3. **TradingView** (Pro+ plan, needed for webhooks):
   - Add `HIGHSTRIKE_ORB_AUTO` to a **QQQ** (or SPY) **15m** chart.
   - Strategy Tester → **Properties**: commission **0**, slippage **1** (equity tick = $0.01).
   - Set `Fixed qty` to a real **share** count (e.g. 10) — *not* 2, and *not* 0 unless you set Risk $.
   - Right-click → **Add alert** → Condition = the strategy → "**Order fills and alert() function
     calls**" → Notifications → **Webhook URL** = your TradersPost URL → Create.
4. The script already sends TradersPost-shaped JSON on each fill:
   `{"ticker":"QQQ","action":"buy","quantity":{{strategy.order.contracts}},"stopLoss":{"type":"stop","stopPrice":737.10},"takeProfit":{"type":"limit","limitPrice":746.20}}`
5. Watch the TradersPost dashboard mirror the fills into Alpaca paper.

## Path B — MNQ futures  (Tradovate native, or TradersPost)
- **Tradovate (simplest):** open a Tradovate account → **demo** mode → in TradingView connect the
  Tradovate broker (Trading panel), or use Tradovate's TradingView webhook. Same alert setup as above.
- **Or TradersPost / PickMyTrade → Tradovate/Apex demo:** same as Path A but the bridge routes to the
  futures broker. Map the symbol to the front-month MNQ contract in the bridge.
- TradingView Properties for MNQ: commission **0.52**, slippage **2** (default), `Fixed qty` = contracts.

---

## Creating the alert (both paths)
- **One alert** on the strategy, condition = "**Order fills and alert() function calls**" (this sends
  both the `alert()` heads-ups and the order-fill bracket JSON).
- Webhook URL = your bridge. Expiration = "Open-ended". Message can stay default (the script supplies
  per-order `alert_message`).
- The **ARMED** alert is informational (a heads-up before the touch) — your bridge will ignore it if it
  doesn't match an order schema; that's fine. If your bridge errors on non-order messages, create a
  **second, alert()-only** notification routed to your phone/Discord instead of the webhook.

## Verify the JSON for your bridge
The `stopLoss`/`takeProfit` shape above is TradersPost's documented format — **check your bridge's
current docs** and tweak the `f_entry_json()` strings in `HIGHSTRIKE_ORB_AUTO.pine` if needed
(PickMyTrade and others use different keys). The `Webhook qty field` input lets you swap
`{{strategy.order.contracts}}` for a fixed number if your bridge requires it.

---

## Go-live checklist (do in order)
1. ☑ Backtest the auto file on QQQ/NQ 15m in TV; confirm it's near the Python (+0.37R / PF ~2.0).
2. ☑ Paper account connected; send a **manual test order** from the bridge → confirm it lands.
3. ☑ Enable the alert on a **paper** account; let it run **2+ weeks**.
4. ☑ Reconcile every day: TV fills vs broker fills vs the backtest — entries at the level, SL/TP set,
   **flat by EOD** (no overnight positions).
5. ☑ Only after paper matches expectations: switch the bridge to a **live** broker, smallest size.

## Known limits
- **Entry is market-on-fill** (the bridge market-buys when TV's stop fills) → a tick or two of slippage
  vs the exact stop. Modeled by the slippage setting; fine on liquid SPY/QQQ/MNQ.
- **Single bracket**, not the scale-out (50%@TP1→BE→TP2). The scale-out needs partial-close webhooks —
  add later if you want; the single bracket is validated and simpler.
- **Options are NOT covered here** — Pine can't build the contract. Use `HIGHSTRIKE_ORB_OPTIONS.pine`
  for the strike suggestions and place those manually, or a bridge that constructs option orders.
