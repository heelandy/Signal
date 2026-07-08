# BOT folder — per-file feature audit (missing / incomplete, by section)

*2026-07-05 · rule orb-standard-2026.07.3 · every `bot/**/*.py` reviewed (77 files) — grep-swept
for stubs/markers + cross-checked against the platform docs. Sections mirror the package layout.
Only GAPS are listed; a file that is feature-complete for its scope is not mentioned.*

## bot/api (server + dashboards)
- **server.py** — complete for current scope. Pending by DESIGN (not bugs): AITP phase-7 items —
  restart recovery (kill-switch/toggles are in-memory, lost on restart), health alerting hooks.
- **static/training.html** — candidate detail shows reports; heads/explain per PENDING model could
  be richer (dashboard already renders heads/AI/kelly on live proposals).

## bot/brokers
- **alpaca_broker.py** — equities paper/live ✓. **No futures broker adapter** — paper autotrade is
  QQQ/SPY-only; NQ/ES paper needs a futures-capable broker (or stays tracker-simulated).
- **base.py** — no broker-side FILL STREAM consumption (AITP phase 7: reconcile against broker
  fills in real time; today reconcile.py polls).

## bot/market_data
- **databento_feed.py** — `stream_live()` raises NotImplementedError — LIVE streaming bars are
  stubbed until the paper/live phase (historical + local store paths work).
- **providers.py** — Webull US_FUTURES 401 handled by fallback; no secondary live futures feed.

## bot/ml
- **pipeline.py** — GroupCalibrator (per symbol/side) built but the champion path still uses the
  GLOBAL isotonic; wire when a model passes gates. `--live-mix` fine-tune flag deferred until
  ≥300 resolved live signals. **No champion yet passes gates (the current blocker — needs L2/new data).**
- **l2_features.py** — pipeline complete; l2_* columns are NaN until the registered MBO files are
  synced (user click) and datasets rebuilt.
- **heads.py / nn/** — heads + NN zoo train; none past gates; NN has no l2 bar-channel yet
  (one-line append once l2 features exist).
- **swing_dataset.py** — 1d/1w labels ✓; **1w (weekly) rules research not run** (daily passed QQQ/SPY).

## bot/nn
- **similarity.py** — clusters PROMOTED and voting ✓. ~~Sequence-model live scoring not wired~~
  **WIRED 2026-07-05**: families.py scores every proposal's 64-bar window through
  `predict_sequence` (champion-gated — None until an NN passes gates); rides proposals as
  `nn_seq` and votes in the ensemble.

## bot/options
- **pricing/strategies/translate/exit_plan** — translation layer implemented. ~~Option-leg fills
  not recorded~~ **RECORDING 2026-07-05**: every shadow-tracked signal now carries its translated
  option structure (strikes/expiry/type/est. cost) into the tracker — the paper phase collects
  the standalone options module's dataset. Still missing: live chain IV feed (IV stays
  model-approximated).

## bot/orderflow
- Live tape scoring ✓ (ws/tape). ~~No persistence~~ **PERSISTING 2026-07-05**:
  `bot/orderflow/persist.py` appends minute-deduped flow scores per scan cycle to
  `data/orderflow_scores.csv`. Schema join deliberately deferred: an `of_score` training column
  would be 100% NaN for all history — the stored file becomes its backfill once months of live
  rows exist (data-first, same pattern as options legs).

## bot/strategy
- **extra.py** — fundamental composite score stays a STUB **by decision (2026-07-05)**: no
  fundamentals data source exists in the stack (no earnings/FCF/balance provider). Un-stub only
  when a fundamentals feed is added; it feeds nothing live today.
- **modules.py** — statuses: equities_swing **GAUNTLET_PASS (QQQ 7/7)** and futures_swing
  **GAUNTLET_PASS (NQ breakout 7/7)** → next: swing-1d-0.x approval ladder (futures also needs
  contract-roll handling in execution); SPY (4/9 years) + ES (9/17) failed — not adopted;
  equities/futures_scalping spec_only (blocked on L2 + 1m loop).
- **reversals.py** — detectors are features ✓; tested as hard vetoes 2026-07-05: **none qualify**
  (veto cohorts positive OOS on all four symbols — they'd cut winners). Stay model inputs.
- **liquidity.py / direction_engine.py** — research-side engines; not in the live proposal path.

## bot/execution + reconcile
- ~~No persistent state across restarts~~ **PERSISTED 2026-07-05**: kill-switch, paper-autotrade
  toggle and paper dedup keys survive restarts via `data/runtime_state.json` (mode deliberately
  NOT restored — live re-earns its double gate every boot).
- ~~Poll-only reconcile~~ **SCHEDULED 2026-07-05**: `reconcile_once` runs every ~10 scan cycles
  while paper autotrade is armed (result on `/api/status` as `reconcile`). Broker fill-STREAM
  consumption remains phase 7.

## root files
- **risk.py** — complete (daily/weekly/streak/correlation/kelly). Portfolio-level exposure cap
  across simultaneous signals is advisory only (no hard netting).
- **tracker.py** — WAL + busy_timeout ✓ (2026-07-05). Options legs not tracked (see options).
- **prop.py** — eval-account ledger ✓; no multi-account support.
- **security.py / audit.py / approval.py** — complete for AITP scope.

## Cross-cutting (the honest blockers, in order)
1. **Model champion** — no candidate passes AUC/Brier gates; unchanged data now auto-skips
   retraining. New data required: L2 sync (user click) → live labels → 15m lineage.
2. **Paper evidence** — 07.3 needs a fresh research→replay→paper approval (version bump revoked
   07.2's); then paper autotrade collects the fills that unlock phases 7–8.
3. **TV compile** — STACK + AUTO carry 07.3 (OR_MID-obligatory arming) and are compile-pending.
