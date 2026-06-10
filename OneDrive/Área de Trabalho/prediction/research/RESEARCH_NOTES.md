# HIGHSTRIKE — ORB research notes

Goal: push the FOUR characteristics as high as possible — expectancy (R/trade), profit factor,
win %, max drawdown (lower = better) — while staying robust (lower 90% CI > 0, both signals > 0).
Tool: `python research/orb_mtf_research.py NQ 15m` (computes harness state + MTF once, sweeps cheaply).

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

## Lever scorecard (cumulative) — adopt only if it clears the gate on QQQ AND NQ, then propagate to ALL scripts
| lever | verdict |
|---|---|
| MTF confirmation (F1) · volume (F11) · VWAP-side (F12) · OR-width (F13) · time-stop (F14) · close+body (F13) | ❌ dead/noise |
| retest entry (F8) | ✅ 15m-only edge; NOT wired (user trades 5m where stop wins) |
| stop-entry · all-day · 4R/scale · per-TF buffer · EOD-flat | ✅ ADOPTED (production) |
| **against-gap (equity)** (F13) | 🟡 real tilt, thin + PF-warning + equity-only → confidence signal, not a filter |
| **VWAP-extension cap** (F16) | ✅ PASSED honest signal-level test (k≈2.0, all 3 assets × both TFs, NQ DD ~halves) — promotion = user decision; costs ~25-60% of trades |
| stop-placement variants (structure vs OR-opposite); per-regime reward | ⬜ untested |

Discipline: every screen here is post-hoc (filters taken trades) — a screen says "does this separate good
from bad", NOT the final number. Graduation = signal-level reimplementation + full re-validation (both
signals >0, lower CI >0) on QQQ AND NQ, THEN propagate to ALL Pine scripts + engine (the consistency rule).
