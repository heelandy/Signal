# Direction-Latency Review — how the system can know price direction faster

Date: 2026-07-02 · Follow-up to `TRADING_BOT_COMPLETE_REVIEW.md` §5.
Question: given everything already researched, what can be changed so the system knows the
current price direction (and commits to it) sooner?

---

## 1. Where the minutes go today (RTH example, 5m chart)

| Stage | Directional information | Available at | Lag after OR close |
|---|---|---|---|
| OR forms | none (levels building) | 09:30–10:00 | — |
| **OR-mid bias** (adopted 2026-07) | day biased LONG/SHORT by which half the OR closed in | 10:00:00 | **0 min** |
| Vol-expansion grade (OR-width/ATR) | quality, not direction | 10:00:00 | 0 min |
| Breakout + dir-seq + strong-body close | direction *of the move* | first qualifying bar close | 5–15 min typical |
| + next-candle continuation (`wait_ft`) | confirmation | +1 bar | +5 min |
| **HH/HL structure state** (`st_state`) | the *validated* trend read (≈2× expectancy) | 2 confirmed pivot pairs; each pivot confirms `lb` bars after its extreme | **median ~50–60 min** (lb=5); lb=3 saves ~10 min/pivot |
| Bot layer | signal surfaced to dashboard/webhook | 60 s polling loop + provider bar-publication lag | +0–2 min |

So the system already "knows" a tradeable direction at **10:00 sharp** (OR-mid bias — adopted,
gauntlet-passed) and at the **first confirmed break** (plain ORB — gauntlet-passed standalone,
F62). What arrives 50–60 minutes later is not direction, it's the *doubling of expectancy* from
the structure gate. That framing drives every recommendation below.

## 2. Review of every prior direction-related finding

**Validated & adopted (the current engine):**
- F20/F17/F23/F28 — HH/HL structure gate: real, walk-forward-graduated, ~2× expectancy
  (NQ +0.16→+0.29, QQQ +0.26→+0.46, SPY +0.37→+0.56); robust to pivot params; edge invariant to
  the pivot tie-rule. Cost: ~50–60 min confirmation latency.
- 2026-07 fast-direction study (`orb_fast_direction.py`, STACK tooltip): **no fast price-derived
  read replaces structure** — VWAP-side, EMA-slope, 2-bar momentum, rolling regression slope all
  land at plain-ORB expectancy ("they show where price WAS, not where it's GOING"). `lb=3` keeps
  the full NQ/futures edge with pivots confirming 2 bars sooner (adopted: futures 3 / equity 5).
- OR-mid bias (2026-07): a **0-lag directional read at OR close**, additive on top of the trend
  gate (NQ +0.169→+0.290, SPY +0.351→+0.563), the dropped counter-bias trades are the losers,
  survives 3× slip. Adopted. This is the fastest validated direction signal in the system.
- F61 dir-sequence: real graduate on touch fills; implied by close-confirm. Adopted.
- Arm-timing (2026-07): delay-0 + chase-1.0 replaced the F38/F39 skip-first-hour — entries now
  arm **at** OR close, a ~60-minute latency win already banked (small per-trade edge traded away
  knowingly).
- F19 clean-vs-messy day, F16 VWAP-extension: quality conditioners, not direction speed.

**Tested and DEAD — do not revisit for speed (the graveyard is the moat):**
- F1 MTF confirmation (hurts monotonically), F12 VWAP-side (96 % already right-side), F13 honest
  strong-body lead (the F12 version was a lookahead artifact), F35 structure projection engine
  (coin-flip; "next swing ≈ last swing" beats extrapolation), F36/F49 kernel bands, F37 RSI/AC,
  F40 ADX/squeeze, F42 AMT value area, F43 liquidity confluence, F44 seasonality, F54 daily ML,
  F62 pre-trade ML (OOS AUC 0.48 — the ML layer correctly refuses to deploy), F32 1-minute chart,
  F31c confirmation entries, F18 fading false breaks.
