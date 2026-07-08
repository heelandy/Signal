# OPRA OPTIONS STUDY + DEDUP-PROOF REGISTRY — design doc (2026-07-08)

User order: "make register path so duplicated files do not happen · with the OPRA we have,
start the options-side study, full run until the goal is met · documentation first, then
implementation, optimization, errors-and-fixes, performance." This document IS that first step;
the implementation follows it exactly.

---

## PART 1 — dedup-proof registration

### Problem
Registration dedups by exact `(path, symbol)` only. The same DATA can still enter twice via a
different path — proven risks already on disk: the archive copied to the new home AND still on
D:; `xnas-itch-...ohlcv-1m.csv` and its `... (1).csv` twin in data/raw; a re-extracted zip landing
in a new folder. Duplicate sources → double synthesis → (the minute-store dedups, so features
survive) wasted hours and a lying registry.

### Implementation
1. **Content fingerprint** per file at register time: `(basename-normalized, size_bytes)` —
   Databento basenames are unique per (venue, date, schema), so basename+size identifies the
   content without hashing gigabytes. Normalization strips Windows copy-suffixes (` (1)`, ` - Copy`).
2. A registered source whose fingerprint matches an EXISTING source (any path) is recorded as
   `{"duplicate_of": <id>, "path": ...}` and **skipped** — visible in the registry, never
   synthesized.
3. **Directory-shaped “files”**: Databento shards big days into a DIRECTORY named `*.csv`
   (OPRA does this). Registration now detects dir-with-single-member and registers the inner
   file; multi-member dirs register per member.

### Errors & fixes
- *Same content, different size* (re-download with more days appended): fingerprint differs →
  registers as new — CORRECT (it is new data); the minute-store append-merge dedups overlap.
- *Basename collision, different content* (two vendors, same name): size differs → no false dedup.
- *Legacy rows without fingerprints*: backfilled lazily on next `register()` call.

### Performance
Fingerprint = one `stat()` — O(1) per file; a 500-file folder scan stays < 1s.

---

## PART 2 — the OPRA options study

### The data (verified on disk)
`D:\OPRA-20260627-5VQCWWD67U` — OPRA.PILLAR `cbbo-1m`, **QQQ.OPT parent** = the ENTIRE QQQ
chain, 2026-05-27 → 2026-06-25 (~21 sessions, 13 GB, ~647 MB/day sharded in `*.csv/`
directories). Columns: ts_recv/ts_event, instrument_id, bid/ask px+sz (level 0), `symbol` =
OCC code (`QQQ   260717C00545000` → expiry 2026-07-17, C, strike 545.000).

### Goals (the "full run", in dependency order — each gate feeds the next)
- **G1 IV-truth**: market-implied IV from real ATM quotes vs our BS/realized-vol `iv_est` —
  calibrate or replace the estimator (every options panel and payoff study inherits this).
- **G2 Real-premium payoff replay**: re-run the ORB options gate (naked / debit / credit) with
  REAL entry-ask and exit-bid premiums including true spreads — confirm or amend the
  options-0.1 NAKED-only verdict that currently rests on modeled premiums.
- **G3 VRP module unblock**: real ATM straddle open/close premiums → the short-straddle
  research candidate finally judged on true prices (its blocker was exactly this data).
- **GOAL MET =** an options expression whose real-premium replay clears the user band
  (win-rate/PF analog on ret-per-premium) across the window AND survives spread-doubling
  stress; anything passing graduates to a lineage on the ladder (options-0.2 etc.).
  ~21 sessions is verdict-grade for pricing truth (G1) and DIRECTIONAL for G2/G3 — final
  adoption still wants the forward journal accruing.

### Implementation (two stages, deliberately split)
1. **`research/opra_extract.py`** — one duckdb pass per day-shard, memory-capped: filter to
   (a) expiry ≤ 30 days, (b) strike within ±6% of that day's QQQ spot (from our own bar store),
   (c) rtype = quote records with non-null bid/ask. Output ONE compact parquet
   (`data/opra_qqq_cbbo.parquet`, ~10-30 MB total) with: minute, expiry, strike, right,
   bid, ask, mid, sizes. Everything downstream reads the parquet, never the 13 GB again.
2. **`research/opra_study.py`** — the three goals off the parquet + our bar store + the
   canonical signal replay:
   - G1: per session, ATM contract at 10:00/12:00/15:00 → implied vol solved from mid via
     BS-inverse → compare to `iv_est`'s realized-vol number → report bias curve (by DTE).
   - G2: for each canonical QQQ signal in the window: entry = ASK at signal minute (0-1 DTE
     ATM per the live translation), exit = BID at underlying TP/stop/EOD minute → real
     ret/premium per structure; compare to the modeled replay's verdicts.
   - G3: ATM straddle mid at 09:35 vs 15:55 close-out per session → real VRP capture, worst-day
     tail, spread cost share.

