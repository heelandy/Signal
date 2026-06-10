# HIGHSTRIKE ORB — Automation Setup (full step-by-step)

End-to-end guide to run `HIGHSTRIKE_ORB_AUTO.pine` on autopilot into a **paper** account, then live.
No prior webhook experience assumed. Two paths are covered: **SPY/QQQ shares** and **MNQ futures**.

> ⚠️ **PAPER FIRST, ALWAYS.** Do every step below on a paper/demo account and run it ≥ 2 weeks,
> reconciling every fill, before a single real dollar. Automation fails silently (a missed webhook, a
> stale stop) — paper is how you find those bugs cheaply.

---

## 0 · How it works (read this first)

```
   TradingView (cloud)  ── runs HIGHSTRIKE_ORB_AUTO on live data, 24/7, even if your PC is off
        │  fires an alert the instant price touches the OR level (calc_on_every_tick = intrabar)
        ▼  HTTPS webhook (a JSON message)
   Bridge  (TradersPost)  ── receives the JSON, translates it to a broker API order
        │  REST API call
        ▼
   Broker PAPER account  (Alpaca = shares · Tradovate = MNQ)  ── fills the order + holds the SL/TP bracket
```

- **TradingView is the brain.** It decides *when* to trade (your validated ORB logic) and fires alerts.
- **The bridge is the translator.** TradingView can't talk to most brokers directly; the bridge turns
  the alert JSON into a real order.
- **The broker executes** and manages the bracket (stop-loss + take-profit) you sent with the entry.
- **Three messages** come out of the script: **ARMED** (heads-up), **ENTRY** (order-fill bracket), and
  **EOD flatten** (close everything at 15:58 ET so nothing is held overnight).

### What it costs (monthly, paper stage)
| Piece | Why | Cost |
|---|---|---|
| TradingView **Essential/Plus or higher** | webhook alerts require a paid plan | ~$15-30/mo |
| **TradersPost** | the bridge | free tier exists; paid ~$49/mo for live/more alerts |
| **Alpaca** paper (shares) | broker | free |
| **Tradovate** demo (MNQ) | broker | free demo |

---

## 1 · Create the accounts (do these in order)

### 1A · TradingView
1. Upgrade to a plan that allows **webhook alerts** (Essential or higher — verify "Webhook URL" is an
   available alert notification on your plan).
2. Open a chart of **QQQ** (shares path) or **MNQ1!** (futures path) on the **15-minute** timeframe.