- **F63 order-flow prediction**: minute-level trade delta/z-CD IC ≈ 0-to-negative vs forward
  returns at 1–30 m; 1 s deep-feature IC also negative. Order flow is contemporaneous, not
  predictive, on this data. (Caveat logged: sub-second event-time OFI with execution-aware
  persistence on *live* data was not fully tested.)
- F46 convergence: after structure + time + OB + VWAP-cap, the OHLCV feature space is exhausted —
  new speed must come from new *data* or new *decision policy*, not more indicators.

**Weak-but-real leads (open):**
- F48 CVD proxy: small (+0.03..+0.07R) but *consistently additive* — the only orthogonal
  life sign; its verdict: real tick/bid-ask data is the single most promising new-edge direction.
- F13 against-gap tilt (equities): confidence/sizing signal, thin sample.
- The Phase-4 detector suite was actually built and run (`orb_dir_state.py`: sign/state-machine/
  persistence/Kaufman-ER; `orb_dirstate2.py`: ε-persistence, HH/LL ratios, Theil–Sen, CUSUM,
  Kalman velocity, OLS-t, Mann–Kendall, z-regime; `orb_efficiency.py`; `orb_lead_lag.py`) — but
  **their verdicts were never written into RESEARCH_NOTES** and none appears as an adopted input,
  which per the propagation rule means none graduated. Gap: the results aren't archived.

## 3. What to change to know direction faster — ranked

### Tier 1 — Engineering latency (free edge, do first)
1. **Event-driven scanning instead of 60 s polling.** The bot scan loop free-runs every 60 s over
   5 m bars; worst case a confirmed break is surfaced ~60 s + provider-lag late. Align the scan to
   bar boundaries (fire at :00/:05… +2 s) and treat the **Pine AUTO webhook as the primary live
   trigger** (it fires at bar close with zero polling delay — the endpoint, auth, and dedup are
   already in place after this review). The scanner then confirms rather than discovers.
2. **Feed priority for freshness.** Yahoo 5 m bars lag several minutes at times; Alpaca IEX is
   near-real-time for equities, Databento Live (already integrated, self-disabling) is real-time
   for futures. Setting `PROVIDER_ORDER` so the freshest entitled feed is first is a pure config
   change; the new stale-gate (15 min) will otherwise correctly block late feeds but can't create
   fresh ones.
3. **Compute-time is already handled** — this review cut `compute_state` 26–33 % (bit-identical),
   so per-scan latency is fetch-dominated, not compute-dominated.

### Tier 2 — Free structural speed inside the validated engine
4. **Switch the pivot tie-rule to `tv`** (tie allowed on the left). F28 proved the edge is
   invariant to the tie rule; the `tv` rule confirms equal-high/low plateaus at their *first* bar
   — pivots (and therefore `st_state`) confirm earlier on plateau structure at zero edge cost.
   One-line change in `H.P(pivot_tie="tv")` + Pine already uses `ta.pivothigh` (the tv rule), so
   this also *tightens Python↔Pine agreement*.
5. **Finish the `struct2` / `struct3rlx` sweep.** `orb_fast_direction.py` already defines both:
   lb=2 pivots (another 2 bars sooner) and "relaxed structure" (block only a *confirmed-opposite*
   trend instead of requiring a confirmed-aligned one — fires earliest while still refusing to
   fight the tape). If `struct3rlx` clears the standard gauntlet on QQQ (the instrument that
   rejected lb=3), equities gain 10–25 min of confirmation latency. The harness supports it today
   (`st_state != 2` for longs); it needs the gauntlet run + archived verdict, nothing new built.

