# Canonical Entry Standard — ARMED → WATCH → FILL (2026-07-04)

ONE entry state machine across every surface: the Pine scripts (STACK / AUTO / OPTIONS), the
Python BOT (live scan + candidate replay) and the research engine. This document is the
strategy-of-record for `strategy_version = orb-standard-2026.07`; the ML/NN layers train against
exactly this rule version.

Source spec: `Trading System Logic` + `README_trading_state_logic` (user strategy docs).

---

## The three layers

| Layer | Responsibility | Rule |
|---|---|---|
| **1 — Market Context** (hard) | May the system look for this side at all? | **Structure** (swing state, 1m-fed) **AND** **VWAP side** must both point the trade way → the side is **ARMED**. If they disagree: no trade. |
| **2 — Trade Quality** (grade) | How strong is the setup? | The **combined slope engine** grades **A+ / A / B+ / B / C / D** along the trade direction. Never gates direction; feeds sizing advice + the ML/NN models. |
| **3 — Execution** (OR levels) | When exactly does the order fire? | **OR mid** activates **WATCH**; **OR high/low** triggers the **FILL** (body close, no wick-only). Cooldown / pullback / range / two-entry rules police the cycle. |

## The state machine (per side, long/short exact mirrors)

```text
WAIT ──context aligned──────────► ARMED
ARMED ──context lost────────────► WAIT
ARMED ──confirmed directional-body close beyond OR mid──► WATCH
WATCH ──body close beyond OR high/low (strong body ≥0.25, next-candle continuation,
        direction sequence, within chase cap)───────────► FILLED
WATCH ──confirmed close back across OR mid──► COOLDOWN (N bars) ──► restart (fresh mid close required)
WATCH ──price extends > chase·ATR past the level pre-fill──► PULLBACK
PULLBACK ──retest within retest·ATR of the level──► WATCH (clean re-check)
WATCH ──> stale bars without a fill──► RANGE (stand down until the mid is lost)
any pre-fill ──confirmed close beyond the OPPOSITE OR edge, or the proposed stop tagged──► INVALID
INVALID ──confirmed close reclaims the breakout edge──► WAIT (fresh confirmation required)
FILLED ──► NEAR TP1 / TP1 HIT / TP2 HIT / STOP HIT
after a terminal trade ──entries used < max──► COOLDOWN (next cycle)   |   else ──► LOCKED
```

State colors (all dashboards): WAIT gray · ARMED yellow · WATCH orange · PULLBACK purple ·
COOLDOWN silver · RANGE dim gray · LOCKED dark gray · FILLED blue · NEAR TP1 light green ·
TP1 green · TP2 dark green · STOP red · INVALID dark red.

**Ordering fix.** The old surfaces displayed WATCH *below* the mid and called the ready-to-fill
stage ARMED. Per the docs' "Known Bug Fix", the canonical ordering is **context arms, the mid
watches, the edge fills** — ARMED comes *before* WATCH everywhere now.

## The rules in detail

- **Watch activation** — a *confirmed* close beyond the OR mid toward the side **with a
  directional body** (long: close > mid on an up candle). Intrabar pokes never change state.
- **Watch invalidation + Cooldown** — a confirmed close back across the mid cancels the watch,
  pulls any resting order, and blocks re-watch for `cooldown_bars` (default **3**). A **new**
  clean close beyond the mid is then required (no instant re-watch — kills mid-chop churn).
- **Pullback rule** — if price runs more than `chase_atr` ATR past the OR level without a valid
  fill, the side enters **PULLBACK**: do not chase. Fills unblock when price retests within
  `retest_atr` ATR of the retest target; normal fill rules then re-check. **Per-asset since
  F75/F78 (2026-07-06):** NQ/MNQ chase **1.5** with the **impulse-midpoint** retest target
  (50% of the extension impulse — releases earlier than a full edge revisit, +13.5R);
  QQQ/SPY/ES chase **0** = pullback mode off (the chased entries ARE the winners there).
- **Range / stale rule (new)** — a watch that produces no valid fill within `stale_bars`
  (default **24** = 2 h on 5m; 0 = off) is a RANGE: the side stands down until the mid is lost
  and a fresh cycle begins.
- **Two-entry limit** — `max_entries` per side per session (equities **2**, futures **3** per
  the validated asset config); after that the side is **LOCKED**.
- **Fill stack (unchanged, validated)** — body close beyond the level (strong body ≥ 0.25 of
  range, right colour), wick-only breaks never fill, next-candle continuation (F59c), direction
  sequence c>c₁>c₂ (F61), vol-expansion OR-width filter, OR-mid day bias, confirmed bar only.
- **Hard invalidation (unchanged)** — confirmed close beyond the *opposite* OR edge or a
  pre-entry tag of the side's proposed stop → INVALID until the breakout edge is reclaimed on a
  confirmed close (hysteresis, no flip-flop).

## One set of knobs (`EntryStandard`)

Defined once in [BOT/bot/strategy/orb_state.py](../BOT/bot/strategy/orb_state.py) (`ENTRY_STANDARD`)
and mirrored as the "Entry standard" input group in all three Pine scripts:

