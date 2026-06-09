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

## Next levers to try (in this file)
- ATR-volatility filter on the breakout bar.
- Per-regime reward (wider target in regime A/trend, tighter in C/volatile).
Each must clear the same gate (both signals > 0, lower CI > 0) and be reported across all four metrics.
