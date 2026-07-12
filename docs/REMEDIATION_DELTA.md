# Remediation delta — how much each fix class moved the numbers

*(started 2026-07-11 with Phase 1; Phase R extends this file per fix class. Method: the canonical
`orb_candidates.load_state → run_backtest` path, identical config, run immediately before and
after each fix on the same store.)*

## Phase 1 — same-day daily-data lookahead removed (2026-07-11)

Fix: `engine/hs_backtest._externals` + live `families.prepare` now join daily VIX / ES-macro /
HTF values from the most recent session **strictly before** the bar's date
(`merge_asof(allow_exact_matches=False)`). Before: every intraday bar saw its own day's completed
daily values — a 09:35 signal read that day's 16:00 close. Tests: `test_pit_no_lookahead.py`
(T1.1–T1.3), red-first proven, full suite 187 green.

| Run | n before → after | exp/R before → after | PF before → after | total R before → after |
|---|---|---|---|---|
| QQQ @5m | 287 → 193 | +0.552 → **+0.469** | 1.875 → 1.719 | +158.4 → +90.5 |
| SPY @5m | 269 → 184 | +0.442 → **+0.166** | 1.698 → 1.232 | +118.9 → +30.5 |
| NQ @5m | 1392 → 1121 | +0.208 → **+0.133** | 1.365 → 1.218 | +290.1 → +149.0 |
| ES @5m | 1226 → 983 | +0.088 → **−0.005** | 1.138 → **0.993** | +107.5 → **−4.7** |
| QQQ @15m | 194 → 136 | +0.325 → **+0.195** | 1.599 → 1.329 | +63.1 → +26.5 |
| SPY @15m | 179 → 124 | +0.378 → **+0.223** | 1.746 → 1.393 | +67.6 → +27.7 |

### Reading

- **The lookahead was carrying a large share of the reported edge** — total R roughly halves on
  every equity run, and **ES flips negative**. The audit's "existing reports cannot be accepted
  as point-in-time evidence" is now quantified, not just argued.
- Trade counts fall 20–33%: with lagged VIX/macro, the regime and context gates admit different
  days (both directions — some previously-blocked days now trade, more previously-traded days are
  blocked; the net is fewer).
- The equity hit is biggest (SPY −62% expectancy) because Layer-1 context is a **hard gate ON for
  equities** — exactly where same-day macro information had the most authority. Futures use
  context as a grade, so NQ/ES lose less proportionally from gating and more from HTF/regime
  tagging.
- ES was already flagged by the cost-stress report ("negative at 2× slip — no live sizing").
  PIT-corrected, it is negative at *base* costs. Phase E's matrix should treat ES as a removal
  candidate pending Phases 2–3.

### Caveats

- These AFTER numbers are **still not clean**: the Phase 2 simulator defects (EOD ordering,
  gap fills, ambiguity, short MFE/MAE) and Phase 3 economics (MNQ costs on NQ/ES/GC) remain in
  both columns. Expect further movement — historically most such fixes reduce reported edge.
- The store itself is the stale pre-Phase-4 store (QQQ/SPY/ES end 2026-06-08). The delta is
  valid because both columns used the identical store; the absolute levels are not final.
- Everything here stays `pre-remediation` lineage until Phase R regenerates on all fixes + fresh
  QA-hard data.

## Phase 2 — simulator execution semantics corrected (2026-07-11)

Fix (all in `engine/hs_backtest.py` + `hs_validate.py`, policy in the `backtest()` docstring):
day trades flatten on the entry day's **last bar** (before: the eod_min check never fired on 5m —
every carried trade exited on the *next morning's* bar, with overnight gaps filling yesterday's
stops/targets); stops fill **gap-aware** (worse of open/stop); same-bar stop+target → **stop wins
uniformly** (was TP2-first after TP1) with an `ambiguous_bars` counter; **side-aware MFE/MAE**
(short excursions were measured at the wrong extremes); touch-mode entry bars evaluate their
remainder; touch-mode state gates are prior-bar (S7); trail moves the stop for the next bar;
`maxdd` starts at 0; validation CI switched to a **day-block bootstrap**. Tests:
`test_simulator_semantics.py` (10, red-first), suite 197 green. BEFORE column = Phase 1's AFTER.