### Optimization
- duckdb `SET memory_limit='1GB'; threads=1; preserve_insertion_order=false` (the OOM law) +
  projection pushdown (SELECT only 8 columns) + predicate pushdown (strike/expiry filters in SQL).
- OCC symbol parsing in SQL (`substr`) not pandas — 30-50M rows/day never reach Python.
- Day-shards processed one-per-process (the proven per-file pattern) — constant memory.
- The compact parquet makes every study re-run seconds, not a 13 GB pass — iterate freely
  ("until the goal is met") without re-touching raw.

### Errors that can happen — and their fixes (pre-cataloged)
| Error | Cause | Fix |
|---|---|---|
| Empty/`rtype 193` rows crash parsing | status records interleaved (seen in row 1) | SQL filter `bid_px_00 IS NOT NULL AND ask_px_00 > 0` |
| `*.csv` is a directory | Databento sharding (verified) | extractor globs `dir.csv/*`; registry Part-1 fix |
| OCC symbol misparse | padded spaces (`QQQ   26…`) | fixed-width substr on the 21-char OCC layout |
| Strike ×1000 confusion | OCC strike is millis (00545000 = 545.000) | `/1000.0` once, asserted vs spot magnitude |
| ts in ns epoch or ISO per shard | Databento encodings vary | the `_ts_expr`-style type probe (existing helper) |
| Crossed/zero-bid quotes | illiquid wings | drop `bid<=0 or ask<=bid` rows in extraction |
| OOM next to the running intake | 647 MB/day scans | QUEUED: the study auto-starts only AFTER the intake sentinel; caps as above |
| Missing sessions/holes | vendor gaps | per-day row-count manifest; studies skip absent days loudly |
| DST minute joins | ET↔UTC | all joins in UTC minutes (house rule) |

### Performance budget
Extraction: 21 shards × ~30-60 s capped = **15-25 min once**. Studies: seconds per run off the
parquet. Disk: +~30 MB. The raw 13 GB stays on D:, never copied (register-path law).

---

## RESULTS (2026-07-08 — the full run)

Extracted 22 sessions (2026-05-27..06-26) → `data/opra_qqq_cbbo.parquet` (17.5M ATM-window quote
rows, 158 MB) in ~22 min. Study report → `BOT/data/ml/reports/opra_study.json`. Full record: F85.

Two extraction-time realities differed from the design and were fixed in place:
- **rtype is not the quote discriminator** — every row is rtype 193; quotes are the rows with a
  POPULATED bid/ask. Filter is `bid>0 AND ask>bid` (as the error catalog above already anticipated).
- **the pandas concat of 22 shards OOM'd** the driver (18M rows at once). The combined parquet is
  now built with a streaming DuckDB `COPY`, and the study loads NEAR-ATM only (±2% via DuckDB) so
  it never materializes the full chain. Per-shard extraction was always constant-memory; only the
  final merge needed the streaming path.

**G1 — IV-truth (verdict-grade, 264 real ATM solves): the headline.** Real ATM IV averaged
**30.8%** vs the shipped flat **20%** (+10.8 pts); 0-1DTE **38.1%**, weekly 23.5%; market charges
**1.56× realized**; real 0DTE half-spread **$0.022 (1.8%)**. → shipped `pricing.default_iv(dte)`
+ `calibrate_realized_iv()` and wired them into `live.py`, `/api/contract`, `/api/options`,
`/api/exit_plan`. Every panel now prices at chain truth instead of 0.20.

**G2 — NAKED confirmed, de-rated.** Only 1 canonical signal fired in-window, so the real-premium
replay is anecdotal (N=1). The verdict comes from re-judging the full 287-trade NAKED replay at
the OPRA-measured IV+spread: **gate PASS** (PF 2.45, CI-lo +0.29), still **PASS at 2× spread**
(PF 2.22). The 20%→38% IV correction ~halved the modeled edge but didn't kill it.

**G3 — VRP refuted (this window).** Short ATM 0DTE straddle on real bids lost (avg −4.8%, PF 0.86,
worst day −340%). Directional over 22 sessions, but not deployable on real prices here.

**Goal.** The literal bar (real-premium expression clearing the WR/PF band + surviving spread-
doubling) is NOT met on 22 sessions — real-premium N is tiny and the WR band doesn't fit convex
naked. Delivered instead: a verdict-grade, now-shipped IV calibration; a full-N confirmation of
the NAKED lineage under realistic pricing; a real-premium refutation of VRP. Verdict-grade G2/G3
want a wider OPRA window; the forward journal already accrues real option outcomes.

> Live note: the server runs without `--reload`, so the pricing calibration takes effect only
> after a manual restart. Pine's realized-vol IV should be scaled by ~1.56 (or floored at the
> 0DTE 0.38 term-structure level) at the next TV recompile to match.
