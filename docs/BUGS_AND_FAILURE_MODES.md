# HIGHSTRIKE — bugs & failure modes across the whole project (2026-07-08)

Every class of bug that can happen here, by plane, with **symptom · cause · guard/fix**. Fixed
ones are marked ✅ (with the guard that prevents regression); latent risks are marked ⚠️. This is
the checklist to run against before trusting any result or shipping any change.

---

## 1. DATA plane

| # | Failure | Symptom | Cause | Guard / fix |
|---|---|---|---|---|
| D1 ✅ | Unit mismatch µs/ns | searchsorted silently matches nothing → 0 trades | pandas 3.0 stores bars as `datetime64[us]`; int64 epochs come out ns | compare `datetime64[ns]` on both sides (target_geometry.py) |
| D2 ✅ | Timezone drift | signals/journal off by hours; DST double-count | UTC vs ET wall-clock joins | ET pinned in SQL; OPRA `minute` in ET; journal joins in UTC minutes |
| D3 ⚠️ | Stale live feed | signals off a frozen quote; wrong entries | provider returns last-good bar during an outage | `source_healthy` gate blocks orders; but scan still scores — verify bar age (QQQ was 9 min old, OK) |
| D4 ✅ | Provider mislabel | QQQ data registered as NQ, mixes symbols | user picked the wrong symbol at registration | auto-label from the file's own `symbol` column; user pick = fallback only |
| D5 ✅ | Duplicate file re-synth | wasted hours; lying registry | same content via a 2nd path (D: copy, ` (1)` twin) | content fingerprint (normalized basename + size) → `duplicate` skip |
| D6 ⚠️ | Databento dir-shaped `*.csv` | reader treats a directory as a file | day-shards are directories | rglob descends to the inner file; OPRA read handles it |
| D7 ⚠️ | Removable scaffolding left in | MBO-derived bars pollute the official store | forgot `--remove` after real OHLCV lands | manifest records the seam; `hs_mbo_bars.py --remove` restores byte-exact |

## 2. DECISION plane (entries & geometry)

| # | Failure | Symptom | Cause | Guard / fix |
|---|---|---|---|---|
| E1 ✅ | **TP1 == TP2** | corrupt row; phantom "tp2" the instant one target hits | single-target lineages wrote the one target into both slots | workers set `tp2=None`; `_walk` single-target; `_levels_ok` REJECTS tp1==tp2 |
| E2 ✅ | Same-bar entry/TP/stop | a 15m row "hits TP on the entry bar" | 5m bars INSIDE the signal candle walked pre-entry | walk starts at `signal_at + (tf−5)min` |
| E3 ✅ | Same-bar stop+target ambiguity | optimistic scoring | intrabar order unknown | score the STOP first (conservative) always |
| E4 ⚠️ | **Wrong-side stop reaches broker** | broken order placed; journal rejects the row (`family=null`) | a signal path emits inverted geometry | `_levels_ok` rejects at journal; **NEW** paper-autotrade geometry guard; `TradeCandidate` validates at source |
| E5 ✅ | Degenerate dedup key | one row per sym/family/session/side ever; signal_at NULL → stuck "open" | proposals lacked candidate bar identity | bar identity (`generated_at`) MANDATORY for auto rows |
| E6 ⚠️ | **PULLBACK never fires** | the WATCH→PULLBACK state is dead | disabled on equities (chase_atr=0); on futures the FILL pre-empts it (price crosses the edge → fills before it can extend 1.5×ATR) | by design mostly; to activate: lower chase_atr or check chase before fill (needs a gauntlet) |
| E7 ⚠️ | Goal infeasible for the geometry | can't reach WR 75-85 at TP1=1.5R | only ~50% of trades reach 1.5R → WR ceiling ~50% | target_from_goal.py surfaces it; needs a CLOSER target (~0.33-0.5R) or better entries |
| E8 ⚠️ | Rule-version desync | Pine ≠ BOT ≠ engine | a knob changed on one surface only | `test_pine_config_sync.py`; one source of truth (`asset_config`) |

## 3. LEARNING plane (journal → training)