| Run | n | exp/R before → after | PF before → after | total R before → after |
|---|---|---|---|---|
| QQQ @5m | 193 | +0.469 → **+0.335** | 1.719 → 1.564 | +90.5 → +64.7 |
| SPY @5m | 184 | +0.166 → +0.176 | 1.232 → 1.264 | +30.5 → +32.4 |
| NQ @5m | 1121 | +0.133 → **+0.039** | 1.218 → 1.075 | +149.0 → +43.5 |
| ES @5m | 983 | −0.005 → **−0.096** | 0.993 → 0.837 | −4.7 → −94.4 |
| QQQ @15m | 136 | +0.195 → **+0.063** | 1.329 → 1.134 | +26.5 → +8.5 |
| SPY @15m | 124 | +0.223 → +0.202 | 1.393 → 1.475 | +27.7 → +25.1 |

### Reading

- **The overnight leak was the dominant flattery for futures**: NQ keeps only ~30% of its
  post-Phase-1 expectancy (+0.133 → +0.039) — overnight gap "wins" on yesterday's targets were
  never tradeable by a day strategy. ES sinks to −0.096R.
- Trade counts are identical per run — Phase 2 changed *exit* semantics only.
- **SPY slightly improves both times exits got honest** — its overnight carries were net
  negative, so flattening at the entry day's close helps. A useful tell that the fixes are
  semantics-neutral, not a systematic penalty.
- **Cumulative from the pre-remediation baseline** (Phases 1+2): QQQ@5m +0.552 → +0.335 · SPY@5m
  +0.442 → +0.176 · NQ@5m +0.208 → +0.039 · ES@5m +0.088 → **−0.096** · QQQ@15m +0.325 → +0.063 ·
  SPY@15m +0.378 → +0.202. Roughly half to four-fifths of the reported edge was simulation
  artifact, depending on the run.
- Phase 3 (true NQ/ES/GC economics) moves these again — NQ/ES commissions are currently priced at
  the MNQ point value, which overstates cost-in-R ~10×, so futures may claw some back.

## Phase 3 — contract registry + roll-adjusted analytics (2026-07-11)

Fix: `engine/hs_contracts.py` is the single economics source (NQ $20/pt · ES $50/pt · GC $100/pt,
0.10 tick · micros · equities), consumed by `backtest()`, `hs_validate` (per-symbol tick in the
slip stress), and the composite/census gauntlet studies (their local MNQ constants removed);
`SLIP_MULT` replaces the `SLIP_TICKS` monkeypatch hook across 17 research scripts. Indicators
(ATR/EMA/DMI/momentum) now compute on the **back-adjusted** series and rescale to raw contract
units — roll jumps no longer print as range or momentum; levels/pivots/VWAP stay raw. Option
economics registered (sealed journals adopt them at their next reset, not mid-study). Tests:
`test_contract_economics.py` (4, red-first), suite 201 green. BEFORE column = Phase 2's AFTER.

| Run | n | exp/R before → after | PF before → after | total R |
|---|---|---|---|---|
| QQQ @5m | 193 | +0.335 → +0.335 | 1.564 → 1.564 | unchanged |
| SPY @5m | 184 | +0.176 → +0.176 | 1.264 → 1.264 | unchanged |
| NQ @5m | 1121 → 1120 | +0.039 → **+0.047** | 1.075 → 1.092 | +43.5 → +52.7 |
| ES @5m | 983 | −0.096 → **−0.068** | 0.837 → 0.881 | −94.4 → −66.8 |
| QQQ @15m | 136 | +0.063 → +0.063 | 1.134 → 1.134 | unchanged |
| SPY @15m | 124 | +0.202 → +0.202 | 1.475 → 1.475 | unchanged |

### Reading

