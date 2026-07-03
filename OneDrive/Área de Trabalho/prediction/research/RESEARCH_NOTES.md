# HIGHSTRIKE — ORB research notes

Goal: push the FOUR characteristics as high as possible — expectancy (R/trade), profit factor,
win %, max drawdown (lower = better) — while staying robust (lower 90% CI > 0, both signals > 0).
Tool: `python research/orb_mtf_research.py NQ 15m` (computes harness state + MTF once, sweeps cheaply).

## F67 (numbers pending) — PROBABLE liquidity-zone engine + bounce-vs-reversal machine (user research 2026-07-03)

`orb_liquidity_zones.py` — RESEARCH SIDE ONLY per user instruction (no STACK/BOT propagation yet;
**when it graduates, STACK + BOT are the PRIMARY propagation targets** — standing user rule). From
the single 1m array: pivot clusters, equal highs/lows, rejection/absorption bars (wick ≥ 2×body +
vol ≥ 1.5×avg), OR H/M/L + prev-day H/L/C + session VWAP, approx volume-by-price POC/HVN — merged
(0.25 ATR tol) and scored `L = 0.25T + 0.20V + 0.20R + 0.15S + 0.10H + 0.10A` (doc's starting
weights; the doc lists 2 variants — WEIGHTS is a dict, tune on data). Wording rule enforced:
PROBABLE / POTENTIAL only — 1m OHLCV can never see actual pending orders (needs L2/MBO). Reversal
machine (mirrored): TREND → DECELERATING → POSSIBLE_TURN → REVERSAL_CANDIDATE → CONFIRMED |
FAILED_BOUNCE on the doc's six checks (slope deceleration, no new extreme, 2-of-3 close
persistence, micro structure break, retracement depth, recovery efficiency); candidate/confirm
need 2-of-3 evaluations (noise control). Synthetic validation green (`--selftest`: triple-touch
support, mirror symmetry, absorption bar, the doc's own 100→97.75→98.60 walkthrough,
failed-bounce, bearish mirror). **Numbers: `python research/orb_liquidity_zones.py NQ ES` on the
data drive** — zone hit-rate vs a RANDOM in-range level control (zones must beat random levels
first), then the standard additivity gauntlet on the stack before any gating. Caution: the F65
graveyard killed all DIRECTION detectors — zones predict LOCATION (where reactions happen), a
different claim, but the same curve-fit discipline applies.

## F66 — SIZING LADDER policy: act on direction sooner via tranches (equity WIN / futures NEUTRAL) (2026-07-02)
`orb_sizing_ladder.py`. NOT a new signal — a POLICY over two existing cohorts: **starter** = break+OR-mid+dir-seq
(the 'none' cohort, independently PASS) at 0.4×; **add** = when st_state(lb3) confirms (struct3, fires ~30–60m
later at a worse price) at 0.6×. Risk-based sizing (1.0 = full budget; maps to GRADE_MULT B=0.4/A=1.0). BINARY =
current (wait; full size on confirmed only). Reentry off (1:1 day/side match). v1 does NOT model the
'exit starter on opposite structure' cut.

| sym | BINARY PnL / maxDD (PnL/|DD|) | LADDER 0.4/0.6 (PnL/|DD|) | unconf-only cohort (BINARY skips) | verdict |
|---|---|---|---|---|
| QQQ | +47.5R / −15.4 (3.08) | **+60.6R / −13.3 (4.57)** | **+0.344R** | LADDER WINS (+28% PnL, lower DD) |
| SPY | +112.0R / −8.1 (13.84) | **+114.4R / −7.4 (15.40)** | +0.163R | LADDER Pareto WIN (more PnL, less DD) |
| NQ  | +90.5R / −19.0 (4.76) | +90.8R / −21.4 (4.24) | +0.041R | NEUTRAL (tied PnL, slightly worse risk-adj) |
| ES  | +45.8R / −29.4 (1.56) | +42.2R / −35.9 (1.18) | −0.031R | LADDER LOSES |

DRIVER: the ladder monetizes the trades BINARY SKIPS (the unconfirmed-only cohort) at 0.4× — that cohort is
POSITIVE on equities (QQQ +0.344 / SPY +0.163) but flat/NEG on futures (NQ +0.041 / ES −0.031). So the ladder is
a risk-adjusted WIN on **EQUITIES**, neutral-to-worse on **futures** → per-instrument policy: LADDER for equity,
BINARY (wait) for futures. The 'act 30–60m sooner' benefit (starter fires at the break) is real everywhere.
NEXT (v2): model the exit-starter-on-opposite-structure cut — may rescue the futures case by cutting the bad
unconfirmed trades early. Plumbing (grades / GRADE_MULT / struct_aligned) already exists — one policy toggle.

## F65 — Direction-detector GRAVEYARD: the full specced suite is DEAD (2026-07-02)
`orb_dir_state.py` · `orb_dirstate2.py` · `orb_efficiency.py` (+ `orb_fast_direction` / `orb_lead_lag` /
`orb_predict` / `orb_flow_channels`). Every detector tested BOTH as a standalone direction gate AND as
additive-confluence on the FULL stack (struct3 + OR-mid + dir-seq + vol-exp 2.4), with the dropped-cohort
additivity control + cross-instrument (NQ/QQQ/SPY) consistency. NONE graduate — the direction edge is saturated
by structure + OR-mid + dir-seq + vol-exp.

ADDITIVE-CONFLUENCE on the full stack (NQ base exp +0.334 / CIlo +0.165):

| detector | NQ B (add) | dropped-disagree | verdict |
|---|---|---|---|
| Theil–Sen slope | +0.205 (<base) | +0.471 (WINNERS) | flips: SPY lifts, NQ drops winners |
| Mann–Kendall | +0.207 | +0.491 (WINNERS) | flips |
| Kalman (α-β) velocity | +0.257 | +0.440 (WINNERS) | flips |
| OLS slope t-significance | +0.120 | +0.483 (WINNERS) | flips |
| persistence ±ε | +0.184 | +0.393 (WINNERS) | drops winners |
| HH/LL candle ratio | +0.063 | +0.386 | dead both sides |
| CUSUM (K=0.5·ATR, h=3·ATR) | n=6 | — | fires too rarely to gate |
| regime-z (HMM proxy) | +0.181 | +0.449 | flips |
| Kaufman efficiency (ER) | +0.341 ≈ base, CIlo↓ | not losers | REDUNDANT with vol-exp |

Standalone, the trend-slope family (Theil–Sen / MK / Kalman / OLS) PASSES — but that's just trend-following,
which structure + ORB already do; as additive confluence it either drops below base or SIGN-FLIPS across
instruments (SPY-only "lifts" are non-monotonic across thresholds = fitted, and the NQ dropped-disagree cohort
are WINNERS = the F44/DoW curve-fit signature). Efficiency looked additive vs a base WITHOUT vol-exp, but the
full-stack control kills it (redundant with the wide-OR filter). See `memory/highstrike-fast-direction` for the
full ~36-method graveyard (momentum / EMA / regression slope / microprice / cross-asset lead-lag / VPIN / Renko /
Donchian / EHMA / Markov-predict / XGBoost-LightGBM-NN-HMM — all redundant, curve-fit-inconsistent, or
worse-than-follow). Conclusion: direction at tradeable resolution is FOLLOWABLE, not forecastable.

## F65 (numbers pending) — DIR-fast component plan: OR → SLOPE → STRUC + the combined slope engine (user, 2026-07-02)

USER OBSERVATION (screenshots, QQQ 5m vs 1m): when the three DIR-fast components AGREE —
OR zone + SLOPE + STRUCTURE — price is moving in that direction; the 1m read is ON-SPOT while the
higher-TF read lags (the velocity of the calculation scales with bar size). Attack order set by the
user: **1) OR, 2) SLOPE, 3) STRUC.**

* **1 OR — DONE (shipped, all 5 production Pine + BOT).** Works as specified: price above OR-mid =
  WATCH (mirror short below); a strong FULL-BODY candle close beyond OR-high = automatic fill when
  the other gated conditions align; confirmed close beyond the OPPOSITE edge / pre-entry stop tag =
  INVALIDATED (orders cancelled, levels cleared) until the breakout edge is reclaimed. The DIR-fast
  OR arrow now shows the LIVE zone, not the frozen 10:00 bias.
* **2 SLOPE — ENGINE SHIPPED, GAUNTLET PENDING.** Combined slope per the user's research doc:
  `S = 0.50·(closeSlope/ATR) + 0.30·(bodyMidSlope/ATR) + 0.20·bodyPressure` over N=12 candles —
  regression over EVERY candle (not first/last), body midpoints catch open/close progression,
  recency-weighted (newest ≈ 2×) body pressure kills the one-big-candle illusion; ATR
  normalization = comparable across instruments/TFs (≈ ATRs advanced per bar). Bands (STARTING
  values, must be tuned per TF): |S| ≥ 0.10 directional, ≥ 0.30 strong. 7-state classifier
  (STRONG_UP…STRONG_DOWN) adds persistence ≥ 60/70 %, ER ≥ 40/60 %, and REQUIRES structure +
  price-location agreement — slope alone must never call direction (doc §7). Computed EVERYWHERE:
  `bot/strategy/orb_state.slope_engine()` + `directional_state()` (in every proposal's `dir_fast`,
  with `aligned` = OR+SLOPE+STRUC agreement), and `f_slope_comb()` inside the 1-minute
  request.security feed of all 5 production Pine (dashboard S value + arrow). Synthetic validation
  green (the doc's own worked examples, mirror symmetry, scale invariance, zero-ATR/flat guards —
  `BOT/tests/test_orb_state.py`). **Numbers: run `research/orb_slope_state.py NQ QQQ SPY` on the
  data drive** — standalone gate sweep, additivity on the stack, alignment cohorts, latency.
  Prior context: raw regression slope landed at plain-ORB (fast-direction study) — the OPEN
  question is whether the COMBINED S (bodies + pressure) with per-TF thresholds does better, and
  whether ALIGNMENT is a usable sizing/skip conditioner even if the gate is not.
* **3 STRUC — 1m FEED SHIPPED, GAUNTLET PENDING.** The struggle is confirmation VELOCITY: lb=5
  pivots confirm in lb×TF minutes (25+ on 5m, 5 on 1m) — the 1m chart is right first because the
  same machine runs on smaller bars. Shipped: `fast_dir` (all gate scripts) computes st_state in
  the 1-MINUTE context on any chart TF, each context keeping its own auto pivot lookback
  (futures 3 / equity 5 = 3–5 minute confirms); BOT twin `families.fast_state_1m()` aligns the 1m
  state causally onto the 5m engine frame. **Gauntlet: gate = st_state on 1m bars** vs the chart-TF
  gate (behavior change vs the validated backtest until it passes; `fast_dir` OFF reverts).
* **3 STRUC update (2026-07-03) — ROOT CAUSE FOUND + FIXED: gap-aware CHoCH.** Even on 1m the
  machine needed ~15 closed bars to flip because the old CHoCH rule required a CROSSING bar
  (previous close still on the old side of the last swing) — in a fast move the swing reference
  itself steps toward price via each newly confirmed pivot, so the crossing bar NEVER exists and
  st_state stays wrong (measured: **41 stale bars** on the diagnostic dump tape, with 0↔1
  oscillation because leftover HH/HL pairs kept re-claiming UP). Fix (engine `choch_gap_aware=True`
  + all 8 Pine machines): flip whenever price CLOSES beyond the last swing against the trend
  (once-only via the prev-state guard), and a claim guard — UP may only be claimed with close ≥
  last swing low, DOWN only with close ≤ last swing high. Verified 41→0 violations; bit-identical
  to the old rule on clean trending tapes both directions (`BOT/tests/test_structure_velocity.py`).
  **This CHANGES the engine gate vs the validated backtest → A/B on the data drive with
  `choch_gap_aware=False` before trusting old numbers.**
* **3 STRUC update (2026-07-03) — multi-TF ROLLING direction engine (user research file,
  detection layer).** One 1m array = single source of truth; every chart TF re-scored on EVERY
  completed 1m bar from its own window (2M/5M/15M/30M/1H/4H = 2/5/15/30/60/240×1m) —
  `D = 0.30·S + 0.20·P + 0.20·E + 0.15·B + 0.15·M`, bands ±0.12/±0.30/±0.65 → RANGE/WEAK/DIR/
  STRONG, RANGE override on low efficiency + midpoint crossings. ROLLING vs clock-aligned
  CONFIRMED states reported side by side ("15M ROLLING: DOWN · 15M CONFIRMED: UP" = pullback in
  an uptrend). Immediate 2-bar read refreshed by the live last trade between minute closes (the
  10–15 s update — true intrabar granularity needs tick data, per the research file's own note).
  Shipped: `bot/strategy/direction_engine.py`, `mtf_direction` on every proposal, `/api/direction`
  poll endpoint. **DETECTION only — the confirmed swing st_state + dir_fast 1m feed remain the
  backup/validated gate until this passes a gauntlet.** Entries stay on the 2-bar cadence.

## Finding 1 — Multi-timeframe confirmation HURTS the ORB (counterintuitive but consistent)
Requiring N of {1h, 4h, Daily} to agree (EMA50>200 stack) with the breakout:

| exit | mtf | n | exp | PF | win% | maxDD | lowerCI | both>0 |
|---|---|---|---|---|---|---|---|---|
| scale_be | **0** | 799 | **+0.133** | **1.29** | 57.1 | −31.3 | **+0.069** | YES |
| scale_be | 1 | 678 | +0.093 | 1.20 | 55.5 | −31.2 | +0.022 | YES |
| scale_be | 2 | 532 | +0.071 | 1.15 | 54.5 | −37.1 | −0.010 | YES |
| scale_be | 3 | 342 | +0.039 | 1.08 | 53.8 | −29.5 | −0.058 | no |
| tp2_full | **0** | 769 | **+0.184** | **1.30** | 41.1 | −36.1 | **+0.096** | YES |
| tp2_full | 3 | 329 | +0.073 | 1.11 | 38.0 | −28.2 | −0.058 | no |

**Every metric falls as MTF tightens.** ORB is a momentum-impulse entry; demanding higher-TF
trend agreement filters out profitable *counter-HTF* breakouts. → **default MTF OFF** (kept as a
toggle in the strategy/indicator for experimentation). The breakout's own chart-TF trend filter
(close>EMA50, EMA21>EMA50) is sufficient.

## Finding 2 — the ORB edge is ROBUST across structural levers (not curve-fit)
OR window {9:30-9:45, -10:00, -10:30} × reward {1.5, 2, 3R}, tp2_full, no MTF — **all 9 PASS**
(both signals > 0 AND lower CI > 0). An edge that survives every sensible variant is a plateau,
not a spike.

## Finding 3 — the four metrics TRADE OFF (a frontier, not a single max)
- **Higher reward (3R)** → higher expectancy (+0.19/+0.21R) but **lower win% (~31%)** and worse maxDD.
- **Lower reward (1.5R)** → higher win% (~47%) but lower expectancy.
- You cannot maximize all four at once. Pick a point on the frontier by preference.

### Recommended points
- **Balanced (default):** OR 9:30-10:00, TP2 2R, scale_be → +0.13R, PF 1.29, **win 57%**, maxDD −31R.
- **Best drawdown/CI:** OR 9:30-**9:45**, TP2 2R, tp2_full → +0.186R, PF 1.30, win 41%, **maxDD −26R**, **CI +0.100**.
- **Max expectancy:** OR 9:30-10:30, TP2 3R → +0.209R, PF 1.29, win 31%, maxDD −48R.

## Finding 4 — PF pushed into the 1.40-1.75 "real edge" zone (`research/orb_optimize.py`)
Targets: PF 1.40-1.75, expectancy >= +0.05R, win up, all reliably above previous, both signals, CI>0.
Swept breakout-strength (clear OR by k*ATR) x time-of-day cutoff x reward x exit (36 configs).
**14 qualify** (broad plateau, not a spike). Two principled levers drive it:
- **Morning-only** (entries before ~12:00-13:00 ET) — the opening drive is the high-quality ORB
  window; afternoon breakouts are noise. Alone with 3R: PF 1.42 even at zero breakout buffer.
- **Breakout strength** (clear OR by 0.10-0.25 x ATR) — kills false breaks, adds win% + PF.
- **3R reward + scale-50%@TP1** — runner captures the trend leg.

| brk | cutoff | RR | exit | n | exp | PF | win% | maxDD | lowerCI |
|---|---|---|---|---|---|---|---|---|---|
| 0.25 | 12:00 | 3 | scale | 524 | **+0.226** | **1.51** | **58%** | **−16R** | **+0.138** |
| 0.10 | 13:00 | 3 | scale | 630 | +0.211 | 1.48 | 59% | −20R | +0.133 |
| 0.00 | 13:00 | 3 | scale | 646 | +0.187 | 1.42 | 58% | −24R | +0.110 |

vs baseline ORB (2R, all-day): exp +0.13 PF 1.29 win 57% maxDD −31R. **All four improved.**
Caveat: PF 1.5 is a 15m peak; same config on **5m still passes** (exp +0.10, both+, CI +0.02) but
PF eases to 1.20 — edge is real on both TFs, the 1.5 is 15m-specific. → **PINE DEFAULTS UPDATED**:
TP2=3R, entry cutoff 13:00, breakout buffer 0.10 ATR (a robust mid-plateau point, not the peak).

## Finding 5 — beating the record (wider sweep: brk x cutoff x reward 2/3/4 x exit)
**60 of 96 configs qualify** (PF>=1.40) — huge plateau. Two extra levers beat Finding 4:
- **Earlier cutoff (11:30 vs 13:00)** — concentrates on the cleanest opening-drive breaks.
- **4R reward** (vs 3R) — TP1 win-rate unchanged (~59%), runner targets a bigger trend leg.

| brk | cutoff | RR | exit | n | exp | PF | win% | maxDD | CI |
|---|---|---|---|---|---|---|---|---|---|
| 0.25 | 11:30 | 4 | scale | 445 | +0.274 | **1.63** | 59% | −18R | +0.166 | ← 15m PEAK |
| 0.10 | 13:00 | 4 | scale | 599 | +0.239 | **1.55** | 59% | −20R | +0.150 | ← robust DEFAULT |
| (prev record, 3R) | | | | | +0.211 | 1.48 | 59% | −20R | +0.133 |

The PF-1.63 peak is 15m-specific but **improved on 5m too** (PF 1.20→1.27, exp +0.10→+0.13, both+,
CI+0.05) — better on BOTH TFs than Finding 4. **Default set to the robust 4R point (PF 1.55)**, not
the peak; set entry cutoff 11:30 for the 1.63 peak. The "4R" win-rate doesn't drop because TP1 is
unchanged — only the runner target widened.

## MTF signal display — `HIGHSTRIKE_ORB_MTF_SIGNALS.pine`
Shows 5m + 15m ORB breakouts on ANY chart via request.security, with a daily-latched 5m+15m
confluence mark + alerts. NOTE: a confluence FILTER (require both TFs) wasn't adopted as an entry
gate — 15m already requires a stronger break than 5m, so 5m-confirmation rarely filters anything.

## Finding 6 — per-timeframe optima + the TF-adaptive mapping (`research/orb_per_tf.py`)
Best robust config per TF (max expectancy among PF>=1.40, both>0, CI>0), NQ:

| TF | breakout | cutoff | RR | exp | PF | win% | maxDD | CI |
|---|---|---|---|---|---|---|---|---|
| 5m  | 0.0 ATR  | 11:30 | 4 | +0.151 | 1.32 | 56% | −29R | +0.064 |
| **15m** | **0.25 ATR** | **11:30** | **4** | **+0.274** | **1.63** | 59% | −18R | +0.170 | ← sweet spot |
| 30m | 0.25 ATR | 13:00 | 4 | +0.168 | 1.38 | 58% | −27R | +0.070 |

→ **TF-adaptive mapping baked into the Pine** (`auto_tf`, default ON): <=5m -> 0.0/11:30; <=15m ->
0.25/11:30; 30m+ -> 0.25/13:00; reward 4R all. The MTF-signals indicator auto-adapts each TF's pull.
**15m is the best TF to trade.**

## Finding 7 — reward beyond 4R is a TAIL TRAP (do NOT chase)
15m reward sweep (brk0.25/11:30/scale): RR4 +0.274R PF1.63 -> RR8 +0.344 PF1.81 -> RR10 +0.366 PF1.89.
Expectancy keeps rising, BUT with the runner->BE exit the gain comes from the rare 4R-10R trend
runners; NQ's 16y was a historic trender so they appeared. This is REGIME-DEPENDENT (dies in chop)
and PF1.89 nears the roadmap's "4.0+ = curve-fit warning". **Default capped at 4R** (the broad
plateau); reward is a tunable input for those who accept the trend-dependence. Robustness > peak R.

## Finding 8 — retest entry: better on 15m, WORSE on 5m (TF-dependent)
Retest = require a break (clear OR by k*ATR) THEN a pullback to the OR edge, enter at the edge
(`execm="retest"` in `_orb_signals`/`backtest`). Fewer trades (some breaks never pull back — ~7% fewer).
- **15m (4R/scale): retest BEATS stop on all four** — exp +0.347->+0.368, PF 1.88->1.97, win 63->64%,
  maxDD −24->−21R, CI +0.253->+0.274 (508 vs 545 trades).
