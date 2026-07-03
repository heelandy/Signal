# Change Implementation Log — bot review 2026-07-02

All changes on branch `claude/trading-bot-review-pq637q`. Rollback for any single change:
`git checkout <pre-review-commit> -- <file>`; the whole review reverts with
`git revert <review commit>`. Finding IDs reference `TRADING_BOT_COMPLETE_REVIEW.md` §19–22.

---

**2026-07-02 · HS-C1 · secrets/logs untracked**
Files: `BOT/conf/token.txt`, `BOT/webull_data_sdk.log*` (11), `BOT/config/{server.log, server.log.err, s8010.log, server.pid}`, 6× `debug.log`, `.claude/settings.json`, `.gitignore`
Reason: live Webull access token + runtime logs committed to source control.
Before: files tracked; any repo reader obtains a live data-API token.
After: `git rm --cached` (files stay on disk for the local SDK), `.gitignore` gains `*.log`,
`*.log.*`, `webull_data_sdk.log*`, `BOT/config/server.pid`, `BOT/conf/`, `token.txt`.
Tests: `git status` confirms untracked; ignore rules verified.
Result: PASS. Residual: token remains in git history → **rotate in the Webull portal**; consider
`git filter-repo` before sharing the remote.
Rollback: `git rm` reversal + delete the .gitignore block (not recommended).

---

**2026-07-02 · HS-C2 · duplicate-order prevention (webhook + manual ticket)**
File: `BOT/bot/api/server.py`
Before: each webhook/ticket built `OrderRequest` with a fresh UUID `idempotency_key` → every
retry/duplicate alert produced a new broker order.
After: `_already_submitted()` process-level key set (bounded 5,000); webhook keys on payload
`signalId` (if the Pine sends one) else the candidate's deterministic
`(symbol|side|setup|session|day)` key; manual tickets key on sha1 of full geometry
`(symbol|side|entry|stop|qty|day)`; duplicates return `{"action":"duplicate"}` without touching
the broker; the key is passed as `OrderRequest.idempotency_key` → Alpaca `client_order_id`
(broker-side dedup across restarts).
Tests: `test_repeated_webhook_creates_one_order`, `test_manual_ticket_dedup_and_distinct_orders_pass`,
`test_webhook_bad_token_rejected`, `test_kill_switch_blocks_webhook` — PASS.
Trading impact: none on first-time orders; retries/dupes are now no-ops.
Rollback: restore file from parent commit.

---

**2026-07-02 · HS-H1 · stale-data gate enforced on the live scan**
File: `BOT/bot/live.py`
Before: `decide(c, Account(equity=equity, source_healthy=True))` — hardcoded healthy.
After: new `source_health(bars, max_bar_age_min=15)` (market-truth QA + last-bar age vs system
time, fail-closed on empty/dirty/old); result feeds `Account.source_healthy` so the risk gate
returns `SOURCE_HEALTH_CRITICAL` on stale feeds; proposals expose `source_healthy`.
Tests: `test_fresh_feed_is_healthy`, `test_stale_feed_blocks_entries`,
`test_empty_and_dirty_feeds_fail_closed` — PASS.
Trading impact: proposals on a stale/dirty feed now show `risk_ok=false` (they previously showed
approved); intended behavior per the system's own market-truth design.
Rollback: restore file.

---

**2026-07-02 · HS-H1b · paper autotrade stale-guard**
File: `BOT/bot/api/server.py` (`_paper_autotrade`)
Before: paper bracket orders placed for any A+/A/B signal regardless of feed health.
After: signals with `source_healthy is False` are skipped.
Tests: covered via `source_health` tests + suite; no order path regression (45/45).
Rollback: remove the two-line guard.

---

