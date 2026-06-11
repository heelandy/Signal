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
| prop-eval survivability (F26) | ✅ stack passes funded rules 93-100%, ~0% blow-up (RTH); Asia wants looser daily/trail limit (11% blow-up tightest); both-sessions best |

Discipline: every screen here is post-hoc (filters taken trades) — a screen says "does this separate good
from bad", NOT the final number. Graduation = signal-level reimplementation + full re-validation (both
signals >0, lower CI >0) on QQQ AND NQ, THEN propagate to ALL Pine scripts + engine (the consistency rule).
