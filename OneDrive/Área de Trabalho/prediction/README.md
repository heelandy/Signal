# HIGHSTRIKE

An **Opening-Range Breakout (ORB)** day-trading system for **futures and equities/ETFs**, profitable
**long and short**, with a fast resting-stop execution, a Python research/validation stack, and
ready-to-trade TradingView Pine scripts.

The discipline throughout: **no curve-fitting.** Every config must clear a hard gate — the lower 90%
bootstrap CI of expectancy must be above zero, **and** the long and short sides must each be
positive — across years, regimes, timeframes, and realistic costs. A number that only looks good
in-sample doesn't ship.

---

## Validated results (current — stop-entry, all-day window, EOD-accurate)

Per-TF config, stop-entry, 4R scale exit, 90% bootstrap CI, costs modeled (equities: $0.01 tick /
commission-free; futures: MNQ 0.52/order + 2-tick slip):

| Instrument | exp (R) | Profit Factor | Win % | Max DD (R) | lower-90% CI | both sides + |
|---|---|---|---|---|---|---|
| **QQQ 15m** | **+0.34** | **2.11** | **66%** | **−5.6** | +0.27 | ✅ |
| SPY 15m | +0.30 | 1.88 | 63% | −7.4 | +0.22 | ✅ |
| NQ 15m | +0.27 | 1.83 | 64% | −10.5 | +0.22 | ✅ |

5m holds too (QQQ/SPY/NQ all pass). Equities are *cleaner* than futures here — lower relative cost
and no overnight gap risk give roughly a quarter of the drawdown. **QQQ 15m is the flagship.**

> Backtests are in-sample even with all the discipline. **A forward paper-test is the real
> out-of-sample gate** before risking money — see step 8.

---

## Tradable deliverables (Pine — TradingView)

| File | What it is |
|---|---|
| `HIGHSTRIKE_ORB_V1_STRATEGY.pine` | **The strategy.** ORB resting stop-entry, per-TF auto-config, macro/regime/trend gates, scale-50%@TP1→BE→TP2 exit, prop-eval guardrails, EOD-flat, SL/TP lines + position-tool panel. Multi-asset (futures + equities/ETFs). |
| `HIGHSTRIKE_ORB_V1_INDICATOR.pine` | **The main indicator.** Mirrors the strategy's gated signal + SL/TP + resting entry + position-tool panel, plus a folded-in 5m/15m MTF overlay. Use this on your chart. |
| `HIGHSTRIKE_ORB_OPTIONS.pine` | **Options-friendly indicator (SPY/QQQ).** Translates the ORB signal into option structures — buy call/put, debit spread, credit spread — with strikes derived from the ORB levels, in a clean dashboard. Strikes/structure only (no chain/IV access in Pine). |
| `HIGHSTRIKE_ORB_MTF_SIGNALS.pine` | Standalone 5m/15m signal display. Now redundant (its feature lives in the V1 indicator) — kept for reference. |
| `HIGHSTRIKE_V44_STRATEGY.pine`, `hs_recon_export.pine` | Legacy V44 + reconcile export (its VWAP/EMA entry had no edge; kept for the reconcile only). |

In TradingView set the per-instrument cost inputs: **futures** commission ≈ 0.52, slippage 2 ticks;
**equities/ETFs** commission 0 (slippage models the spread).

---

## Deploy from scratch (start over)

If you ever rebuild from zero, run these in order. Everything derives from the source 1-minute files.

**0. Prereqs**
```
python -m pip install -r requirements.txt      # pandas, numpy, duckdb, pyarrow
```

**1. Get raw 1-minute data (Databento)**
- **Futures** — dataset `GLBX.MDP3`, schema `ohlcv-1m`, symbols NQ/ES (continuous via parent or all
  contracts). Macro vol: VIX (spot daily + `XCBF` VX futures).