**2026-07-02 · HS-H2 · OMS fill guards**
File: `BOT/bot/execution/oms.py` (`on_fill`)
Before: `qty=0` divided into avg-price math; duplicate broker fill events re-applied to the
position (doubling it); overfill unbounded.
After: qty ≤ 0 → ERROR event; fills on terminal orders (FILLED/CANCELLED/REJECTED/EXPIRED/ERROR)
→ ERROR "duplicate/late fill ignored"; overfill clamped to remaining order quantity.
Tests: `test_oms_rejects_zero_and_negative_fill`, `test_oms_ignores_duplicate_fill_event`,
`test_oms_clamps_overfill`, `test_oms_partial_fill_updates_quantity_and_avg` — PASS (plus the
module self-test).
Rollback: restore file.

---

**2026-07-02 · HS-H3 · constant-time webhook/API token check**
File: `BOT/bot/api/server.py`
Before: `p.get("token") != settings.webhook_token` and header `!=` compare.
After: `bot.security.verify_token` (`hmac.compare_digest`) in both places.
Tests: `test_webhook_bad_token_rejected` — PASS.
Rollback: restore file.

---

**2026-07-02 · HS-H4 · Pine close-confirm entries gated on confirmed bars**
Files: `production/HIGHSTRIKE_ORB_AUTO.pine`, `production/HIGHSTRIKE_ORB_STACK.pine`
Before: AUTO runs `calc_on_every_tick=true`; close-confirm conditions read `close` and could fire
mid-bar on the realtime bar (entries/alerts the finished candle never confirms — live ≠ backtest).
After: `cc_bar_ok = not conf_close or barstate.isconfirmed` added to the AUTO entry condition and
the STACK signal latch. Historical bars are always confirmed → backtests unchanged; live now fires
only on the closed candle in close-confirm mode. Wick/touch mode keeps intrabar behavior by design.
Tests: not compilable here — **action: load both scripts in TradingView (compile check) and
forward-paper-test**; logic change is minimal and additive.
Rollback: remove `and cc_bar_ok` + the `cc_bar_ok` line in each file.

---

**2026-07-02 · HS-H6 · auth on control endpoints**
File: `BOT/bot/api/server.py`
Before: `/api/control/mode`, `/api/control/paper_autotrade`, `/api/control/kill` unauthenticated
even with `API_REQUIRE_AUTH=true`.
After: mode + paper toggle behind `Depends(auth)`; kill **arm** always allowed (emergency stop),
kill **disarm** token-gated.
Tests: suite passes with auth disabled default; behavior inspected (auth off by default preserves
current UX).
Rollback: restore file.

---

**2026-07-02 · HS-H5 · tracker same-bar conservative outcome**
File: `BOT/bot/tracker.py` (`_walk`)
Before: after TP1, a bar containing both the stop and TP2 scored TP2 (+4R, optimistic) — inflated
the live-vs-backtest scorecard that gates sizing up.
After: stop checked before TP2 in all states (matches the engine's stop-first convention and the
documented BACKTEST_REF model).
Tests: `test_walk_same_bar_stop_and_tp2_after_tp1_scores_stop`,
`test_walk_same_bar_stop_and_tp1_scores_stop`, `test_walk_clean_tp2_and_zero_risk_guard` — PASS.
Trading impact: already-recorded outcomes unchanged (DB rows are final once closed); future
tracked outcomes are equal or more conservative.
Rollback: restore file.

---

**2026-07-02 · HS-H7/M10 · tracker self-test unpack + missing data dir**
File: `BOT/bot/tracker.py`
Before: `out, r = _walk(...)` (4-tuple) crashed the self-test; `_con()` crashed on a fresh
checkout (`BOT/data/` absent).
After: 4-value unpack; `DB.parent.mkdir(parents=True, exist_ok=True)`.
Tests: `python -m bot.tracker` → "tracker OK".
Rollback: restore file.

---

**2026-07-02 · PERF-1/2/3 · hs_harness optimizations (output-identical)**
File: `engine/hs_harness.py`
1. `pivots()` vectorized fast path for constant lookback (rolling max/min both directions; loop
   kept for the adaptive path). 2. `_macro_regime` per-bar `.iloc` → numpy views. 3.
   `_zones_sweep_patterns` per-bar `np.max/np.min` slices → precomputed shifted rolling extremes.