| Knob | Default | Meaning |
|---|---|---|
| `ctx_gate` | on | Layer 1: Structure + VWAP must align to ARM |
| `watch_gate` | on | Layer 3: confirmed close beyond OR mid required (WATCH) |
| `cooldown_bars` | 3 | bars blocked after a watch cancel |
| `stale_bars` | 24 | max bars in WATCH without a fill → RANGE (0 = off) |
| `chase_atr` | NQ/MNQ 1.5 · others 0 | extension past the level that flips WATCH → PULLBACK (F75/F78 per-asset; 0 = off) |
| `retest_atr` | 0.25 (ES 0.5) | retest distance that restores WATCH (gauntlet-adopted per asset) |
| `retest_mode` | NQ/MNQ impulse_mid · others edge | retest target (F78: impulse midpoint adopted on NQ/MNQ) |
| `max_entries` | 1 (eq) / 3 (fut) | entry limit per side per session (F76: equity re-entries lose) |
| `strong_body` | 0.25 | fill: min body/range (no wick-only) |
| `ft_confirm` | on | fill: next-candle continuation (F59c) |
| `dir_seq` | on | fill: direction sequence (F61) |

## Where each surface implements it

| Surface | File | What it does |
|---|---|---|
| Python FSM (reference) | `BOT/bot/strategy/orb_state.py` — `OrbSideState` | full canonical machine incl. LOCKED/`reset_cycle()`; `slope_grade()` = Layer 2 |
| Engine (backtest truth) | `engine/hs_backtest.py` — `_orb_signals(watch_live, cooldown_bars, stale_bars, retest_atr)` | causal watch tracking: bar *i* fires on the watch state as of bar *i−1*'s close |
| BOT candidate replay | `BOT/bot/strategy/orb_candidates.py` — `run_backtest()` (the ONE canonical call) | context via `st_state`+`vwap_sess` arrays; `STRATEGY_VERSION` pins the rule version |
| BOT live scan | `BOT/bot/strategy/families.py` — breakout family | 1m-fed structure + VWAP context; slope grade + PIT feature snapshot attached to every signal |
| Pine STACK | `production/HIGHSTRIKE_ORB_STACK.pine` | inputs group "Entry standard"; watch machine in the confirmed-bar block; canonical dashboard states + why-strings |
| Pine AUTO | `production/HIGHSTRIKE_ORB_AUTO.pine` | resting order rests ONLY while WATCH is live; cancel pulls it; chase/retest guard on close-confirm entries |
| Pine OPTIONS | `production/HIGHSTRIKE_ORB_OPTIONS.pine` | same states/gates on the signal layer |

Known one-bar nuance: with `wait_ft` off, the Pine can activate watch and fill on the same
breakout candle (its close > mid by definition), while the engine requires the watch from the
prior bar. With the shipped default (`wait_ft` on) the two are identical.

## Validation status — A/B RUN 2026-07-04 (data drive, 2018→2026)

`research/ab_entry_standard.py` (report: `BOT/data/ml/reports/ab_entry_standard.json`, visible on
the Training Lab dashboard `/training`). Three variants per symbol — baseline (pre-standard
plain-ORB), layer3_only (watch/cooldown/stale/pullback), standard (+ Structure+VWAP context):

| Sym | Variant | Trades | Win% | Avg R | Total R | PF | MaxDD | Yrs+ |
|---|---|---:|---:|---:|---:|---:|---:|---|
| QQQ | baseline | 433 | 32.3 | +0.273 | 118.2 | 1.40 | −14.1 | 8/9 |
| QQQ | layer3_only | 421 | 34.2 | +0.340 | 143.3 | 1.52 | −14.2 | 9/9 |
| QQQ | **standard** ✅ | 312 | 36.2 | **+0.449** | 140.0 | **1.70** | **−9.1** | 8/9 |
| SPY | baseline | 460 | 31.3 | +0.183 | 84.0 | 1.26 | −23.3 | 7/9 |
| SPY | **standard** ✅ | 341 | 35.2 | **+0.329** | 112.0 | 1.50 | −15.4 | 8/9 |
| NQ | baseline | 728 | 40.0 | +0.140 | 101.6 | 1.23 | −49.5 | 13/17 |
| NQ | **layer3_only** ✅ | 707 | 40.6 | **+0.155** | 109.3 | 1.26 | −45.8 | 13/17 |
| NQ | standard | 576 | 38.4 | +0.109 | 62.8 | 1.17 | −50.2 | 12/17 |
| ES | baseline | 729 | 39.0 | +0.073 | 52.9 | 1.11 | −63.0 | 12/17 |
| ES | **layer3_only** ✅ | 713 | 38.8 | **+0.087** | 62.1 | 1.13 | −56.5 | 11/17 |
| ES | standard | 593 | 37.8 | +0.041 | 24.4 | 1.06 | −50.0 | 10/17 |

**Adopted (2026-07-04):**
- **Layer 3 (watch / cooldown / stale / pullback) is ON everywhere** — it improves all four
  instruments (avg R, PF, and mostly DD) while trimming trades.
- **Layer-1 context is PER ASSET**: hard gate **ON for equities** (QQQ/SPY — big lift + lower DD),
  **OFF for futures** (NQ/MNQ/ES/GC — the chart-TF structure lags the break; context stays a
  GRADE there). Implemented as `Asset.ctx_gate` in `asset_config.py` and the `ctx_auto` input
  (equities ON / futures OFF) in the STACK/AUTO Pines.

Remaining caveats: the historical replay uses chart-TF structure for context (live uses the 1m
feed — forward-verify); Pine edits still need a **TradingView compile-check** + a forward paper
session. OPTIONS/V1/MTF scripts are intentionally NOT updated (user scope rule 2026-07-04) — on a
futures chart, toggle OPTIONS' `ctx_gate` OFF manually until told to update it.
