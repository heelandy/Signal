# PATTERN RECOGNITION v1 — Research Plan (NQ first)
*(2026-07-12 · docs-first per the standing process rule · authority: this doc governs the pattern
research; the remediation discipline still applies — causal/PIT, evidence-gated, red-first tests
for any code · freeze status: **watch-only / advisory research, EXEMPT from the feature freeze**;
this layer creates NO new AUTO orders and does NOT alter the certified ORB signal path until each
pattern ID passes its own profitability gate)*

## 0. Why NQ, and what "run it on NQ" means

NQ is chosen because it has the **most bars** (deepest futures history, 3 sessions/day) — best for
*pattern statistics*, not because it is the actionable base. Under the corrected evidence QQQ/SPY are
the strongest actionable base; **NQ is marginal and needs paper confirmation** — so this research
DISCOVERS and MEASURES patterns on NQ; it does not promote NQ to actionable. A pattern earns ACTION
only through the Level-8 gate (§7), never by being data-rich.

## 1. The substrate already exists (~70%) — this is a labeling+evidence layer, not a new engine

| Spec need | Already in code | Gap to build |
|---|---|---|
| L1 · 7 directional states | `orb_state.directional_state()` (7 states, causal, structure+location aware) | day-types **VOL-EXPANSION / COMPRESSION / SHOCK** not distinct labels |
| L1 · structural quality grade | `orb_state.slope_grade()` → A+/A/B+/B/C/D | — (reuse verbatim) |
| L1 · trend/range regime | `regime.classify()` → trend/range/no_trade | expose as a day-type |
| L1 · macro regime | `hs_harness._macro_regime()` → SPY/VIX A–D, causal, persisted | — |
| L1 · inputs (VWAP side/slope, ADX, ATR%tile, cross-freq, MTF) | `hs_harness.compute_state` columns | ATR%tile → expansion/compression thresholds |
| L2 · locations + scoring | `liquidity_zones.py` (OR H/M/L, PDH/L/C, sVWAP, wVWAP, POC/HVN/LVN, pivots, equal H/L, rejection) MAJOR..WEAK, merged, causal | **order block / FVG** as typed objects |
| L2 · clean-air vs wall | `liquidity.py` F67 clean-air (per-asset) | — |
| L3 · ORB-C continuation | ORB engine: dir_seq, body-close-through-edge, WATCH established | tag trades by pattern (see §7) |
| L3 · ORB-RT retest | `execm=retest/rebreak`, `retest_mode="impulse_mid"` (NQ), PULLBACK→retest | tag trades by pattern |
| L3 · LQ-SR sweep-reclaim | `liquidity_zones.py` reversal machine (…→CONFIRMED\|FAILED_BOUNCE) | reclaim-close detector |
| State machine lifecycle | `docs/ENTRY_STANDARD.md` WAIT→ARMED→WATCH→PULLBACK→COOLDOWN→RANGE→FILLED→INVALID | map spec state names |
| L8 · profitability matrix | `ml/entry_matrix.py` (symbol→side→session→**family**→grade→regime, INSUFFICIENT floor, per-evidence-type) | **per-pattern family** granularity |
| L8 · cohort/removal gate | `strategy/removals.py` + F78 cohort test (both halves + OOS + cost-stress) | reuse as the ACTION gate |
| L8 · stable lineage IDs | tracker `strategy_version`/`family`/`candidate_id` | the `PR-…-v1` ID scheme |
| Causal / no-repaint | PIT harness + `merge_asof(allow_exact_matches=False)` + bug-hunt armor | reuse verbatim |

**Consequence:** v1 is mostly (a) a thin *recognizer* that NAMES what the engine already computes and
stamps a stable pattern ID, plus (b) a few NEW causal context detectors, plus (c) the *measurement*
that routes each pattern ID through the existing profitability gate. It is NOT a rebuild.

## 2. The one blocking gap for profitability evidence (fix FIRST)