Measurement: see `PERFORMANCE_REPORT.md` (before/after, method).
Validation: scripted old-vs-new comparison — 30 state columns identical on 3 seeds (n=777, 5000,
adaptive path) + permanent regression test `test_pivots_fast_path_matches_loop_path`.
Trade-offs: none functional; +~20 lines.
Rollback: restore file (behavior identical either way).

---

**2026-07-02 · TESTS · new regression suite**
File: `BOT/tests/test_review_fixes.py` (new, 24 tests)
Result: full suite 45 passed / 0 failed (`pytest BOT/tests -q`).

---

**2026-07-02 · HS-H8 · ORB zone state machine (state-staleness fix) + entries-cap 0=unlimited**
Files: `production/HIGHSTRIKE_ORB_STACK.pine`, `production/HIGHSTRIKE_ORB_AUTO.pine`,
`BOT/bot/strategy/orb_state.py` (new), `BOT/bot/strategy/families.py`, `BOT/bot/live.py`,
`BOT/bot/api/server.py`, `BOT/tests/test_orb_state.py` (new, 15 tests)
Reason: a pending side had NO invalidation path — the dashboard showed "LONG ARMED @ 730.01"
with price at 719, below the OR low AND below the proposed stop (user screenshot, QQQ 5m).
Before: pending state persisted regardless of structure break; AUTO's resting order kept resting.
After (mirrored long/short, confirmed bars only):
  * HARD INVALIDATE: confirmed close beyond the OPPOSITE OR edge, or the side's proposed stop
    tagged pre-entry -> entry/stop/TP cleared, resting order cancelled (`strategy.cancel` via the
    arm condition in AUTO; `pending_cancelled` flag in Python), side blocked.
  * Reclaim of the breakout edge on a confirmed close -> WAITING; a completely NEW confirmation
    is required to re-arm (hysteresis — no flip-flop, no same-structure re-arm).
  * SOFT WATCH: confirmed close on the wrong side of OR mid pulls the pending entry until price
    re-crosses the mid (fresh break still required).
  * Dashboard: new INVALID (dark red) / WATCH (orange) states with the reclaim level in the
    "why" text; entry lines (bright + dim) cleared while INVALID.
  * Bot: proposals now carry `or_high/or_low` + `signal_state` (active|watch|invalid|unknown);
    paper autotrade and the shadow tracker skip `invalid` signals.
  * Entries cap: `0 = UNLIMITED` supported in STACK (manual mode) and AUTO (state machine still
    forces a fresh confirmed break per entry and hard-blocks an INVALID side).
  * `bot/strategy/orb_state.py`: mirrored FSM + spec math (Kaufman ER with zero-path guard,
    noise-thresholded directional persistence, mean-normalized regression slope, zone_of).
Tests: 15 new (screenshot scenario, stop-tag invalidation, soft-cancel/re-break, hysteresis,
stop-first same-bar, exact long/short mirror via reflected prices, zones, ER/persistence/slope
invariants, monotonic sequences, bad-geometry rejection) — suite 60/60 PASS.
Residual: Pine edits need a TradingView compile + forward check (no compiler here).
Rollback: restore the four edited files; delete the two new files.

---

