# UI/UX Recommendations — future implementation

Grounded in what's validated as of 2026-07-03. Every item maps to a field that already exists (or a
research verdict) — nothing here invents a new signal. Standing display rules that got us here and must
not regress:

* **State color legend (user spec):** WAIT gray · WATCH orange · ARMED yellow · FILLED blue ·
  NEAR TP1 light-green · TP1 green · TP2 dark-green · STOP red · INVALID dark-red.
* **Simple chart rule (user 2026-06-29):** FILL marker + level lines only; hit-times live in the
  dashboard, not as chart clutter.
* **Every WAIT must say WHY** (the STATE row block-reasons: `OR-mid: short day`, `narrow OR`,
  `trend gate`, `macro D`…). Never a silent block.
* **Awareness ≠ tradability.** Display-only reads (slope S, DIR-fast, MTF rolling direction) must
  never look like entry signals — no green/red BUY/SELL styling on them; arrows + neutral tones only.

---

## 1. STACK Pine dashboard (primary manual surface)

| Priority | Item | Spec |
|---|---|---|
| P1 | **TRANCHE row (equities only)** | F66 ladder is adopted: on QQQ/SPY show `STARTER 0.4x` (orange chip) when the break fires unconfirmed, flipping to `FULL — struct confirmed` (green) when st_state aligns. Futures show `BINARY — waiting struct` while unconfirmed. Data: `eff_up/eff_down` vs fired state — no new computation. |
| P1 | **AIR row (when clean-air graduates)** | `AIR 3.2 ATR ✓` (lime, ≥2–3 ATR clear ahead) / `WALL 0.8 ATR ⚠ zone overhead` (orange). One number + one word; the zone map itself stays off the Pine chart (Pine can't hold the 1m zone engine — feed the verdict via the BOT if automated, else leave BOT-only). |
| P2 | Keep DIR-fast row as-is (OR/VWAP/Slope arrows + Struct `(edge)` tag) — it survived review; do not add more detector arrows (graveyard rule). |
| P2 | **Latency hint on REGIME** — when structure is not yet confirmed, append the expected wait: `No Structure (~40-60m to confirm)` so the operator knows the gate isn't stuck (numbers from the fast-direction study). |

## 2. BOT dashboard (`dashboard.html`, Orion layout)

| Priority | Item | Spec |
|---|---|---|
| P1 | **Tranche badge on signal cards** — the proposal now carries `tranche`: `starter` → orange `STARTER 0.4×` badge + the conviction line ("ADD to full when structure confirms"); `full` → green `FULL`. Sort starters below fulls within a symbol. |
| P1 | **Macro chip is now REAL** (SPY/VIX feed wired): show `Regime B · SPY↑ · VIX 17` in the status bar; gray `macro: fallback` when the feed is down (permissive mode) so the operator knows which gates are actually live. |
| P1 | **signal_state chip** — `active` green / `watch` orange / `invalid` dark-red strikethrough on the whole card (already skips autotrade; make the UI say so: "skipped — structure broke against signal"). |
| P2 | **Zone panel (candidate — build behind a flag until clean-air graduates)** — per symbol: top 3 MAJOR/STRONG zones (level, score, label) + the AIR number for the active signal. Feed: `orb_liquidity_zones.detect_zones` on the cached 1m frame, per completed 1m bar. |
| P2 | **MTF direction strip** — the `/api/direction` 7-state per TF (2M…4H) as a compact row of arrows with the ROLLING vs CONFIRMED distinction (rolling = hollow arrow, confirmed = solid). Detection layer styling (neutral), never buy/sell colors. |
| P3 | **First-touch study panel** stays; add tranche as a study dimension (starter vs full outcomes) so the F66 policy keeps validating itself on paper fills. |

## 3. Chart (TradingView / STACK)

| Priority | Item | Spec |
|---|---|---|
| P1 | Keep: OR high/low/mid (bias-colored), entry/stop/TP lines, FILL markers, WATCH/INVALID states. This set is complete for the entry story. |
| P2 | **Zone bands (only if clean-air graduates):** max 3 boxes, MAJOR only, opacity ∝ score, no labels on the band (score in the dashboard AIR row). Anything more re-creates the clutter the simple-chart rule removed. |
| P3 | Starter/add visual on equities: FILL marker subscript `0.4×` on starter fills; a second marker `+0.6×` on the confirm-add. |

## 4. What NOT to build (graveyard — decided, don't revisit in UI)

* No slope/momentum/persistence/efficiency/Hurst/Markov/VPIN/Renko/Donchian indicators as panels or
  signals — all dead or redundant (F68). DIR-fast + 7-state classifier is the only awareness surface.
* No 1m-fed GATE toggle in any UI — F69 failed it; `fast_dir` is display-plumbing only.
* No OBI/order-book widgets as direction hints (F63: contemporaneous only). If OBI ever ships it's
  inside paper-execution (fill shading), invisible in the signal UI except a fill-quality stat.
* No "cut starter" button/automation — ladder v2 rejected; the starter rides its normal exit.
* No countdown timers pushing earlier entries — the latency IS the edge; the UI should normalize the
  wait (see the REGIME latency hint), not fight it.

## 5. Sequencing

1. **Now (fields already flowing):** tranche badge + macro chip + signal_state strikethrough (BOT), TRANCHE row (STACK).
2. **After clean-air graduates (slip + WF + SPY gates):** AIR row (STACK) + zone panel/bands (BOT/chart).
3. **Ongoing:** first-touch study tranche dimension — the paper-fill loop that keeps every adopted policy honest.
