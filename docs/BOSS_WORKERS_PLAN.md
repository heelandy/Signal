# BOSS / WORKERS PLAN — per-symbol specs → one supervised bot (2026-07-06, REFINED same day)

User goal: **WR 75–85% · PF ≥ 1.7 · max drawdown ≤ 10%** — per symbol, then assembled under one
orchestrator: a **Main Boss** that looks over **five Workers** (QQQ · SPY · NQ · ES · **GC**),
each running its own spec. Refinements (user, same day): gold ladders to paper like everyone
else; a worker that misses the band moves to the **OBSOLETE section** (auditable graveyard, not
deletion); and the platform gets an **ALWAYS-LEARNING loop** — studies + journaling + trades +
exit/TP mining from which NEW candidate systems emerge automatically (drafted, never
auto-adopted). Approved — execution running in the order of §5.

---

## 0. The math that makes the target reachable (so the specs aren't wishes)

PF = WR·b / (1−WR), b = avg win in R (net). The user's band pins b:

| WR | b needed for PF 1.7 | read |
|---|---|---|
| 75% | ≥ 0.57R | tight target ~0.55–0.60× stop |
| 80% | ≥ 0.43R | target ~0.45× stop |
| 85% | ≥ 0.30R | target ~0.33× stop |

High WR is **bought with geometry** (small target under a structural stop) and **earned with
selectivity** (each symbol's proven gates + a loser-veto). The geometry study showed the raw
tight-target baseline sits ~75% WR — so every spec needs +3–8 points of WR from selectivity to
clear the band WITH PF intact. Costs matter enormously at tight targets (ES most exposed).

DD ≤ 10%: at the platform's 0.25% risk/trade, 10% ≈ 40R. Specs target **≤ 10R per worker**
(≈ 2.5%) so the four-worker book stays far inside 10% even correlated; the Boss's existing
trailing-3% lockout remains the hard portfolio stop.

## Step 0 — Synthesis auto-labels its sources (no user symbol selection)

The NQ/QQQ mislabel happened because registration trusts the user's symbol pick. Change:
- `register(path)` (symbol optional): probe the file's `symbol` column (duckdb, LIMIT-cheap),
  take the distinct symbols FOUND; one symbol → auto-label; several → register one source row
  per symbol (the synthesis filter already splits them correctly); none (no symbol column) →
  fall back to the user's pick, flagged `label_source: "user"` vs `"auto"`.
- UI: symbol dropdown becomes optional override; the registry shows the auto-detected label.
- Re-probe existing rows once at startup; mismatches get flagged in the registry (never silently
  reassigned after features exist).

## 1. The four Worker specs (each written to hit WR 75–85 / PF ≥ 1.7 / DD ≤ 10R OOS)

Common skeleton every worker shares (all already live in 07.7): canonical ARMED→WATCH→FILL entry,
struct stop with per-asset floors/caps, EOD flat, real per-asset costs, macro gates, risk
lockouts. What differs per worker: arming pair, fill timing, geometry, and the selectivity stack.

### Worker Q — QQQ (the quality worker)
- **Base stack**: struct_vwap arming (its edge), same-candle fill (ft_confirm off), single entry,
  RANGE-regime block ON, clean-air ON, RTH only. Base edge today: +0.552R avg, PF 1.88 at 1.5/4
  geometry — the strongest raw material of the four.
- **Geometry**: TP 0.45×stop, full position (no scale), BE never (binary win/loss keeps the WR
  math honest). Sweep cells: b ∈ {0.40, 0.45, 0.50, 0.55} × stop mode {struct, struct+0.25 buf}.
- **Selectivity**: grade A+/A only · clean-air pass · optional loser-veto model (see §2).
- **Acceptance (OOS 30%)**: WR ≥ 75%, PF ≥ 1.7, maxDD ≤ 8R, n ≥ 120 IS / ≥ 40 OOS, survives 2×
  slip with PF ≥ 1.4.

### Worker S — SPY (the patient worker)
- **Base stack**: struct_vwap arming, ALWAYS-WAIT fill (instant off — its OOS edge), single
  entry, RANGE block ON, macro stand-downs ON. Base: +0.442R avg, PF 1.70, OOS 0.620.
- **Geometry**: same sweep as Q; SPY's tighter intraday range may prefer b 0.50–0.55 at WR ~76%.
- **Selectivity**: grade A+/A · gap-day study rerun at tight geometry (gap cohorts were positive
  at 1.5/4 — tight targets may invert that; re-test, don't assume).
- **Acceptance**: same gates as Q.

### Worker N — NQ (the volume worker)
- **Base stack**: A∨B∨C arming, chase 1.5 + impulse-mid retest (F78), 3 sessions, re-entry ×3,
  chop traded. Base: +0.207R avg, PF 1.36, n 1370 — hugely liquid signal stream but DD −42R at
  1.5/4: **the DD budget is N's whole battle.**
- **Geometry**: tighter than equities — b ∈ {0.33, 0.40, 0.45}; at 85% WR × b 0.33 PF hits 1.87.
- **Selectivity (the veto stack, in test order)**: session subset (keep only sessions whose
  tight-target WR clears 75 standalone) · grade A+/A · combined-slope STRONG only ·
  the loser-veto model — the NQ 75%-WR study already showed vetoing ~24% of losers reaches
  81% WR profitably; at tight geometry the veto has an easier job.
- **Acceptance**: WR ≥ 78% (volume allows a higher bar), PF ≥ 1.7, **maxDD ≤ 10R**, n ≥ 400 IS /
  ≥ 120 OOS, 2× slip PF ≥ 1.4. Micro-sizing via MNQ inherits N.

### Worker E — ES (the conditional worker)
- **Base stack**: A∨B∨C arming, always-wait fill, stale 24 + cooldown 3 (its earners), chop
  traded. Base: +0.088R avg, PF 1.14 — the weakest edge AND the worst cost profile (negative at
  2× slip). **E ships only if the numbers appear; the Boss benches it otherwise.**
- **Geometry**: b ∈ {0.55, 0.60} only (tight targets amplify ES's cost share — chase the 75–78%
  WR × bigger-b corner, not the 85% corner).
- **Selectivity**: A+ only · RTH session only · stale/cooldown kept.
- **Acceptance**: same gates PLUS the standing rule — no live sizing until measured execution
  beats the 2× stress case. Failure to pass = E stays a signals-only worker (still feeds the
  Boss's market read, places nothing).

### Worker G — GC gold (the probation worker)
- **Status**: `unverified` — the F30 gold edge did NOT reproduce under the current engine. G
  enters the SAME discovery protocol as everyone else (geometry grid → cohorts → gauntlet) with
  zero grandfathering; its history earns it nothing.
- **Base stack**: A∨B∨C arming, US-morning RTH_FUT session only (its only historically live
  window), futures costs, GLD as the options root.
- **Geometry**: full grid b ∈ {0.30…0.60} — no prior; the grid speaks first.
- **Acceptance**: identical gates to N (futures bar). **Ladders to PAPER regardless of verdict**
  (user rule: "for gold as well") — as a signals-only paper study if it misses the band, so the
  paper data itself becomes the evidence that promotes or buries it.

### The OBSOLETE section (the graveyard is part of the system)
A worker (or any module lineage) that misses its band does not ship AND does not vanish:
- `modules.py` gains status **"obsolete"** — the contract stays registered with its full
  evidence trail (what was tried, which gate failed, the report paths).
- Dashboard "Bot Strategies" renders an OBSOLETE section (collapsed) so the graveyard is
  visible — nothing is silently deleted, and a buried worker can be re-opened only by passing
  the full gauntlet again on NEW data.

## 2. The loser-veto model (shared selectivity engine)

Per-symbol binary model: P(this qualifying signal is a loser) from the 59-feature PIT snapshot
(+ l2_* where coverage exists — QQQ already joined). Gate to deploy a veto: OOS WR lift ≥ +3
points at ≤ 25% signal cost, spread holds per year-slice, same honest gates as every champion
(no gate loosening — if no veto passes, the worker must make its band on geometry+rules alone,
or it doesn't ship).

## 3. Discovery protocol (how each spec gets FOUND, not assumed)

1. `research/worker_specs.py` — per symbol: tight-target geometry grid **under the full 07.7
   per-asset gate stack** (the old geometry study ran a leaner stack), IS 70% picks the cell,
   OOS 30% judges. Output: per-symbol scoreboard vs the band.
2. Selectivity tiers, cohort-tested one at a time on the chosen cell (grade tier → sessions →
   clean-air/slope → veto model). Adopt only cohorts whose removal-set is net-negative.
3. Full 7/7 gauntlet per worker + 2× slip + walk-forward halves.
4. Freeze each passing spec as a versioned contract: `worker-q-0.1`, `worker-s-0.1`,
   `worker-n-0.1`, `worker-e-0.1` in modules.py — each with its OWN approval ladder, duel entry,
   paper study and phase-7/8 auto-advance (all infrastructure already live).

## 4. The Main Boss (orchestrator)

`bot/boss.py` — supervises, never trades its own opinion:
- **Contract registry**: each worker's frozen spec + acceptance band travels with it.
- **Live conformance watch**: rolling scorecard per worker (n≥30 window): WR below (band−10pts)
  or DD > budget → **auto-DISARM that worker only** (audit-logged), others unaffected; re-arm
  needs a fresh green window on paper or manual approval.
- **Risk allocation**: the shared budget (0.25%/trade · 0.75%/day · trailing 3%) plus
  **correlation buckets** — QQQ/SPY/NQ/ES same-direction fires share one bucket cap (the four
  workers are one macro bet when aligned; the Boss sizes accordingly).
- **Conflict rule**: opposite-direction fires on correlated symbols → highest-grade wins, other
  stands down that cycle.
- **Surfaces**: `/api/boss` + dashboard panel (worker states: ACTIVE/DISARMED/BENCHED, rolling
  bands vs targets); every Boss decision in the audit trail.
- Reuses as-is: approval ladder, kill switch, phase78, duel, tracker, risk lockouts.

## 4b. The ALWAYS-LEARNING loop (evolution engine — new systems emerge from the journal)

User: "the script needs to be always learning; based on study and journaling, trades, exit/TP,
a new system can emerge." `bot/evolve.py` + a nightly tick in the continuous loop:

- **Journaling deepened**: every trade already lands in tracker/journal/live_labels with PIT
  snapshots; add **exit efficiency** per trade (realized R ÷ MFE, plus MAE-vs-stop margin) so
  the exits themselves become study data.
- **Nightly mining** over ALL evidence streams: per-worker slices (session/grade/DOW/hour),
  exit/TP studies (are winners' MFEs leaving money above the TP? are stops wider than any
  winner's MAE needs?), missed-winner rejects (build_rejects hypothetical outcomes), duel
  results, and the paper scorecards.
- **EMERGENCE**: when a mined pattern holds on an honest split (n ≥ 100, both halves
  band-grade), the engine **DRAFTS a candidate**: `emergent-<slug>-0.1` — a written spec +
  report card on the dashboard. Drafts enter the SAME promotion path as everything else
  (gauntlet → module → ladder → paper). **The engine never adopts its own drafts** — it
  proposes; the gauntlet and the ladder judge. TP/exit findings similarly draft worker spec
  REVISIONS (worker-q-0.2, …) — versioned, gauntleted, never hot-patched.
- Surfaces: `/api/evolve` (latest drafts + mining report) + a dashboard card; every draft in
  the audit trail.

## 5. Order of work

| # | Step | Depends on |
|---|---|---|
| 1 | Step 0 auto-label synthesis | — (small, isolated) |
| 2 | worker_specs.py geometry grids ×5 (incl. GC) | — |
| 3 | Selectivity cohorts per worker | 2 |
| 4 | Loser-veto training (QQQ first — L2 joined) | 2, L2 store ✅ |
| 5 | Gauntlets ×5 → freeze contracts (misses → OBSOLETE) | 3,4 |
| 6 | Boss orchestrator + UI + tests | 5 |
| 7 | Evolution engine (journal/exit-TP mining → emergent drafts) | 6 (journal streams ✅ live) |
| 8 | Ladder every worker incl. G to paper → duel → phase 7/8 auto-advance | 6 (infra ✅ live) |

## 6. Honesty clauses (unchanged platform law)

- OOS judges; IS only nominates. No gate is loosened to make a worker fit the band.
- A worker that misses the band **does not ship** — the Boss launches with however many pass
  (E is the most likely bench; N's DD is the second risk).
- Every adopted knob mirrors BOT + STACK/AUTO Pines + the sync test, same as F75–F78 law.
- Paper study per worker before live; the lock file stays manual.