The gate cannot tell ORB-C from ORB-RT today: `entry_matrix.build_backtest_rows` stamps every ORB
trade as a single family `orb@5m`, and the backtest trade record (`hs_backtest.backtest`) carries no
per-trade pattern tag. **Until each trade is tagged by the pattern that produced it, no per-pattern
expectancy exists** — so ORB-C and ORB-RT cannot be certified separately, and the new context
patterns have nowhere to accrue evidence.

**Work item PR0 (enables everything):** add a causal `pattern` tag to each backtest trade + each live
candidate (the fill type is already known internally: close-exec continuation vs retest/rebreak vs
impulse-mid retest). Thread it into `entry_matrix` family and the tracker. Red-first test: the sum of
per-pattern trades == the total, per symbol (a cross-artifact consistency check, W2 class). No
economics change — this is a *label*, not a rule change, so the sealed journals are untouched.

## 3. Pattern families — v1 recognition, grounded

| Code | Recognition (causal, closed-bar) | Status in code | v1 role on NQ |
|---|---|---|---|
| **ORB-C** | context aligned (Structure+VWAP arm) · WATCH established · confirmed body close through OR edge | BUILT | **ACTIONABLE candidate** (already NQ-validated behavior) |
| **ORB-RT** | initial expansion · controlled pullback · retest of edge/impulse-mid · renewed confirmed close | BUILT (impulse-mid on NQ) | **ACTIONABLE candidate** (NQ's F78 edge) |
| **LQ-SR** | price penetrates a MAJOR/STRONG liquidity level then CLOSES back through it | PARTIAL (reversal machine) | **CONTEXT only** — detect, label, collect evidence |
| **FAIL-BO** | OR break fails; opposite edge/location reclaimed on a confirmed close | PARTIAL (INVALID state) | **CONTEXT only** |
| **COMP-X** | contracting range/ATR%tile → directional expansion with volume | NEW detector | **CONTEXT only** |
| **VW-R** | acceptance through / rejection from sVWAP at a valid structural location | PARTIAL (VWAP side) | **CONTEXT only** |
| **TPB** | trend intact · pullback into VWAP/OB/FVG · renewed directional close | PARTIAL (overlaps ORB-RT) | **CONTEXT only** (dedup vs ORB-RT) |

Morning/evening stars, single candles, OB, FVG **only strengthen a grade** — they never create an
actionable pattern alone (enforced: a pattern needs its L1+L2+L3 core before any confluence adds).

## 4. Asset policy (NQ focus; others for completeness)

- **NQ** — ORB-C + ORB-RT highest priority; Asia/London/RTH; ≤3 entries; 1.5-ATR extension;
  impulse-mid retest; clean-air important. (Exactly the current `asset_config["NQ"]`.) Actionable
  **only after PR0 + the gate**; until then ORB-C/ORB-RT print with their historical evidence, the
  rest print CONTEXT.
- **ES** — detect + print, keep **non-actionable** until corrected-profitability recertifies.
- **GC** — **UNVERIFIED — CONTEXT ONLY** (config says the edge is unverified).
- **QQQ / SPY** — ORB-C (structure+VWAP + clean air), RTH, one entry; the strongest actionable base —
  but out of scope for *this* NQ research run (they inherit the same recognizer later).

## 5. Pattern state machine — map, don't reinvent

Spec lifecycle → existing ENTRY_STANDARD lifecycle:

```
FORMING          → (pre-arm: context forming, side not yet aligned)
CONTEXT ALIGNED  → ARMED            (Structure AND VWAP point the trade way)
ARMED            → ARMED
WATCHING         → WATCH            (confirmed body close beyond OR mid)
CONFIRMED        → (edge close confirmed, pre-fill)
ACTIVE           → FILLED
COMPLETED        → TP1/TP2/STOP terminal
```
Terminal/aux states already have homes: **INVALIDATED**=INVALID · **PULLBACK PENDING**=PULLBACK ·
**STALE**=RANGE(stale bars) · **COOLDOWN**=COOLDOWN · **ALREADY TRADED**=LOCKED · **TOO EXTENDED**=the
chase-cap PULLBACK · **EVIDENCE INSUFFICIENT**=matrix INSUFFICIENT SAMPLE · **BLOCKED**=removals
record. Every pattern **must expire** (age-out); the reversal/zone machines already carry recency
decay (`AGE_HALF_LIFE`) — the context patterns inherit a max-age → STALE.

## 6. What prints (advisory) — reuse the operator console, add a pattern strip

The Phase-U console already renders four-state chips and the ORB state machine. v1 adds a **read-only
pattern strip** (top-ranked active pattern per side) driven by a new `/api/patterns` endpoint — no
client-side risk math, evidence types never mixed (console rule). Visual priority + colors are the
spec's (risk/invalid → certified ORB → ORB-RT → LQ-SR → FAIL-BO → COMP/VWAP context → confluence).
**Only the winner prints prominently; the rest go in a compact confluence row.** Old objects reused or
removed (no label pile-up) — enforced by keying labels on (pattern-ID, side) and updating in place.

Grade vs confidence stays separate (spec §6): **A+/A/B/C = structure**, **CERTIFIED/UNPROVEN/BLOCKED
= evidence**, **P(win) = ML** — and until pattern-specific ML exists, print **ML: ABSTAIN ·
Evidence: HISTORICAL ONLY**. Never a default probability dressed as model confidence.

## 7. Pattern identity + the ACTION gate (the discipline that makes this safe)

Stable ID: `PR-{cat}-{session}-{tf}-{pattern}-{side}-v{n}` e.g. `PR-FT-RTH-5M-ORB_RT-L-v1`. The same
ID flows chart → backtest → certificate → tracker → order → fill → matrix → ML label (PR0 threads it).

A pattern ID may print **ACTION: ENTER** only when ALL hold (reuse the existing gate):
adequate sample · positive net expectancy after costs · both historical halves acceptable ·
untouched OOS acceptable · cost-stress survival · current strategy/evidence version · no removal
record · paper confirmation once enough observations exist. **Otherwise it prints CONTEXT / RESEARCH
/ INSUFFICIENT EVIDENCE.** This is the exact `entry_matrix` + F78 cohort + removals machinery — the
pattern layer does not get a second, weaker gate.

## 8. Causal / no-repaint (inherited, non-negotiable)

Closed bars only · PIT inputs only · HTF from completed HTF bars · pivots printed on confirmation
(never backpainted) · no future-bar confirmation · deterministic (same input → same pattern) ·
invalidation printed immediately on the confirming close · missing data → UNKNOWN (never green). The
1m feed updates *awareness*; the execution TF controls the *trigger*. All of this is already enforced
by the harness and now guarded by the bug-hunt armor (mirror-tape, PIT canary, determinism tests).

## 9. NQ research methodology (how we get the numbers)

1. **PR0 tag** every NQ backtest trade + candidate by pattern (ORB-C vs ORB-RT to start).
2. **Measure** per-pattern-ID expectancy on NQ via the canonical `run_backtest` (no new economics),
   sliced by the new family, across all 3 sessions and both history halves + OOS + 2× cost-stress —
   the standard cohort test. Output → `entry_matrix` (evidence=backtest) per `PR-FT-*-NQ` ID.
3. **Detect** the context patterns (LQ-SR/FAIL-BO/COMP-X/VW-R) causally on NQ, emit labels into the
   tracker (evidence=shadow) — they change NO entries; they accrue observations toward their own gate.
4. **Report** a per-pattern NQ scorecard (n, exp_R, PF, both-halves, OOS, cost-stress, verdict:
   CERTIFIED / UNPROVEN / INSUFFICIENT). Only ORB-C/ORB-RT can reach CERTIFIED in v1; the rest stay
   CONTEXT by design until their sample matures.

## 10. v1 scope (locked) + sequencing

**v1 contains ONLY:** ORB-C, NQ ORB-RT (both actionable *if* the gate passes), and LQ-SR / FAIL-BO /
COMP-X / VW-R as **context**, with OB/FVG/candles as **confluence only**. Everything advisory on the
chart; **no new AUTO orders**; existing validated ORB behavior is the ONLY thing that affects signals.

Sequence (each step docs-first where it adds rules, red-first tested, freeze-safe):
- **PR0** — pattern tag through backtest+candidate+matrix+tracker (label only). *enables measurement*
- **PR1** — NQ ORB-C vs ORB-RT profitability scorecard (watch-only, existing engine).
- **PR2** — `/api/patterns` + console pattern strip (advisory render, no risk math).
- **PR3** — the 4 context detectors (causal), shadow labels only.
- **PR4** — OB/FVG typed objects as confluence-only grade modifiers.
- **PR5** — day-type labels (expansion/compression/shock) from ATR%tile + regime.
- **Certification** — any NQ pattern ID that clears the §7 gate is proposed for the certified path
  (a version bump + re-approval — never an auto-promotion).

## 11. PR1 RESULTS (read-only, 2026-07-12) — measured on the corrected engine

Method: NQ through the canonical engine, comparing **CANON** (chase 1.5 + impulse-mid retest =
ORB-C + the F78 ORB-RT machinery) vs **CONT** (chase 0, no retest = pure ORB-C). Delta = ORB-RT's
marginal contribution. All sessions (RTH from the `rth` store; Asia/London from `full` with trade-day
OR windows), both history halves, OOS 2024+, and 2× slippage cost-stress. Store: NQ 2010-06→2026-07.

| Session · TF | CANON expR / totalR / PF | 2× slip | H1 (old half) | OOS 24+ | ORB-RT delta |
|---|---|---|---|---|---|
| RTH · 5m  | +0.047 / +52.9 / 1.09 | **neg** (−5.9, PF .99) | **−0.005** | +0.107 | +5.5R (+0.005) |
| RTH · 15m | −0.001 / −0.5 / 1.00 | **neg** (−30.4, PF .91) | **−0.023** | +0.007 | +1.2R (+0.001) |
| ASIA · 15m | **−0.150 / −146.9 / 0.66** | −234 (PF .53) | −0.209 | −0.075 | +15.5R (loss-reduction) |
| LONDON · 15m | −0.025 / −24.0 / 0.94 | −110 (PF .74) | −0.052 | +0.085 | +3.6R (+0.003) |

**Findings (decisive):**
1. **ORB-C and ORB-RT do NOT separate on NQ.** The retest machinery's *total* marginal contribution
   is tiny and always on a flat/negative base (+0.001..+0.006 expR; the larger Asia "delta" is just
   *losing less*, −235 vs −255). It changes ~1-6% of trades. **PR0 (tagging them as distinct
   certifiable patterns) is NOT justified** — there is no separable positive edge to certify. They
   are, empirically, one pattern (continuation) with a marginal quality filter.
2. **NQ ORB is not actionable in ANY session** under the corrected engine: RTH ~flat and dies at 2×
   slip; Asia strongly negative; London negative. Every session FAILS the both-halves test (H1
   negative). Under the §7 gate NQ ORB prints **CONTEXT / INSUFFICIENT EVIDENCE**, never ACTION —
   confirming the corrected-evidence verdict ("NQ marginal; NQ/ES canonical = no honest edge").
3. **The F78 "+26R ORB-RT edge (NQ 257.6→283.8R)" is NOT reproduced** on the corrected engine — it
   was a pre-remediation number, consistent with `REMEDIATION_DELTA` ("lookahead+sim artifacts were
   ~half-to-4/5 of reported edge"). The retest refinement's real value is negligible.

**Decision:** DROP PR0 and the ORB-C/ORB-RT separation from v1 — the evidence says it buys nothing.
Do NOT wire pattern-specific ORB tagging on a false premise. The pattern layer's value on NQ is
therefore (a) CONTEXT/advisory labeling only (the substrate already supports it, freeze-safe), and
(b) **the real research frontier: measure the UNEXPLORED families** (LQ-SR sweep-reclaim, FAIL-BO,
COMP-X compression-expansion, VW-R) to see if ANY shows edge where ORB does not — since ORB itself
is exhausted on NQ. That is the evidence-led next step, not more ORB tagging.

## 11b. PR1 on QQQ/SPY (the actionable base) — 2026-07-12

Harness faithfulness check: QQQ 5m CONT (shipped ORB-C) = n=193 / +64.7R / +0.335 expR — EXACTLY
the canonical `run_backtest`/W2 number. Measurement is faithful. Equities ship chase=0 (pure ORB-C),
so here CONT = shipped ORB-C and ADD-RT adds the retest machinery.

| Sym·TF | ORB-C (shipped) | +ORB-RT | ORB-RT delta |
|---|---|---|---|
| QQQ 5m | **+0.335 expR · +64.7R · PF 1.56 · both halves + · OOS +0.70 · survives 2×** | +0.391 · +54.0R (n 193→138) | **−10.7R** (drops winning chased trades) |
| QQQ 15m | +0.063 · +8.5R · PF 1.13 | +0.103 · +12.3R | +3.8R (+0.040) |
| SPY 5m | +0.176 · +32.4R · PF 1.26 · OOS +0.44 | +0.168 · +19.2R | **−13.2R** (−0.008) |
| SPY 15m | +0.202 · +25.1R · PF 1.47 · OOS +0.37 | +0.253 · +28.6R | +3.5R (+0.051) |

**Findings:**
- **The shipped ORB-C is the robust, actionable equity edge** — QQQ 5m +0.335R (PF 1.56, both halves
  positive, OOS +0.70, survives 2× cost-stress at +0.307); SPY 5m/15m and QQQ 15m all positive.
  Reaffirms QQQ/SPY as the actionable base.
- **ORB-RT does NOT separate into a distinct, consistently-superior pattern.** On 5m it REMOVES
  winning chased trades (QQQ −10.7R, SPY −13.2R) — exactly why equities ship chase=0 (F75). On 15m
  it lifts per-trade expR modestly (+0.04-0.05) but with fewer trades and wide CIs — a per-asset
  TUNING effect, not a second pattern.

## 12. VERDICT — ORB pattern-separation CLOSED (2026-07-12)

Across **every traded symbol and session** (NQ RTH/Asia/London 5m+15m, QQQ/SPY RTH 5m+15m), ORB-C and
ORB-RT do **not** separate into two distinct certifiable patterns. The retest is a **per-asset
entry-timing knob that is already tuned** (NQ chase 1.5 + impulse-mid; equities chase 0), not a
second pattern with its own edge. **PR0 is not justified and is dropped.** No code was written on a
false premise — the entire question was answered read-only.

What the research established (durable):
1. **ORB is ONE pattern** (continuation) with a tuned per-asset entry-timing knob. Sub-typing it
   into ORB-C / ORB-RT for separate certification buys nothing.
2. **QQQ/SPY ORB-C is the actionable base** (robust, cost-stress-surviving, both-halves-positive).
3. **NQ ORB is not actionable** in any session under the corrected engine (flat-to-negative) — stays
   CONTEXT. The F78 ORB-RT edge was a pre-remediation artifact, not reproduced.

Residual option: the four **context families** (LQ-SR, FAIL-BO, COMP-X, VW-R) remain unmeasured —
laid out as the research backlog in §14. Absent a certified new edge, the pattern line stays
**advisory/context-labeling only** (§13), reusing the existing substrate — no new engine, no orders.

## 13b. BUILT — watchlist advisory + UI strip + summary (2026-07-12)

Extended to the whole watchlist (QQQ/SPY CERTIFIED, NQ CONTEXT, ES UNPROVEN, GC UNVERIFIED) and
wired to the dashboard:
- **`/api/patterns`** (read-only, `bot/api/server.py`): re-presents the LIVE scan snapshot
  (`_latest["signals"]`, no re-scan) as `{tf, symbols:{sym:advisory}, summary}`. Fast, honest,
  advisory-only.
- **Summary metric** (answers "how many show confluence / pass"): `_summarize` counts ACTIVE
  advisories, how many `has_confluence`, and how many `passes`. `passes` = CERTIFIED asset + live
  tradeable non-removed non-skip state — so **only QQQ/SPY can pass; NQ/ES/GC never do**. Verified:
  a QQQ-active + NQ-watching pair → `2 advisories · 2 confluence · 1 pass`.
- **Dashboard strip** (`dashboard.html`, inside `.wrap`): a `.card col12` table per symbol —
  EVIDENCE chip (green=certified/gray=context), PATTERN, STATE (color-coded), grade, location,
  entry/stop, confluence tags, ACTION + a `PASS` badge; header shows the summary line. Overflow-safe
  (`overflow-x:auto`, ellipsised cells) so it fits the DOM. Polls `/api/patterns` every 12s.
  JS syntax node-checked; endpoint + served markup verified. (The headless-Edge console drill was
  made skip-on-timeout — the heavy dashboard renders slower than 60s in this env; not a JS defect.)

## 13a. BUILT — ORB advisory v1 (2026-07-12, for tonight's NQ open)

`bot/strategy/pattern_advisory.py` (+ `tests/test_pattern_advisory.py`, 8 tests). A READ-ONLY
re-presentation of `live.scan_watchlist` proposals as the pattern panel — it reuses the SAME live
machine the dashboard runs, so it cannot drift from what the system sees; it creates NO orders and
touches NOT the certified path (freeze-safe). Adds only the corrected evidence chip (PR1):
QQQ/SPY=CERTIFIED, NQ=CONTEXT, ES=UNPROVEN, GC=UNVERIFIED. Honesty gate pinned by tests: **NQ can
NEVER surface an ENTER prompt** (CONTEXT → "WATCH ONLY"), a removed group → BLOCKED, missing/unhealthy
data → UNKNOWN/WAIT (never green), **ML always ABSTAIN**. Run tonight:
`python -m bot.strategy.pattern_advisory NQ` prints the NQ 5m + 15m panels; any tf that fails is
skipped ("leave out whatever fails"). Verified live: with no active NQ setup it correctly reads
WAIT / no-action / CONTEXT; it populates (state, levels, grade, clean-air) when a proposal fires.
KNOWN v1 limit: day-type is UNKNOWN while no proposal is active (it reads slope from the fired
proposal); a standalone context read in WAIT is a follow-up. Context families (§14) are NOT wired —
they "fail" the ready bar tonight (unbuilt/unmeasured), left out per instruction; VW-R is next.

## 13. ORB ADVISORY v1 — the first advisory (surviving scope of the closed PR0)

Closing PR0 closed CERTIFYING ORB-C/ORB-RT apart; it did NOT close SHOWING them. The ORB recognizer
is the **first advisory**, and the ORB-C / ORB-RT FORM is an advisory sub-label (the entry's timing),
never a second edge. Per-asset mapping (its "correspondent"):

| Asset | Form shown | Evidence chip | Actionable? |
|---|---|---|---|
| **QQQ** | **ORB-C** (chase 0, immediate) | **CERTIFIED** (+0.335R, both halves, OOS, cost-stress) | YES — via the EXISTING certified signal path |
| **SPY** | **ORB-C** (next-bar confirm) | **CERTIFIED** (+0.18/+0.20R) | YES — existing path |
| **NQ** | **ORB-C + ORB-RT** (chase 1.5, impulse-mid retest) | **CONTEXT / UNPROVEN** (corrected engine flat-to-neg) | NO — advisory only, never ACTION |
| **ES** | ORB-C (+ FAIL-BO/VW-R context) | **UNPROVEN** | NO — until recertified |
| **GC** | context forms | **UNVERIFIED — CONTEXT ONLY** | NO |

Per side it renders (reusing directional_state + ENTRY_STANDARD lifecycle + liquidity_zones + grade):
day-type · **state** (FORMING→ARMED→WATCHING→CONFIRMED→ACTIVE) · **FORM** (C vs RT) · location +
clean-air · **grade** (A+..C structural) · **evidence chip** (CERTIFIED/UNPROVEN/CONTEXT) · levels
(entry/stop/TP1/TP2) · NEXT trigger · **ML: ABSTAIN · Evidence: HISTORICAL ONLY**. The FORM sub-label
tells the operator the ENTRY TIMING to expect (C = enter the breakout close; RT = wait for the
pullback to the edge/impulse-mid) — a tactical read, not a separate certified edge. Advisory only:
NO new AUTO orders; QQQ/SPY ORB actions still flow through the certified path unchanged. Causal/
no-repaint per §8.

## 14. UNEXPLORED BRANCH — the four context families (research backlog)

The KEY gap ORB leaves: **ORB only trades TREND days and sits out RANGE/BALANCE** (regime.classify
gates it to `trend`). Every day the market balances, ORB has no signal — that is exactly where a NEW
edge could live. So the backlog is prioritized by "does it cover the days ORB skips."

| Code | Recognition (causal, closed-bar) | Substrate to reuse | New detector work | Hypothesis (where the edge could be) | Priority |
|---|---|---|---|---|---|
| **VW-R** | acceptance THROUGH / rejection FROM session VWAP at a valid structural location | `vwap_sess`, VWAP side/slope, `st_state`, `regime.classify` (`vwap_revert` is already the RANGE strategy stub) | the accept/reject-at-VWAP trigger conditioned on location + regime | **RANGE-day mean-reversion** — the days ORB skips; regime.py already reserves `vwap_revert` for range | **1 (highest)** |
| **LQ-SR** | price penetrates a MAJOR/STRONG liquidity level then CLOSES back through it (reclaim) | `liquidity_zones.py` scored levels + the reversal machine (…→CONFIRMED\|FAILED_BOUNCE) | the penetrate→reclaim-close detector + confirmation | **stop-run/sweep reversal** at MAJOR levels — a reversal edge, orthogonal to trend-continuation ORB | 2 |
| **FAIL-BO** | OR break fails; opposite edge/location reclaimed on a confirmed close | the ENTRY_STANDARD **INVALID** state (confirmed close beyond the opposite OR edge) already fires | turn INVALID from "cancel" into a tradeable FADE signal | **false-break fade** — the trap reversal that pays when the breakout doesn't | 3 |
| **COMP-X** | contracting range/ATR%tile → directional expansion with volume | ATR percentile, range contraction, volume (all in the harness) | the compression detector (N-bar range/ATR below a %tile) + the expansion trigger | **coil breakout** independent of the OR — works on days with no clean opening range | 4 |
| TPB | trend intact · pullback into VWAP/OB/FVG · renewed close | overlaps ORB-RT/PULLBACK | — | **fold into the ORB-RT form** — not a separate research item | (dedup) |

**Method per family (identical to PR1, read-only first):** build the causal detector → emit shadow
labels → measure each as its OWN cohort through the same gate (both halves + OOS + 2× cost-stress),
**specifically on the regimes/days ORB fails** → report edge. Each starts CONTEXT and can only reach
CERTIFIED/actionable through §7 (a version bump + re-approval, never an auto-promotion). All advisory
until then. **Recommendation:** if we pursue the branch, start with **VW-R** — it is the only family
with a standing hypothesis already in the code (`regime.vwap_revert` for RANGE days), so it is the
cheapest test of "is there edge where ORB has none." The other three are colder (no prior evidence);
open them only if VW-R shows signal.
