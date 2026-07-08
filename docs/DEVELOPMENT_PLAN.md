# Development plan — every remaining partial/incomplete item, and how each gets built
*(2026-07-05 · rule orb-standard-2026.07.2 · maintained alongside TASKS_INCOMPLETE.md)*

## 0. THE ULTIMATE GOAL — win rate 85% · PF 1.8–1.9 · adverse ≤ 45 ticks (futures) / $4 (equities)

The math pins the exit shape: PF = WR·W/((1−WR)·L) → **W/L ≈ 0.33** — the target must sit near
ONE-THIRD of the stop (NQ: ~15 ticks TP vs 45-tick stop; QQQ: ~$1.30 TP vs $4 stop). That is a
high-win-rate SCALP exit — the inverse of today's 4R-cap runner (WR 36–41%, big winners).
A driftless random walk already "wins" ~75.4% at that geometry, so the ENTRY must add ~10 points
of win probability AFTER costs — and costs are brutal at small targets (2–3 ticks round-trip
≈ 15–20% of a 15-tick target on NQ).

**How we pursue it (evidence-first):**
1. `research/target_geometry.py` (run kind=geometry) sweeps TP ∈ {0.25…1.0}×stop on the CANONICAL
   entries with the user's exact stop budget + honest costs → measures WR/PF/DD per geometry and
   flags any cell meeting the goal. This tells us TODAY how far the entries are from 85%.
2. Whatever gap remains is the MODEL's job: the no-trade/similarity/L2 stack must veto the
   losers. Each vetoed loser at 0.33 geometry raises WR ~0.4pts — the gap closes through
   selectivity, not more knobs.
3. L2 flow features (absorption/imbalance at the break) are the most plausible carrier of that
   selectivity — hence L2 → scalping module is the critical path for this goal.
4. Track progress on the Training Lab: geometry report (goal cells), threshold study (veto lift),
   paper scorecard (real-cost confirmation). The goal is declared MET only when a geometry cell
   shows WR ≥ 85% & PF ≥ 1.8 on OOS data AND paper trading reproduces it.

**Measured baseline (2026-07-05, full-history canonical entries, honest costs — target_geometry.json):**

| @0.33×stop | WR | PF | verdict |
|---|---|---|---|
| SPY ($4 stop) | 70.7% | 1.44 | best carrier — gap 14 WR pts |
| QQQ ($4 stop) | 69.1% | 1.32 | second carrier |
| ES (45t = 11.25pt) | 74.0% | 1.07 | highest WR, costs eat the PF |
| NQ (45t = 11.25pt) | 61.1% | **0.42** | **structurally impossible** — 45 ticks < NQ noise; every geometry loses |

Gap math (SPY): to reach 85% WR keeping all wins, the veto stack must remove ~57% of losers with
near-zero false vetoes. That is far beyond the current no-trade model (AUC 0.546) — it is the
L2-selectivity bet. Interim milestone that IS plausible: veto ~30% of losers → ~77% WR / PF ≈ 1.6.
**Decision needed (user):** futures goal at 45 ticks only makes sense on ES (or MNQ at a larger
tick budget, e.g. 120–180 NQ ticks ≈ the same $ risk as MNQ 45t×10). NQ at 45 ticks is dead on
arrival regardless of entry quality.

**NQ ≥75% WR search (2026-07-05, user ask — nq_winrate.py + nq_scratch.py, run kind `nqwr`):**
768 cells swept: stop {45–300 ticks, 0.5–2.0×ATR(14)} × TP {0.25–0.60×stop} × regime {all, A}
× BE-move {–, 0.10, 0.15×stop} × time-stop {–, 3, 6, 12 bars} × soft-abort {–, 0.5×stop close}.
- NQ **does** reach 75–81% WR — but only at vol-adaptive stops (2×ATR ≈ 136 ticks median full-
  history, ≈ 76 ticks in regime-A) and best PF is **0.91** (all|2×ATR|tp0.33: 76.7% / 0.91).
- Every exit trick (BE, time-stop, abort) LOWERS PF at these geometries — they scratch/clip more
  winners than the losses they save. Exit engineering alone cannot make high-WR NQ profitable.
- ES is the closest futures cell TODAY: 60-tick stop, TP 0.25× → **76.8% WR, PF 1.12, +0.017R**.
- **The path for NQ 75%+ profitable:** keep all|2×ATR|tp0.33 and add a loser-veto model that
  removes ~24% of losers (0 false vetoes) → **~81% WR, PF 1.2**. That is the first concrete,
  modest selectivity target for the no-trade/L2 stack — far easier than the 57% the 85% goal
  needs, and measurable with the existing threshold study.

## The list (priority order)

1. Model side: get a P(win)/heads/no-trade champion past the gates ← **main effort now**
2. L2/L3 depth features into the models
3. 15-minute timeframe validation (second timeframe lineage)
4. Paper phase: approve the 07.2 ladder → collect live evidence
5. AUTO Pine TV compile (now has TP1 scale-out + v2 parity)
6. Swing module completion (dataset ✅ → rules → gauntlet → registry)
7. Scalping module (after L2)
8. Options as an independent strategy
9. Repo hygiene: OneDrive move, research split, SQLite WAL, schema stamp, report retention
10. AITP phase 7 (hardening) → phase 8 (live review)

---

## 1. Shift effort to the MODEL side — the runbook

**Goal:** a champion in `signal_winprob` (and ideally `no_trade`) that passes AUC > 0.52 + Brier +
buckets + slices. Closest so far: tp2_prob AUC 0.641, no_trade 0.546/0.55, NN GRU 0.556.