- **Equities byte-identical** — the correct invariance check: registry equity economics equal the
  old carve-out, and `adj_factor == 1` leaves their indicators untouched.
- Futures claw back modestly as predicted (commission-in-R was overstated ~10× for NQ, ~25× for
  ES). One NQ trade shifted (1121 → 1120): roll-adjusted indicators changed a marginal signal.
- **ES stays negative** (−0.068R, PF 0.881) even at correct economics — the honest chain now
  reads: ES's apparent edge was lookahead + overnight-leak artifact. Phase E's matrix should
  treat canonical ES as a removal candidate once Phase R confirms on fresh data.
- Cumulative (Phases 1+2+3 vs pre-remediation): QQQ@5m +0.552 → +0.335 · SPY@5m +0.442 → +0.176 ·
  NQ@5m +0.208 → +0.047 · ES@5m +0.088 → **−0.068** · QQQ@15m +0.325 → +0.063 · SPY@15m
  +0.378 → +0.202.

## Kept-strategy re-test under the corrected foundation (2026-07-11, user directive)

Every SELECTED strategy — not just the canonical engine runs — re-judged after Phases 1–3 (no new
strategy search; feature freeze holds). Studies with local MNQ-cost defects (composite, census,
volbreak re-validation) were migrated to the registry first.

| Kept lineage | Re-test | Verdict after fixes |
|---|---|---|
| Canonical ORB (6 runs) | engine, Phases 1–3 | QQQ@5m +0.335R · SPY@5m +0.176R · SPY@15m +0.202R positive; NQ@5m +0.047R and QQQ@15m +0.063R marginal; **ES@5m −0.068R negative → Phase E removal candidate** |
| nq-composite-0.1 | gauntlet re-run (registry costs) | **ALL-7 + ADOPT_CANDIDATE unchanged** |
| futures_volbreak (duel) | F105 exact-spec, 5m AND 1m, registry costs | **ALL PASS both resolutions** — +0.349R, PF 1.62, OOS +0.465; not resolution-fragile |
| qqq monday (base of qqq-composite-0.1) | census QQQ | **ADOPT_CANDIDATE 7/7** (+14.6bps, PF 1.46) |
| spy-monday-0.1 | census SPY | **ADOPT_CANDIDATE 7/7** (+9.0bps, PF 1.40) |
| census monday-drift NQ | battery | still 6/7 (PF gate) — unchanged watch |
| tsmom · overnight · swing-geometry · acceptance (duel/battery) | battery | pass counts unchanged |
| session relay/fade · asia-fade · weekend-fade · turn-of-month | battery | unchanged (watch studies) |
| QQQ/SPY first-hour-follow | census | REJECT — already rejected pre-fix, unchanged |
| 7DTE condor | — | sealed forward study; not re-simulated by design (economics adopt the registry at its next reset) |

**Pattern worth keeping:** the lineages that survived untouched are the simple, same-day,
PIT-by-construction specs (open→close windows, prior-day inputs, gap-aware fills). All the
flattery lived in the intraday engine strategy — daily-data-fed gates + positions held to the
close. The canonical ORB is now the WEAKEST member of the kept book on futures, not the strongest.

## Phase R — evidence regenerated on the corrected engine (2026-07-11, frozen-span waiver)

User decision: NO historical refresh — the store's forward edge grows only from live accrual, so
R ran on the frozen spans with the staleness waiver stamped into every artifact's lineage
(`remediation-2026-07-11 · corrected engine · frozen-span waiver`). QA stays honestly red on
freshness — that is the waiver's visible cost, never hidden.

**Regenerated:** A/B entry-standard report (live version stamp — the old hardcoded
"orb-standard-2026.07" was why `ab_strategy_version_match` read false forever; now TRUE) ·
canonical backtest cells (the entry matrix, 28 cells) · all six ML datasets (labels re-derived
from the corrected replay; stats mirror the canonical runs exactly) · the tracker's
live-vs-backtest reference (+0.24R/42% flattered → **+0.335R/39.4%** honest).

**The corrected A/B — the re-decision evidence:**