| # | Failure | Symptom | Cause | Guard / fix |
|---|---|---|---|---|
| L1 ⚠️ | **Corpus starvation** | "no improvement"; "insufficient sample" | ORB is selective → journal grows slowly (14 core rows now) | expected; needs forward accrual or backfill — NOT a bug, the sample gate holds |
| L2 ⚠️ | All-loser sample | model trains on 100% losses; live −14R | an adverse streak on a tiny N (14/14 stops, verified genuine) | sample gate refuses to promote; watch for L3 |
| L3 ⚠️ | **Live ≠ backtest entries** | live loses while backtest wins | live fills at a different bar/price than the engine assumes | the sample gate is the tripwire; run a live-vs-backtest entry audit when N grows |
| L4 ✅ | Non-core contamination | worker/trail rows train the core lineage; 14-vs-10 mismatch | tight-target geometry unioned into core dataset | `CORE_ONLY_SQL` + `is_core_family` exclude worker-/emergent-/trail-/options-native- |
| L5 ✅ | tf mismatch | 5m rows train the 15m lineage | union ignored timeframe | tf-matched union (5m→5m, 15m→15m) |
| L6 ⚠️ | Brier/AUC gate gaming | a model "passes" on a lucky slice | small OOS window | 7-check gauntlet, OOS judges, no gate loosening |

## 4. OPTIONS plane