**Do, in order:**
1. `run_server.bat` → Continuous training **Start** (or `BOT_CONT_TRAINING=1`). Each cycle:
   dataset → ML zoo → NN zoo, `--no-promote`. Zero effort after the click.
2. **Register the L2 disk** (item 2) — the six l2_* features are the highest-value missing signal;
   spread/imbalance at the breakout minute is exactly what separates absorbed breaks from real ones.
3. When a model lands in **Pending models** → review buckets/calibration in its report → Promote.
4. After any promotion, run **10 · Threshold study** — even a modest champion may add expectancy
   as a top-bucket filter before it's good enough for sizing.
5. Weekly: check `/api/training/reports` trend — if AUC plateaus under the gate for ~10 cycles,
   the missing edge is DATA (L2, more symbols, live outcomes), not architecture. Resist
   architecture churn; Transformer/MoE are already in the zoo and will surface if they help.
6. As live/paper outcomes accumulate, `live_labels` rows become a second training table —
   fine-tune the champion on them once ≥300 resolved signals exist (add a `--live-mix` flag to
   `pipeline` then; small job).

**Definition of done:** a promoted `signal_winprob` champion whose OOS buckets are monotone AND
whose threshold study shows ≥ +0.05R avg lift at a cutoff keeping ≥40% of trades.

## 2. L2/L3 depth into the models
- **State:** pipeline complete (register path/folder, zip/zst in place, drag-drop, per-minute
  synthesis, dataset auto-join). Blocked only on the physical files.
- **Develop:** plug the disk in → L2 panel → paste folder → Sync each source → `1 · Rebuild
  dataset` per symbol → retrain. Then extend `_bar_channels` with an l2 channel for the NN
  (one-line append once features exist).
- **Done when:** datasets show l2_* non-NaN and a training report shows their permutation
  importance > 0.

## 3. 15-minute timeframe lineage
- **State:** dataset builds (QQQ@15m: 209 rows, +0.454R). Nothing validated.
- **Develop:** TF=15m → dataset for all four → sweep (needs a `--tf` pass-through in the sweep
  script — 30-minute job) → gauntlet winners → per-TF entry in the module registry. Keep 15m
  models in their own registry versions (`@15m` suffix already wired).
- **Done when:** a 15m config passes the 7-check gauntlet vs its own baseline.

## 4. Paper phase (unblocks everything in 10)
- Approve research → replay → paper on `/training` (the WHAT panel shows the evidence, including
  the stale-A/B warning — re-run `4 · A/B` first so `ab_strategy_version_match` turns true).
- Enable paper autotrade; let it run ≥60 trades or 8 weeks; watch `/api/scorecard`.
- **Done when:** paper expectancy per grade sits inside the backtest's CI and slippage ≤ the
  stress assumptions (ES's gate to relevance).

## 5. AUTO Pine compile
- AUTO now has: ctx_source auto pairs, instant fill, bias supersede, pullback refinements,
  vol-confirm, **TP1 scale-out** ("Scale 50% @ TP1 → BE → TP2" — two broker-held exits, runner
  stop to break-even after TP1). Paste into TV, compile, run one forward paper session comparing
  its fills to STACK's signals before trusting the scale mode.

## 6. Swing module
- **State:** 1d/1w triple-barrier datasets build; strategy rules spec_only.
- **Develop:** (a) train heads on `tf=1d` (labels exist); (b) write the swing STRATEGY spec in
  `bot/strategy/modules.py` with concrete entry (EMA20/50 trend + pullback-to-EMA20 or breakout),
  exit/stop from the triple-barrier geometry; (c) replicate the sweep/gauntlet pair on daily bars
  (new small script — the IS/OOS split logic copies over); (d) approval ladder as its own
  strategy version (`swing-1d-0.x`).
- **Done when:** swing gauntlet passes on ≥2 symbols and the module registry flips to implemented.

## 7. Scalping module
- Blocked on L2 (flow imbalance is the candidate edge) + a 1m execution loop. After L2: research
  script on 1m bars with l2_flow_imb/absorption as the trigger, ORB-mid context reuse, engine
  costs at 1-tick granularity. Do not start before item 2 lands.

## 8. Options standalone
- Extend the tracker to record option-leg fills during the paper phase (data first). Then an
  `options_flow` module spec: IV-rank filter, expected-vs-implied move from the existing pricing
  lib, defined-risk structures only. Gauntlet equivalent = payoff-simulated replay on the
  underlying champion's signals. Start only after item 4 produces option fill data.

## 9. Repo hygiene (half-day, big risk reduction)
- Move `prediction/` out of OneDrive (or exclude `data/`, `BOT/data/`, `.venv/`, `BOT/conf/` —
  the Webull token lives there and is being cloud-synced).
- `PRAGMA journal_mode=WAL` + busy_timeout in `tracker._con()` before paper scale-up.
- Split `research/` → `tools/` (ab, sweep, gauntlet, pairs, report, parity, verify, threshold)
  vs `archive/`.
- Stamp `SCHEMA_VERSION` into datasets/registry metadata; add a 90-day report retention sweep.

## 10. AITP phases 7–8
- Phase 7 (after ≥2 weeks of paper): broker fill stream, reconcile scheduling, restart recovery
  (persist kill-switch/toggles to disk), health alerting. Checklist in PAPER_TO_LIVE.md.
- Phase 8: green scorecard + execution-quality report + 'live' approval + lock file → minimum
  size, equities only. No shortcuts by design.

---

## Standing loop (what "done for now" looks like day-to-day)
Continuous training grinding → pendings promoted when gates pass → paper autotrade collecting
fills under the approved ladder → weekly sweep/phase-2 sweep as new data accrues → gauntlet
anything flagged → adopt only 7/7. Every claim traceable to a report; every state change in the
audit trail.
