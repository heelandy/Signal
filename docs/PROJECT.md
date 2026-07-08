# HIGHSTRIKE — the whole project, from the roots (2026-07-07)

The complete map: what this system is, why every piece exists, how data becomes decisions,
decisions become a journal, and the journal becomes learning. Newcomer-readable; every claim
traceable to a report or an F-number in `research/RESEARCH_NOTES.md`.

---

## 0. The root idea

One trading organism with **four planes** and **one law**:

| Plane | Job | Home |
|---|---|---|
| DATA | bars in, transient; nothing hoarded | `bot/market_data/` · `pipeline/` · `engine/hs_db` |
| DECISION | one canonical entry machine, per-asset knobs | `bot/strategy/` · `engine/hs_backtest.py` · `production/*.pine` |
| LEARNING | the trade JOURNAL is the training corpus | `bot/tracker.py` · `bot/ml/` · `bot/nn/` · `bot/evolve.py` |
| GOVERNANCE | nothing trades or promotes without evidence | `bot/approval.py` · `bot/boss.py` · `bot/phase78.py` · `bot/risk.py` |

**The law**: evidence first — IS nominates, OOS judges, gates never loosen, every adopted knob is
cohort-tested (run the variant, diff the trade sets, the blocked cohort's sign decides), every
state change lands in the audit trail, and one source of truth per fact (every production bug
found here — F75's silent divergences, the journal starvation — was a second copy of the truth
drifting from the first).

## 1. Instruments & goal

- **Core book**: QQQ · SPY (equities, live via Webull/Alpaca) · NQ/MNQ · ES (futures, delayed via
  Yahoo until entitlements) · GC (gold, unverified — signals only).
- **Ultimate goal** (user): WR 75–85% · PF ≥ 1.7 · maxDD ≤ 10% — pursued per symbol by the
  WORKERS (§7); the core 4R-cap system is the engine that generates the entries they reshape.

## 2. Data plane

- **Historical**: Databento OHLCV/MBO archives ingested to `data/*_continuous_1m.parquet` →
  `pipeline/hs_resample.py` → hive-partitioned bar store (`data/bars/`) read by `engine/hs_db`.
  `pipeline/hs_mbo_bars.py` can build 1m bars from raw MBO trade prints (removable scaffolding —
  manifest + `--remove` restores the official store byte-exact).
- **Live**: `bot/market_data/providers.py` — ONE router, priority chain (`PROVIDER_ORDER` in
  .env; currently webull → alpaca → yahoo). **Env-ready contract**: paste a provider's API key in
  `BOT/config/.env` and it activates — key-ready providers auto-join the chain (databento,
  tradestation), `WEBULL_FUTURES=true` re-includes Webull for futures on entitlement day. No code
  edits, ever. Live bars are TRANSIENT (`persist=False`) — the journal is the only durable record.
- **L2/L3 depth**: `bot/ml/l2_features.py` — auto-labeled registration (the file's own `symbol`
  column decides; user pick = fallback), duckdb synthesis under a memory cap, per-minute `l2_*`
  features joined onto candidates. Verdict so far: 24 days of history is too thin to move a
  champion; the value is forward capture.

## 3. The decision plane — the canonical entry standard

One entry machine on every surface (Pine STACK/AUTO · live scan · backtest engine · FSM spec):

```
WAITING → ARMED (Layer-1 context) → WATCH (confirmed close beyond OR mid)
        → FILL (strong-body close beyond OR high/low + continuation + dir-seq)
   + PULLBACK (chase cap → retest) · COOLDOWN · RANGE/stale · LOCKED · INVALIDATED
```

- **Rule version** `orb-standard-2026.07.7` (`bot/strategy/orb_candidates.py` header carries the
  full .1→.7 history). Bumping the version re-keys datasets/models/approvals — models train
  against ONE rule at a time.
- **Per-asset truth** lives in `bot/strategy/asset_config.py` ONLY (chase/stale/cooldown/fill
  timing/retest/geometry per symbol) with `layer3_kwargs()` as the single resolver feeding the
  canonical backtest, the live scan, and the label builder. The Pines mirror it via the
  `auto_asset` toggle, and `BOT/tests/test_pine_config_sync.py` machine-verifies Pine ≡ config.
- **Adopted per-asset map (F75–F78)**: QQQ struct+VWAP arm, same-candle fill, chase 0 · SPY
  always-wait fill · NQ/MNQ A∨B∨C arm, chase 1.5 + impulse-mid retest, 3 sessions, re-entry ×3 ·
  ES stale 24 + cooldown 3, always-wait (cost-fragile: excluded from live sizing).
- **Canonical numbers** (parity 100%×4 candidates ≡ engine): QQQ +158.4R PF 1.88 · SPY +118.9R
  PF 1.70 · NQ +283.8R PF 1.36 · ES +107.5R PF 1.14 (full history, 4R-cap geometry).

## 4. Research method (how anything gets adopted)

1. **Cohort test**: run the variant through the ONE canonical call, diff trade sets by entry
   time; the blocked/gained cohort's sign decides (a gate whose blocked cohort is positive costs
   money — F75's chase cap, F77's stale rule, F78's ten pullback verdicts all fell to this).
2. **Combined verify** before adoption (knob interactions), **7/7 gauntlet** + 2×-cost stress +
   walk-forward for anything promoted, **OOS judges** always.
3. Adoption = asset_config + both Pines + version bump + CHANGELOG + RESEARCH_NOTES F-entry.
4. Dead ends stay recorded (F79 fresh entry, scalp round 1, GC) — a REJECTED verdict is a
   finished study, not an open task.

## 5. The learning plane — THE JOURNAL IS THE TRAINING LAB

**Standing requirement (user): the system auto-learns from previous entries.** The loop:

```
scan (5m + 15m passes, QQQ/SPY live) → every acceptable signal auto-journaled with its
bar identity + PIT feature snapshot + strategy family + tf  →  track_outcomes resolves
TP/stop first-touch  →  build_live_labels turns resolved rows into labeled training rows
→  dataset.build() UNIONS them into the matching lineage (symbol × timeframe), core
families only  →  the continuous-training loop detects corpus growth and retrains
(--no-promote)  →  gate-passing challengers wait as PENDING for a human click.
```

- **Approval-free learning**: journaling and training never wait on the ladder — approval gates
  *trading*, never *learning*. Only the journal (+ derived feature stores) persists.
- **Lineages** in continuous training: QQQ, SPY, NQ, ES, **QQQ@15m, SPY@15m**, ALL (pooled).
  The 15m lineage is the current champion frontier (first-ever AUC-gate pass, 0.556).
- **Honest ML gates** (`bot/ml/pipeline.py`): OOS AUC > 0.52, Brier beats base rate, bucket
  monotonicity, per-slice non-inversion — enforced in promotion; nothing has fully passed yet
  (that is the system working, not failing).
- **The evolution engine** (`bot/evolve.py`, nightly subprocess + `/api/evolve`): mines the
  journal, exits/TP headroom, and the reject store on honest splits and DRAFTS
  `emergent-*` candidates (first: `emergent-qqq-dir_seq-0.1`). It proposes; the gauntlet judges.

## 6. The journal (single durable substrate)

`bot/tracker.py` (SQLite WAL) — one row per decision: bar identity (candidate_id +
signal_at), symbol/side/family/session/**tf**, entry/stop/TP1/TP2, taken/skip, PIT snapshot in
json, resolved outcome + result_R/MFE/MAE. Rules: auto-tracking dedups one row per candidate;
manual Take/Skip is a ONE-TIME trigger (a second click updates, never duplicates); worker and
emergent lineages live here too but are **sealed out of** the core dataset and the paper
scorecard (`CORE_ONLY`) — each lineage is judged only on its own stream.

## 7. Workers & the Main Boss (the WR-75-85 pursuit)

- **Five workers** = per-symbol tight-target contracts over the same canonical entries
  (`bot/boss.py` WORKERS): Q (QQQ 0.40× + slope-STRONG) · S (SPY 0.33×) · N (NQ 0.30× +
  early-only) · E (ES) and G (GC) **OBSOLETE** (evidence in modules.py; graveyard visible on the
  dashboard; revival = fresh gauntlet on new data). None is in band yet on history — the paper
  shadow study is the judge (each worker records its own tight-target what-if trades, tagged by
  family).
- **The Boss** supervises: rolling per-worker conformance (auto-disarm on band break),
  **band-pass notification** (audit + dashboard badge + one-click paper-approve button next to
  it), correlation buckets (aligned QQQ/SPY/NQ/ES fires = ONE macro bet — only the bucket lead
  places a paper order), obsolete arm-lock. `/api/boss`.

## 8. Governance — the ladder and the phases

- **Approval ladder per lineage** (`bot/approval.py`): research → replay → paper → live; paper
  autotrade hard-blocked without 'paper'; revocation cascades. Every lineage (core, modules,
  workers, emergent drafts) walks the same ladder.
- **Paper trading**: Alpaca paper brackets for QQQ/SPY (grade-sized, dedup'd, stale-feed
  gated, Boss bucket rule enforced); futures via Pine webhooks. The scorecard judges live-vs-
  backtest on CORE trades only.
- **Phase 7–8 auto-advance** (`bot/phase78.py`): the paper study evaluates itself hourly (≥60
  core trades AND ≥8 weeks AND scorecard consistent AND no grade inversion + hardening checks +
  execution quality vs 2× stress) → the 'live' stage advances automatically, audit-logged.
  **The LIVE_APPROVED.lock file stays manual forever** (double gate); ES excluded by cost stress.
- **Kill paths**: kill switch (always armable), revoke any stage, mode switch. Risk lockouts:
  0.25%/trade · 0.75%/day · 2%/week · 3% trailing · streak · correlated buckets · news.

## 9. Ops

- **Server**: `BOT/run_server.bat` → uvicorn --reload on :8000 (dashboard `/`, Training Lab
  `/training`). Reload kills in-flight background jobs — sequence bot/ edits around them.
- **Known hazards**: repo lives inside OneDrive (12.9GB commit balloon + file locks — the move
  out is the durable fix, user's hands); stacked stale uvicorn supervisors after reload storms
  (kill all python except the port-8000 pair); heavy research runs must be SERIAL (one process,
  memory caps) — never next to training.
- **CI**: GitHub Actions pytest (130 tests incl. Pine↔config sync), requirements.txt pinned.

## 10. Current state & the live threads (2026-07-07)

- Rule 07.7 everywhere · parity 100%×4 · 130 tests green · TV compile of STACK+AUTO pending
  (user).
- Journal-fed continuous learning LIVE for QQQ/SPY at 5m + 15m; first real day of worker shadow
  trades: all three hit their tight targets while the core 4R entries stopped — the geometry
  thesis, live.
- Champion frontier: the 15m lineage (AUC 0.556 > 0.52, Brier a hair short) — grows with the
  journal. Historic L2 closed as too thin; forward capture is the path.
- Waiting on data/time, not code: worker band-passes (paper evidence), phase 7–8 green, the
  next emergent drafts. Waiting on the user: TV compiles, provider keys as they come,
  the OneDrive move.

## 11. File map (where anything lives)

```
BOT/bot/strategy/   entry standard: orb_candidates (canonical) · asset_config (per-asset truth)
                    families (live scan) · orb_state (FSM spec) · modules (registry) · duel
BOT/bot/ml/         dataset (journal union) · pipeline (gates) · features_pit · l2_features
                    live_labels · heads · registry (stores/models)
BOT/bot/            tracker (journal) · boss · evolve · phase78 · approval · risk · live (scan)
                    api/server.py (everything web) · api/static/ (dashboard + training lab)
engine/             hs_backtest (the ONE simulator) · hs_harness · hs_db
production/         HIGHSTRIKE_ORB_STACK.pine · _AUTO.pine (+CHANGELOG — versioned claims)
research/           one script per study, RESEARCH_NOTES.md F1..F81 (the evidence trail)
pipeline/           ingest/resample/QA/mbo-bars (bar store construction)
docs/               this file · ENTRY_STANDARD · BOSS_WORKERS_PLAN · PAPER_TO_LIVE ·
                    TASKS_INCOMPLETE (living checklist) · DEVELOPMENT_PLAN
```