**2026-07-02 · HS-H9 · 1-minute direction feed (structure + slope at 1m speed on any chart TF)**
Files: `production/HIGHSTRIKE_ORB_STACK.pine`, `production/HIGHSTRIKE_ORB_AUTO.pine`,
`BOT/bot/strategy/orb_state.py` (fast_direction), `BOT/bot/live.py`, `BOT/tests/test_orb_state.py`
Reason: user screenshots — 5m structure read "Bullish Trend" (and DIR-fast OR/Slope arrows read UP)
while price had dumped below the OR low; the 1m chart's structure followed price correctly. Bar-based
pivot confirmation scales with the timeframe (lb=5 -> 25 min on 5m vs 5 min on 1m).
Before: st_state, the DIR-fast Struct/Slope arrows, and the trend gate were chart-TF only; the
DIR-fast OR arrow displayed the FROZEN 10:00 day bias as if it were a live read.
After: new `fast_dir` input (default ON) runs the identical structure machine in the 1-MINUTE
context via request.security (lookahead_off) — the trend gate + DIR-fast read at 1m speed on every
chart timeframe, each context keeping its own automatic pivot lookback (futures 3 / equity 5);
slope likewise from the 1m context (12-minute window). DIR-fast OR arrow now shows the LIVE zone
(price vs OR high/mid/low). Stop anchors unchanged (chart-TF swings — validated risk geometry).
Bot proposals gain `dir_fast` votes from a best-effort 1m fetch.
Tests: fast_direction vote tests + a timing regression proving the 1m structure flips DOWN >=10
wall-clock minutes before the 5m structure on the same tape — suite 63/63 PASS.
Residual: needs TradingView compile + the standard gauntlet run for the 1m-fed GATE (behavior
change vs the chart-TF backtest); revert toggle provided (`fast_dir` OFF).
Rollback: restore the four edited files.

---

**2026-07-02 · HS-H10 · combined slope engine everywhere (user research spec) + notes**
Files: `BOT/bot/strategy/orb_state.py` (slope_engine, directional_state, fast_direction upgrade),
`BOT/bot/live.py` (opens+ATR into dir_fast), all 5 `production/*.pine` (f_slope_comb in the 1m
feed + dashboard S row; STACK DIR-fast shows S + ALIGNED tag), `research/orb_slope_state.py`
(new gauntlet), `research/RESEARCH_NOTES.md` (F65 plan entry), `BOT/tests/test_orb_state.py` (+6).
Reason: user research doc — slope must be COMPUTED in the BOT and every script (not visual-only),
as S = 0.50·Sc/ATR + 0.30·Sm/ATR + 0.20·BodyPressure with the 7-state classifier; alignment of
OR+SLOPE+STRUC = direction. Attack order recorded: 1 OR (done) → 2 SLOPE → 3 STRUC.
Validation here: 71/71 tests (doc worked examples: dip-still-positive, choppy≠bullish, STRONG_UP
arrays, mirror symmetry, scale invariance, zero-ATR/flat guards, slope-alone-never-calls-direction).
Numbers pending: `orb_slope_state.py` gauntlet on the data drive (thresholds are per-TF).
Rollback: restore listed files; delete the research script.

---

**2026-07-03 · HS-H11 · gap-aware CHoCH (8 structure machines) + multi-TF rolling direction engine**
Files: `engine/hs_harness.py` (P.choch_gap_aware=True, relaxed CHoCH + claim guard),
`production/HIGHSTRIKE_ORB_STACK.pine` / `_AUTO.pine` / `_OPTIONS.pine` / `_V1_STRATEGY.pine`
(chart + f_struct_1m machines, mirrored edits), `BOT/bot/strategy/direction_engine.py` (NEW),
`BOT/bot/live.py` (`mtf_direction` on proposals), `BOT/bot/api/server.py` (`/api/direction`),
`BOT/tests/test_structure_velocity.py` (NEW, 13 tests), `research/RESEARCH_NOTES.md` (F65 STRUC
updates), `production/CHANGELOG.md`.
Reason: user — structure too slow (~15 closed 1m bars to know direction; price past the ORs by
then); wants every-2-bars checks updated every 10–15 s; keep the current 1m feed as BACKUP.
Root cause found: the old CHoCH required a CROSSING bar, but in fast moves the swing reference
steps toward price via newly confirmed pivots so the crossing never exists — st_state stale 41
bars on the diagnostic tape (0↔1 oscillation from leftover HH/HL claims).
After: flip on any close beyond the last swing against the trend (once-only) + claim guard
(UP needs close ≥ last swing low, mirrored); rolling engine scores every TF from the same 1m
array each completed bar (D = 0.30S+0.20P+0.20E+0.15B+0.15M, bands ±0.12/±0.30/±0.65, RANGE
override, ROLLING vs clock-aligned CONFIRMED, live-price IMMEDIATE read). Detection only —
dir_fast + confirmed st_state remain the gate/backup.
Validation: 41→0 violations; bit-identical on clean trends both directions; research-file
pullback example reproduces; mirror symmetry; suite 84/84 PASS.
Residual: TradingView compile (4 scripts); gauntlet A/B `choch_gap_aware=False` on the data
drive (gate behavior change); rolling engine has NO edge numbers yet — do not gate on it.
Rollback: `choch_gap_aware=False` (engine) / restore the 4 Pine; delete direction_engine.py +
the live.py/server.py hooks.