- **Equities/ETFs** — dataset `XNAS.ITCH` (or `DBEQ.BASIC`), schema `ohlcv-1m`, `stype_in=raw_symbol`,
  symbols SPY / QQQ (split-adjusted; SPY/QQQ don't split in this window so raw is fine).
- History: 2018→present minimum; more years = stronger validation.

**2. Ingest → continuous 1-minute parquet** (`data/<sym>_continuous_1m.parquet`)
```
python hs_build_continuous.py <futures_csv> <SYM>     # futures: volume roll + ratio back-adjust
python hs_ingest_equity.py "<equity_csv>" <SYM>       # equities: no roll (adj_factor=1)
```

**3. Resample → all timeframes** (`data/bars/sym=/tf=/session=/year=`, hive parquet)
```
python hs_resample.py <SYM>                           # 5m/15m/30m/1h/4h/1d, RTH + full
```

**4. Build the macro VIX** (unified daily; spot + VX futures)
```
python hs_build_vix.py
```

**5. Build the DuckDB views + sanity report**
```
python hs_db.py                                       # views: <sym>_1m, bars, vix_daily
python hs_db.py "SELECT sym, tf, count(*) FROM bars GROUP BY 1,2 ORDER BY 1,2"
```

**6. Backtest + validate** (confirm the four metrics + the gate)
```
python research/orb_optimize.py        # PF/expectancy sweep (the "real edge" zone)
python research/orb_per_tf.py          # best config per timeframe
python research/orb_sessions.py        # session check (US RTH is the edge; Asia is not)
```
Or a one-liner reproducing the flagship:
```
python -c "import sys; sys.path.insert(0,'research'); import hs_backtest as B; from orb_optimize import state, metrics; m=metrics(B.backtest(state('QQQ','15m'),'scale_be','both',False,'orb',0,None,4.0,570,600,0.25,900,'stop')); print(m['exp'], m['pf'], m['loCI'])"
```
The engine is **asset-aware** (equity vs futures economics, auto-detected from the symbol) and
**EOD-flat** (`eod_min=958`, flatten ~15:58 to match the Pine).

**7. TradingView** — paste `HIGHSTRIKE_ORB_V1_STRATEGY.pine` + `HIGHSTRIKE_ORB_V1_INDICATOR.pine`,
set the cost inputs per instrument, and confirm the Strategy Tester is in the ballpark of the Python.
Known reconcile deltas (not bugs): intrabar same-bar exits, gap-through fills at the bar open, and
TradingView's real `SPY`/`CBOE:VIX` vs the Python's ES/stitched-VIX proxy.

**8. Forward paper-test → live.** The real out-of-sample proof. Especially confirms stop-fill
slippage in fast breaks, which no backtest fully captures.

---

## Python stack

| File | Role |
|---|---|
| `hs_ingest_equity.py` | Databento equity 1m CSV → continuous-1m parquet (no roll) |
| `hs_build_continuous.py` | Futures continuous front-month (volume roll, ratio back-adjust) |
| `hs_resample.py` | 1m → 5m/15m/30m/1h/4h/1d (RTH + full), hive parquet |
| `hs_build_vix.py` | Unified daily macro VIX (spot + VX futures) |
| `hs_db.py` | DuckDB query layer over the parquet (`connect()`, `bars()`) |
| `hs_qa.py`, `hs_qa_data.py`, `hs_recon_contracts.py` | Data QA + contract inventory |
| `hs_harness.py` | Python port of the chart logic (indicators, regime, levels) for `state()` |
| `hs_backtest.py` | Event-driven backtest → trade list (ORB entry, stop/close/retest exec, asset-aware costs, EOD-flat) |
| `hs_validate.py` | Expectancy + 90% bootstrap CI, PF, win%, maxDD, regime/year stratification, slippage stress |
| `hs_reconcile.py` | Diff Python state vs a TradingView export (the trust gate) |

## Research lab
`research/RESEARCH_NOTES.md` records every experiment (Findings 1-10): why MTF confirmation hurts,
the PF-into-the-1.5+-zone levers, per-TF optima, the reward tail-trap, retest entry (15m-only),
the equity validation, and why looking **all day** beats morning-only once execution is the stop-entry.
Sweep scripts: `orb_optimize.py`, `orb_per_tf.py`, `orb_sessions.py`, `orb_mtf_research.py`.

## Repo hygiene & GitHub upload
The raw 1m CSVs (100 MB+ each), the `data/` parquet/DuckDB stores, and `__pycache__` are **git-ignored**
(`.gitignore` at the project root) — large and fully rebuildable from the runbook above. Re-download
the source data per step 1.

To publish just this project (the working tree currently sits inside a home-directory git repo),
initialize a fresh repo at the project root and push:
```
cd "<project folder>"
git init
git add .                          # .gitignore keeps data/ + CSVs out
git commit -m "HIGHSTRIKE ORB system"
git branch -M main
git remote add origin <your-github-url>
git push -u origin main
```
Before the first commit, confirm `git status` shows **no** `data/`, `*.csv`, or `*.zst`.

## Roadmap
- **Options-friendly indicator** (`HIGHSTRIKE_ORB_OPTIONS.pine`) — translate the ORB signal into
  credit/debit spreads + calls/puts for SPY/QQQ (0DTE + weekly), strikes from the ORB levels, in a
  separate dashboard so the main indicator stays clean. *(first up)*
- Validate the edge on single-name equities (NVDA/TSLA/AVGO/ORCL — split-adjusted data needed).
- Forward paper-test SPY/QQQ + NQ, then a prop-eval / live run.

## Disclaimer
Educational and research use. Backtested performance is **not** a guarantee of live results; a
forward paper-test is required before risking capital. Nothing here is financial advice.

## License
The Pine scripts carry an MPL-2.0 header (© heelandy).
