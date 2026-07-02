# Backtest Integrity Report — bot review 2026-07-02

Scope: `engine/hs_backtest.py` (the validated backtest), `bot/execution/replay_broker.py`
(pipeline replay), `bot/tracker.py` (live first-touch scorecard), research sweeps.

## Look-ahead review

* **OR levels**: computed as a per-day aggregate and broadcast, but entries can only fire at
  `mins >= or_e (+ entry_delay)` — after the range is complete. The OR-mid bias uses the *last
  OR-bar close*, also only consumed post-OR. **No leak.**
* **Pivots / structure**: swing levels update only at the confirm bar (`lb` bars after the
  extreme); `sph/spl` used for stops are the last *confirmed* swings. **No leak.**
* **HTF confirmation** (`attach_mtf`): prior *closed* HTF bar via `shift(1)` + backward
  `merge_asof`. **No leak.**
* **VWAP cap**: uses `vs_prev` (prior-bar session VWAP) explicitly for causality. **No leak.**
* **Externals** (VIX/SPY/HTF daily): merged by ET **date** onto intraday bars — a same-day daily
  value is technically end-of-day information available intraday. VIX input is `sma5`/`close[5]`
  (lagged); SPY trend uses same-day daily EMA state, mirroring the Pine's `request.security(…, "D")`
  with `lookahead_off` on *closed* daily bars in live. Residual same-day usage is a known,
  documented approximation ("the reconcile quantifies it") — impact bounded to the macro regime
  gate, not entries/exits. **Documented limitation.**
* Repo-wide scan for `shift(-`, `rolling(center=True)`, forward `merge_asof`, `bfill`:
  hits only in research label/target construction (fwd-return targets in `strat_ml`,
  `strat_orderflow_book`, `orb_obi_book`, `orb_lead_lag`) and a `__main__` IC diagnostic in
  `orderflow/deep.py`. None feed a signal path.

## Repainting review

Production Pine: all `request.security` calls `lookahead_off`; entry state uses frozen OR levels +
confirmed pivots; labels are created at fill and never re-anchored. The one repaint-class defect —
intrabar evaluation of close-confirm conditions in the AUTO strategy (`calc_on_every_tick=true`)
and the STACK signal latch — is **fixed** this review (`barstate.isconfirmed` gate; HS-H4).
The research V44 script's single `lookahead_on` uses the safe `[1]`-offset idiom (confirmed prior
HTF bar).

## Fill assumptions

* Close-confirm entries fill at the confirming bar's **close** (live sends a market order on the
  same event — slippage then modeled separately).
* Stop/retest/sweep entries fill at the level, **gap-aware**: `max(level, open)` for longs /
  `min(level, open)` for shorts — a resting stop never fills better than the bar's open.
* Stops fill at the stop price (no gap-through modeling on exit — a fast gap through the stop
  fills optimistically at the stop; futures overnight gaps are avoided by session-flat design).
  **Documented limitation.**
* Entry bar is excluded from exit management (`i+1` walk; the Pine mirrors this — "no same-bar
  fill→TP/stop inflation").

## Same-bar / intrabar assumptions

* Stop + target inside one bar, pre-TP1: **stop wins** (conservative) in engine, replay broker,
  and tracker.
* `scale_be` mode, TP1 + TP2 inside one bar: both banked in sequence (optimistic — needs
  lower-TF data to resolve). The **shipped default** exit (`tp2_full` / cap-4R) does not have
  this ambiguity pre-TP1.
* Post-TP1 same-bar TP2 vs BE-stop: engine prefers TP2 (optimistic, documented). The live
  **tracker** had the same optimism and is now stop-first (HS-H5) so the live-vs-backtest
  scorecard can only be equal-or-worse than reality reports, never inflated.

## Spread and slippage

Futures: MNQ $0.52/order commission + 2-tick slippage per contract-fill (~2× position per round
trip), stress-tested at +1/+2 extra ticks in `hs_validate` (and 2×/3× slip in the research
gauntlets). Equities: $0 commission + 1-tick ($0.01) slip. No explicit bid-ask spread model
(no quote data in the 1m set) — slippage ticks proxy it; equity ETFs (QQQ/SPY) are penny-wide.
**Documented.**

## Survivorship bias / corporate actions

Universe is index futures + the two largest ETFs — no delisting risk; survivorship bias not
material. Futures continuity handled properly (outrights only, volume-crossover roll, ratio
back-adjust, raw + adjusted kept separately). Equity 1m data unadjusted; QQQ/SPY had no splits in
the sample window — a future split requires a data rebuild (flagged).

## Walk-forward setup

Research process (RESEARCH_NOTES, 1,403 lines): every adopted lever passed expectancy lower-90 %
bootstrap CI > 0 **and** both-sides-positive, per-year consistency (e.g. 13/17 years), regime
windows (2011 / 2015-16 / 2018-Q4 / 2020 / 2022), OOS walk-forwards (`orb_*_walkforward.py`),
parameter-sensitivity sweeps (plateaus required, peaks rejected — documented repeatedly), and
cost stress. Monte-Carlo trade-order testing: bootstrap maxDD 5th percentile in `hs_validate`.
Delayed-entry testing: arm-timing study (delay-0 vs delay-60) documented. Time-of-day and
long-vs-short breakdowns built into the validator.

## Remaining limitations

1. Same-day daily externals in the macro regime (approximation, bounded to a gate).
2. No intrabar sequencing for scale-mode TP1+TP2 bars and post-TP1 engine exits (needs 1m/tick
   sub-bars; the default exit mode is unaffected pre-TP1).
3. Stop fills not gap-stressed on exit.
4. No spread model beyond slippage ticks.
5. The backtest cannot be re-executed in this review environment (market-data parquets are
   git-ignored and absent) — engine verification here is code-level + synthetic-data tests; the
   validated numbers in README/RESEARCH_NOTES were not re-reproduced this pass.
6. Forward paper trading remains the declared out-of-sample gate before any sizing (correct; keep it).