---

**2026-07-03 · HS-H12 · WATCH-before-ARMED promotion (OR-mid pass with clear direction)**
Files: `BOT/bot/strategy/orb_state.py` (WAITING→WATCH promotion, live-bias WATCH→WAITING
demotion, `on_bar(open_px=…)`), `production/HIGHSTRIKE_ORB_STACK.pine` +
`_OPTIONS.pine` (`l_watch`/`s_watch` confirmed full-body latches; state labels; OPTIONS WATCH
color), `BOT/tests/test_orb_state.py` (+4), `production/CHANGELOG.md`.
Reason: user — "price must pass the OR-mid bias… the 'watch' before the armed; price cross on
either side with clear direction we on 'watch'". Audit found the mid-pass GATE already enforced
(FSM arm() refuses close on the wrong side of the mid; Pine arm conditions carry
`not l_below_mid`) and the ARMED→WATCH soft cancel present, but WATCH was reachable only by
DEMOTION — no visible WAITING→WATCH stage when price crossed the mid toward a side.
After: confirmed FULL-BODY close beyond the OR mid toward a side promotes it to WATCH; the
watch follows the live mid bias (confirmed cross back = demote to WAITING, mirror side
promotes); hard invalidation always wins; exact long/short mirror. AUTO/V1_STRATEGY: no state
display — behavior already consistent via their arm conditions, no edit needed.
Validation: suite 88/88 (promotion, clear-direction body requirement, live-bias mirror flip,
promotion-never-overrides-invalidation). Entry firing logic UNCHANGED — display + FSM stage only.
Residual: TradingView compile-check (STACK, OPTIONS).
Rollback: restore the 2 Pine + orb_state.py.

---

**2026-07-03 · HS-H13 · probable liquidity-zone engine + reversal machine (research side only)**
Files: `research/orb_liquidity_zones.py` (NEW), `research/RESEARCH_NOTES.md` (F67).
Reason: user research doc 'Research over probabilistic area' — infer PROBABLE entry/stop/liquidity
zones from 1m OHLCV (never claiming to see actual orders) + bounce-vs-reversal state machine.
User instruction: research side ONLY, no STACK/BOT propagation yet; when it graduates, STACK +
BOT are the PRIMARY targets (standing rule recorded in F67).
Scope: detectors (pivot clusters, equal H/L, rejection/absorption, OR/session/prev-day levels,
volume-by-price POC/HVN), ATR-scaled merge, L = 0.25T+0.20V+0.20R+0.15S+0.10H+0.10A scoring with
MAJOR/STRONG/MODERATE/WEAK bands, zone dicts matching the doc's data structure, mirrored
6-check reversal machine with 2-of-3 noise-control votes, data-drive evaluation mode (zone
hit-rate vs random in-range control levels).
Validation: --selftest green (support cluster, mirror, absorption, doc walkthrough, failed
bounce, bearish mirror). Suite untouched: 88/88.
Numbers pending: data-drive run (needs the *_continuous_1m.parquet views), then the standard
additivity gauntlet before any gate/size use.
Rollback: delete the research script + F67 note (no production surface touched).