### Tier 3 — The big one: turn latency into a **sizing ladder** (policy change, strongest evidence)
6. **Trade a starter tranche on the fast signal; add on structure confirmation.** The system's own
   numbers make the case: plain ORB + OR-mid bias + dir-seq (all available at/near the break,
   0–15 min after OR close) **passes the full gauntlet standalone** (F62: NQ +0.158, QQQ +0.264
   9/9 yrs, SPY +0.270). Structure confirmation, arriving ~30–60 min later, roughly doubles
   per-trade expectancy but does not change the sign of the early cohort. So instead of the
   binary "wait for structure":
   - at the confirmed break with OR-mid alignment → enter **~0.4–0.5× size** (this is exactly the
     existing grade-B bucket — change its meaning from "skip/0.4× curiosity" to "early tranche");
   - when `st_state` confirms aligned (grade upgrades to A/A+) → **add to full size** (and only
     then count the full risk budget);
   - if structure confirms *opposite*, exit the tranche (early-failure semantics).
   This makes the system *act* on direction 30–60 minutes sooner without betting the validated
   edge on an unvalidated fast read. It must still be gauntlet-run as a policy (entry-price of
   the add, combined R accounting), but both legs are individually validated already — the
   research is a policy backtest, not a new-signal hunt. The grade plumbing (`GRADE_MULT`,
   `struct_aligned`, dashboard grades) already exists end-to-end.
7. **Expose the OR-mid bias + dir-seq as the bot's "current direction" field** (the STACK
   dashboard's `DIR·fast` row has no equivalent in the API). Add `direction_now` (OR-side +
   VWAP-side + slope votes) to `/api/signals` so the UI/user sees the 0-lag read explicitly,
   labeled *awareness*, with `st_state` labeled *confirmed*. Pure surfacing — no trading change.

### Tier 4 — Know you're **wrong** faster (order flow's honest role)
8. Per F63/F62, order flow does not *predict* entries here — but the Evidence-spec
   `DirectionStateMachine` (`orderflow/score.py`, built and tested) supports **EARLY_FAILURE**: a
   hard opposite flip in QI/ATI while in a trade exits before the structural stop. Wiring the
   Databento live (or Webull) feed into that early-exit path shortens time-to-exit on wrong
   direction — which is "knowing direction faster" where it pays (risk), without claiming
   predictive power the data has refuted. F48's CVD proxy can serve as the interim input.

### Tier 5 — Research hygiene + the one new-data bet
9. **Archive the detector verdicts.** Re-run `orb_dir_state.py`, `orb_dirstate2.py`,
   `orb_efficiency.py`, `orb_lead_lag.py`, `orb_fast_direction.py` (needs the local data drive —
   not possible in this review environment) and write their tables into RESEARCH_NOTES like every
   other F-number. Right now the strongest anti-curve-fit asset — the graveyard — has undocumented
   plots. If ER/CUSUM/Kalman produced any additive quality (not direction) lift, it would appear
   there.
10. **If new edge is ever hunted again, it's tick-level order-book event data** (F48's explicit
    verdict), tested as *execution-time confirmation/exit*, not entry prediction (F63).

### Anti-recommendations (all previously tested dead — resist re-adding for "speed")
Shorter EMAs / faster oscillators / kernel bands (F36/F37/F49), MTF agreement (F1), dropping to
1 m bars (F32), predicting swing targets (F35), ML direction (F54/F62), tighter chase caps
(F57/F61 — the "late" confirmed entries are the winners), minute-level order-flow entry (F63).

## 4. Suggested execution order

| Step | Effort | Risk to edge | Latency gained |
|---|---|---|---|
| 1. Bar-aligned scan + webhook-primary | small | none | up to ~1–2 min per signal |
| 2. `pivot_tie="tv"` | one line + reconcile | none (F28) | bars, on plateaus |
| 3. `struct3rlx`/lb-2 gauntlet run | rerun existing script | none until adopted | 10–25 min if it passes |
| 4. Two-tranche sizing ladder (B=early, add on A) | policy backtest + small bot/Pine change | bounded (both legs individually validated) | **30–60 min of acting time** |
| 5. Order-flow EARLY_FAILURE wiring | medium (live feed) | none to entries | faster wrong-exit |
| 6. Archive detector verdicts | rerun + notes | none | keeps the graveyard honest |