| # | Failure | Symptom | Cause | Guard / fix |
|---|---|---|---|---|
| O1 ✅ | **Flat-IV mispricing** | panel prices every option wrong | shipped `iv=0.20` vs real 0DTE ~38% | F85 calibration: `default_iv(dte)` + `calibrate_realized_iv` (×1.56) |
| O2 ✅ | BS proxy destroys the edge | options-native PF 1.69→1.1 | BS flat-IV can't price 0DTE skew/smile | journal ONLY on a real chain; BS rows flagged advisory |
| O3 ✅ | Strike-window artifact | backtest PF 1.71 vs live 1.35 | research loaded ±3.5% strikes, dropped 2.0×EM directional legs | load the full window; share ONE geometry module (research≡live) |
| O4 ⚠️ | Naked short tail | −340%/day | selling premium undefined-risk | defined-risk only (iron condor); the naked straddle is dead (G3) |
| O5 ⚠️ | Needs a real feed | options-native can't accrue forward | no live chain | **Alpaca options data confirmed** (94.7% two-sided) — wire it in |
| O6 ⚠️ | OCC parse errors | wrong strike/expiry | fixed-width OCC, strike in millis, rtype-193 status rows | SQL substr parse; `/1000`; filter on populated bid/ask (not rtype) |
| O7 ✅ | **THE 0-DAY ERROR** | a non-0DTE position priced/settled as if it expires TODAY — mispriced P&L, force-closed 1-2 days early at the wrong price | `alpaca_chain_0dte` took the NEAREST expiry as "0DTE-ish" and no caller checked `is_0dte`, while `manage_open` force-settles at today's 15:55 close. On a day with no same-day expiry the nearest is 1-2 DTE, so today's intrinsic is the wrong settle value | gate the live chain to a TRUE 0DTE (`require_0dte`: refuse when `expiry != today`, so live matches the backtest's `dte=0`); store the position's `expiry` and settle at the EXPIRY date's close, never an earlier day's |
| O8 ⚠️ | Backtest ≠ live perf | the per-structure scorecard is 100% backtest (`opra_chain`) until real fills land | live path (`manage_open`) only journals `alpaca_live` closes once approved + trading | scorecard now splits `backtest_n` / `live_n` per structure so the source is explicit; live rows accrue as they close |
| O9 ✅ | 0DTE time-of-day mispricing | a 15:00 contract's greeks priced as if 6h remain | `describe`/`bs_quote` used a fixed 360-min T | `describe` now uses `_mins_to_close()` (live minutes to 16:00 ET, floored at 1); display only — real credit/max-loss come from the chain bid/ask |
| O10 ✅ | 0-div in research P&L | `pnl/ml` crash if credit ≥ wing (ml ≤ 0) | `opra_smallacct`/`opra_longer_dte` guarded `wing>0`, not `wing>credit` | guard now `wing > credit` (max-loss > 0) before dividing |
| O11 ✅ | **7DTE condor was SIGNAL-ONLY (perf never fills)** | the `condor_7dte` scorecard bucket would stay empty forever; "accrues forward paper" was not true | `condor_7dte` was wired ONLY into the live SIGNAL endpoint. `record_session` iterates the 0DTE `STRUCTURES` and `manage_open` entered only 0DTE `credit_spread` — nothing journalled or settled a 7-day hold | FIXED: `_options_native_live` now enters one `condor_7dte`/session (slot `7d`) and marks EVERY open on the chain matching ITS expiry (7DTE opens on the 7-day chain via `alpaca_chain_dte`, 0DTE on the 0DTE chain), settling only at the stored expiry's close (O7). Test `test_manage_holds_until_stored_expiry` |
| O12 ✅ | **7DTE managed ≠ hold (the edge IS the management)** | held to expiry the F89 geometry is only **PF 1.08 / WR 72.2% — OUT of band**; a naive live path that holds to settle loses the whole edge | `manage_open` applied ONE global spec to all opens; a 7DTE condor managed on the 0DTE `SPEC` would use the wrong tp/stop. The +0.122R / PF 1.73 needs the early TP at 0.6×credit (research≠live trap, [[cross-check-research-vs-live]]) | FIXED: `manage_open` resolves the spec PER POSITION (`dict(spec, **STRUCTURE_SPECS[struct])`), so `condor_7dte` manages on `SPEC_7DTE` (tp 0.6) regardless of the caller's spec. Stop is cosmetic (never binds) → size on the FULL wing. Tests `test_manage_tp_at_7dte_spec`, `test_manage_tp_override_ignores_global_spec` |
| O13 ✅ | **Live signal DROPPED the strikes → instant false TP** | the managed 0DTE credit spread (and 7DTE condor) would TP on management tick 1 at +tp·credit, every time, off a phantom fill | `live_signal_from_alpaca` returned `describe()` output, which emits only `legs` for display and OMITS `ksc/klc/ksp/klp`. `open_position` stored them as None → `manage_open`'s `mark_cost` saw all-None legs → cost 0 → `pnl_now == credit >= tp·credit` → false TP | FIXED: `live_signal_from_alpaca` now merges the raw geometry (`ksc/klc/ksp/klp/cp/long_k/short_k/structure_type/spot_entry`) back onto the signal so a position can be re-priced. Tests `test_live_signal_carries_strikes`, `test_manage_no_false_tp_when_no_profit`. **Pre-existing — also fixes the shipped 0DTE credit-spread manager.** |

**0-DAY SWEEP (whole project, 2026-07-08):** BS core (`pricing.price`/`greeks`) guards `T<=0`→intrinsic and `year_frac` floors at 1 min ✅. Pine `f_bs` has no internal `T>0` guard but its ONE caller floors `T=max(30, 960-mins)/390/252` so `sqrt(T)` is never 0 ✅. `translate`/`exit_plan`/`options_replay` `_t_years` all floor ✅. Real 0-day bugs found & fixed: **O7** (settle non-0DTE at today), **O9** (fixed-T display), **O10** (research 0-div). The one that mattered was O7. **Regression-locked 2026-07-08:** `BOT/tests/test_zero_day_options.py` (13 tests) pins the chain 0DTE gate (refuse when nearest expiry ≠ today), `manage_open` settling only at the STORED expiry close (a future expiry stays open), the `ret_on_risk`/`describe` 0-max-loss guards, and the live minutes-to-close greeks — so a later edit or a stale server (R1) can't silently reintroduce them.

## 5. GOVERNANCE plane

| # | Failure | Symptom | Cause | Guard / fix |
|---|---|---|---|---|
| G1 ✅ | Auto-adopt an unproven lineage | a draft trades on IS luck | evolution/worker promoted without OOS | nothing auto-adopts; `LIVE_APPROVED.lock` manual forever |
| G2 ⚠️ | Phase 7→8 premature | advances on a thin sample | self-eval window too small | ≥60 core trades, ≥8wk, scorecard-consistent, no inversion |
| G3 ⚠️ | Correlated one-macro-bet | 5 shorts on correlated names = 1 bet ×5 | same-direction fires on QQQ/SPY/NQ | Boss correlation buckets; only the lead places (stand_down) |
| G4 ⚠️ | Approval bypass | a revoke doesn't take effect | cached approval | re-checked every scan cycle |

## 6. OPS / RUNTIME

| # | Failure | Symptom | Cause | Guard / fix |
|---|---|---|---|---|
| R1 ⚠️ | **Stale server (no --reload)** | code changes not live; old bugs persist (the `family=null` rejects) | server started without reload; runs old code all day | RESTART after code changes; relaunch via run_server |
| R2 ⚠️ | Stacked/zombie pythons | 8 instances serving 13-min-old code; OOM | dead reload watcher; repeated starts | sweep all python, single clean start |
| R3 ⚠️ | OOM | box killed; job dies mid-run (the OPRA concat) | heavy python concurrent with the server/OneDrive | never run heavy python concurrently; duckdb 1GB/1-thread/temp-spill; stream, don't materialize |
| R4 ✅ | OneDrive file lock | PermissionError on rewrite | OneDrive.exe holds the handle | migrated OFF OneDrive; retry + rename-aside |
| R5 ✅ | cp1252 console crash | intake dies at a `�` print | Windows console can't encode replacement char | `sys.stdout.reconfigure(utf-8)` |
| R6 ⚠️ | Copied-venv shim paths | `.exe` shims point at the old path | venv copied, not recreated | `python -m` works; recreate venv if pip needed |
| R7 ⚠️ | Re-place paper order on restart | duplicate order after a restart | placed-set not persisted | `_persist_runtime()` after each placement; dedup key |
| R8 ⚠️ | Folder-scan cap truncation | a 2-year intake lands only 50 sessions | `register` broke at 50 files | cap raised to 5000 + fingerprint dedup |

## 7. UI / API SERVING plane (dashboard review, 2026-07-09)

| # | Failure | Symptom | Cause | Guard / fix |
|---|---|---|---|---|
| U1 ✅ | **`latest_price` NameError (whole endpoint aborts)** | Selected Contract shows "chain closed" ALWAYS (even RTH); options-native paper loop never enters/manages a trade | `latest_price` is imported INSIDE some functions but was USED without importing in `options_native_feed` + `_options_native_live` → NameError → the function's `try/except` swallows it before any pricing runs | import `latest_price` locally in both; **scanned every endpoint (`test_serving_imports`) — the whole class is cleared** |
| U2 ✅ | **Live-vs-backtest "insufficient sample" with 18 trades** | verdict stuck at "insufficient sample" though 18 taken+closed exist — HID that live is net-negative | `target = by_grade["A"] or overall` judged the tiny grade-A subset whenever ANY grade-A trade existed | judge grade-A only when its own `n >= MIN_SAMPLE`, else the full book; surfaces the honest verdict |
| U3 ✅ | **Selected Contract "only QQQ"** | a multi-symbol options lineage (volbreak-0dte QQQ/SPY) could only price QQQ | the feed used `underlyings[0]`; no picker | `?underlying=` param + a `#ctrund` picker shown when the lineage trades >1 symbol; feed labels the picked underlying (was defaulting to QQQ) |
| U4 ✅ | **Approval doesn't reflect on the dashboard** | approve a lineage → nothing moves in Bot-Strategies | `loadStrategies` cached `/api/duel` (`if(!DUELD)`) and never re-fetched | always re-fetch; `test_lineage_duel_sync` locks the lineage↔duel↔render chain |
| U5 ✅ | **Options-data merge/scale (MBP-10 API)** | `l2_depth_imb` ~3.5e6 (should be ∈[-1,1]); one feature column with two meanings | Databento sizes are UNSIGNED (`bid_sz-ask_sz` underflows to ~4e9); `l2_quote_rate` written by both flow AND book synthesis | cast sizes to float64; drop `l2_quote_rate` from the depth merge; crossed-book (`ask<bid`) guard |

**Full panel sweep 2026-07-09** (every Training-Lab + dashboard panel run independently; regression-locked in `BOT/tests/test_review_bugs_2.py`, 10 tests):

| # | Failure | Symptom | Cause | Guard / fix |
|---|---|---|---|---|
| T1 ✅ | **PIT features never reached the journal (learning starved)** | ALL 30 journal rows had every feature NaN → `trainable_with_features: 0` forever; "the journal IS the dataset" fed nothing | `families.scan` computes `pit_features` per candidate and `live.py` even uses it locally, but the PROPOSAL dict `scan_watchlist` returns never copied the field — the autotracker/boss stored `s.get("pit_features")` = None on every decision | one-line plumb: the proposal now carries `pit_features`; features accrue on every new tracked signal (old rows stay NaN — their snapshot moment has passed) |
| T2 ✅ | **"Latest training run" always empty** | zoo charts/gates/buckets blank though real ml/nn runs exist | `phase78` re-saves itself hourly → newest mtime → sorted first, but it has `created_at: null` and no zoo — the panel rendered IT by default | `list_reports` drops un-timestamped STUDY reports (they have their own panels) |
| T3 ✅ | **Strategy duel frozen on month-old data** | equity duelists armed on 2026-06-08 bars; `max_days=1` volbreak positions "open" for a month; duel never advanced | duel frames came from the curated hs_db snapshot (equities end 2026-06-08) with no live extension | `_live_daily_frame`: hs_db + live daily bars (completed only — today's forming bar excluded), indicators recomputed on the merged frame |
| T4 ✅ | Orphaned duel state after the volbreak split | 3 phantom "open" positions + 1 invisible closed trade under `daily_volbreak` (module no longer exists) | rename/split left state rows with no owner; the UI iterates DUELISTS so they never showed | `_migrate` on every load: closed rows remap by symbol into the split books; orphan armed markers dropped |
| T5 ✅ | Stale volbreak arm books a bogus fill | a 1-day arm left open across a data gap would "resolve" against a much-later bar's bands | `_resolve` walks only the newest bar; nothing checked the gap | stale-arm guard: volbreak arms >4 days old are dropped as scratch |
| T6 ✅ | Blanket "IN THE DUEL" badge (training lab) | every research-approved lineage looked equally live | the lab's duel table ignored the `stage` map (dashboard was already fixed) | shows the highest APPROVED stage (`PAPER ✓`) per lineage |
| D1 ✅ | Vol-Expansion always "narrow OR" | Underlying Signals showed narrow OR on every signal, wide or not | UI read `s.vol_exp`; the signal field is `vol_expansion` — undefined is falsy | field name fixed |
| D2 ✅ | **Alerts panel stuck at "no alerts yet"** | alert history never appeared in the panel (beeps/toasts fine) | the "alert on new" CHECKBOX and the panel DIV shared `id="alerts"` — the selector returned the checkbox, so `renderAlerts` wrote history into the checkbox's innerHTML | checkbox renamed `alerton`; ids unique (regression-locked) |
| D3 ✅ | Equity curve flat + Attribution empty next to a 30-trade Performance panel | `/api/equity` = `[25000]`, `/api/attribution` = `{}` while `/api/performance` showed 30 trades | equity/attribution read the REPLAY journal, which the live scan never writes (`persist=False`); performance reads the tracker | both endpoints now prefer the tracked live record (same population as `/api/performance`), replay journal as fallback |
| D4 ✅ | **Header frozen at "market: unknown" + dead feed dot for HOURS** | `/api/market` served `{"regime":"unknown"}` with a 16:05 timestamp at 19:00 — the DATA FEED dot went yellow "—" and stayed | `market_context` pinned **yahoo** for SPY (rate-limits at the close) with no error guard; the FAILED context was cached into `_latest["market"]` and `or` treated it as valid — a frozen failure that never healed | `_series` never raises; SPY via the provider CHAIN (webull covers it); last-good context served through hiccups (marked `stale`); `/api/market` recomputes when the cache is a failure or >15 min old |

**OPS addendum (same sweep):** the worker crashing with `BOT_CONT_TRAINING=1` (continuous training kills the scan loop → snapshot frozen, scanning=True stale) is mitigated by scan-only + the **watchdog** (`BOT/watchdog.ps1`, health-check every 30s → relaunch via `start.ps1`; single-instance mutex; auto-start at logon via `install_autostart.ps1` → Startup-folder VBS). `stop.ps1` kills the watchdog FIRST (else it resurrects the server ~30s later); `stop.ps1 -KeepGuard` = deliberate restart-through-watchdog.

## How to use this
Before trusting a result: check the relevant plane's rows. Before shipping a change: does it touch
a ✅ guard? keep the guard. Most production bugs here were **one source of truth drifting into two**
(Pine≠BOT, research≠live, journal≠engine) — when in doubt, reconcile the two copies.
