# Performance Report — bot review 2026-07-02

## Benchmark environment

* Linux 6.18 container, Python 3.11.15, pandas 2.x / numpy 2.x (pip, 2026-07)
* Single process, no other load; timings are **best of 3** (`time.perf_counter`)
* Method: benchmark script (synthetic OHLCV, seeded RNG) + `cProfile` to locate hot spots
  before changing anything. Live market-data latency could not be measured here (no network
  feeds / credentials in the review environment — by design).

## Test dataset

Synthetic 5-minute OHLCV frames (seeded `numpy.default_rng`), 2,000 bars (≈ the live scanner's
5-day/5-m window per symbol) and 20,000 bars (research-scale), exercising the full
`engine/hs_harness.compute_state` path (indicators, pivots, structure state machine, order
blocks/FVG/sweeps, macro regime, scoring, triggers).

## Baseline (before)

| Path | 2,000 bars | 20,000 bars |
|---|---|---|
| `pivots()` (high+low, lb=5) | 6.4 ms | 62.5 ms |
| `compute_state` (full) | 89.9 ms | 668.3 ms |

`cProfile` (20 k bars): `_zones_sweep_patterns` 0.50 s cum (per-bar `np.max/np.min` slices +
list churn), `_macro_regime` 0.36 s cum (per-bar pandas `.iloc` — the single hottest call site:
20,014 `indexing.__getitem__` calls), `pivots` 0.095 s.

Memory: peak RSS during the 20 k-bar run ≈ steady (frame-sized); no leak observed across repeated
calls (bounded lists `ob_keep`/FVG-8 confirmed in code).

## Changes

1. **PERF-1** `pivots()`: vectorized fast path for constant lookback — rolling max/min forward +
   reversed (exact same tie semantics, `strict` and `tv`); the O(n·L) Python loop remains for the
   adaptive-lookback mode.
2. **PERF-2** `_macro_regime`: numpy views (`vix.to_numpy`, `spy_trend.to_numpy`) replace per-bar
   `.iloc` inside the persistence loop.
3. **PERF-3** `_zones_sweep_patterns`: precomputed shifted rolling max/min arrays replace the
   per-bar `np.max(h[i-L:i])` slices (constant-lb case; per-bar fallback kept).

## Results (after)

| Path | 2,000 bars | 20,000 bars | Improvement |
|---|---|---|---|
| `pivots()` | **0.9 ms** (was 6.4) | **3.2 ms** (was 62.5) | −86 % / −95 % |
| `compute_state` | **66.7 ms** (was 89.9) | **448 ms** (was 668) | −26 % / −33 % |

Throughput equivalent: the live scanner's per-symbol state build drops from ~90 ms to ~67 ms;
a 4-symbol scan cycle spends ~270 ms in state computation instead of ~360 ms (the cycle is
dominated by network fetches, which this review could not measure). Research-scale replays gain
~1/3 on the state stage.

Memory: unchanged in magnitude (three additional O(n) float arrays for the rolling extremes,
~0.5 MB at 20 k bars).

## Validation

* Old vs new `compute_state`: **all 30 state/derived columns identical** on seeds 777/5000 and on
  the adaptive-lookback path (scripted comparison against the pre-change file from git).
* Permanent regression test: `test_pivots_fast_path_matches_loop_path` (both tie rules, high+low,
  plateau data).
* Full test suite: 45/45 pass.

## Trade-offs

None functional. ~25 added lines; the adaptive-lookback path keeps the original loop (unchanged
performance there — it is research-only).

## Remaining bottlenecks (measured, not yet optimized)

1. `_zones_sweep_patterns` residual Python loop (OB/FVG list filtering per bar) — the next ~35 %
   of `compute_state`; a numpy interval-stack rewrite is possible but higher-risk (stateful list
   semantics), not justified for a 60 s scan cadence.
2. The structure state machine loop (inherently sequential Pine-port semantics; correct as-is).
3. Live scan wall-time is dominated by provider HTTP fetches (`get_bars` per symbol per cycle,
   `yf.download` etc.) and `databento_live` opening a fresh session per futures price
   (HS-M11). Batching/streaming is the right next lever if the 60 s cadence ever tightens.
4. `journal.read()` re-parses the whole JSONL per dashboard poll (HS-M5) — fine at current size.