### 1B · Broker paper account
**Shares → Alpaca**
1. Sign up at alpaca.markets → switch the dashboard to **Paper Trading** (toggle, top of the page).
2. Generate **API Key** + **Secret** (you'll paste these into the bridge, not the script).

**Futures → Tradovate**
1. Sign up at tradovate.com → open a **Demo** (simulated) account.
2. Note your demo login — the bridge (or Tradovate's native TradingView link) uses it.

### 1C · Bridge — TradersPost
1. Sign up at traderspost.io.
2. **Connect a broker:** Brokers → Connect → choose **Alpaca (Paper)** and paste the key/secret from
   1B (or **Tradovate Demo** for futures).
3. **Create a Strategy:** Strategies → New → name it `HIGHSTRIKE ORB`.
4. Open that strategy → copy its **Webhook URL** (looks like
   `https://webhooks.traderspost.io/trading/webhook/xxxxxxxx/...`). **You'll paste this into the
   TradingView alert in Step 3.** Keep it secret — anyone with it can place orders in your account.

---

## 2 · Load the strategy on TradingView

1. Open `HIGHSTRIKE_ORB_AUTO.pine` in the Pine Editor → **Add to chart**.
2. **Strategy Tester → ⚙ Properties** (this is where per-instrument costs live, because the header
   values must be constants):
   - **Shares (QQQ/SPY):** Commission = **0**, Slippage = **1** tick.
   - **MNQ futures:** Commission = **0.52**, Slippage = **2** ticks (defaults).
3. **Strategy settings (⚙ on the strategy name):**
   - `Fixed qty` → a **real size**: e.g. **10** shares for QQQ, or **1** contract for MNQ.
     (Do **not** leave it at 2 for shares — that's $1.5k, trivially small. Use 0 only if you set
     `Risk $ per trade` and want auto-sizing.)
   - `Take-profit R` → **2** (or 3 for more expectancy). Leave the gates at defaults.
4. Sanity-check the Strategy Tester reads roughly **+0.3–0.4R/trade, PF ~2.0** on QQQ/NQ 15m — this
   confirms the file is behaving before you wire money to it.

---

## 3 · Create the alert (the actual automation)

1. Right-click the chart → **Add alert** (or the ⏰ icon).
2. **Condition:** select **`HIGHSTRIKE ORB AUTO`** (the strategy) — *not* "any indicator value".
3. In the dropdown beneath it, choose **"Order fills and alert() function calls."** ← critical. This
   sends BOTH the `alert()` heads-ups (ARMED, EOD) and the order-fill bracket JSON.
4. **Trigger / frequency:** leave default (the script controls frequency).
5. **Expiration:** set **Open-ended** (so it doesn't expire in a few weeks).
6. **Notifications tab → Webhook URL:** paste the **TradersPost Webhook URL** from Step 1C. Tick the
   **Webhook URL** box on.
7. **Message:** leave it as the default `{{strategy.order.alert_message}}` — the script supplies the
   real JSON per order; don't overwrite it.
8. Click **Create.**

That single alert now runs the whole pipeline.

### What the script actually sends (for reference)
On an entry fill, the order's `alert_message` is already built for you, e.g. a long:
```json
{"ticker":"QQQ","action":"buy","quantity":{{strategy.order.contracts}},
 "stopLoss":{"type":"stop","stopPrice":737.10},
 "takeProfit":{"type":"limit","limitPrice":746.20}}
```
On the 15:58 EOD flatten it sends `{"ticker":"QQQ","action":"exit"}`. The **ARMED** message is plain
text (a heads-up). If TradersPost rejects the plain-text ARMED message, route ARMED to a **second**
alert that goes to your phone/email/Discord instead of the webhook (see Step 6).

---

## 4 · Match the JSON to your bridge

The `stopLoss`/`takeProfit` shape above follows **TradersPost's documented schema**. If you use a
different bridge (PickMyTrade, Capitalise, etc.) the keys differ — open `HIGHSTRIKE_ORB_AUTO.pine`,
find **`f_entry_json()`**, and edit the string to match your bridge's docs. The **`Webhook qty field`**
input lets you swap `{{strategy.order.contracts}}` for a fixed number if the bridge wants a literal.

**MNQ note:** in TradersPost (or Tradovate's native link) map the ticker to the **front-month MNQ
contract**. For Tradovate's *native* TradingView integration you skip TradersPost entirely — connect
Tradovate in TradingView's trading panel and the alert routes through it (fewest hops, lowest latency).

---

## 5 · Test before trusting it

1. **Manual webhook test:** in TradersPost, use **"Send test"** on the strategy (or paste a sample
   buy JSON) → confirm a paper order appears in Alpaca/Tradovate. This proves the bridge↔broker link.
2. **Dry-run the alert:** with the market open, watch the script's dashboard go
   `OR forming… → ARMED → IN TRADE`. When it ARMS, you should get the heads-up; when price touches the
   level, the ENTRY webhook should place a paper order with the SL/TP bracket attached.
3. **First real signal:** when the first automated trade fires, immediately check **all three** match:
   - TradingView Strategy Tester shows the entry,
   - TradersPost shows the webhook received + order sent,
   - the broker shows the filled position **with a stop and a target** attached.

---

## 6 · Daily reconciliation routine (non-negotiable on paper)

Every trading day, confirm:
- ☑ Entry filled **at/near the OR level** (a tick or two of slippage is normal).
- ☑ The **bracket is live** at the broker (stop + target both present).
- ☑ The position is **flat by ~15:58 ET** (the EOD flatten fired — nothing held overnight).
- ☑ TradingView fills ≈ broker fills ≈ what the backtest would have done.
- ☑ No **duplicate** orders and no **orphaned** stops (a stop left behind after an exit).

Keep a simple log (date, signal, TV fill, broker fill, slippage, result). Two weeks of clean logs is
the bar to clear before going live.

---

## 7 · Go-live checklist (in order — do not skip)
1. ☑ Strategy Tester on QQQ/NQ 15m ≈ Python (+0.3–0.4R, PF ~2.0).
2. ☑ Bridge↔broker link proven with a manual test order.
3. ☑ Alert live on a **paper** account; runs **2+ weeks**.
4. ☑ Daily reconciliation clean (Step 6) — entries, brackets, EOD-flat, no dupes/orphans.
5. ☑ Latency measured: ARMED/fill timestamp vs broker fill is a couple of seconds (if 10s+, the bridge
   or broker is the bottleneck — fix before live).
6. ☑ Only now: point the bridge at a **live** broker, **smallest size**, and re-reconcile daily.

---

## 8 · Troubleshooting

| Symptom | Likely cause | Fix |
|---|---|---|
| No webhook received | Alert not "Order fills and alert() function calls", or wrong URL | Recreate the alert; recopy the TradersPost URL |
| Webhook received, no order | JSON schema mismatch, or broker not connected | Check TradersPost logs; fix `f_entry_json()` to the bridge's schema |
| Order placed, **no stop/target** | bridge ignored `stopLoss`/`takeProfit` | Verify the bridge supports brackets; check the key names |
| Entry fires at bar close, late | `calc_on_every_tick` off | It's ON in the auto file — confirm you loaded the auto file, not the V1 strategy |
| Double orders | both an ARMED-as-order and a fill-order routed to the webhook | Route ARMED to a non-webhook notification; only order fills hit the bridge |
| Position held overnight | EOD flatten didn't reach the broker | Confirm `EOD: flatten` is on and the bridge processed the `"action":"exit"` |
| Bridge errors on ARMED text | bridge expects JSON only | Second alert for ARMED → phone/email/Discord, not the webhook |

---

## 9 · Known limits
- **Entry is market-on-fill** (the bridge market-buys when TV's stop fills) → a tick or two of slippage
  vs the exact level. Modeled by the slippage setting; small on liquid SPY/QQQ/MNQ.
- **Single SL/TP bracket**, not the V1 scale-out (50%@TP1→BE→TP2). Validated and simpler; the scale-out
  would need partial-close webhooks (a later upgrade).
- **Options are NOT covered** — Pine can't build the contract. Use `HIGHSTRIKE_ORB_OPTIONS.pine` for the
  strike suggestions and place those manually (or a bridge that constructs option orders).
- **TradingView must keep the alert running** — it lives on their servers, but if your plan lapses or the
  alert expires, automation stops silently. Set expiration **Open-ended** and watch your alert count.