| Symbol | baseline | standard (07.7) | verdict |
|---|---|---|---|
| QQQ | +0.114R · PF 1.18 · DD −27R | **+0.306R · PF 1.52 · DD −18R · 8/9 yrs+** | standard ~3x baseline — HOLDS |
| SPY | +0.053R · PF 1.08 | **+0.169R · PF 1.27** | HOLDS |
| NQ | +0.036R | +0.007R | no honest edge in ANY variant |
| ES | −0.124R | −0.102R | negative in ANY variant (cohort test still rejects removal — OOS 2024+ positive) |

The 07.7 standard's equity edge was never the lookahead — it survives honest math with a wide
margin. The canonical ORB's futures edge does not; volbreak/composite are the futures carriers.

**Deliberately NOT re-run (feature freeze):** per-asset champion parameter sweeps and the
geometry study — re-sweeping parameters is new mining, which the freeze forbids; the frozen 07.7
parameters are what the corrected A/B just re-validated. The cost-stress report re-runs when ES
sizing is next on the table. **Manual step remaining (the user's click, by AITP design):** the
formal 07.7 paper re-approval with `override=True` (QA red = frozen-span staleness only) — this
converts the legacy record into a fingerprint-pinned, snapshot-carrying approval.

## Phase E — Entry Profitability Matrix live + FIRST REMOVAL CYCLE (2026-07-11)

The matrix (`bot/ml/entry_matrix.py`, `/api/entry_matrix?evidence=...`) is live: 28 backtest
cells (corrected engine, frozen span, pre-R waiver) across symbol → side → session → family →
grade → regime; one evidence type per call; n<30 cells say INSUFFICIENT SAMPLE; removed groups
stay visible. Removals registry (`bot/strategy/removals.py` + `config/entry_removals.json`)
enforced in BOTH the live scan (tradeable=False, signal stays visible, shadow accrues) and the
ExecutionService (submit → rejected). Tests TE.1–TE.4 (6), suite 243 green.

**First removal cycle — documented end to end (the gate's deliverable):**
1. **Nominated** (negative expectancy, n≥30, CI-upper < +0.05R): ES long orb@5m
   (n=218, −0.088R, PF 0.844) · an ES-long regime cell (n=69, −0.359R, CI fully negative) ·
   NQ long orb@5m regime cell (n=89, −0.174R).
2. **Cohort test** on ES orb@5m (n=983, 2010→2026): half1 −0.129R · half2 −0.007R ·
   **OOS (2024+) +0.167R over 125 trades**.
3. **VERDICT: REJECT** — the blocked cohort is PROFITABLE out-of-sample. Removing ES on its
   full-history number would have cut a currently-working regime: the F78 lesson fired on the
   very first cycle, which is precisely why the matrix nominates and never auto-blocks.
   ES stays a WATCH (still live-excluded from sizing by the cost-stress rule); the regime-level
   ES cell (CI fully negative) is the next nomination candidate once regime cells accrue more
   shadow data.

## Phase 4 — fail-closed data pipeline (2026-07-11)

No expectancy delta — this phase changes what the pipeline REFUSES. QA gained freshness (3
trading days), zero-volume, short-day (2%), and grain (median+p95 spacing) gates plus per-symbol
fingerprints and a top-level `store_fingerprint`/`all_ok`; the intake now raises on any step
failure and blocks datasets/training on a red QA report; equity ingest enforces instrument
identity (symbol column, duplicate-ts, price continuity) and refuses silent overwrites; the 5m
append fails loud on full overlap and records source sha256. Tests:
`test_pipeline_fail_closed.py` (10, red-first), suite 211 green.

**Gate proof (the phase's deliverable):** the real store now FAILS QA on all five symbols —
QQQ/SPY/ES stale 25 trading days, NQ stale 4 + 3.1% short days, GC 15.5% short days (636 sessions
under 90% of the grid — GC's data problem was invisible under the fail-open QA). `data_qa_all_ok`
is now honestly **false** until the store is refreshed — which is the explicit prerequisite for
Phase R regeneration.