- **5m: retest LOSES** — exp +0.246->+0.161, PF 1.58->1.35, maxDD −19->−33R (5m noise turns pullbacks
  into stop-outs). → On 5m keep STOP. Retest is a 15m-only edge; NOT wired into Pine (user trades 5m,
  where stop wins). Available in the backtest engine for 15m users.

## Finding 9 — the ORB edge VALIDATES on equities/ETFs (SPY, QQQ) — cleaner than futures
XNAS.ITCH 1m 2018-2026, equity economics ($0.01 tick, commission-free, 1-tick slip). Per-TF
stop-entry 4R/scale, ALL PASS (with EOD-flat, see Finding 10):
- **QQQ 15m: +0.34R PF 2.11 win 66% maxDD −5.6R CI +0.27** (the flagship — ¼ of NQ's drawdown)
- SPY 15m: +0.30R PF 1.88 win 63% maxDD −7.4R CI +0.22 ; both run +0.30/5m too.
The SAME NQ-tuned config transfers (not curve-fit). Equities are cleaner: lower relative cost +
no overnight gap. SHORT side especially strong on QQQ (+0.47R). Engine is asset-aware (`EQ` set).

## Finding 10 — look ALL DAY (not morning-only) — REVERSES Finding 4, because of stop-entry + EOD-flat
Two engine fixes made this honest: (a) **EOD-flat** added to the sim (`eod_min=958`, flatten at
~15:58 to match the Pine — before, late entries were held overnight = inflated); (b) the **stop-entry**
fills better than the old close-confirm. With both, extending the entry cutoff 11:30 -> 15:00 IMPROVES
exp/PF/win/CI on all of SPY/QQQ/NQ at 5m+15m; 15m drawdown also improves (NQ −20 -> −10R). The old
"morning-only" rule (Finding 4) was an artifact of the close-confirm entry. → **Pine cutoff default
now 15:00 (auto_tf), all TFs.** 5m drawdown worsens slightly (afternoon noise) but exp/PF still rise.
NOTE: Finding 4/5/6/7 numbers predate EOD-flat (used close-confirm, held overnight) — Finding 9/10 are
the current, EOD-accurate, stop-entry numbers.

## Finding 11 — volume confirmation does NOT help (within-noise / hurts)
Require breakout-bar relative volume > k x SMA(vol,20) (`vol_conf`/`vol_mult` in `_orb_signals`/`backtest`).
QQQ 15m: base +0.342/PF2.11 -> vol>1.0x +0.355/2.14 (marginal, -34 trades) -> vol>1.5x +0.346/2.07 (worse).
NQ 15m: base +0.274/PF1.83/maxDD−10.5 -> vol>1.2x +0.273/1.79/−15.6 -> vol>1.5x +0.265/1.74/−21.4 (DD blows out).
Loosest threshold = within noise; tighter = culls trades and WORSENS drawdown. Same pattern as close-confirm
/retest/bigger-buffer — trend+regime+buffer already select; more confirmation trades fills for noise.
**NOT adopted** — `vol_conf` stays an off-by-default engine toggle, NOT wired into any Pine file.

## Finding 12 — VWAP-side = dud; entry-bar STRENGTH = real lead (but a catch) — `research/orb_levers.py`
POST-HOC screen (filter the taken trades, see if the subset is better; not the final number):
- **VWAP-side** (long>VWAP / short<VWAP): 96% of breaks are ALREADY on the right side -> filters almost
  nothing and slightly HURTS (QQQ +0.342->+0.301, NQ +0.274->+0.242). NQ wrong-side n=30 +1.17R is a
  tiny outlier sample. **Dropped.**
- **Entry-bar STRENGTH** (break bar closes in the top/bottom half toward the trade): clearly separates —
  QQQ strong-body PF 2.11->2.42 (+0.405R, CI+0.319, 73% kept) vs weak-body PF1.45; NQ 1.83->2.13
  (+0.335R, maxDD −10.5->−6.7, 72% kept) vs weak-body PF1.28. **Real quality signal.**
  ⚠️ CATCH: body is only known at BAR CLOSE, but stop-entry fills INTRABAR on the touch — so it can't be
  applied at entry. Using it = switch to CLOSE-CONFIRM (which gave worse fills). Net unproven until
  "close-confirm + strong-body" is tested at SIGNAL level. NOT adopted; flagged for a proper test.

## Finding 13 — entry-quality round 2: body lead is DEAD, OR-width is noise, GAP is a real equity tilt — `research/orb_entry_quality.py`
Decisive, honest tests on QQQ + NQ + SPY (15m, prod config), resolving the Finding-12 lead:
- **close-confirm + strong-body = DEAD.** The Finding-12 "strong-body PF 2.42" was a LOOKAHEAD ARTIFACT — it
  filtered STOP-entry trades by a bar-close that occurs AFTER the intrabar fill. Done honestly (switch to
  close-confirm so the body is actually known at fill), the body filter culls almost nothing (89-92% kept —
  a close-confirm bar already closes beyond the level, i.e. is already "strong-body") AND the worse fills
  crater the edge: QQQ +0.342→+0.205, NQ +0.274→+0.128, SPY +0.298→+0.077. C (close+body) ≈ B (close), both
  << A (stop). **Stop-entry stays. The one open lead is closed.**
- **OR-width filter = DUD.** Tercile buckets (narrow/mid/wide OR in ATR) disagree across assets — NQ: wide is
  worst (PF1.51); SPY: mid is worst (PF1.50); QQQ: all ~2.0-2.2. No robust rule; the feature-study corr
  (Finding 15) also FLIPS sign. **Dropped.**
- **GAP (equity only) = a real, cross-validated QUALITY TILT.** Breakouts AGAINST the overnight gap (long
  after a gap-down / short after a gap-up) are far better on BOTH equities: QQQ against-gap +0.500R/PF3.14/
  win73%/CI+0.377 vs with-gap +0.273/PF1.80; SPY +0.446/PF2.55/win69% vs +0.222/PF1.61. ⚠️ NOT a skip-filter
  (with-gap still passes, +0.22R) — it's a CONFIDENCE/SIZING signal. Caveats: PF3.14 nears the "4.0=curve-fit"
  zone, against-gap is only ~30% of trades (~19/yr/symbol — thin), equity-only (NQ trades ~24h, no clean gap).
  **Logged as a lead, NOT adopted.**

## Finding 14 — exits & sizing: tp2_full is a frontier point, time-stop is DEAD, vol-sizing is already baked in — `research/orb_exits.py`
(adds an off-by-default `time_stop` engine param — reproduces production exactly when 0, like `vol_conf`.)
- **Exit mode is a FRONTIER, not a winner.** Full-position-to-target (`tp2_full`, 4R/-1R) beats the prod
  scale-out (`scale_be`) on EXPECTANCY + CI on all three (QQQ +0.408 vs +0.342, NQ +0.337 vs +0.274, SPY
  +0.389 vs +0.298) but at LOWER win% and ~3R MORE drawdown (QQQ −5.6→−8.8). Same PF. `scale_be` is the
  deliberate smoother/high-win point; this VALIDATES the AUTO file's single-bracket design. `trail` is worse
  everywhere. **No change.**
- **TIME-STOP = DEAD.** Flattening after N bars only drops expectancy monotonically for marginal DD relief
  on all three (NQ +0.274→+0.181 to shave −10.5→−7.2). The "dead" trades it cuts are net contributors (slow
  winners). **EOD-flat is the right and only time bound. Dropped.**
- **SIZING.** R-metrics already assume fixed-$-RISK per trade (= volatility sizing: fewer contracts when ATR
  is high) — that is the disciplined, tail-safe default. Fixed-CONTRACTS shows a higher Calmar in-sample
  (QQQ 38.9 vs 31.4) but that is a HIGH-VOL-REGIME ARTIFACT (risk_pts is fattest exactly where the edge was);
  it concentrates risk in vol spikes and is NOT a robust reason to switch. **No new knob; keep fixed-% risk.**

## Finding 15 — feature study + WALK-FORWARD: edge is time-stable; VWAP-EXTENSION is the new #1 lead — `research/orb_validation.py`
Systematic instead of one-lever-at-a-time. Spearman-corr each pre-entry feature with net_R; a lead counts
only if the SIGN agrees across QQQ + NQ + SPY (7 of 8 do).
- **WALK-FORWARD (the headline):** per-year edge is **QQQ 9/9, SPY 9/9, NQ 16/17 full years positive**; OOS
  split @70% HOLDS on all three (e.g. QQQ IN +0.325/PF2.01 → OUT +0.380/PF2.35). The only soft patch is NQ
  2010-2013 (deep-past futures, PF~0.9-1.5); everything 2016+ is strong. **The edge is not one lucky regime.**
- **VWAP-EXTENSION = strongest consistent feature (corr −0.20).** Breakouts that fire while already EXTENDED
  from session VWAP underperform; the best breaks fire NEAR VWAP. This correctly REFRAMES the old VWAP-side
  dud (side doesn't matter — *extension* does) and rhymes with the against-gap finding (price near/reverting
  = higher quality). **The one genuine new lead — candidate for an honest signal-level test (skip/penalize
  entries > k·ATR beyond VWAP, using the PRIOR bar's VWAP to stay causal). NOT adopted until tested like a
  signal, not a screen (the body lead is why).**
- **Volatility level helps** (`atr_lvl`/`risk_pts` +0.12..+0.19, consistent) — characterizes WHY the edge is
  regime-dependent; not a tradable filter (can't trade only high-vol days without losing all-weather).
- **Shorts > longs, robustly** (`dir_long` −0.10..−0.17; shorts +0.39..+0.47 vs longs +0.21..+0.26 on all
  three). A real asymmetry, but both sides positive → NOT a filter; at most a mild size tilt.
- **`entry_body` +0.10..+0.15 consistent** — confirms body is a real quality signal but (Finding 13) it's
  untappable given stop-entry. **`or_w_atr` flips** — confirms OR-width is noise. Friday looks strong on all
  three but is left as curve-fit (not adopted).

## Finding 16 — VWAP-extension cap PASSES an honest signal-level test (the first real lead to graduate) — `research/orb_vwap_cap.py`
Skip the entry AT SIGNAL TIME when the breakout level sits > k*ATR beyond the PRIOR-bar session VWAP
(causal; skipping a long leaves the engine flat so a later short can still fire). Off-by-default engine
param `vwap_cap` (0 = production, unchanged). Swept k on QQQ/NQ/SPY at 15m AND 5m:
- **The relationship is REAL: monotonic + sign-consistent across all 3 assets × both TFs** (tighter cap →
  higher exp/PF/win, lower DD). That cross-asset/TF consistency is the opposite of curve-fit — every dead
  lever flipped; this never does.
- ⚠️ **The low-k tail is a curve-fit MIRAGE — ignore it.** k<=1.0 shows PF 6-43, win 85-100% on only
  30-140 surviving trades (survivorship). Not usable. The signal lives in the MODERATE caps.
- **k=2.0 is the robust adoption point** — the only level where exp improves on all three, both TFs,
  both sides >0, CI up, DD down:
  | | 15m Δexp / PF / DD | 5m Δexp / PF / DD | kept |
  |---|---|---|---|
  | QQQ | +0.037 / 2.11→2.32 / −5.6 | +0.050 / 2.01→2.27 / −8.6→−3.6 | 74% / 42% |
  | NQ  | +0.071 / 1.83→2.17 / **−10.5→−6.3** | +0.194 / 1.66→2.56 / **−21.2→−5.8** | 53% / 38% |
  | SPY | +0.007 / 1.88→1.89 / −7.4 | +0.110 / 1.86→2.30 / −7.8→−6.0 | 84% / 54% |
  Standout = **NQ drawdown roughly halves** (its worst metric); risk-adjusted (Calmar) ~doubles. Milder
  k=3.0 keeps most trades and still cuts NQ DD but is ~flat on QQQ/SPY.
- **COST = frequency.** k=2.0 culls ~25-60% of trades (NQ 5m 60→23/yr). It trades trade-COUNT for much
  better per-trade quality + lower DD. Whether that's worth it is a preference (quality vs frequency).
- Minor: the ratio's ATR denominator uses the entry-bar ATR (consistent with how the engine already sizes
  the stop); a Pine port would use the confirmed prior ATR — immaterial (ATR is slow). VERDICT: **CONFIRMED
  real edge, clears the gate; promotion to production is a user decision (changes the tested system +
  frequency, triggers the all-scripts propagation).**

## Finding 17 — up/down/range STRUCTURE: prod is the robust all-weather point; loosening is strictly bad, tightening is a TF-dependent lead — `research/orb_structure_opt.py`
Tested alternative definitions of the two structure gates the ORB uses — **up/down** (the EMA trend filter
inside `_orb_signals`) and **range** (the `local_regime` ADX block) — holding everything else at prod (OR
0930-1000, cutoff 15:00, per-TF buffer, 4R/scale, EOD-flat, macro ON). Efficient: harness state computed
ONCE/sym/TF, then only the `trend_up/down` and `local_regime` columns are swapped per variant and the cheap
trade loop re-runs. Adoption gate = beat prod on ALL FOUR metrics AND clear (both>0, CI>0) on BOTH NQ and QQQ,
BOTH TFs. Cells show Δexp R vs prod; ✓ = beats prod on all four.

**TREND (up/down) filter** — range held at prod ADX20:
| variant | NQ 5m | NQ 15m | QQQ 5m | QQQ 15m |
|---|---|---|---|---|
| none (no trend gate)      | −0.131 | −0.176 | −0.119 | −0.163 |
| close>EMA50 (drop stack)  | −0.104 | −0.108 | −0.086 | −0.107 |
| EMA 8/21 (faster)         | −0.086 | −0.095 | −0.077 | −0.082 |
| **EMA 21/50 (PROD)**      | +0.255 | +0.274 | +0.358 | +0.342 |
| EMA 50/200 (slower)       | +0.086 ✓ | −0.059 | +0.085 ✓ | −0.030 |
| HH/HL st_state            | +0.229 ✓ | +0.012 ✓ | +0.300 ✓ | −0.014 |

**RANGE filter** — trend held at prod 21/50:
| variant | NQ 5m | NQ 15m | QQQ 5m | QQQ 15m |
|---|---|---|---|---|
| no range block            | −0.079 | −0.060 | −0.093 | −0.033 |
| ADX≥15                    | −0.055 | −0.045 | −0.070 | −0.035 |
| **ADX≥20 (PROD)**         | +0.255 | +0.274 | +0.358 | +0.342 |
| ADX≥25                    | −0.002 | +0.035 ✓ | +0.045 ✓ | +0.006 (PF↓) |
| ADX≥30                    | −0.036 | +0.052 ✓ | +0.044 ✓ | −0.014 |
| st_state-3 (struct range) | −0.099 | −0.033 | −0.135 | −0.058 |

- **Loosening either gate is strictly worse — all 4 cells, every metric.** `none`/`close>EMA50`/`8/21`
  (looser trend) and `no-block`/`ADX15` (looser range) all lose. The prod up/down/range filter is NOT too
  tight; trend+regime+buffer already select (rhymes with F1/F11). **Don't loosen anything.**
- **Tightening helps but is TF-dependent → a lead, not a clean adopt.** Slower trend (50/200) and HH/HL win
  on 5m but lose on 15m; stricter range (ADX25/30) wins on NQ-15m + QQQ-5m but not QQQ-15m. No variant
  clears all four on both symbols × both TFs. Consistent shape: tighter = fewer trades, higher per-trade
  quality, lower DD — the same frequency↔quality tradeoff as F16.
- **HH/HL st_state is the standout AND the trap.** It is CAUSAL (5-bar confirmed pivots, no lookahead) and
  applied at signal time, so it's a genuine signal-level filter, not a post-hoc screen — and it's spectacular
  on 5m (QQQ 5m +0.658R / PF 3.76 / win 75% / DD −4.1; NQ 5m +0.484 / PF 2.58 / DD −10.7). BUT PF 3.76 sits in
  the documented "4.0 = curve-fit" zone, it culls ~15-20% of trades, and it FAILS on QQQ 15m. → **#1 structure
  lead; candidate for a dedicated walk-forward (like F15/F16) before any adoption; NOT adopted (TF-inconsistent
  + PF warning).**
- **st_state-3 (structure) range block = DEAD** — worse than the ADX range filter on every cell. ADX is the
  better range definition.

VERDICT: **production 21/50 trend + ADX20 range is the robust all-weather point — confirmed, no change.** The
only forward lead is a TF-adaptive *tighter* structure gate (HH/HL on the fast TF / higher ADX on the slow TF),
which must clear an honest walk-forward first and would trigger the all-scripts propagation.

## Finding 18 — FADING the false ORB breakout is DEAD (it's the wrong side of the momentum edge) — `research/orb_false_breakout.py`
Engine gained an off-by-default `execm="fade"` (LONG = swept below the OR low by k·ATR then a bar CLOSES
back above it; SHORT = swept above the OR high then closes back below; entry = reclaim-bar close, OR-anchored
stop with the same clamps, 1R/4R scale_be, EOD-flat). Swept k ∈ {0.0, 0.1, 0.25} × trend {aligned, off} on
NQ+QQQ × 5m+15m, head-to-head vs the breakout-stop baseline. Δ = fade vs breakout.

- **0 of 24 fade configs clear the gate** (both>0 & lower-CI>0). Fade PF 0.66-1.11 vs the breakout's
  1.66-2.11; expectancy −0.22R..+0.05R vs +0.26..+0.36R. The fade systematically loses because it takes the
  OPPOSITE side of ORB's validated continuation edge — most breakouts continue, so the fade gets run over.
- **trend-OFF fade is catastrophic** (NQ 5m maxDD **−201R**): fading with no trend context just bleeds.
  **trend-aligned** (buy the failed breakdown in an uptrend / sell the failed breakout in a downtrend) is
  ~breakeven-to-slightly-negative — much better, still fails.
- **deeper sweep helps monotonically** (k=0.25 least-bad everywhere). Single best corner = QQQ 15m, k=0.25,
  trend-aligned: +0.048R / PF 1.11 — but lower-CI −0.073 → still FAILS. Equities/slow-TF/deep-sweep is the
  only faintly-alive corner; not adoptable.
- The chart instance that motivated this was a genuine false-breakout reversal, but a SURVIVOR example.
  **VERDICT: DEAD — keep trading the breakout, do not fade it.** `execm="fade"` stays an off-by-default
  engine option for future research only.

## Finding 19 — the false breakout is no ENTRY, but "clean vs messy day" is a powerful breakout QUALITY filter — `research/orb_fb_variations.py`
Four false-breakout variations on NQ+QQQ × 5m+15m vs the breakout baseline (engine gained off-by-default
execm `sweepgo`/`rebreak`; `fade` from F18). Gate = both sides >0 AND lower-90%-CI >0.
1. **FADE + reversion exit = still DEAD.** Re-ran the fade with a reversion exit (tp2_full 1.0R/1.5R, not
   the 4R runner) to check F18 wasn't an exit artifact. Fails every cell (exp −0.15..+0.02, CI<0). The fade
   ENTRY has no edge — the exit was not the problem. **F18 confirmed.**
2. **SWEEP-THEN-GO (stop-run → opposite-edge breakout) is DOMINATED by the plain breakout.** Passes 3/4
   standalone (NQ 15m fails, long −0.02) but exp +0.15..+0.25 / PF 1.40..1.78 is WORSE than the breakout's
   +0.26..+0.36 / PF 1.66..2.11 on every cell, with far fewer trades. Requiring a prior sweep selects WORSE
   breakouts — opposite of the liquidity-grab thesis (and consistent with #3).
3. **CLEAN vs MESSY day = the win (strongest lead since F16).** Split breakout trades by whether a false
   break (sweep+reclaim of EITHER OR edge) happened earlier that day. CLEAN-day breakouts crush messy-day
   ones on ALL FOUR cells:
   | cell | CLEAN exp / PF / win / DD | MESSY exp / PF / win / DD |
   |---|---|---|
   | NQ 5m  | +0.472 / 2.62 / 72% / −5.7 | +0.092 / 1.20 / 56% / −29.4 |
   | NQ 15m | +0.430 / 2.57 / 72% / −7.6 | +0.142 / 1.37 / 58% / −16.9 |
   | QQQ 5m | +0.621 / 3.49 / 76% / −3.1 | +0.152 / 1.34 / 55% / −13.2 |
   | QQQ 15m| +0.473 / 2.80 / 73% / −3.8 | +0.216 / 1.61 / 60% / −5.2 |
   Clean ~doubles expectancy, lifts PF to 2.5-3.5, win to 72-76%, cuts DD 3-5×, and beats the all-days
   baseline. Both sides +, lower-CI>0 every cell. Mechanism: an earlier false break = a whippy/indecisive
   day where the breakout is far likelier to fail — this is WHY sweep-then-go (#2) loses (it trades the messy
   subset). ⚠️⚠️ **UPDATE — strict-causal retest KILLED this (`research/orb_cleanday.py`, NQ+QQQ+SPY × 5m+15m):
   it was a SAME-BAR LOOKAHEAD ARTIFACT.** Reimplemented as a real signal-time skip using only the PRIOR-bar
   false-break flag, the 2× gap VANISHES and inverts: CLEAN beats production on just 3/6 cells by trivial
   margins (+0.001..+0.031R), LOSES on all three 5m cells (−0.000..−0.056R), and the MESSY complement is often
   BETTER (SPY 5m messy +0.437 vs clean +0.272; NQ 5m +0.312 vs +0.231). The post-hoc gap came from a breakout
   that reversed intrabar tagging its OWN bar "messy" via that bar's close, so "clean" excluded the losers by
   construction — the exact F13 body-filter trap. **DEAD — not a lever.** (Faint 5m hint that a prior false
   break is mildly POSITIVE — reversal/expansion day — but not both-TF consistent → no lever either.)
4. **RE-BREAK (second break only) = valid but NOT better.** Passes all 4 cells but ≈ baseline (NQ 5m worse
   DD −34.7; QQQ 15m marginally better PF 2.40 vs 2.11). No improvement, no adoption.

VERDICT: the false breakout yields NOTHING usable — fade dead, sweep-then-go dominated, re-break neutral, and
the clean-day filter was a LOOKAHEAD MIRAGE that dies under the strict-causal retest. Best new lead reverts to
the HH/HL structure gate (F17). Lesson reinforced: a post-hoc day/trade screen MUST be reimplemented as a
prior-bar signal-time skip before it can be believed (F13, now F19).

## Finding 20 — HH/HL structure gate GRADUATES via walk-forward: a real 5m-specific edge (neutral on 15m) — `research/orb_hhhl_walkforward.py`
The F17 #1 lead, put through the F15 protocol (per-year positivity + 70/30 OOS split) on NQ+QQQ+SPY × 5m+15m.
Replace the EMA 21/50 up/down trend gate with the harness swing-structure state (long = st_state 1 = HH+HL,
short = 2 = LL+LH); range gate held at prod ADX20. CAUSAL (5-bar confirmed pivots) — no same-bar lookahead,
unlike the F19 clean-day mirage.
- **5m = a large, walk-forward-validated, cross-asset WIN.** exp NQ +0.255→+0.484, QQQ +0.358→+0.658, SPY
  +0.328→+0.548; PF to 2.6-3.8; DD roughly HALVED (NQ −21→−11, QQQ −9→−4, SPY −8→−4). Positive EVERY year
  (NQ 15/17 — only 2013-14 deep-past chop; QQQ 9/9; SPY 9/9) and the 70/30 OOS HOLDS on all three (e.g. QQQ
  in +0.737 → out +0.475, still > production's full +0.358). The QQQ-5m PF 3.76 is high but EARNED — 9/9 years
  + OOS holds = quality concentration, not curve-fit.
- **15m = NEUTRAL.** NQ +0.286 vs +0.274 (tiny+), QQQ +0.328 vs +0.342, SPY +0.264 vs +0.298 (tiny−). All
  still robust (every year +, OOS holds) but EMA trend is as good or better → 15m keeps EMA.
- **VERDICT: GRADUATED as a TF-adaptive trend gate** — st_state HH/HL on ≤5m, EMA 21/50 on ≥15m (mirrors the
  per-TF mapping of F6). First new entry-logic edge to clear the walk-forward since the original system.
  ⚠️ ADOPTION COST: (1) signal-level entry change → all-scripts-consistency propagation (5 Pine + engine,
  re-validate); (2) requires PORTING the pivot/st_state structure machine into the ORB Pine (today it lives
  only in the harness/V44, not the ORB indicators) + reconcile vs the Python harness; (3) ~17% fewer trades on
  5m. Real engineering + a user go-ahead before adoption.

## Finding 21 — HH/HL gate + VWAP cap are ADDITIVE on 5m (stack them — but PF enters the curve-fit zone) — `research/orb_hhhl_vwapcap.py`
The two graduated 5m edges (F20 structure gate + F16 VWAP-cap k=2.0), stacked, on NQ+QQQ+SPY 5m. BOTH beats
the better single filter on ALL THREE:
| | PROD exp/PF/DD | HH/HL | cap | BOTH exp/PF/win/DD/CI (kept) |
|---|---|---|---|---|
| NQ  | +0.255/1.66/−21.2 | +0.484/2.58 | +0.449/2.56 | **+0.736/4.53/79%/−3.7/+0.64** (42%) |
| QQQ | +0.358/2.01/−8.6  | +0.658/3.76 | +0.408/2.27 | **+0.801/5.32/81%/−3.1/+0.70** (53%) |
| SPY | +0.328/1.86/−7.8  | +0.548/2.78 | +0.438/2.30 | **+0.680/3.61/74%/−5.1/+0.58** (63%) |
They measure DIFFERENT quality axes — in-structure (HH/HL) AND not-overextended-from-VWAP (cap) — so stacking
roughly DOUBLES production expectancy and cuts DD 2-6× (NQ −21→−4), both sides +, CI strongly +.
⚠️ PF 4.53 (NQ) / 5.32 (QQQ) is in the "4.0+ = curve-fit" zone — the natural result of intersecting two
validated filters (thin samples n=303-406), NOT a fitted spike (each half already cleared its own walk-forward,
F16/F20). So the COMBINED config must clear its OWN per-year + OOS walk-forward before adoption. Keeps 42-63%
of trades. VERDICT: additive AND **WALK-FORWARD CONFIRMED** (`research/orb_stack_walkforward.py`): the stack is
positive EVERY adequately-sampled year (NQ 15/15, QQQ 9/9, SPY 9/9 — no negative years) and the 70/30 OOS HOLDS
on all three (NQ in +0.708→out +0.801, QQQ →+0.636 still > prod's full +0.358, SPY →+0.660 ≈ in), both sides +,
CI +0.58..+0.71 → the PF 3.6-5.3 is EARNED quality concentration, not curve-fit. Fully validated; the ONLY
barrier to adoption is engineering — the Pine st_state PORT + all-scripts propagation F20 requires. Frequency
cost: keeps 42-63% (~20-25 trades/yr on NQ).

## Finding 22 — the validated STACK extends to the ASIA session on NQ/MNQ 5m (Tokyo-open OR) — `research/orb_asia.py` + `orb_asia_walkforward.py`
Re-opens the old "Asia is not the edge" result (orb_sessions.py) now that the F20+F21 stack exists. Tested 5 Asia
opening-range windows (trade-day coords, 18:00 ET = 0; the engine's EOD-flat was made trade-day-aware so a session
crossing midnight isn't chopped) × {production EMA breakout, the STRUCTURE STACK, a fade/mean-reversion} on NQ 5m
+ 15m, with US RTH as the benchmark.
- **Production breakout DEAD in Asia** (confirms the prior finding): nearly every window fails the gate (CI < 0).
- **Fade/mean-reversion CATASTROPHIC** (PF 0.26-0.55, −0.3..−0.7R every window) — Asia breakouts follow through
  enough that fading them is the wrong side. Kills the "Asia is range-y, so fade it" hypothesis.
- **STRUCTURE STACK PASSES on 5m, every window** — exp +0.42..+0.52R, PF 2.4-2.8, both sides +, positive 14-17/17
  years. Strongest = **19:00-20:00 ET (Tokyo-open hour): +0.50R, PF 2.78, 17/17 years +**. (15m weaker — only the
  18:00-18:30 and 20:00-21:00 windows pass.)
- **WALK-FORWARD (orb_asia_walkforward.py)**: NQ 5m 19:00-20:00 — 70/30 OOS HOLDS (in +0.455 → out +0.603), survives
  2× slippage (+0.33R/PF 1.9) and 3× (+0.15R/PF 1.3). 19:00-19:30 + 18:00-18:30 also pass (one neg year: 2013).
- **Cross-instrument (ES — the only Asia futures cross-check; equities don't trade Asia)**: corroborates the
  DIRECTION (19:00-20:00 best, both sides +, OOS holds) but is WEAKER and **dies under 2× slippage** (early years
  2010-14 negative). The edge is NQ-strong, ES-marginal.
⚠️ Two caveats keep it a CANDIDATE: (1) **slippage** — Asia liquidity is thinner than RTH; the NQ edge absorbs 2×
but thins at 3×, and ES already fails 2×, so real fill quality is the live risk → forward-paper-test fills first.
(2) it carries the SAME unreconciled **st_state** dependency as F20/F21. VERDICT: **validated CANDIDATE on NQ/MNQ
5m, Tokyo-open window** → new Pine file `validatedResearch/HIGHSTRIKE_ORB_ASIA.pine` (trade-day 18:00-ET reset on a
CME futures chart; futures only). Adoption gate = st_state reconcile + forward-test, same as the RTH stack.

## Finding 23 — the structure stack is ROBUST to its pivot params (lb5/tol0.10 is a plateau, not a spike) — `research/orb_struct_robust.py`
Before adopting the F20/F21 stack, swept its only free knobs — pivot lookback `struct_lb` + tolerance — on NQ 5m (+QQQ), stack config
(st_state gate + VWAP-cap k2, RTH). EVERY point clears the full gate (both sides+, CI>0, positive every year):
- **lb sweep (tol 0.10):** lb3 +0.574/PF3.28, lb4 +0.700, **lb5 +0.736 (adopted)**, lb6 +0.709, lb8 +0.686, lb10 +0.697 — all PASS, 12-16/yrs+.
- **tol sweep (lb5):** 0.05 +0.771, 0.10 +0.736, 0.15 +0.744, 0.20 +0.718 — all PASS.
- **QQQ** holds the plateau (lb5 +0.801, lb8 +0.716, 9/9).
lb5/tol0.10 sits NEAR THE TOP of a broad plateau (lb4-6 ≈ identical) — not a fitted peak → the edge does not depend on a lucky param.
**ADAPTIVE lookback is STRICTLY WORSE** (+0.459/PF2.39, n 406→228) → confirms the adopted fixed-lb / adaptive-OFF choice. De-risks adoption.

## Finding 24 — the stack is INDEX-GENERAL (ES confirms) and RTH⊕Asia are uncorrelated (diversify) — `research/orb_xinstrument.py`
(a) **ES 5m RTH stack:** +0.536R, PF 2.92, CI +0.45, both sides+, 15/16 yrs+ → the 5m stack holds on the 4th index future too
(NQ+QQQ+SPY+ES all validated). Not an NQ artifact.
(b) **NQ RTH vs Asia** stack daily-PnL correlation = **−0.09** (≈0); only 8% of active days overlap; combined maxDD **−6R** vs −4R(RTH)+−7R(Asia)
summed −11R → trading BOTH sessions diversifies (smoother curve), consistent with F26's higher both-sessions pass-rate.

## Finding 25 — the stop is TOO WIDE for the 5m stack (structure / tighter stop = strong LEAD); vol-scaled reward is dead — `research/orb_exit_levers.py`
On the NQ 5m stack: (a) **STOP placement** — production OR-edge+2.5ATR cap risks 48pts/trade; a STRUCTURE-anchored stop (last HH/HL swing,
new off-by-default engine `stop_mode="struct"` + harness `sph`/`spl`) risks 29pts and lifts exp **+0.736→+1.003R** (PF 4.53→5.55, CI +0.65→+0.90,
both sides+); a plain 1.5-ATR cap captures most (+0.934/risk29). With FIXED-R (prop) sizing this is a clear win — same $ risked, more R,
smaller DD. In raw points the wider stop banks slightly more absolute (35 vs 29 pt-equiv) → the gain is risk-normalised / variance reduction.
**WALK-FORWARD (F25b, `research/orb_stop_walkforward.py`): GRADUATED.** The structure-anchored (and 1.5-ATR) stop clears the full gate on
NQ+QQQ+SPY — both sides+, CI+, positive EVERY year (15/15 · 9/9 · 9/9), 70/30 OOS holds (NQ +1.01→+0.99, QQQ +1.22→+0.90, SPY +1.04→+0.95),
survives 2× slip — exp +0.74→+1.00 / +1.12 / +1.01R, risk roughly halved. **ES is the marginal exception** (13-14/16 yrs, thins to +0.23 at
2× slip — same ES weakness as F22/F24). VERDICT: adopt the tighter (structure / 1.5-ATR) stop WITH the stack (ES caveat = size down / forward-
test). PF 5-6 is earned — each half already validated.
(b) **VOL-scaled reward** — TP2 3→6R barely moves exp on high-vol days (+0.711→+0.742, flat) and the stack almost never fires on low-vol
days (<30 trades) → 4R stays right; reward is insensitive to vol regime within the stack. DEAD.

## Finding 26 — the stack PASSES a funded-account eval with near-zero blow-up (best trading both sessions) — `research/orb_prop_eval.py`
Rolling-start Monte-Carlo of the chronological trade path vs funded rules in R (1R = your per-trade $ risk; fixed-R sizing): profit
target / trailing-DD / daily-loss. NQ 5m:
- **RTH:** 93-98% PASS, 0% blow-up across profiles (+9/−6/−4 .. +30/−12/−8 R); median 12-39 trades to pass.
- **Asia:** 89-100% PASS; **11% BLOW-UP only on the TIGHTEST** (−6 trail / −4 daily) profile → Asia's bigger adverse swings want a slightly
looser daily/trailing limit (rhymes with the F22 slippage caution).
- **BOTH sessions:** 98-99% PASS, ≤2% blow-up, fastest (more, diversified trades). Read: the stack survives a typical eval easily; trade
both sessions and don't set the daily stop too tight for Asia.
**F26b (2026-06-11) — re-run with LONDON (F29) included, all sessions + combos:**
- **London standalone:** 92-100% PASS, **0% blow-up on every profile** — the best single-session eval profile (tightest +9/−6/−4: London
  100% vs RTH 98% vs Asia 89%); median 15-50 trades to pass. Confirms F29's "more robust than Asia" from the eval-survival angle too.
- **Pairs:** RTH+London is the cleanest pair (100/99/96% PASS, 0% blow-up); RTH+Asia 98/99/98% (2% blow-up tightest); Asia+London
  97/99/98% (3% blow-up tightest — Asia is always the blow-up contributor on tight rails).
- **ALL THREE on one account:** **99/99/98% PASS, ≤1% blow-up, median 14-46 trades to pass** — diversification dilutes Asia's
  tight-profile risk (11% → 1%) and is the fastest/safest overall. Read: trade all three sessions on one eval account; if the firm's
  daily/trailing limits are tight (≤−4R daily), Asia is the session to skip or size down.
**F26d (2026-06-11) — GC added to the user's eval ($3,000 tgt / $1,500 trail / $700-800 daily).** GC US-morning stream
(F30) vs NQ all-three: daily-PnL corr **+0.12** (real instrument diversification) BUT GC and NQ-RTH both fire at the 09:30
open → same-DAY clustering against one daily limit. Net effect: median pass ~15% faster (71→61d @$200, 55→45d @$250,
41→34d @$300) at slightly higher blow-up on tight rails ($700 daily @$250: 4→9%). Best combos: **$200/trade + GC + $800
daily = 98% pass / 1% blow-up / median 61d**; **$250 + GC + $800 = 95% / 5% / 45d** (the speed pick). At $700 daily,
adding GC is only worth it at $200. GC is still pending its forward paper-test — don't add it to a live eval before that.
**F26c (2026-06-11) — the USER'S actual eval rules: target $3,000 / trailing max loss $1,500 / daily loss $700.** Swept the
per-trade risk (1R $) that maps those $ rules into R. Result = a clean risk-sizing frontier (ALL-THREE stream):
- **1R = $150/trade → +20R / −10R / −4.7R: PASS 99%, BLOW-UP 0%, median 32 trades (~4 months at ~7 trades/mo). THE SWEET SPOT.**
- 1R = $100: 98% pass, 0% blow-up but slow (median 46 trades); 1R = $200: 98% but 2% blow-up creeps in (Asia); **1R = $250: Asia
  standalone BLOWS UP 18%** (daily $700 = only −2.8R) and all-three drops to 96%/4%.
- RTH+London is 0% blow-up at EVERY size tested (96-99% pass) — the no-Asia fallback if sizing up.
Verdict: on this ruleset risk **$150/trade** (≈2-3 MNQ with the ~29-pt structure stop), trade all three sessions, don't size past
$200/trade while Asia is in the mix. NB: simulated with the F26 config (scale_be exit, OR-edge stop) — the adopted structure-stop
+ trail (~+1.0R/trade vs +0.74) should only improve pass speed; not re-simulated.

## Finding 27 — the stack wants a MOMENTUM-CAPTURE exit (trail / run-more beats scale-50%@1R/BE/4R) — `research/orb_exit_mgmt.py`
The production exit (bank 50% at TP1=1R → BE → runner to 4R) under-monetises the stack's trades, which trend hard (they're the
filtered, in-structure, near-VWAP breakouts). On NQ 5m stack (QQQ confirms), every "let it run" lever beats prod, both sides+ & CI+:
- **MODE:** TRAIL (ATR chandelier) > scale_be. trail 2ATR +0.851/PF6.02/DD−3, trail **3ATR +0.980**/PF5.73 (vs prod +0.736/4.53/−4);
  QQQ trail 2ATR +0.931/PF6.96 (vs +0.801). tp2_full 3R also strong (+0.925). [NB: REVERSES F14's "trail is worse" — that was the
  BARE ORB; on the filtered stack, trend-continuation rewards trailing. Regime-specific, not a contradiction.]
- **scale fraction:** bank LESS at TP1 — take 33% +0.815 > 50% +0.736 > 67% +0.656 (make the runner bigger).
- **TP1 later:** 1.5R +0.821 > 1.0R +0.736 > 0.5R +0.593 (0.5R = best win 87% / DD −2 but lowest exp — the scalp end of the frontier).
- **TP2 further:** 4→6R monotonic +0.736→+0.748 (flat; the runner reward is NOT a tail-trap here, unlike F7's full-position case).
Common thread with F25's stop: CUT LOSSES SHORT (tighter/structure stop) + LET WINNERS RUN (trail / run-more) — the stack's trade
quality supports both. **WALK-FORWARD (F27b, `research/orb_exit_walkforward.py`): GRADUATED.** trail 2ATR, trail 3ATR, and run-more
(33%/1.5R/6R) ALL clear the full gate on NQ+QQQ+SPY+ES — both sides+, CI+, positive every year, 70/30 OOS holds, survive 2× slip.
trail 3ATR strongest (NQ +0.980, QQQ +1.057, SPY +0.876, ES +0.740); trail 2ATR most slip-robust (gives back least). VERDICT: adopt a
momentum exit with the stack — trail 2ATR for futures (slip-robust), trail 3ATR for equities (max exp), or run-more to keep hard TP/BE
targets. New off-by-default engine `scale_frac`. (ES carries its usual lone 2017 soft year across ALL exits incl. prod — not exit-specific.)

## Finding 28 — the st_state RECONCILE, resolved (mostly) OFFLINE: the edge is INVARIANT to the pivot tie-rule — `qa/pivot_check.py` + `research/orb_pivot_impact.py`
The Pine st_state port's only un-verified piece was the pivot TIE-rule: the harness pivots() used strict > on both sides; TradingView's
ta.pivothigh allows a tie on the LEFT (strict right). `qa/pivot_check.py`: the two rules differ on **~16% of pivots** on NQ 5m (22k bars).
BUT the st_state machine (tolerance + swing-sequence) absorbs almost all of it — re-running the 5m stack walk-forward with the harness set
to the Pine rule (`pivot_tie='tv'`, new off-by-default H.P field) is WITHIN NOISE of strict and still PASSES on NQ+QQQ+SPY (NQ +0.736→+0.748,
QQQ +0.801→+0.805, SPY +0.680→+0.684; all 15/15·9/9·9/9, OOS holds). So the edge is ROBUST to the pivot convention → **live==backtest is
secured for what matters**, even before a formal bar-for-bar TradingView diff. The state-machine logic was already verified line-by-line;
the only residual is confirming ta.pivothigh's exact tie-rule (a free 2-min Data-Window glance — now low-stakes, since the edge is
rule-invariant). Engine: `pivots(tie=…)` + `H.P.pivot_tie` + `qa/pivot_check.py`. A formal `qa/hs_reconcile.py` diff on a saved export is
the optional 100% confirmation.

## Finding 29 — the stack ALSO works in the LONDON session (NQ/MNQ 5m, London-open OR) — `research/orb_london.py` + `orb_london_walkforward.py`
Mirror of F22 (Asia). London opens ~03:00 ET. On NQ 5m the structure stack on the London-open OR clears the full gate on every
window; the production breakout is DEAD and a fade CATASTROPHIC (same off-hours pattern as Asia).
- Best = **03:00-03:30 ET (London open): +0.574R, PF 3.45, win 75%, 17/17 years +**. Walk-forward: OOS holds (+0.56→+0.61), and it
  survives 2× (+0.461) AND **3× slippage (+0.348)** — MORE slip-robust than Asia (European-open liquidity is deeper than Tokyo's).
  03:00-04:00 (+0.591) and 02:00-02:30 (+0.528) also pass + survive 3× slip.
- ES corroborates the direction (both sides+, OOS holds) but is the marginal instrument again — 11-12/17 yrs, dies under 2× slip.
  Same NQ-strong / ES-weak split as F22/F24. 15m is weak (same as Asia) → 5m is the TF.
VERDICT: validated NQ/MNQ candidate → added as the LONDON phase of the STACK auto-session (**Asia → London → RTH**, by the clock).
The three sessions trade on different clocks (near-independent) → the auto-session diversifies across all three.

## Lever scorecard (cumulative) — adopt only if it clears the gate on QQQ AND NQ, then propagate to ALL scripts
| lever | verdict |
|---|---|
| MTF confirmation (F1) · volume (F11) · VWAP-side (F12) · OR-width (F13) · time-stop (F14) · close+body (F13) | ❌ dead/noise |
| retest entry (F8) | ✅ 15m-only edge; NOT wired (user trades 5m where stop wins) |
| stop-entry · all-day · 4R/scale · per-TF buffer · EOD-flat | ✅ ADOPTED (production) |
| **against-gap (equity)** (F13) | 🟡 real tilt, thin + PF-warning + equity-only → confidence signal, not a filter |
| **VWAP-extension cap** (F16) | ✅ PASSED honest signal-level test (k≈2.0, all 3 assets × both TFs, NQ DD ~halves) — promotion = user decision; costs ~25-60% of trades |
| **"Neural Kernel Bands" filter** (F36) | ❌ REDUNDANT with VWAP-cap — kernel state/slope/side/cap all improve the stack (NQ+QQQ+SPY+ES, every yr+, OOS holds, 2× slip ok) BUT tightening the existing vwap-cap k to matched trade-count matches/beats it → no orthogonal axis; the all-variants-improve pattern = the F1/F11 cull trap. Don't adopt; fine as a discretionary visual |
| **"Neural Kernel Bands" STANDALONE Buy/Sell signal** (F49) | ❌ DEAD — the band-cross flip labels have ~ZERO directional accuracy (fwd hit-rate 44–50% i.e. ≤ coin flip, mean fwd move 0.00–0.02 ATR) on NQ+QQQ 5m & 15m; flip-to-flip always-in is net-NEGATIVE after costs (NQ 5m −0.575R PF0.66, NQ 15m −0.235R, QQQ 5m −0.047R; only QQQ 15m +0.07R but raw −47%); win 31–33% (trend-chase shredded in chop). The chart "looks on point" is an ILLUSION: the Buy label is drawn at the bar LOW but the fill is the close, already ~1.2–1.6 ATR past the band → hindsight perfect, unfillable. Not a replacement for the ORB entries. `orb_kernel_signal.py` |
| **RSI + Accel/Decel filter** (F37) | ❌ REDUNDANT with VWAP-cap — all 6 RSI/AC variants pass the gate (NQ+QQQ+SPY+ES, every yr+, OOS, 2× slip); ac_agree (Bill Williams) even sat slightly ABOVE the frontier at the default point, but the ADDITIVITY sweep (lift across the vwap-cap k grid) oscillates around 0 (negative mid-range) → no frontier lift. Don't embed; cheap-to-port doesn't rescue zero orthogonal edge |
| Statistical: DoW / seasonality / day-context (F44) | ❌ DEAD — DoW best/worst day FLIPS across NQ/QQQ/SPY (curve-fit, confirms F15); against-prior-day + prior-range are sign-consistent but thin tilts (≈ F13 against-gap) that cull ~60% for ~flat exp = below the frontier. No tradable edge. `orb_stack_stat.py` |
| Liquidity confluence (F43) | ❌ DEAD — sweep-confluence too rare (<30 trades); prior-day-level take-out (pdsweep) culls 60-70% for flat-to-worse exp (NQ +0.75/QQQ +0.80/SPY +0.54) = below the frontier. Level take-out ≈ extension (vwap-cap handles it). `orb_stack_liquidity.py` |
| Auction Market Theory value-area (F42) | ❌ DEAD — prior-day value-area / POC confluence culls 35-50% of trades for flat-to-LOWER exp (NQ +0.74→+0.69, QQQ +0.80→+0.73, SPY +0.68→+0.62) = below the vwap-cap frontier; "outside value" conflicts with the adopted VWAP-cap (both about extension). Built a real volume profile (`orb_stack_amt.py`). Other AMT angles redundant (IB≈ORB, VA-migration≈trend) or exit-side (POC magnet) |
| Order Flow: CVD proxy (F48) | 🟡 WEAK lead — CVD (close-location-signed volume, session-cumulative) lifts the frontier CONSISTENTLY +0.02..+0.07 at every k (NQ+QQQ) AND adds ~+0.07 on top of F45 — NOT redundant (unlike kernel/RSI/AC), but small (~+0.05R, within noise) + a crude proxy. Significance: order flow is the one family with life via proxy → real tick/delta data is the most promising NEW-data direction. `orb_stack_orderflow.py` |
| **SMC order-block param-robustness** (F47) | ✅ DE-RISKED — +ob is a broad PLATEAU over body{0.2-0.5}/keep{3-8}/dist{2-5}/vol{0.5-1.0}: NQ exp +0.92..+1.06, QQQ +1.09..+1.17, all PASS, every yr+, V44 default mid-plateau not a spike. F41/F45 not param-fitted. `orb_ob_robust.py` (harness OB params now off-by-default P fields) |
| **SMC order-block confluence** (F41) | ✅ GRADUATED — strongest orthogonal filter found. Require the breakout to fire at a bull OB (long)/bear OB (short): NQ +0.74→+0.97, QQQ +0.80→+1.11, SPY +0.68→+0.91, every yr+, OOS, 2× slip, keeps ~94% of trades. Lifts the vwap-cap frontier +0.11..+0.20 (NQ)/+0.23..+0.28 (QQQ) at every k AND adds on top of F38 time gate (NQ +0.98→+1.14, QQQ +1.14→+1.37) → orthogonal to both. +zone (OB+FVG) marginal (FVG dilutes). Uses V44 OB params (untuned=good); de-risk = OB-param robustness sweep before propagation |
| squeeze (compress) / ADX strength (F40) | ❌ not adopted — ADX is REDUNDANT with vwap-cap (frontier-lift delta NEGATIVE at the operating point on NQ+QQQ; trend-family, rhymes w/ F17); squeeze additive on NQ only, NEGATIVE on QQQ at operating point + adds ~nothing on top of the F38 time gate (it's a midday shadow) + culls to ~5 trades/yr. The other F38 feature-study "leads" were shadows of time-of-day or the cap |
| **TIME-OF-DAY: skip the opening hour** (F38→F39) | ✅ GRADUATED + UNIVERSAL — the first ORTHOGONAL edge that LIFTS the vwap-cap frontier (delta +ve at every k) not rides it. Skip stack entries for the first ~60min after EACH session's OR close (RTH ≥11:00 / Asia ≥21:00 / London ≥04:30 ET). RTH (F38): exp +33-50% (NQ +0.74→+0.98, QQQ +0.80→+1.14, SPY +0.68→+0.98), DD ~halved, win 86-91%. F39: transfers to Asia (NQ +0.50→+0.63) + London (NQ +0.57→+0.87) AND RESCUES ES off-hours (Asia ES 2× slip −0.17→+0.13; London ES FAIL→PASS) — fixes the F22/F29 ES-slippage caveat. Every yr+, OOS holds, 2× slip ok, additivity +ve all streams (stronger off-hours). Near-free (clock gate, no port). Adopt all 3 sessions; propagation + forward-test pending. Secondary leads compress(−0.29)/adx(+0.20) testing next |
| false-breakout fade (F18) | ❌ dead — 0/24 configs pass, loses to the breakout (wrong side of the momentum edge); trend-off catastrophic |
| false-breakout entries: fade reversion-exit · sweep-then-go · re-break (F19) | ❌ no entry edge — fade dead even w/ reversion exit; sweep-then-go dominated by the plain breakout; re-break ≈ baseline |
| clean-vs-messy-day breakout filter (F19) | ❌ LOOKAHEAD ARTIFACT — post-hoc 2× gap was same-bar close lookahead; strict-causal (`orb_cleanday.py`, NQ/QQQ/SPY×5m/15m) it vanishes/inverts (beats prod only 3/6 by <0.03R, loses on all 5m; messy often better). Dead (same trap as F13) |
| loosening up/down/range gates (F17) | ❌ strictly worse on all 4 cells — prod filter is not too tight |
| **HH/HL structure gate** (F17→F20) | ✅ GRADUATED on 5m — walk-forward holds on NQ+QQQ+SPY (every yr +, OOS holds, exp +60-90%, DD halved, PF earned not curve-fit); NEUTRAL on 15m. TF-adaptive adopt (st_state ≤5m, EMA ≥15m); needs Pine st_state PORT + all-scripts propagation + user go-ahead |
| **HH/HL + VWAP-cap stacked, 5m** (F21) | ✅ ADDITIVE + WALK-FORWARD CONFIRMED (NQ+QQQ+SPY) — exp ~2× prod (+0.68..+0.80), DD cut 2-6×, positive every yr (15/15·9/9·9/9), OOS holds, CI +0.58..+0.71; PF 3.6-5.3 is earned not curve-fit. FULLY VALIDATED — only barrier = Pine st_state port + propagation. Recommended 5m adoption |
| stricter trend (50/200) / range (ADX25-30) (F17) | 🟡 TF-dependent quality↑/DD↓; not robust across all 4 cells |
| **Asia-session stack, NQ/MNQ 5m** (F22) | ✅ validated CANDIDATE — STRUCTURE stack on the Tokyo-open OR (19:00-20:00 ET): +0.50R, PF 2.78, 17/17 yrs +, OOS holds, survives 2× slip. Prod breakout + fade both DEAD in Asia. ES corroborates direction but dies at 2× slip → slippage is the live risk. Futures-only. Pending forward-test |
| **London-session stack, NQ/MNQ 5m** (F29) | ✅ validated CANDIDATE — stack on the London-open OR (03:00-03:30 ET): +0.574R, PF 3.45, 17/17 yrs +, OOS holds, survives 2× AND 3× slip (more slip-robust than Asia — deeper EU-open liquidity). Prod breakout + fade dead. ES marginal. Futures-only. Now the London phase of the STACK auto-session (Asia→London→RTH) |
| **structure / tighter STOP, 5m stack** (F25→F25b) | ✅ GRADUATED via walk-forward — structure-anchored (last HH/HL swing) or 1.5-ATR stop lifts exp +0.74→+1.00R (PF 4.5→5.5), risk 48→29pt, both sides+, CI+, positive every year + OOS holds on NQ/QQQ/SPY (15/15·9/9·9/9), survives 2× slip; ES weaker (13-14/16 yrs, +0.23 at 2× slip). Adopt the tighter stop with the stack. Engine `stop_mode="struct"` + harness `sph/spl` |
| **momentum EXIT for the stack: TRAIL / run-more** (F27→F27b) | ✅ GRADUATED via walk-forward — trail 2-3ATR & run-more(33%/1.5R/6R) all clear the gate on NQ+QQQ+SPY+ES (both sides+, CI+, every yr+, OOS holds, survive 2× slip). trail 3ATR strongest (NQ +0.98, QQQ +1.06), trail 2ATR most slip-robust. Adopt with the tighter stop = cut-short/run-long. Reverses F14 (bare ORB). Engine `scale_frac` |
| vol-scaled reward (F25) | ❌ dead — TP2 insensitive to vol regime in the stack (3→6R flat); 4R stays right |
| structure-param robustness (F23) | ✅ stack is a PLATEAU not a spike — lb3-10 + tol0.05-0.20 all PASS on NQ+QQQ (every yr+); adaptive-lb strictly worse → fixed lb5/tol0.10 confirmed. De-risks adoption |
| index-generality + session diversification (F24) | ✅ ES RTH stack +0.54R/15-16yr (NQ+QQQ+SPY+ES all hold); RTH⊕Asia corr −0.09, combined DD < summed → trade both |
| **GOLD GC stack, 5m US-morning** (F30) | ✅ validated CANDIDATE — stack on the 09:30-10:00 OR: +0.438R, PF 2.68, 15/15 yrs, OOS holds, survives 2× slip (dies 3×); COMEX-open window passes too but corr +0.61 = same edge → take 09:30 only; ALL overnight windows + 15m + prod + fade DEAD on gold; macro gate still SPY/VIX (gold-native variant untested) |
| prop-eval survivability (F26→F26b all 3 sessions) | ✅ stack passes funded rules 93-100%, ~0% blow-up (RTH); Asia wants looser daily/trail limit (11% blow-up tightest); London BEST single session (92-100%, 0% blow-up all profiles); ALL THREE on one account = 98-99% pass, ≤1% blow-up, fastest — trade all three, skip/size-down Asia on tight rails |

Discipline: every screen here is post-hoc (filters taken trades) — a screen says "does this separate good
from bad", NOT the final number. Graduation = signal-level reimplementation + full re-validation (both
signals >0, lower CI >0) on QQQ AND NQ, THEN propagate to ALL Pine scripts + engine (the consistency rule).

## Finding 30 — GOLD (GC): the stack validates in US-MORNING liquidity only; one session, not three — `research/orb_gold.py` + `orb_gold_walkforward.py`
Fresh campaign on user-supplied Databento GC 1m (2010-06→2026-06; pipeline: 83 fronts, 82 rolls ≈5/yr
G/J/M/Q/Z cadence, QA clean, missing days = the known feed-wide 2014 gaps). Tested 6 gold-native session
opens × {prod, stack, fade} × {5m, 15m}:
- **DEAD:** prod EMA breakout negative in EVERY window (worst overnight); fade catastrophic everywhere
  (PF 0.06-0.32) — same off-hours pattern as NQ. ALL overnight windows dead even for the stack: Asia/Tokyo
  −0.013 (stack lifts prod's −0.46 to breakeven, still no edge), Shanghai −0.08, London open +0.080
  (PF 1.18, CI −0.03, 9/16 — closest miss), London AM fix −0.30. All of 15m dead. **Gold does NOT give
  three sessions — the NQ session map does not transfer.**
- **PASS (5m stack only): the US morning.** COMEX open 08:20-08:50 (+0.451R, PF 2.87, CI +0.36, 12/16 yrs,
  NEG 2013/14/17/18) and US equity open 09:30-10:00 (+0.438R, PF 2.68, CI +0.335, **15/15 yrs**, OOS
  +0.433→+0.450). Both survive 2× slip (+0.21/+0.17), both DIE at 3× — slippage tier = NQ-Asia.
- **The two windows are ONE edge:** daily-PnL corr +0.61 on shared days (they overlap 09:30-13:30).
  → adopt the **09:30-10:00 window only** (every-year-positive, OOS-stable); drop COMEX-open as a stream.
VERDICT: **validated candidate** — GC/MGC 5m, US equity-open OR, stack gates, trade to 15:00, flat EOD.
Adds an INSTRUMENT-diversified 4th stream to the NQ Asia→London→RTH rotation (not a 4th time slot).
⚠️ provisional bits: macro gate is SPY/VIX (equity-native) — a gold-macro (DXY/real-yield) variant is
untested; slippage-sensitive (paper-test GC fills, MGC spread is wider); same forward-test gate as the rest.

## F61 — research-folder entry-mistake re-audit + re-run: NO uncorrected mistake remains (2026-06-23)
User asked to "correct the same underlying entry mistake and run all the research again." Did a full sweep:
- **The ~60 `orb_*` scripts route through `B.backtest`** → they INHERIT the engine fixes (F56 gap-aware fill +
  the F59x `execm`/`strong_body`/`ft_confirm` params). No per-script edit needed; the corrected-entry re-run of
  the ORB family is F60 (NQ/QQQ/SPY PASS, ES marginal/fails slip, GC dead).
- **The 4 custom-sim `strat_*` scripts have their OWN fill loops (not the engine)** — re-read + verified all are
  already gap-aware / close-honest (no stale-level, no same-bar phantom): strat_daily (`e=max(level,open)`, exits
  i+1), strat_volbreak_test (`e=max(u,o[i])`, exit at close), strat_rangefade (enter at signal CLOSE, stop worse
  of {stop,next open}, exits i+1), strat_ml (next-day-return direction, no fill to game). RE-RAN all four → results
  are BYTE-IDENTICAL to F52-F55 (volbreak passes both-side on NQ/QQQ/SPY, short dead, ES/GC fail, ~30% path-amb;
  range-fade dead every config; Connors + ML pass ONLY QQQ/SPY post-2018; VIX-fade/Donchian dead). They don't
  depend on the engine entry, so nothing moved — confirming they never had the F56 mistake.
- **CONCLUSION: there is no uncorrected fill mistake left in the research folder.** The F56 bug was engine-central
  (fixed there, inherited by every orb_* test); the custom sims were built honest from the start (F57 audit, now
  re-confirmed by re-running). "Re-running under the corrected entry" only changes the ORB family, and that = F60.

## F64 — WHERE to take TP1 / TP2 (R-multiple sweep, NQ/QQQ/SPY/GC 5m) (2026-06-29)
`research/orb_tp2.py`. Full-to-cap vs scale(50%@TP1, runner→TP2) vs trail.

- **TP2 = 4R is the knee** (validated). QQQ cap 4R +0.264 / 5R +0.265 / 6R +0.266 = a PLATEAU, but OOS
  is BEST at 4R (4R OOS +0.294 vs 6R +0.222) and every-year-positive — beyond 4R adds ~nothing and
  costs robustness. SPY trends harder (6R +0.302 raw) but yr+ drops 8/9→7/9; 4R is the disciplined cap.
- **medMFE ≈ 1.0R** on every instrument — the MEDIAN trade only runs ~1R favorable. So 4R is a FAT-TAIL
  target: most trades never reach it; the cap is filled by the minority of big winners. Take-profit
  structure must respect this (most money is near 1R; 4R is the lottery on trend days).
- **TP1**: full-to-4R-cap (no scale) has the highest expectancy (QQQ +0.264) but ~42% win; SCALING 50%
  at **TP1 = 1.5R** trades exp down (+0.219) for a much higher win% (49%) and smoothness — and 1.5R is
  the best scale point (beats 1.0R). Choose by goal: max EV = full-to-4R; smoother/higher-hit = scale@1.5R.
- **Trail LOSES** everywhere (QQQ +0.091, NQ +0.002, SPY +0.077) — worst of all; do NOT trail (reverses
  the tail-inflated F27b under honest fills).
- **GC FAILS this config** (cap 4R −0.10R, all negative) — because skip-first-hour (entry_delay=60) MISSES
  gold's US-morning move; GC's validated edge (F30, +0.44R) is the immediate 09:30-10:00 OR with
  **entry_delay=0** + its own session. Gold needs its own TP/entry config, NOT the index-tuned one.
- **OPTIONS MAP**: TP1=1.5R = the DEBIT-spread short leg (high-probability workhorse, most trades reach
  ~1R); TP2=4R = the NAKED target (convex tail-capture for trend days); CREDIT spread short @ the
  structure stop = theta/range income. See `bot/options/exit_plan.py`.

## F63 — BOOK-LEVEL order flow is NOT predictive (QQQ MBO, 12 days) (2026-06-29)
`research/strat_orderflow_book.py`. The F62 open question: is L3 order flow ADDITIVE (predicts
direction) or just a filter? 4,680 RTH minutes of QQQ MBO, signed aggressive-trade flow (cum-delta +
z-score) vs forward returns.

| feature | fwd1m | fwd5m | fwd15m | fwd30m |
|---------|-------|-------|--------|--------|
| delta   | −0.007 | −0.011 | −0.034 | −0.017 |
| zcd     | −0.001 | −0.006 | −0.057 | −0.047 |

- **Every IC is ~0 / slightly NEGATIVE** → minute-level trade order flow has NO positive predictive
  power for forward direction (mild reversion at 15–30m). Continuation toy (trade the strong-imbalance
  direction, hold 5/15m) is NEGATIVE expRet at every threshold (−0.003%..−0.032%, win 39–48%).
- **VERDICT: order flow is contemporaneous/reversion only, NOT predictive/additive** at 1s–30m
  (confirms the earlier 1s-ahead negative IC; QI–microprice +0.96 is same-instant only).
- Combined with F62 (bar features OOS AUC 0.48) → **the ORB breakout outcome is largely UNPREDICTABLE**
  from both bar context AND order flow at testable resolutions. The edge stays the rule-based breakout;
  ML/order-flow do NOT add predictive power.
- CAVEATS: 12 days (decent for IC, small for a strategy); tested TRADE cum-delta, NOT full sub-second
  event-time OFI/queue-imbalance with execution-aware persistence (the Evidence claim) — but the 1s
  deep-feature IC was also negative, so that path is unpromising. The honest "predictive+adaptive" ML
  layer (`bot/ml/pipeline.py`) is wired but correctly REFUSES to deploy (no model beats random).

## F62 — FOUR-FAMILY head-to-head on NQ/QQQ/SPY (5m RTH), honest gauntlet (2026-06-29)
`research/strat_four_families.py`. One clean representative of each family, capped-TP2/struct-stop/
skip-1st-hr, gauntlet = exp net R>0 + CIlo>0 + both sides>0 + ≥70% yrs+ + 70/30 OOS>0.

| family | NQ | QQQ | SPY |
|--------|----|-----|-----|
| 1 trend/momentum (gated ORB) | +0.176 fail (yr 11/17) | **+0.304 PASS** | **+0.344 PASS** |
| 2 **breakout / vol-expansion** (plain ORB) | **+0.158 PASS** | **+0.264 PASS (9/9 yrs)** | **+0.270 PASS** |
| 3 mean-reversion / range-fade | −0.174 DEAD | −0.086 DEAD | −0.073 DEAD |
| 4 smc / order-block (F41 OB) | +0.157 fail | **+0.229 PASS** | **+0.284 PASS** |
| 4b smc / liquidity-sweep (sweepgo) | +0.279 fail (n138) | +0.362 PASS (n79) | +0.204 fail (CI<0) |

- **BREAKOUT/vol-expansion is the only edge that PASSES all three instruments** (cleanest: QQQ every
  year+). It is THE validated edge (= the production ORB stack, confirms F58).
- **Trend/momentum** and **SMC/order-block** PASS on **equities (QQQ/SPY) only**, FAIL NQ on year-
  consistency; both just FILTER the breakout trades (OB: 371 vs 728 NQ, similar exp) → ~0 additive net
  of honest fills (confirms F58, not a separate edge). Liquidity-sweep intriguing on QQQ (PF 1.75) but
  small-n / not robust (SPY CI<0).
- **MEAN-REVERSION / range-fade is DEAD on all three** (negative exp, ~every year −) — fades get run
  over by range-day breakouts (confirms F18/F53). Do not trade intraday on these instruments.
- Numbers tie out to prior validated findings (breakout QQQ +0.264=F58, trend QQQ +0.304/SPY +0.344=F59).
- **OPTIONS**: the passing QQQ/SPY families translate to 0DTE naked/debit/credit via `bot/options`
  (naked call/put, debit @ TP1, credit @ structure stop). NQ/MNQ = futures or NQ options.
- **Verdict**: trade the BREAKOUT core on all instruments; the equity trend/SMC filters are optional
  selectivity on QQQ/SPY (fewer trades, not strongly additive); skip mean-reversion.

## F61 — DIRECTION-SEQUENCE entry gate (example.txt / Evidence "where is price going") (2026-06-29)
`research/orb_dir_seq.py`. User rule: a long fires only while price is PUSHING UP — close>close[1]
AND close[1]>close[2] (the 101→102→103 up-sequence); short mirror ("no middle-of-trend, no chase,
no opposite-direction signal"). New engine `dir_seq` param + STACK `dir_seq` input (default ON).

| sym | fill mode | base exp | +dir_seq exp | base PF | +PF | n→ | yrs+ | OOS | 2× slip |
|-----|-----------|----------|--------------|---------|-----|----|------|-----|---------|
| NQ  | wick/touch | +0.151 | **+0.261** | 1.26 | **1.47** | 856→792 | 13/17 | +0.314 | +0.203 (PF1.35) ✓ |
| QQQ | wick/touch | +0.276 | **+0.448** | 1.52 | **1.91** | 513→477 | 9/9 | +0.461 | — |
| SPY | wick/touch | +0.257 | **+0.383** | 1.48 | **1.76** | 526→484 | 8/9 | +0.489 | — |
| NQ/QQQ/SPY | close-confirm | (shipped) | **≈ unchanged** | — | — | ~0 cut | — | — | — |

- On the **wick/touch fill** the gate is a real graduate (exp↑, PF↑, CIlo>0, yrs+ majority, OOS
  holds/improves, survives 2× slip) — it removes the counter-trend pokes the user saw in the
  screenshots. On the **close-confirm fill** (shipped default) it's ~neutral because strong-body +
  next-bar continuation already imply the up-sequence → **safe default-ON everywhere**.
- **No-chase re-tested, stays OFF** (F57 confirmed): close+chase0.5 drops NQ +0.156→+0.081,
  QQQ +0.264→+0.106, SPY +0.270→+0.186. Forcing near-zone entries selects weak breakouts; the
  honest gap-aware fill already prices a late entry correctly, and those late confirmed entries
  are the winners. The user's "don't chase" intuition is a visual preference that costs edge here.
- ADOPTED: `dir_seq` default ON (engine param + STACK input). Propagate to OPTIONS/AUTO/V1_* next.

## F60 — CONSOLIDATED GAUNTLET under the FINAL entry (all fixes in one config) (2026-06-23)
`research/orb_final_gauntlet.py` (run one symbol/process — low-RAM box). Re-ran the whole validation under the
single production entry = clean-TREND gate (structure) + close-confirm + STRONG full-body candle (0.25) +
NEXT-candle CONTINUATION + honest fill at the confirming close + struct stop + skip-1st-hr + cap4 exit; cap/OB off.

**FINAL-config gauntlet, RTH 5m:**
| sym | n | exp R | PF | win | CIlo | gate | long/short | yr+ | worstYr | IS/OOS | 2x slip |
|---|---|---|---|---|---|---|---|---|---|---|---|
| NQ  | 582 | +0.173 | 1.29 | 42% | +0.068 | PASS | +0.174/+0.172 | 11/17 | −0.460 | +0.174/+0.173 | +0.111 ✓ |
| QQQ | 361 | +0.304 | 1.56 | 43% | +0.156 | PASS | +0.406/+0.156 | 7/9  | −0.176 | +0.324/+0.260 | (equity) |
| SPY | 379 | +0.344 | 1.66 | 44% | +0.202 | PASS | +0.420/+0.235 | 8/9  | −0.141 | +0.258/+0.545 | (equity) |
| ES  | 559 | +0.127 | 1.21 | 41% | +0.013 | pass* | +0.154/+0.083 | 11/17 | −0.492 | +0.092/+0.210 | **−0.021 DIES** |
| GC  | 450 | −0.067 | 0.92 | 36% | −0.201 | **FAIL** | +0.009/−0.261 | 7/17 | −0.830 | −0.117/+0.050 | dead |

**Entry-fix ladder (cumulative, structure gate):** NQ touch +0.188→close +0.215→+strong +0.179→+ft FINAL +0.173;
QQQ +0.299→+0.287→+0.283→+0.304; SPY +0.221→+0.176→+0.232→**+0.344**. So the fixes do NOT raise NQ headline R
(slightly lower) — their value is HONESTY (no phantom fills) + RISK-QUALITY (follow-through filters reversals,
lifts win% and SPY/QQQ markedly); SPY is the big winner, NQ ~flat-to-slightly-lower but still passes.

**VERDICT:** the user's finalized entry PASSES the full gauntlet on **NQ / QQQ / SPY** (CIlo>0, OOS holds, majority
years+, NQ survives 2x slip; QQQ/SPY strong PF 1.56/1.66). **ES** barely clears the CI gate (+0.013) and **DIES at
2x slip** → not tradeable. ⚠️ **GC is DEAD under the new entry** (CIlo −0.201, neg everywhere) — F30's gold edge
was under the OLD plain-stop US-morning entry; the trend-gate + strong-close + follow-through combo does not suit
gold. DECISION NEEDED: drop GC, or run GC on the legacy plain-stop entry (`brk_confirm`="Wick/touch", gate off).
Worst-years are deep on the futures (NQ −0.46, ES −0.49) — real losing years exist; equities (QQQ/SPY) are the
cleaner streams.

## F59c — next-candle CONTINUATION confirm ("don't fire into a reversal") — VALIDATED, improves QQQ/SPY (2026-06-23)
User (chart: a long FILL fired on a breakout candle that immediately rolled into a downtrend): "after the price
moves above/below the ORB, WAIT for the NEXT candle to continue the trend to fire." = a 2-candle confirmation:
the breakout candle qualifies (strong full-body close beyond the level, F59b), then the FOLLOWING candle must
CONTINUE (higher close for a long / lower close for a short) before the fill. Added to the engine (`_orb_signals`/
`backtest` params `strong_body`, `ft_confirm`; close-confirm branch) and tested on top of TREND gate + close-confirm
+ strong0.25, NQ/QQQ/SPY 5m RTH:
| sym | no follow-through | + FOLLOW-THROUGH |
|---|---|---|
| NQ  | +0.179 PF1.30 CIlo+0.074 | +0.173 PF1.29 CIlo+0.060 (≈neutral) |
| QQQ | +0.283 PF1.51 CIlo+0.146 | **+0.304 PF1.56 CIlo+0.156** |
| SPY | +0.232 PF1.42 CIlo+0.105 | **+0.344 PF1.66 CIlo+0.208** |
Cuts ~13% of trades; improves QQQ + SPY clearly (it filters exactly the pop-and-reverse fills the user flagged),
~neutral on NQ, all pass the CI gate. ADOPTED default ON. Pine (all 5): new `wait_ft` input → close-confirm fills
on the continuation bar = `qual[1] and close ⋛ close[1]` (qual = strong full-body breakout candle); strategies
(AUTO/V1_STRATEGY) market-enter on that continuation bar. Engine `ft_confirm`/`strong_body` default OFF (other
callers unchanged). NEEDS TV COMPILE on all 5.

## F59b — USER FILL RULE finalized: clear-trend gate ON + STRONG full-body close-confirm (2026-06-23)
User (3rd restatement, explicit): "long has to fill DURING A CLEAR UPTREND, [a] close strong candle above the ORB
then fill; short mirror it." Two requirements stacked: (1) a clear TREND in place (the structure/EMA gate — so
F58's gate-OFF default is REVERSED per user's discretionary setup), (2) a STRONG, full-bodied candle that CLOSES
beyond the OR level (bullish-coloured + body ≥ k·range). Tested (engine: structure gate + execm="close" + body
skip-mask), NQ/QQQ/SPY 5m RTH:
- **TREND gate + close-confirm (no body filter)**: NQ +0.215 (PF1.36, CIlo+0.110, BETTER than plain +0.190),
  QQQ +0.287 (CIlo+0.155, ≈plain), SPY +0.176 (CIlo+0.052, slightly < plain but passes). → the two core
  requirements VALIDATE; requiring a clean trend + full-body close holds the edge (NQ improves).
- **+ strong-body filter** (body ≥ k·(high−low)) sweep: k=**0.25 is the SWEET SPOT** — NQ **+0.233** (best of all),
  QQQ **+0.306** (best), both CIlo up; it rejects dojis/long-wick rejections (the user's actual concern). Going
  heavier monotonically HURTS: k0.4 NQ +0.168, k0.5 NQ +0.150 (CIlo+0.016) & SPY FAILS the CI gate, k0.6 NQ CIlo
  −0.039. SPY dislikes any body filter (prefers off). → default **strong_body = 0.25** (light, decisive-candle).
ADOPTED across all 5 Pine: `trend_mode` default back to "Auto (structure ≤5m / EMA ≥15m)" on STACK/AUTO/OPTIONS
(V1 pair already gate-on); new `strong_body` input (default 0.25) → close-confirm also requires `close>open` (long)
/`close<open` (short) AND `|close−open| ≥ strong_body·(high−low)`. NOTE: the trend gate is kept ON as the user's
SETUP (clean-trend breakouts only), NOT for added expectancy — F58 still stands that it doesn't ADD edge net of
honest fills (it's ≈neutral here too); the user's preference governs the entry. NEEDS TV COMPILE on all 5.

## F59 — full-body CLOSE-confirm entry vs the resting-stop touch (2026-06-23)
User directive: a FILL needs a **full-body candle close beyond the level**, not a wick that just tags it (they
were seeing the FILL marker on wick-touch bars). The engine already models this as `execm="close"` (fire on
`close > level`, fill AT the close — honest, never better than the close). Head-to-head on PLAIN ORB (gate off,
cap4 exit, struct stop, skip-first-hour), honest, NQ/QQQ/SPY 5m RTH:
| sym | stop/touch | close-confirm |
|---|---|---|
| NQ  | +0.151 PF1.26 CIlo+0.066 | **+0.190 PF1.34 CIlo+0.096** (BETTER) |
| QQQ | +0.276 PF1.52 CIlo+0.159 | +0.282 PF1.54 CIlo+0.160 (≈equal) |
| SPY | +0.257 PF1.48 CIlo+0.140 | +0.197 PF1.36 CIlo+0.082 (mildly worse, still passes) |
Close-confirm fires ~5-8% fewer trades, PASSES the CI gate on all three, is BETTER on NQ (primary futures),
neutral on QQQ, mildly worse on SPY. Net: a legitimate, validated-enough entry that also removes the "wick fill"
look. ADOPTED as the production default (the engine was already on execm="close"). Pine: new `brk_confirm` input
(default "Candle close beyond level (full body)"; "Wick / touch (resting stop)" = the F58 stop entry) →
`conf_close ? close>=Le : high>=Le`; fill `l_ep = conf_close ? close : max(Le,open)`; risk `l_rk = l_ep − Ls`
(honest from the actual fill, both modes). Propagated to all 5 (AUTO/V1_STRATEGY swap the resting stop order for
a market-on-close-confirm when conf_close). NEEDS TV COMPILE on all 5.

## F58 — ⚠️ HONEST RE-VALIDATION: the structure/OB GATE adds ~0 and the VWAP-CAP HURTS (2026-06-23)
`research/orb_honest_revalidation.py`. The F56-fix question, settled head-to-head with honest gap-aware fills,
net of costs, cap4 exit + struct stop + skip-first-hour (= the production STACK config), varying ONLY the gate
and the cap. NQ/QQQ/SPY/ES 5m RTH.

**A) The GATE (F20 struct HH/HL + F41 OB confluence) adds nothing — confirmed F56:**
| sym | pure ORB exp | struct exp | stackOB exp | gate verdict |
|---|---|---|---|---|
| NQ  | +0.151 (12/17 yr+) | +0.188 (13/17) | +0.158 (9/17) | ~neutral, OB thins it |
| QQQ | +0.276 (8/9)  | +0.299 (7/9)  | +0.298 (9/9)  | ~equal |
| SPY | +0.257 (8/9)  | +0.221 (8/9)  | +0.236 (7/9)  | gate HURTS pt-est + worst-yr |
| ES  | +0.046 (7/17) | +0.036 (10/17)| +0.035 (7/17) | all ~zero (ES dead) |
The gate cuts ~40% of trades without lifting expectancy; bootstrap CIs are WIDER for stackOB (fewer trades) →
strictly LESS confidence for the same/lower exp. So F20/F21/F41/F45's headline lift was the stale-fill artifact.

**B) The VWAP-cap (F16, k=2.0) HURTS honest fills** (it was tuned against inflated entries). NQ monotonic decay:
no-cap +0.151 → k2.0 +0.094 → k1.3 +0.106; ES same; QQQ/SPY noisy-but-not-better. Best cap = NONE — consistent
with F57 (the late-momentum entries the cap removes ARE the winners). → disable the cap on honest fills.

**Bootstrap 90% CI (the WIN gate):** pure ORB PASSES (CIlo>0) on NQ [+0.066,+0.240], QQQ [+0.158,+0.395],
SPY [+0.139,+0.377]; FAILS on ES [−0.043,+0.138]. stackOB also passes NQ/QQQ/SPY but with wider CIs.
**2x slip:** NQ pure survives (+0.151→+0.098); ES pure DIES (+0.046→−0.100). OOS (70/30) holds for NQ/QQQ/SPY.

**VERDICT (part 1):** the honest tradeable core is a **PLAIN ORB on NQ/QQQ/SPY** (cap4 exit, struct stop,
skip-first-hour), exp ~+0.15–0.28R, PF 1.26–1.52, CIlo>0, OOS holds. **ES is dead.** The structure gate, OB
confluence, and VWAP-cap are NOT the edge — drop/disable them (gate neutral-to-harmful; cap harmful).

**Part 2 — honest re-check of the levers held CONSTANT above** (`research/orb_honest_levers.py`, plain ORB,
one-lever sweeps, NQ/QQQ/SPY):
- **TIME GATE (skip first hour, F38) = REAL and survives the fill fix** — and MORE skip is better: delay 0→90m
  lifts exp on all three (NQ +0.149→+0.214 CIlo+0.118; QQQ +0.205→+0.307 CIlo+0.186; SPY +0.205→+0.276
  CIlo+0.158). The 10:00–11:00 post-OR hour is the chop; later breakouts are cleaner. KEEP (delay 60–90).
- **STOP anchor (F25b struct vs OR) = NEUTRAL** — struct ≈ OR to 3 d.p. on all three (NQ +0.151 vs +0.150;
  QQQ identical; SPY +0.257 vs +0.262). The struct stop's claimed lift was ALSO the artifact; it doesn't hurt,
  but it adds nothing — can keep or simplify to the OR-edge stop.
- **EXIT (F34b) cap4 = CORRECT (already shipped)** — full→4R cap is the best honest exit on all three (NQ +0.151,
  QQQ +0.276, SPY +0.257) and beats scale_be-4R / tp2_full-2R / trail. **trail is the WORST** (NQ +0.032
  CIlo−0.020 FAIL) — confirms F50/F51 that trail's old headline was tail-inflation; the Trail→cap4 default
  switch was right.

**FULL HONEST CONFIG = plain ORB + skip-first-hour (60–90m) + cap4 exit, NO direction gate, NO OB, NO VWAP-cap,
OR-or-struct stop (either), on NQ/QQQ/SPY (ES dead).** Production STACK currently ships gate+OB+cap2.0 ON =
now known SUBOPTIMAL. Simplification surgery (across all 5 Pine + keep engine defaults off) pending user's call —
it gives up the gate's chart-readability and ~40% more (both-side) fires for tighter CIs at equal/better exp.

## F57 — research-code fill audit + the no-chase guard (the lateness is a FEATURE) (2026-06-22)
Audited ALL research code for the F56-class fill mistakes (stale-level fill, same-bar fill→TP, lookahead):
- **The mistake is CENTRALIZED in the engine** (`_orb_signals` execm + `backtest` entry-at-level) → inherited by
  all ~59 engine-based scripts; fixing the engine fixes them all. Scripts that produce signals/levels and route
  through `B.backtest` (orb_confirm_entry's `_signals` override, orb_kernel_filter, all orb_stack_* filters,
  eval/prop scripts which reuse `tr["net_R"]`) are now PROTECTED by the engine gap-aware-entry fix.
- **Custom-sim scripts checked individually**: orb_projection_test (enters at the signal-bar CLOSE, exits from
  j=i+1 → clean, no stale level / no same-bar); strat_daily/rangefade/ml/volbreak_test/kernel_signal (built
  gap-aware/causal in F49/F52-55). No independent fill bug found in the custom sims.
- **Structure columns are CAUSAL** — `H.pivots()` returns the pivot only at the CONFIRM bar (`right` bars AFTER
  it; `ci=i-L`), so st_state/sph/spl LAG, they don't peek. This is WHY the gate fires late (F56), and confirms
  the F56 problem was the fill, not a structure lookahead. (Prior known lookahead: F19 clean-day, already killed.)
- **NO-CHASE guard tested** (engine+Pine `chase_atr`/`chase_max`, off by default): only fire while price is still
  within k·ATR of the level (don't chase a late fill). Result: it HURTS — NQ +0.156→−0.039R (chase0.5)→−0.141
  (0.25), QQQ slightly worse. The late, confirmed-momentum entries are the WINNERS (the structure gate confirms
  only after a real move); forcing near-level entries selects weak breakouts. So the chart's "late fill at
  exhaustion" is intrinsic + beneficial; the only real bugs were the stale FILL PRICE and same-bar TP (both fixed
  F56). Left `chase_atr` as an off-by-default option. Honest stack with the fixes ≈ +0.15-0.23R (marginal).

## F56 — ⚠️ CRITICAL: the gated-stack "edge" is largely a STALE-FILL ARTIFACT (2026-06-22)
User flagged two fill issues that "inflate the stack production": (1) mid-bar/stale fill, (2) fill+TP on the same
bar. Both were REAL, and chasing them down unravelled a chunk of the program.
- **Same-bar fill→TP**: the PINE STACK booked TP/stop on the SAME bar as the fill (the `if in_long` block ran on
  the fire bar). FIXED → `if in_long and not long_fire` (management starts the bar AFTER fill, matching the
  engine's i+1). The Python engine was already clean here (entry at i, scan from i+1).
- **STALE-LEVEL fill (the big one)**: `execm="stop"` fires `lsig` on the first bar where `high>=lh` AND the
  TREND GATE (`tup`) is true — but `high>=lh` stays true for every bar after the break, so when the structure
  gate confirms LATE (it lags the breakout), the fire lands well past `lh` while the engine recorded the entry AT
  `lh`. Measured on NQ 5m: mean (firing-bar open − level)/ATR = PURE ORB **−0.56** (fills at the cross, honest) →
  +structure **+0.60** → +structure+OB (the stack) **+1.82 ATR**, with 73% of stack fires opening ABOVE the level.
  So the stack credited entries ~1.8 ATR better than fillable. FIXED → engine + Pine entry = WORSE of
  {level, bar open} (gap/late-aware).
- **HONEST head-to-head (NQ 5m RTH, scale_be, no cap)**: pure ORB exp **+0.124** (n198) vs structure+OB stack exp
  **+0.129** (n411) — IDENTICAL. The structure gate / OB confluence add ~0 per-trade once fills are honest. With
  cap2 the stack is +0.156 on ~110 trades (~6/yr) = marginal. Documented F45 ~+1-2R and the F20/F25b/F41 lifts
  were substantially the stale-fill artifact (the gates pick already-run breakouts; the backtest bought the pre-run level).
- **IMPLICATION**: F20 (structure gate), F21, F25b (struct stop), F41 (OB), F45 (the ~2× config) — all validated
  via `execm="stop"` with stale-level fills — are SUSPECT and need honest re-validation. The PURE ORB fills
  honestly and is the clean baseline (~+0.12R). Cap/costs need re-tuning for honest fills (vwap_cap2 on honest
  entries behaves differently — pure+cap2 went NEGATIVE). The kernel/CVD/AMT/etc FILTER studies compared deltas
  on the same inflated base, so their RELATIVE conclusions (redundant/dead) likely survive; absolute exp does not.
- FIXES SHIPPED: engine `hs_backtest.py` gap-aware entry; STACK pine same-bar defer + gap-aware fill. AUTO uses
  the broker emulator (strategy.*) so its fills are broker-modeled; review separately. NEEDS TV compile.
VERDICT: pause new-strategy adoption; the urgent task is an HONEST re-validation of whether the structure stack
beats a plain ORB at all once fills are realistic.

## F55 — volatility-breakout FULL GAUNTLET: fails once stressed (2026-06-22)
`research/strat_volbreak_test.py`. The F52 survivor stress-tested: (A) k-plateau NQ/QQQ/SPY pass k0.2-0.4,
ES/GC fail; (B) **2× slippage = futures FAIL** (NQ 15/17 at 2×, ES/GC collapse), only QQQ/SPY survive (equity
costs ~0.25bp) but those are 2018+ only; (C) **short side dead everywhere** (long/drift effect); (D) weaker
pre-2018 even on NQ; (E) **~30% of trades are both-levels-hit days** (path-ambiguous). Path test: assume-long
+0.12% / skip-both-hit **+0.31% PF3.8** / pessimistic **−0.07%** → the headline depends entirely on the coin-flip
both-hit days. VERDICT: not tradeable as a daily-bar strategy (fails 2× slip on futures, short dead, 30%
path-ambiguous); the clean single-break-day edge is real but needs an INTRADAY re-run (take first break) to resolve
fills honestly — deprioritized given F56.

## F54 — Supervised ML / learned combiner (daily direction): NO robust edge → DEAD (2026-06-22)
`research/strat_ml.py`. HistGradientBoosting on causal OHLCV+VIX features (returns 1/2/3/5/10d, RSI2/14, SMA5/20/
50/200 distance, ATR%, range%, gap, vol-z, DoW, VIX level+rel), target = sign(next-day return). WALK-FORWARD
(train years<Y, predict Y; OOS only). Edge counts only if OOS acc > base rate (majority class) AND strat passes.
- NQ acc 55.9% vs base 56.3% (BELOW base, fail), ES 55.9 vs 54.6 (yr+7/13 fail), GC 51.7 vs 52.5 (fail).
- QQQ acc 62.4 vs 54.9 Sharpe 4.14 PASS, SPY 63.3 vs 54.2 Sharpe 4.68 PASS — but IMPLAUSIBLY high + does NOT
  REPLICATE: the same indices via futures (NQ/ES, 2010+ history) only hit ~56% ≈ base rate. QQQ/SPY series start
  2018 so their OOS is just 5 recent trending years.
VERDICT: **DEAD** — no robust daily-direction edge. The QQQ/SPY pass is the SAME post-2018 equity-regime artifact
as Connors RSI-2 (F52): both pass on QQQ/SPY 2018+ and fail on the longer NQ/ES history. Daily direction ≈ base
rate out-of-sample, as expected. (A learned combiner on INTRADAY ORB-entry features — not daily direction — is a
different, untried question; would need the harness feature matrix at entry bars.)

## F53 — Range-day VWAP fade + the regime-switch ensemble: BOTH DEAD (2026-06-22)
`research/strat_rangefade.py`. Idea: the stack SKIPS local_regime==2 (chop/low-ADX) bars; fade VWAP extension
(>= k·ATR) back to VWAP on exactly those bars to harvest them. Conservative fills (entry at signal-bar close,
cover at VWAP = limit, stop at WORSE of stop/next-open). Result on NQ 5m RTH: DEAD across k{1.5,2.0}×stop{1.0,1.5}
— expR −0.17..−0.25, PF 0.69-0.74, win 31-45%, NEGATIVE in ~15/17 years, both-sides fail. Low-ADX "range"
classification does NOT imply mean-reversion — fades get run over by range breakouts. → the regime-switch
ENSEMBLE (stack on trend days + fader on chop days) is MOOT: there is no profitable chop-day leg to switch into,
so the stack's existing "skip chop" (exclude local_regime==2) is already the correct behavior. (Multi-symbol run
OOM'd on the memory-starved box; NQ alone decisive.)

## F52 — FOUR new standalone DAILY strategies: volbreak + Connors graduate, donchian/VIX die (2026-06-22)
`research/strat_daily.py`. Gauntlet on NQ/ES/QQQ/SPY/GC 1d, conservative gap-aware fills (stop-entry fills at the
WORSE of level/open; exits gap-aware; no target booked on the entry bar — addresses the user's mid-bar-fill-then-TP
concern). Gate = exp>0 net costs AND bootstrap CI(R)>0 AND >=70% yrs+ AND 70/30 OOS-out>0 AND both-sides.
- **Volatility breakout (Crabel/Williams, open±k·prior-range, EOD exit), k0.3 = GRADUATES**: NQ +0.12%/t PF1.54
  win56% **17/17 yrs+**, QQQ PF1.69 **9/9**, SPY PF1.55 **9/9**, all PASS, OOS+. ⚠️ thin (~12 bps/trade, fires
  ~daily) → SLIPPAGE-SENSITIVE (k0.5 weaker; ES fails 14/17; GC dead). An intraday momentum/trend-persistence edge.
- **Connors RSI-2 (close>SMA200 & RSI2<10 → long; mirror short) = GRADUATES on EQUITIES only**: QQQ PF1.97 win73%
  CI+0.182 PASS, SPY PF2.14 win77% PASS — but REGIME-DEPENDENT: fails NQ/ES over full 2010+ (NEG '11/'15/'16/'18);
  the QQQ/SPY pass rides the post-2018 dip-buy regime (those series only start 2018). Real but not all-weather.
- **Donchian/Turtle (N{20,55} breakout, M=N/2 exit, 2ATR stop) = DEAD as graded**: real but LUMPY (win 33-44%,
  many negative years, CI<0) — classic trend-following fails the strict every-year gauntlet. N55 has fat per-trade
  (+0.5..+1.6%) but n small + CI<0.
- **VIX-spike fade (VIX>sma5·1.10 → LONG index, exit 5d/VIX-normalises) = DEAD**: PF 0.16-0.56, big losses
  '18/'20/'21 — naive "buy the index on a vol spike" catches falling knives.
VERDICT: two genuine NEW return streams = volbreak (best consistency, slippage caveat) + Connors RSI-2 (equity,
regime-dependent). Both are DIFFERENT streams from the intraday ORB stack → diversification value. Donchian/VIX/
range-fade dead. Next: forward/slippage-stress volbreak before it could be a real 5th stream.

## F51 — struct-stop "inflation" dig RESOLVED + production exit/floor updated (2026-06-22)
Followed up the F50 flag (`orb_stop_floor.py`, NQ+QQQ 5m RTH, prod config). Findings:
- **The entry/stop EDGE is real, not inflated.** With a BOUNDED exit (scale_be / capped-TP2) expectancy is
  +1.4..+1.7R (scale) / +2.1..+2.4R (capped 4R) = consistent with documented F45 (~2× stack). Robust to the
  stop floor: MIN_STOP_ATR sweep 0.5→1.5 moves exp <0.15R (NQ +1.362→+1.211, QQQ +1.660→+1.473). My F50 worry
  (tight-stop artifact) is DISPROVEN.
- **The inflation was the TRAIL exit's R-metric only** — a few low-ATR trades blow up the R-denominator
  (grossR max ~50R), so trail R/PF is tail-driven (already documented F34b: "trail PF tail-inflated 17 vs
  capped honest 3-6"). In $ terms trail is fine; in R it misleads — and F27b made trail the DEFAULT on exactly
  that R-comparison. So the default was resting on the unreliable metric.
- **The 0.5-ATR floor is noise-tight on equities** (QQQ median structure stop ≈0.57 ATR; 52% of QQQ trades
  resolved ≤1 bar at 0.5 = trivial TP1). Expectancy-neutral to widen.
PRODUCTION CHANGES (user-directed, overriding the batch-defer rule for this script):
1. **STACK default exit Trail → "Full → cap @ TP2 (struct stop)"** (the F34b honest/eval-steady graduate;
   trail demoted to a toggle). `production/HIGHSTRIKE_ORB_STACK.pine` exit_mode default + tooltip.
2. **Ticker-adaptive min-stop floor**: futures 0.5 ATR, stocks/funds 0.75 ATR (`auto_minstop` ON by default,
   `eff_min_stop = syminfo.type=="futures" ? 0.5 : 0.75`). Engine matched for parity:
   `min_stop_atr_ = 0.75 if EQ else MIN_STOP_ATR` in `hs_backtest.backtest` (verified: NQ min riskATR 0.50,
   QQQ 0.74). Capped-TP2 then reads NQ +2.14R PF9.0 win75% / QQQ +2.40R PF11 win74% (realistic, bounded).
⚠️ TODO consistency: the same exit-default + min-stop change should propagate to AUTO (real-order twin — must
match the STACK display) and the other Pine (V1/OPTIONS/ASIA/MTF) + a TV compile; not yet done (scope was STACK).

## F50 — OB-port reconcile (PASS) + the VWAP-cap "earlier-entry" frontier (2026-06-22)
User asks: (1) is the order-block actually implemented in the STACK pine, (2) the ORB fill feels "mid-range/too late".
**(1) OB RECONCILE — Pine ⇄ harness: FAITHFUL PORT, no logic drift.** Mapped `HIGHSTRIKE_ORB_STACK.pine`
L170-209 against `hs_harness._zones_sweep_patterns` L302-345 line-for-line: formation (bull `close>high[1] &
close[1]<open[1] & ob_strong` → zone (open[1],low[1]); bear mirror), ob_strong (`|close-open|≥atr·0.3 & vol≥sma20·0.7`),
keep-N FIFO (5), invalidation (close beyond far edge OR |close-near edge|>3·atr), containment (`low≤top & high≥bot`),
and the gate uses `in_bull_ob[1]` (prior bar = causal) == engine `.shift(1)`. ALL MATCH. Pine array loops are
guarded (size>0) and remove top-down (safe). Only true open item = a TV COMPILE (can't run TV here); the OB block
itself is syntactically clean. OB is default-ON, F47-robust params.
**(2) VWAP-cap = the anti-late lever** (`orb_cap_lateness.py`, NQ+QQQ 5m RTH, prod config: struct gate + OB + time
gate + struct stop). Measured entry extension beyond prior-bar session VWAP (ATR) per cap k:
- NQ: ext mean +0.28 (uncapped, entries CHASE) → −0.17 (k2.0 prod) → −0.36 (k1.5) → −0.60 (k1.1); extMax mechanically
  bounded by k (6.4→2.0→1.5→1.1); MAE_R (initial heat) −0.32→−0.25→−0.22→−0.20. Trades kept 100%→86%→78%→68%.
- QQQ same shape. So lowering k pulls the AVERAGE entry from the chasing side to the VWAP side and halves worst-case
  lateness, monotonically, costing ~14% (k2.0) → ~22% (k1.5) → ~32% (k1.1) of trades. Sweet spot **k≈1.3–1.5**.
- Expectancy RISES as k tightens (validated frontier, consistent w/ F16/F36) — but ⚠️ the ABSOLUTE exp/win% from
  this harness config look OPTIMISTIC (85-94% win, hold med 1 bar): the struct stop pins to MIN_STOP_ATR=0.5 floor →
  4R target ≈ 2 ATR, reached intrabar where the engine assumes TP-before-stop. RELATIVE frontier is trustworthy;
  absolute struct-stop expectancy (F25b/F45) may be inflated by tight-stop intrabar optimism — flag to revisit.
VERDICT: OB is correctly wired (needs only a TV compile to close). For "too late" the validated knob is **lower the
VWAP-cap toward 1.3–1.5** (user-tunable Pine input; NOT changing the default per defer-propagation). Retest/confirm
entries stay dead on 5m (Finding 8/11).

## F49 — "Neural Kernel Bands" STANDALONE Buy/Sell signal: ~zero accuracy, the chart look is an illusion → DEAD (2026-06-22)
`research/orb_kernel_signal.py`. User reported the stack's 5m/15m ORB entries "are not working" and that the
kernel-band Buy/Sell labels "look on point" on the chart — asked to test the label accuracy directly. F36 tested
this indicator as a FILTER (redundant w/ VWAP-cap); this tests the band-cross flip AS ITS OWN ENTRY. Reused the
verified causal port (kernelMA=EMA(Σwᵢ·close[i]/Σwᵢ), bands=±mult·σ(resid), state→±1 on close vs band, "Buy"/"Sell"
= held-state flip). Three causal reads (signal confirmed at close[t] → entry at open[t+1]):
- **forward-return accuracy**: dir hit-rate 44→50% across H=1..20 bars (BELOW coin flip early, ~50% at 20) on
  NQ+QQQ × 5m+15m; mean fwd move 0.00–0.02 ATR = statistically zero. The labels do NOT predict direction.
- **flip-to-flip always-in** (reverse on opposite flip): GROSS expR tiny + (+0.04..+0.12, just the always-in trend
  drift) but win 31–33% (chopped); NET of realistic costs negative everywhere (NQ 5m −0.575R PF0.66 over ~48k
  flips, NQ 15m −0.235R, QQQ 5m −0.047R; QQQ 15m +0.07R but raw return −47%).
- **charitable re-check (both polarities, RTH-only, real ATR bracket stop=1.0/target=1.5R, exit on opp flip/EOD)**:
  FOLLOW the label (momentum) loses — NQ 5m −0.283R PF0.63, 15m −0.167R; QQQ 5m −0.082R, 15m −0.006R (≈breakeven);
  FADE it (mean-reversion to the kernel) loses too — NQ 5m −0.334R, 15m −0.239R; QQQ 5m −0.069R, 15m −0.074R.
  Win 38–42% vs a 1.5R target = breakeven before costs, negative after. NEITHER direction is tradeable.
- **the illusion, quantified**: the Buy label is drawn at the bar LOW, but the fill is the CLOSE — already
  **+1.2–1.6 ATR past the upper band**. So the marker sits at a swing low and price "rallies away from it" in
  hindsight = looks perfect, but that ~1.3-ATR is unfillable. That marker placement + the smoothed band hugging
  price IS why it "looks accurate."
VERDICT: **DEAD as an entry**, consistent with F36 (dead as a filter). Fine as a discretionary visual; not a
replacement for the ORB stack entries. (Separately: the user's "5m/15m entries not working" is about the STACK,
not the kernel — 15m was never a validated stack TF anyway: structure gate graduated on 5m only, 15m-retest
non-replicates. Need to clarify whether "not working" = not firing in Pine vs not profitable, then target that.)

## F48 — Order Flow (CVD proxy): a WEAK but CONSISTENT additive lead → real tick data is the one live direction (2026-06-17)
`research/orb_stack_orderflow.py`. True order flow needs TICK / bid-ask / trade-delta data we DON'T have; the
honest OHLCV proxy = CUMULATIVE VOLUME DELTA (CVD: each bar's volume signed by close-location-value clv =
((c−l)−(h−c))/(h−l), session-cumulative). Tested cvd_agree (CVD slope direction) + cvd_lvl (session CVD sign)
as causal stack filters, full gauntlet.
- **Gate:** both PASS on NQ+QQQ+SPY (modest lift, ~93-95% retention, every year+, 2× slip+).
- **ADDITIVITY — the key difference from the dead momentum filters:** kernel (F36) and RSI+AC (F37) OSCILLATED
  around 0 (redundant); CVD's frontier-lift is CONSISTENTLY POSITIVE at every k on BOTH NQ (+0.03..+0.07) and
  QQQ (+0.02..+0.07), AND it adds on top of F45 (NQ +1.144→+1.218, QQQ +1.372→+1.451, ~+0.07). So CVD is NOT
  redundant — a real (if small) orthogonal signal.
- BUT magnitude is SMALL (~+0.03..+0.05R, within ~1 SE) and it's a CRUDE proxy → too marginal to headline /
  not a strong graduate like F38/F41.
VERDICT: order-flow CVD = a **weak-but-real additive lead**. Its significance: even a coarse OHLCV proxy carries
a small orthogonal signal the dead momentum filters lacked → **REAL tick/bid-ask/delta data is the single most
promising direction for NEW edge** (the one untested family shows life). Recommended next DATA step = source tick
data and re-test order flow properly; the proxy itself is too marginal to adopt into F45.

## F47 — F41/F45 DE-RISKED: the order-block edge is a broad PLATEAU over its params (2026-06-17)
`research/orb_ob_robust.py` (+ harness OB params parametrized as off-by-default `P.ob_body_atr/ob_vol_mult/
ob_keep/ob_dist_atr`; defaults = V44, all prior results unchanged). Swept each OB param around its default and
re-ran +ob on the stack (NQ+QQQ), like F23 did for the pivot params.
- **PLATEAU, not a spike.** Every param value clears the gate, every year+, exp in a TIGHT band: NQ +0.92..+1.06
  across body {0.2-0.5}, keep {3-8}, dist {2-5}, vol {0.5-1.0}; QQQ +1.09..+1.17. The untuned V44 default sits
  MID-plateau, not at a peak. keep-count barely matters (few active OBs sit near price); body/dist/vol all flat.
VERDICT: **the F41 order-block edge does NOT depend on the (untuned) V44 OB params → DE-RISKED** (mirrors F23 for
pivots). F45 (the combined config) is robust to its order-block parameterization. Adoption de-risk done.

## F46 — 3rd-axis hunt on the F38+F41-filtered residual: CONVERGED, no new orthogonal axis (2026-06-16)
`research/orb_stack_features2.py`. Re-ran the F38 feature-separation study on the residual trades AFTER both new
edges applied (stack + skip<11:00 + order-block) on NQ+QQQ+SPY — anything still separating winners would be a 3rd
independent axis. The only sign-consistent separators left are ALL already accounted for:
- **vwap_ext** (−0.31/−0.39/−0.42) = the adopted VWAP-cap axis (tightening it = the known frontier, not new).
- **adx** (+0.30/+0.26/+0.27) = F40 REDUNDANT (trend-strength rides the frontier; corr persists but additivity
  already killed it — the session's core lesson: correlation ≠ additivity).
- **compress** (−0.10/−0.19) = F40 dead, and now WEAKER post-F38 (confirms it was a time-of-day shadow).
- **tod_min** collapsed +0.34→+0.07/+0.15 (F38 captured it); **gap_dir** = the F13 thin against-gap tilt.
VERDICT: **the systematic feature-based hunt has CONVERGED.** After structure + VWAP-cap + time-of-day (F38/F39)
+ order-block (F41), the measurable orthogonal edge in this feature space is exhausted. To go further needs
genuinely NEW data (Order Flow / tick — the one untested agenda family) or new feature families, not more
indicators on OHLCV. The 2-day push's harvest = F38/F39 + F41 (+ the F45 combined config). Open de-risk before
any propagation = F41 OB-param robustness sweep (untuned V44 params, like F23 for pivots).

## F45-PROP — F45 adopted: live-semantics re-validated + PROPAGATION started (engine done, STACK done) (2026-06-17)
User called the hunt done → propagate (freeze lifted). Two important pieces:
- **LIVE-SEMANTICS re-validation.** The research applied F38 via `skip_mask` (a morning break CONSUMES the day's
  signal); the natural live/Pine form is a WINDOW GATE (no entries until OR-close+delay → the first AFTERNOON
  break fires, latch not consumed in the morning). They differ slightly. Re-validated F45 in the LIVE form
  (engine `entry_delay=60` + `ob_confluence`): NQ +1.053/PF10.7/17-of-17 yr, ES +0.942/PF8.8/16-of-16, QQQ
  +1.268/PF16.5/9-of-9, SPY +1.084/PF9.2/9-of-9 — every year+, OOS holds/improves, 2× slip ok, and MORE trades
  than the skip_mask version (it's slightly more robust). So backtest==live; these are the official F45 numbers.
- **ENGINE (`hs_backtest.py`) — DONE + verified.** Added off-by-default `entry_delay` (F38; skip N min after OR
  close) + `ob_confluence` (F41; AND the prior-bar order-block into the firing gate). ⚠️ caught + fixed a LATCH
  bug: applying ob AFTER `_orb_signals` let the once-per-day latch fire on the structure-only signal then filter
  it out (n 406→79); fix = AND the ob mask INSIDE `_orb_signals` at the firing check (with the latch). Defaults
  off → all prior results unchanged.
- **STACK.pine — DONE (primary).** entry_delay input + OR-close capture + `past_delay` in `window` (F38); OB
  inputs + a ported order-block array machine (`obBull/BearT/B`, mirrors `_zones_sweep_patterns`) + `in_bull_ob`/
  `in_bear_ob` ANDed into `gate_long/short` as `[1]` (prior bar, causal) (F41). ⚠️ NEEDS the user's TV COMPILE
  check + an OB RECONCILE vs the harness (like st_state F28) — I can't compile Pine.
- **REMAINING:** propagate to AUTO / OPTIONS / V1_INDICATOR / V1_STRATEGY (all-scripts rule) — staged AFTER the
  STACK compiles clean (so a Pine error in the OB port isn't replicated ×4); then forward paper-test.

## F45 — CONSOLIDATION: F38 (time) + F41 (order-block) STACK into a ~2× expectancy config → validated (2026-06-16)
`research/orb_stack_combined.py` (+ `--additive`). The session's two new orthogonal edges combined on the stack
(structure gate + VWAP-cap + **skip<11:00** + **order-block confluence**), NQ+QQQ+SPY+ES:
- **BOTH > each single on all four:** NQ +0.736→**+1.144** (PF 14.7, win 92%, DD −3), ES +0.536→**+0.961**
  (PF 10.5, win 90%), QQQ +0.801→**+1.372** (PF 26.8, win 95%), SPY +0.680→**+1.070** (PF 9.4, win 87%).
  ~DOUBLES stack expectancy (+55%/+79%/+71%/+57%), every year+ (16/16·13/13·9/9·9/9), OOS holds/IMPROVES on all
  four, survives 2× slip (NQ +1.089, ES +0.826), keeps 65-76% of trades.
- **Frontier-lift PRESERVED combined:** delta vs the vwap-cap frontier is +0.15..+0.24 (NQ) / +0.26..+0.35 (QQQ)
  at every k ≈ F38-lift + F41-lift (they ADD) → the combo stays strongly orthogonal to extension.
- High PF (15-27) is earned (per-year + OOS hold — the F21 intersection-of-validated-filters pattern); thin-
  sample = the usual forward-test caveat.
VERDICT: **new best stack config = structure gate + VWAP-cap + skip<11:00 (F38) + order-block confluence (F41).**
~2× expectancy, DD ~halved, win 87-95%, on all four index futures/ETFs. Two new orthogonal axes found +
validated this push (+ F39 extends F38 to Asia/London). Still NO propagation ([[highstrike-defer-propagation]])
— banked for the eventual batch. Open de-risk: F41 OB-param robustness sweep (untuned V44 params, like F23).

## F44 — Statistical (day-of-week / seasonality / day-context): no tradable edge → DEAD (2026-06-16)
`research/orb_stack_stat.py`. Honest screen on the stack's residual trades with the cross-asset-consistency bar.
- **Day-of-week / seasonality = CURVE-FIT.** The stack is positive EVERY day on every asset (+0.6..+0.9R) but the
  best day FLIPS across assets (Fri/Mon/Wed) and the worst flips (Thu/Thu/Tue) → no consistent calendar edge.
  Confirms F15 (Friday was curve-fit).
- **Day-context = thin tilts that don't beat the frontier.** Breakouts AGAINST the prior RTH day's direction are
  mildly better than WITH on all 3 (NQ +0.77 vs +0.71, QQQ +0.89 vs +0.72, SPY +0.88 vs +0.55) — sign-consistent
  but ≈ the known F13 against-gap theme, and as a GATE it culls ~60% of trades for ~flat exp (NQ against-day
  +0.774 at n=168 << the vwap-cap frontier's ~+1.1 at that n) → BELOW the frontier, not a tradable filter.
  Prior-day RANGE corr weakly negative (−0.06..−0.12; big prior range → slightly worse) — same thin-tilt status.
VERDICT: **Statistical yields no tradable orthogonal edge — DEAD.** Calendar = curve-fit; day-context = thin
quality tilts (echo F13) that don't beat tightening the VWAP-cap. Closes the queued research agenda.

## F43 — Liquidity confluence (sweep / prior-day-level take-out): DEAD (2026-06-16)
`research/orb_stack_liquidity.py`. Two liquidity-CONFLUENCE reads as stack filters (sweep-as-ENTRY already dead
F18/19): require a recent liquidity sweep before the break, or require the breakout to take out the prior-day
RTH high/low (the external stop pool).
- **+swept** (harness bull/bear_sweep_active, prior bar): n=21/12/24 on NQ/QQQ/SPY — TOO RARE (<30) to be a
  usable filter; a recent sweep + a stack breakout rarely co-occur.
- **+pdsweep** (OR-high > prior-day high / OR-low < prior-day low): culls ~60-70% of trades for FLAT (NQ
  +0.736→+0.748, QQQ +0.801→+0.798) to WORSE (SPY +0.680→+0.544) exp — at NQ n=128 the vwap-cap frontier is
  ~+1.1 vs pdsweep's +0.748, i.e. far BELOW the frontier → fails the gate (no additivity needed).
VERDICT: **Liquidity yields no orthogonal entry edge — DEAD.** Consistent with pdlvl_brk being WEAK in the F38
study + AMT value-area dead (F42): taking out a daily liquidity level overlaps with EXTENSION, which the adopted
VWAP-cap already handles; sweep-as-confluence is too rare. The order-block (F41) is the only SMC/liquidity-style
zone that carries orthogonal edge.

## F42 — Auction Market Theory (prior-day value-area confluence): DEAD (2026-06-16)
`research/orb_stack_amt.py`. Built a real VOLUME PROFILE of the prior RTH day (volume distributed across each 5m
bar's [low,high], 50 bins) → POC + 70% value area (VAH/VAL); causal (today uses yesterday's completed profile).
Tested the canonical AMT thesis as a stack confluence filter: take the breakout only if its entry (OR level) is
accepted OUTSIDE prior value (outside_va: long OR-high>prior VAH / short OR-low<prior VAL) or beyond prior POC.
- **DEAD at the gate (no additivity test needed).** Both variants CULL 35-50% of trades AND exp goes flat-to-
  DOWN: NQ +0.736→+0.688/+0.726, QQQ +0.801→+0.734/+0.773, SPY +0.680→+0.618/+0.611. Lower exp at fewer trades
  = strictly BELOW the vwap-cap frontier (at NQ n=195 the frontier is ~+1.1 vs AMT's +0.69) → fails the gate.
- Why: "outside value" partly selects MORE VWAP-extended breakouts, conflicting with the adopted VWAP-cap (F16)
  that already penalizes extension; and the structure gate already ensures quality, so a coarse daily value-area
  level doesn't separate the stack's trades (in-value breakouts are just as good). Consistent with the F38
  feature study where pdlvl_brk (entry beyond prior-day level) was already WEAK (−0.06).
- Other AMT angles are redundant or exit-side: initial-balance extension ≈ the ORB breakout itself; value-area
  migration ≈ a trend proxy (dead family); naked-POC-as-magnet is an EXIT/target concept (exits already
  optimized F25b/F27b/F34b). VERDICT: **AMT yields no orthogonal ENTRY edge for the stack — DEAD.**

## F41 — SMC ORDER-BLOCK confluence: the strongest orthogonal stack filter found → GRADUATES (2026-06-16)
`research/orb_stack_smc.py` (+ `--additive`). Working the Smart Money Concepts family: market STRUCTURE (HH/HL
st_state) already GRADUATED (F20), liquidity SWEEPS already DEAD as entries (F18/F19). The untested SMC piece =
ORDER-BLOCK / FVG zone confluence as a stack FILTER — the harness already computes the zones (in_bull_ob/
in_bear_ob + at_bull_zone/at_bear_zone, V44 defaults). Tested as a causal (prior-bar) AND-gate on the stack.
- **+ob** (require the breakout to fire while price is at a bull order block for longs / bear OB for shorts):
  NQ +0.736→**+0.971** (PF 8.2), QQQ +0.801→**+1.113** (PF 10.6), SPY +0.680→**+0.907** (PF 5.9). Every year+,
  OOS holds/improves, 2× slip strong, and it KEEPS ~94% of trades — it RE-SELECTS (occupancy/delay), barely culls.
- **ADDITIVITY = the largest, most stable lift of any filter.** vs the vwap-cap frontier it's POSITIVE at every k:
  NQ +0.11..+0.20, QQQ **+0.23..+0.28** (flat across the whole grid — bigger than time-of-day's +0.03..+0.10).
  AND it adds substantially ON TOP of the F38 skip<11:00 gate at ~same n: NQ +0.980→+1.144, QQQ +1.136→**+1.372**
  → orthogonal to BOTH VWAP-extension AND time-of-day. Two independent new axes now stack (F38 + F41).
- **+zone (OB-OR-FVG) = MARGINAL** (frontier-lift ~0 on NQ, +0.05..+0.10 QQQ; near-zero on top of F38). Adding
  the FVG component DILUTES the OB signal → OB-only is the lever, FVG is not.
- Mechanism: an ORB breakout firing from/at a bullish order block (institutional demand zone) is a genuine SMC
  confluence — supported breakouts are higher quality independent of how extended (VWAP) or what time of day.
VERDICT: **GRADUATED — the strongest orthogonal stack filter found.** Banked, NO propagation yet
([[highstrike-defer-propagation]]). ⚠️ It uses the V44 OB params (untuned here = NOT curve-fit to this test, a
plus); recommended DE-RISK before eventual propagation = an OB-param robustness sweep (like F23 did for pivots).
SMC is the richest family: structure gate (F20) + order-block confluence (F41) both graduate; sweeps + FVG dead.

## F40 — the secondary leads (squeeze / ADX): ADX redundant, squeeze is a thin time-of-day shadow → not adopted (2026-06-16)
`research/orb_stack_squeeze.py` (+ `--additive`). The two other sign-consistent leads from the F38 feature study —
compress = ATR(7)/ATR(28) prior bar (corr −0.29, lower=squeeze=better) and adx (corr +0.20) — put through the
full gauntlet incl. the additivity control and an on-top-of-F38 check.
- **Both LOOK strong standalone** (gate sweep, NQ+QQQ+SPY): adx≥30 → NQ +1.03/QQQ +1.00/SPY +0.89, every yr+,
  OOS holds, 2× slip ok; compress≤0.95 → NQ +1.13/QQQ +1.13/SPY +1.22. But both cull HARD (adx≥30 keeps ~40%,
  compress≤0.95 keeps ~15-20% = ~5 trades/yr) — the classic pre-additivity-test illusion.
- **ADX = REDUNDANT with VWAP-cap.** At the adopted operating point (vwap k=2.0) the frontier-lift delta is
  NEGATIVE on both NQ (−0.048) and QQQ (−0.200) — adx≥30 is WORSE than tightening the cap to the same n. It only
  goes positive deep in the survivorship tail (k≤1.2, where the vwap frontier has plateaued). adx is trend-family
  → rides the frontier exactly like the kernel/RSI/AC (F36/F37), and consistent with F17 ("stricter ADX = TF-
  dependent, not robust"). DEAD as a new lever.
- **SQUEEZE (compress) = a thin, NQ-only, TIME-OF-DAY SHADOW.** Additive on NQ (delta +0.05..+0.14 in the
  realistic k-zone) BUT on QQQ it's NEGATIVE at the operating point (−0.071 @k2.0) and only marginally + when
  tightened. Decisively: ON TOP OF the F38 skip<11:00 gate it adds ~nothing — QQQ +1.136→+1.129 (−0.007) while
  cutting trades 196→46. So the −0.29 corr was largely because squeezes CLUSTER midday; F38's time gate already
  captures the axis. Plus it culls to ~5 trades/yr (n=46-83) = impractical.
VERDICT: **neither adopted.** ADX is redundant with the VWAP-cap; squeeze is asset-inconsistent + largely
subsumed by F38 (time-of-day) + far too thin. The lesson holds: testing the secondary leads vs BOTH the vwap-cap
frontier AND the already-graduated F38 gate is what exposed them — a raw +1.0R standalone meant nothing. F38/F39
(time-of-day) remain the session's real find; the feature-study's other "leads" were shadows of it or of the cap.

## F39 — TIME-OF-DAY is UNIVERSAL: the opening-hour skip transfers to Asia + London AND rescues ES → GRADUATES (2026-06-16)
`research/orb_session_tod.py` (+ `--additive`). Tests whether F38's RTH "skip the opening hour" generalises:
skip the first N min after EACH session's OR closes (RTH 10:00, Asia 20:00 ET, London 03:30 ET; trade-day
coords for off-hours). Off-hours = NQ + ES only. The structure-maturity mechanism (the HH/HL gate needs
post-open intraday swings to FORM) should apply to any session open — and it does, even harder off-hours.
- **Transfers + monotonic on all 3 sessions.** Recommended robust point = skip first **60 min** (matches RTH;
  60-90 is the plateau). Asia NQ +0.500→**+0.631** (PF 2.78→3.84, 17/17 yr, OOS holds, 2× slip +0.33→+0.47);
  London NQ +0.574→**+0.866** (PF 3.45→8.98, 14/14, OOS +0.83→+0.95, 2× +0.46→+0.77).
- **It RESCUES ES off-hours — the #1 open caveat on Asia/London (F22/F29 "NQ-strong, ES-marginal, dies at
  2× slip").** Asia ES base +0.193/PF1.49/DD−54/5 neg yrs/**2× slip −0.165 (NEGATIVE)** → skip+60 +0.457/
  PF2.85/DD−8/15-of-17 yr/**2× slip +0.128**; at skip+120 → +0.540, 14/14 yrs, 2× +0.213. London ES base
  +0.271/**FAIL** (6 neg yrs, 2× slip 0.000) → skip+60 +0.674/PF5.52/**PASS**/15/15 yr/OOS +0.62→+0.80/
  **2× slip +0.44**. The opening hour was WHERE the ES off-hours fragility lived; cutting it fixes it.
- **ADDITIVITY (the F37 control) = POSITIVE at every k on all four off-hours streams** (Asia NQ +0.01..+0.08,
  Asia ES +0.12..+0.20, London NQ +0.08..+0.21, London ES +0.14..+0.31) — STRONGER than RTH (+0.03..+0.10).
  The off-hours vwap-cap frontier PLATEAUS (it can only filter extension, not time-structure noise) while the
  time gate climbs past it → strongly ORTHOGONAL, not a frontier-ride. Mechanism confirmed cross-session.
VERDICT: **GRADUATED — the opening-hour skip is a UNIVERSAL stack gate, all 3 sessions** (skip the first ~60min
after each session's OR close: RTH ≥11:00, Asia ≥21:00, London ≥04:30 ET). It both lifts every session's edge
AND de-risks the off-hours ES slippage problem that was the main barrier to Asia/London — so it strengthens the
"trade all 3 sessions" case (F26b). Adoption = the same near-free clock gate per session → all-scripts
propagation ([[highstrike-all-scripts-consistency]]) + forward-test. Pairs with F38 (RTH) = one rule everywhere.

## F38 — TIME-OF-DAY: skip the opening hour — the first ORTHOGONAL edge that LIFTS the frontier → GRADUATES (2026-06-15)
`research/orb_stack_features.py` (feature hunt) + `research/orb_stack_tod.py` (drill + controls). After F36/F37
(every trend/extension cull just rides the VWAP-cap frontier), I ran F15's feature-separation study on the
STACK'S RESIDUAL trades (post HH/HL gate + post VWAP-cap) across NQ+QQQ+SPY — so the adopted axes are factored
out and only ORTHOGONAL separators show. Sign-consistent leads: **tod_min +0.34** (time-of-day), compress −0.29
(squeeze), adx +0.20, vwap_ext −0.42 (the adopted control). Time-of-day was the standout and is causal + free.
- **The pattern (all 3 assets):** opening-hour breakouts are near-dead on the stack — 09:30-11:00 exp +0.07/
  +0.22/+0.27 (NQ/QQQ/SPY), PF 1.1-1.7 — while 11:00-15:00 carry everything (PF 7-23). Mechanism: the HH/HL
  st_state gate needs intraday swings to FORM; pre-11:00 signals fire on stale overnight/pre-market structure.
- **skip-mornings sweep (skip stack entries before T; engine skip_mask, a later break same day still fires).**
  Monotonic + every config PASSES on NQ+ES+QQQ+SPY. Recommended robust point **T = 11:00** (broad plateau
  10:30-12:00, not a fitted spike):
  | | exp (from) | PF | win | DD | per-yr | OOS | 2× slip | kept |
  |---|---|---|---|---|---|---|---|---|
  | NQ  | **+0.980** (0.736) | 9.0 | 88% | −3 | 13/13 | +0.95→**+1.04** | +0.93 | 75% |
  | ES  | +0.780 (0.536) | 5.5 | 84% | −3 | 12/12 | +0.77→+0.82 | +0.65 | 68% |
  | QQQ | **+1.136** (0.801) | 16.4 | 91% | −2 | 7/7 | +1.19→+1.00 | — | 65% |
  | SPY | +0.982 (0.680) | 8.0 | 86% | −2 | 8/8 | +1.00→+0.95 | — | 59% |
  exp +33-50%, DD ~halved, win 86-91%, every year+ (it even REMOVES ES's lone 2017 down-year), OOS holds/
  improves, survives 2× slip. (skip<10:00 = no-op, n unchanged — the OR closes 10:00 so nothing fires earlier;
  internal-consistency check passed.)
- **THE DECISIVE CONTROL — additivity / frontier-lift (the F36/F37 killer): PASSES.** delta = (skip<11:00 +
  vwap k) MINUS vwap-only at matched n, across the whole k grid: **NQ {+0.06,+0.07,+0.06,+0.03,+0.03,+0.10},
  QQQ {+0.07,+0.08,+0.07,+0.05,+0.05,+0.08} — POSITIVE at EVERY k on BOTH assets.** Unlike the kernel/RSI/AC
  (which oscillated around 0 = redundant), time-of-day LIFTS the whole vwap-cap frontier by ~+0.05-0.07R → it
  is genuinely ORTHOGONAL (mornings are low-edge for a reason unrelated to VWAP extension — structure-gate
  immaturity). This is the first new lever since F27b to clear the full gate INCLUDING the frontier-lift test.
VERDICT: **GRADUATED — adopt a "no entries before ~11:00 ET" gate on the RTH stack.** Near-free (an entry-time
clock gate, NO indicator port unlike F36), every-year-positive, OOS-stable, 2×-slip-robust, frontier-additive.
⚠️ Adoption cost = it changes the tested system → all-scripts propagation ([[highstrike-all-scripts-consistency]])
+ the forward-test gate, same as every graduated lever. ⚠️ RTH-SPECIFIC as tested: the Asia/London analog
("skip the first ~90min after THAT session's OR") is untested — the structure-maturity mechanism should
transfer but must be checked per-session before applying off-hours. Secondary orthogonal leads compress(−0.29
squeeze) + adx(+0.20) are real + sign-consistent but untested at signal level — next in the queue.

## F37 — RSI and Accelerator/Decelerator as STACK FILTERS: also REDUNDANT with VWAP-cap → DEAD (2026-06-15)
`research/orb_momentum_filter.py` (+ `--robust` / `--additive`). Same drill as F36 on two classic momentum
oscillators, embedded as causal (prior-bar) AND-gates into the stack trend gate. Indicators (textbook params,
no mining): **RSI(14)** Wilder; **AO** = SMA(hl2,5)−SMA(hl2,34); **AC** (Accel/Decel) = AO−SMA(AO,5). Six
variants: rsi_side (>50/<50), rsi_cap (don't-chase: skip RSI>70 longs / <30 shorts), rsi_slope, ac_sign
(AC>0/<0), ac_accel (AC rising/falling), ac_agree (Bill Williams: AC>0 AND rising / AC<0 AND falling).
- **All six LOOK like graduates** — every variant PASSES (both sides+, CI>0) on NQ+QQQ+SPY+ES, every year+,
  OOS holds, survives 2× slip. The AC pair is strongest: **ac_agree** NQ +0.736→**+0.847**, QQQ +0.801→
  **+0.912**, SPY +0.680→**+0.794**, ES +0.536→**+0.639** (PF to 6+, DD cut, 2× slip NQ +0.793/ES +0.494).
  RSI variants milder (+0.03..+0.07R). By the F16/F20/F21 checklist all would pass.
- **The redundancy + additivity controls KILL them.** At the *default* operating point ac_agree sat a hair
  ABOVE the vwap-cap frequency↔quality frontier (NQ +0.020, QQQ +0.056 at matched n) — the only filter yet
  to do so, which warranted the stronger test: does it lift the WHOLE frontier? **No.** Re-running ac_agree
  *over the vwap-cap k grid* and differencing vs the vwap-only frontier at matched n, the delta **oscillates
  around zero** — NQ {+0.02, −0.02, −0.03, −0.04, +0.03}, QQQ {+0.06, +0.02, −0.02, +0.01, +0.02} — i.e.
  *negative through NQ's mid-range*. The only big +deltas (+0.10) are at k=1.0 where n collapses to 138-196
  (PF 11-19) = the **F16 survivorship mirage**, unusable. ac_sign sat BELOW the frontier; RSI variants ON it.
- So RSI and AccelDecel are the SAME story as the kernel (F36): they all proxy "price trending in the trade
  direction / not over-extended," already captured by st_state HH/HL + VWAP-cap. The single-point "above
  frontier" reading for ac_agree was a lucky cull location, not an orthogonal axis — the additivity sweep
  (lift across multiple k) is the control that exposes it (stronger than F36's single matched-n point).
VERDICT: **DEAD — do NOT embed RSI or Accelerator/Decelerator in the stack.** Cheap-to-port (AC = a few SMAs)
does NOT rescue a redundant filter: it adds a knob + propagation cost for zero orthogonal edge. (Robustness
real, additivity nil — identical to F36.) Methodology note: ANY momentum cull mimics graduation; only the
*frontier-lift / additivity* test vs the existing levers separates a real axis from a frontier-rider.

## F36 — "Neural Kernel Bands" as a STACK FILTER: REDUNDANT with the VWAP-cap → DEAD (2026-06-15)
`research/orb_kernel_filter.py` (+ `--robust`). User-supplied TradingView indicator. First, what it IS:
the "kernel regression / ML core" is — on inspection — a **causal one-sided weighted moving average**
(weights decay with bar AGE i, `wᵢ=exp(-i²/2h²)`, NOT a predictor feature), EMA-smoothed; bands =
kernelMA ± mult·σ(residual). It is non-repainting (uses only `close[i]`, i≥0). Its primary signal is a
**volatility-band BREAKOUT** (close crosses the band) — a momentum read, same family as the ORB. Tested AS A
FILTER on the validated 5m stack (F21 HH/HL gate + VWAP-cap k2, scale_be, OR stop) by AND-ing a causal
(prior-bar) kernel-agreement condition into the trend gate — exactly how `orb_stack_walkforward.py` injects
st_state. Four variants: **state** (held band-cross state must agree = the literal "band-cross filter"),
**slope** (kernelMA rising/falling), **side** (close vs kernelMA), **cap** (don't-chase: skip if already >1σ
beyond kernelMA).
- **It LOOKS like a graduate.** Every variant beats or ties the stack on all four metrics, PASSES (both
  sides+, CI>0) on **NQ+QQQ+SPY+ES**, positive every year, **OOS holds**, and **survives 2× slip** on the
  futures. `slope`: NQ +0.736→**+0.817**, QQQ +0.801→**+0.836**, SPY +0.680→**+0.756**, ES +0.536→**+0.658**
  (PF 4.5→5.6, DD cut, CI up). `state` similar. By the F16/F20/F21 checklist alone it would graduate.
- **The redundancy control KILLS it.** Tightening the **existing** VWAP-cap knob `k` to the SAME trade count
  reproduces the entire lift: NQ vwap-cap **k=1.7 → n=351, +0.823** ≈ kern:state **n=375, +0.822**; and
  **k=1.5 → n=307, +0.892** *beats* kern:state at FEWER trades. The kernel filter lands right on the
  frequency↔quality frontier the stack already exposes via one input. The fact that **all four** variants
  (incl. orthogonal `cap`) improve is the tell — they're all proxies for "price trending in the trade
  direction / not over-extended," which **st_state HH/HL + VWAP-cap already capture.** The marginal +0.05R
  at matched-n is within ~1 SE and is dominated by simply turning the cap knob further.
- This is the **F1/F11/F13/F19 trap caught again**: a cull that rides the frontier mimics every graduation
  signal (cross-asset, per-year, OOS, slip) without adding orthogonal information — the redundancy control is
  the only test that separates them, and the methodology demanded it.
VERDICT: **DEAD as a quant filter — do NOT adopt.** It does not earn the heavy engineering cost (port the
kernel + adaptive bandwidth + residual bands + band-state machine into Pine, reconcile, propagate to 5
scripts) for a benefit you already own via VWAP-cap. Fine as a **discretionary visual**; not a signal lever.
(Robustness intact — the cross-asset/OOS/slip wins are *real*, just not *additive*.)

## F34 (option A) — production-config validation in DOLLARS, cross-instrument (2026-06-15)
`orb_config_validate.py` — NQ/QQQ/SPY/ES/GC 5m RTH, fixed $250 risk/trade, per-year + OOS + STOP-rate.
Resolves F33-CONFIG: is the production struct+trail config real or just optically hot?
- **The +3.6R/PF17 is tail-inflated but NOT broken.** struct+trail $/trade: AVG ~$700-860 vs **MEDIAN
  ~$170-270** — the gap is a few huge trail winners; every instrument is +17/+9/+15 yrs and OOS holds,
  so the tail dollars are real but unreliable in a small eval window. It also scratches 10-15% of trades
  to breakeven (BE%), the trail giving profit back.
- **Best CENTRAL-TENDENCY config = struct stop + 2R cap ("struct+trail capped", tp2_full):** highest
  MEDIAN $ on EVERY instrument (NQ +527, QQQ +423, SPY +377, ES +356, GC +289), avg≈median (stable, not
  tail-driven), believable PF 3.2-6.5, PASS all 5 incl GC. struct+scale (F25b) is good on equities/NQ
  but WEAK on ES/GC (GC fails). or+scale (the eval-sim baseline) is the lowest median everywhere → the
  F31d/e/f eval pass-rates were computed on the MOST CONSERVATIVE config (so they're safe/under-stated).
- **STOP-out rate (the user's screenshot whipsaw) = 20-35% on ALL configs — normal, not pathological.**
  Tighter struct stop trades MORE stop-outs (capped 29-35%) for BIGGER, cleaner wins; wider OR-edge stop
  fewer stop-outs (or+scale 18-26%) but lower median. Genuine tradeoff, not a bug.
RECOMMENDATION: for EVAL-passing (high stable median, low variance) the capped config dominates; keep
the unlimited trail only for funded/personal accounts chasing tail trend-months. Until adopted production
stays struct+trail; trust median-$ not the PF-17.

### F34b — capped-target WALK-FORWARD: cap-4R GRADUATES (2026-06-15)
`orb_cap_walkforward.py` — struct stop + fixed-R target cap (full position, mode tp2_full), caps 2R/3R/4R,
full gate (both>0, CI>0, ≥70% yrs, OOS-out>0, 2× slip) on NQ+QQQ+SPY+ES+GC.
- **cap-4R PASSES all five incl 2× slip**: NQ +1.69R PF6.3 (15/15, 2×slip +1.54), QQQ +1.71R (9/9, +1.71),
  SPY +1.59R (9/9, +1.59), ES +1.19R (14/16, +0.82), GC +0.98R (15/15, +0.26).
- cap-3R FAILS (GC dies at 2× slip −0.13); cap-2R FAILS (ES and GC die at 2× slip). 4R is the only level
  surviving 2× slip on all five AND the highest expectancy → robust pick, not tuned.
- The TRAIL also passes the gate (it always did) — both are valid; the choice is preference (stable median
  vs tail capture), not validity.

### F34c — eval path on cap-4R (2026-06-15)
`orb_eval_cap.py` — combined NQ, adopted F31f frame, F26 profiles.
- cap-4R: **median $402/trade (≈2× trail's $221)**, PASS 97/99/100%, blow-up 3/1/0%. Trail: med $221,
  99/100/100%, 1/0/0%. Old scale_be baseline: med $218, 97/98/95%, 3/1/4% (the eval sims used the WORST
  config → prior pass-rates were conservative).
- cap-4R accumulates ~2× faster (median $) and is 99-100%/0-1% on the realistic profiles; the only knock
  is 3% blow-up at the TIGHTEST daily limit (−4R) vs trail's 1% (cap's −1R/+4R distribution is harsher on
  a 4R daily cap than trail's −0.77R avg loss). The day-throttle + "size daily ≥6R away" guidance covers it.
VERDICT: **cap-4R is a graduated config** — best for eval accumulation. ADOPTED 2026-06-15 as a user-toggle
(NOT the default — trail stays default): STACK new exit mode "Full → cap @ TP2 (struct stop)"; AUTO "Fixed
TP bracket" default bumped 2R→4R; V1_STRATEGY "Full to TP2" already had TP2 R=4 (=cap-4R), tooltip clarified.
Activate/deactivate freely. All need the pending TV compile check.

## F35 — Structure Projection Engine: NOT viable as a predictive/tradeable engine (2026-06-15)
`orb_projection_test.py` — feasibility of the user's spec (predict next HH/HL/LL/LH + projection band)
BEFORE building the indicator. Tested its two load-bearing claims on NQ+QQQ 5m using the harness swing
sequence (sph/spl, st_state).
- CLAIM 1 (predictive) FAILS hard: linear projection (proj = 2·last − prev) has MAE **38-44% WORSE**
  than the naive "next swing ≈ last swing"; directional hit ~48-50% (coin flip); corr(Δproj, Δactual)
  ≈ 0 (−0.01 to −0.03). Swings do NOT extrapolate linearly — there is zero forecasting skill.
- CLAIM 2 (tradeable continuation) FAILS: target = projected HH, stop = last HL → NQ −0.083R PF 0.94,
  QQQ +0.076R PF 1.05 (sub-edge). The spec's "confidence" proxy doesn't separate: the high-win-rate
  tight bucket (84-88% win) is ~0R (target so close it always hits for nothing); the bulk wide bucket
  is negative.
VERDICT: **do NOT build the projection engine as specced.** It forecasts no better than a coin flip and
the implied trade has no edge. SALVAGEABLE only as a *visual of CURRENT confirmed structure* (the st_state
HH/HL gate is validated) — but it must not project FUTURE levels or be traded off projected targets.
Useful corollary: since naive "next ≈ last" beats linear extrapolation, the most accurate forward
reference is the current swing level (horizontal) — which the stack already uses as the structure-stop
anchor. Nothing new to add there.

## F33 — local RANGE block: KEEP IT (the opposite of regime B) (2026-06-15)
`orb_range_block.py` (raw slice) + `orb_range_eval.py` (trustworthy read). Question: is there edge in
the trades the LOCAL range gate (local_regime==2, ADX<20 chop) discards? Same F31 protocol: gate forced
open, trades sliced by TRUE local_regime at entry, baseline = adopted F31f macro frame.
- Read on the EVAL-CANONICAL config (scale_be + OR stop — see F33-CONFIG note; the raw struct-stop+trail
  slice is R-inflated and unreadable). lr=2 RANGE slice: RTH +0.189R (IS CI −0.04 FAIL, OOS +0.48 only),
  Asia +0.076R (CI −0.01, **NEGATIVE −0.13R at 2× slip**), London +0.142R (IS CI −0.12 FAIL).
- This is the MIRROR IMAGE of regime B: B passed in-sample AND OOS-stronger AND survived 2× slip; RANGE
  is flat in-sample (every session IS-CI ≤ 0 — the marginal "pass" is carried entirely by 2022+) and
  DIES at 2× slip (Asia goes negative). Physically sensible: range = no momentum, ORB = momentum bet.
- Eval path (combined): unblocking RANGE makes it WORSE — blow-up 0%→4% at the tight profile, pass
  100%→96%. It dilutes quality and adds tail risk.
VERDICT: **the RANGE block stays ON, all sessions — no change.** (It is engine-hardwired and part of every
validated result; the live STACK already does this.) Also useful: lr=2 trades being only ~⅓ the trend-slice
expectancy shows the block is NOT redundant with the HH/HL gate — it earns its keep.

## F33-CONFIG — the production struct-stop+trail config is R-INFLATED; eval sims used a different config (2026-06-15)
`orb_f33_debug.py` — 2×2×2 gate×exit×stop matrix on NQ 5m RTH (unblock-B), with median per-trade risk.
- The production STACK Pine default (struct gate + **struct stop + trail**) prints **+3.611R, PF 16.85,
  avg-win +5.46R** — NOT tradeable; it is a measurement artifact. The struct stop halves median risk
  (19.8→9.7 pts, the real F25b effect), and pairing that sub-ATR denominator with an uncapped trail
  explodes the R-MULTIPLE while the dollar moves stay normal. PF 17 is the tell.
- The combination was **never walk-forwarded together**: F25b graduated struct-stop with **scale_be**
  (+1.025R), F27b graduated trail with **OR stop** (+0.879R) — separately. The eval sims (F26/F31d/e/f)
  used `stack()` = **scale_be + OR stop** (+0.744R) → trustworthy + dollar-meaningful, but that is a
  MORE CONSERVATIVE system than the live Pine trades.
- Also caught: `orb_regimeb_entries/oos.py` (F31 magnitude tables) silently ran on the **EMA gate** (never
  set trend_up/down from st_state) → their +0.39R numbers are off-gate. F31's DIRECTION holds (reproduced
  on both gates; eval sims used the correct gate) but those two scripts' magnitude tables are void.
OPEN DECISION: either (a) re-run the eval sims on the ACTUAL production config (struct+trail) with realistic
costs to learn its true dollar pass-rate, or (b) reconsider the production default toward the validated
scale_be+OR / struct+scale_be. Until resolved, trust the scale_be+OR eval numbers, not the PF-17 headline.

## F31 — macro regime B: the block is discarding a validated edge (2026-06-12)
`orb_regimeb_entries.py` + `orb_regimeb_oos.py` — NQ 5m, adopted stack (struct gate + VWAP cap +
struct stop + 2ATR trail), macro_allow gate disabled, trades sliced by entry regime.
- **Regime B passes the full gate in ALL THREE sessions** on both exit configs (trail+struct AND
  scale_be baseline): RTH +0.395R PF 2.55 (n=530, 14/14 yrs), Asia +0.435R PF 2.37 (13/16),
  London +0.281R PF 1.83 (12/15). Regime A is the *weakest* passing slice everywhere; C also strong;
  D = too few trades / CI<0 → keep blocking D.
- **OOS (2022+) is STRONGER than IS in all 3 sessions** (RTH +0.72R PF 4.9, Asia +0.51R PF 3.2,
  London +0.74R PF 4.5) — not a decayed artifact.
- **Unblock B (keep D blocked)**: ~2.4× the trades at same/better expectancy — RTH n=895 +0.390R
  CI +0.32 (survives 2× slip at +0.32R), Asia n=913 +0.416R (2× slip thins to +0.16R, CI +0.07),
  London n=938 +0.304R (2× slip +0.14R, CI +0.06).
- Why: the ORB stack's edge doesn't need a trending SPY — the structure gate + VWAP cap do the real
  filtering. block_b was inherited from the V43/V44 macro design and never re-tested for the stack.
VERDICT: **validated candidate — flip "Block trend in REGIME B" OFF** (settings-only; the input already
exists in every script). RTH = adoption-worthy outright; Asia/London = real but slippage-thin at 2×
(their existing caveat, now with 2× the fills). ⚠️ Before trading it on a funded eval, re-run the
F26d daily-limit sim with the ~2.4× trade frequency.

## F31d — eval sim at unblock-B frequency: safe-to-better, one caution (2026-06-12)
`orb_prop_eval_b.py` — F26 profiles, production vs unblock-B streams. Median trades-to-pass is
unchanged (~12-24) but arrives ~2.4× faster in CALENDAR time. RTH: 98→100% / 93→97% pass, 0% blow-up.
Asia: the old 11% blow-up at (+9/−6/−4) DISAPPEARS (100%/0%). ALL THREE: 99-100% pass, ≤1% blow-up.
⚠️ London standalone at the tight (+9/−6/−4) profile: blow-up 0→13% — size London down, use a looser
profile, or run the combined account. VERDICT: unblock-B is eval-safe everywhere except London-only
on a tight daily limit. **ADOPTED 2026-06-12: STACK default block_b=false** (other 4 scripts pending
propagation per the consistency rule; engine default left as the research baseline).

## F31f — MIXED B-block (London only) = the ADOPTED final form (2026-06-12)
`orb_prop_eval_mixed.py` — user's proposal: unblock B for RTH+Asia, keep B blocked in London.
ALL-THREE account: **100/100/99% pass, 0% blow-up at every profile, fastest medians (13/22/44)** —
strictly dominates both full-unblock (99%/1% at tight) and old production. RTH+London two-session
variant equally clean (100/99/98%, 0%). The London-B trades added tail risk without adding speed.
**ADOPTED: STACK "Block REGIME B trend" selector = Off / London only (DEFAULT) / All sessions**,
applied during London hours 03:00-09:30 ET on the trade-day clock (works in Auto + standalone).
Propagation to AUTO (same selector) + OPTIONS/V1 (RTH-only → plain unblock) pending.

## F31e — day throttle (max 5 signals/day, lock after 2 losers): FREE (2026-06-12)
`orb_prop_eval_throttle.py` — identical pass/blow-up/median in every stream × profile × ruleset cell.
Per-session streams never reach the caps (≤2 trades/day); on ALL THREE the skipped trades are too rare
to move anything. Diagnostic: with the 2-loss lock a day can't lose >~2R, yet London-unblock-B still
blows up 13% at the tight profile → that risk is TRAILING-DD bleed across days, not single-day
clustering — a day throttle cannot fix it. VERDICT: free discipline insurance — added to STACK as
EVAL inputs (cap 5 / lock 2, active only with EVAL on, suppresses signals like ev_halt).

## F31c — confirmation entries: DEAD (user spec, exact side-by-side) (2026-06-12)
`orb_confirm_entry.py` — body-CLOSE breakout candle (wick-only excluded) → stop entry above the
breakout candle's high (below low for shorts) → invalidate if price closes back inside the range;
variants: multi-bar pending, strict next-candle-only, +volume(1.2×20bar), +retest-and-hold.
- **Every variant fails in every session.** Best case RTH plain confirm +0.086R CI −0.08 (vs prod
  touch +0.383R CI +0.28 PASS); Asia/London all deeply negative (−0.20…−0.39R, PF 0.33-0.54).
  Volume and retest options make it WORSE everywhere. Confirms F19 (false-break/retest dead) and the
  generic confirm sweep (close-confirm / next-bar-open / next-bar-high all ≤0 in `orb_regimeb_entries.py`).
- Why: the ORB edge is captured AT the level — confirmation enters 1+ bars later at a worse price
  with the same structure-stop anchor, so risk widens, R shrinks, and the trail math collapses.
VERDICT: **production touch entry (resting stop at the OR level) stands. No Pine change.**

## F32 — the stack on the 1-MINUTE chart: DEAD (2026-06-12)
`orb_1m.py` + `orb_1m_robust.py` — NQ 1m (5.4M bars, continuous parquet via direct loader; 1m is not
in the hive bars dataset), adopted stack, all 3 sessions, std + shorter OR windows.
- Std windows on 1m: RTH +0.00R (dead), Asia −0.66R (catastrophic), London −0.37R (dead). Cause:
  the structure gate on 1m pivots is noise, and 1m structure stops are so tight that fixed costs eat
  the R — same edge, smaller denominator, negative net. Everything dies at 2× slip.
- Only the ultra-short ORs pass full-sample: RTH 09:30-09:35 (+0.145R CI +0.06) and London
  03:00-03:05 (+0.159R CI +0.02), both 13/17 yrs. Robustness kills both: IS CI < 0 (the pass is
  carried entirely by 2022+), and **both DIE at 2× slip** (RTH +0.03 CI −0.06; London −0.30) — the
  graduation gate requires 2× survival. The OOS-only strength is real but unsupported by the
  in-sample years → not adoptable.
VERDICT: **1m is for WATCHING, not signal generation.** Trade the 5m stack; keep 5m-validated levels
on the 1m chart for execution visuals. No further 1m testing warranted (user gate: failed step 1).

## Propagation log (all-scripts consistency rule)
| Script | Stack status (structure gate + VWAP cap + structure stop + trail + sessions) |
|---|---|
| `production/HIGHSTRIKE_ORB_STACK.pine` | ✅ PRIMARY — full stack, RTH/Asia/London + Auto (incl. 18:00-19:00 stale-gap guard) |
| `production/HIGHSTRIKE_ORB_AUTO.pine` | ✅ REBUILT as the STACK's automation twin — same engine as a strategy; trail via broker-held initial structure SL + EXIT webhook (bracket mode = fallback); provider-agnostic webhooks (TradersPost / PickMyTrade / Generic relay multi-account / custom template), token + account-id inputs ready for keys |
| `production/HIGHSTRIKE_ORB_OPTIONS.pine` | ✅ REBUILT on the stack engine (was V1/EMA + OR-edge stop, reported not working) — SPY/QQQ, RTH only, 0DTE entry / max 4-DTE hold, naked BUY-only call/put at 1-2 ITM/OTM (selector + ladder), debit spread capped @TP1, credit vertical short @structure stop, trail-break = EXIT alert. Multi-day hold ≤4 DTE is an options-layer allowance, NOT separately backtested (underlying edge is intraday) |
| `production/HIGHSTRIKE_ORB_V1_INDICATOR.pine` | ✅ structure-stop + trail available, off by default |
| `production/HIGHSTRIKE_ORB_V1_STRATEGY.pine` | ✅ stack upgrades propagated as OFF-BY-DEFAULT toggles (structure gate F20 + VWAP cap F16 + structure stop F25b + trail exit F27b); defaults = V1 legacy. PROPAGATION COMPLETE across all 5 Pine + engine |
| `engine/hs_*.py` | ✅ logic-of-record (stop_mode="struct", scale_frac, sessions) |

Remaining adoption gate: **forward paper-test of fills** (≥2 weeks clean reconciliation, RTH first, then
Asia/London — slippage-sensitive). The AUTO file + `docs/AUTOMATION_SETUP.md` are the harness for it.
