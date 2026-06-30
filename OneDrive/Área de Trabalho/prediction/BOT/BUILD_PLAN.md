# HIGHSTRIKE BOT — Build Plan (the one aligned plan)

**Status:** authoritative. This file supersedes the scattered intent in the 112 `*.md`
spec docs and `Botreview` for *what we build and in what order*. The spec docs remain the
**target-architecture reference**; this is the **MVP execution plan**.

Last aligned: 2026-06-29.

---

## 0. Decisions locked with the user (2026-06-29)

| # | Decision | Choice |
|---|----------|--------|
| 1 | Execution target | **Equity + options (Alpaca) first; futures (NQ/ES/GC via Tradovate/IBKR) behind the same broker interface, later** |
| 2 | First build safety | **Decision engine + replay/paper first. Live execution is HARD-LOCKED** until the readiness gate passes |
| 3 | Direction engine in v1 | **Candle / VWAP / EMA direction now** (the example.txt rule). **MBO order-flow** (cum-delta, imbalance, absorption) is the **next** layer |

These three answers shape every phase below.

---

## 1. What this BOT actually is

An **auditable decision engine**, not (yet) a live trading bot:

```
Market Data ─▶ Market Truth ─▶ TradeCandidate ─▶ RiskDecision ─▶ Replay/Paper Order
                                                                       │
                              Journal ◀── PositionState ◀──────────────┘
                                 │
                              Review dashboard
```

Every arrow is logged with a trace id. Live broker orders are impossible until Phase 8's
gate is satisfied (`BOT_MODE=live` **and** a hand-created `config/LIVE_APPROVED.lock`).

This is exactly the path `Botreview` recommended after reviewing all 112 docs, narrowed to
our instruments and reusing the existing engine instead of rebuilding it.

### Evidence.docx is the master spec the scattered files point to

`Evidence.docx` (read in full) is the most concrete source and reconciles everything:

- It defines **two alpha engines, one risk engine, one execution engine, one DB** — and
  **Strategy A / Setup 1 "opening-range continuation" is literally the validated HIGHSTRIKE ORB
  stack** we already trade. So the existing engine *is* the first day-trading strategy.
- It is the quantified version of `example.txt`'s "know where price is going": exact order-flow
  feature formulas (queue imbalance `QI`, microprice `Δμ`, aggressive-trade imbalance `ATI`,
  order-flow imbalance `OFI`, add/cancel `ACI`, cumulative delta `CD`, sweep detector) with
  starting thresholds, an **intrabar direction score (0–100)**, and a **signal state machine**
  (FLAT→ARMED→ENTER→ACTIVE→EARLY_FAILURE/TP/PROTECTIVE→LOCKOUT).
- Its risk engine first-live settings, shared-signal JSON, validation gates (OOS PF ≥1.20–1.30,
  no single-symbol/month dependence, survives 2× costs + delayed entries — *the exact gauntlet
  the ORB research already uses*), and deployment ladder (research→sim→paper→shadow→live) are
  adopted as the BOT's risk, contract, validation, and deployment standards respectively.
- Key data fact: it specs the order-flow engine on **L2/L3 depth**. Our **XNAS MBO is full L3
  for QQQ**, so `QI/OFI/ACI/microprice/sweeps` are computable offline now; live NQ needs
  GLBX.MDP3 MBO via the Databento key (the `databento_feed` puller is ready for it).

---

## 2. Reuse, don't rebuild

The repo already contains most of the "intelligence" half. The BOT wraps it; it does not
replace it.

| BOT layer (spec doc) | Already exists | New work |
|----------------------|----------------|----------|
| Market Data (`MDE-001`) | `pipeline/hs_ingest_equity.py`, `hs_build_continuous.py`, `data/*_continuous_1m.parquet` | `BOT/bot/market_data/` Databento puller + **local D: CBBO/MBO loader** ✅ |
| Market Truth (`MTE-001`) | `qa/hs_qa_data.py`, `macro_data_quality` | candle schema + stale/gap/dup gate, **fail-closed** |
| Strategy / signal (`SDE-001`,`EIE-001`) | `engine/hs_harness.py`, `engine/hs_backtest.py` (ORB stack), the 5 Pine scripts | `TradeCandidate` emitter wrapping `_orb_signals` + the **direction gate** |
| Risk (`RE-001`,`RRL-001`,`CPE-001`,`PFR-001`) | eval-ledger logic inside the Pine | `BOT/bot/risk/` pure decision service, fail-closed |
| Execution (`EC-001`,`BF-001`,`OMS-001`) | webhook JSON in `HIGHSTRIKE_ORB_AUTO.pine`, `docs/AUTOMATION_SETUP.md` | `BOT/bot/brokers/` interface + replay/paper/Alpaca adapters |
| Journal (`TLJ-001`) | `web/` trade journal models (other repo) | `BOT/bot/journal/` append-only event log |

---

## 3. Canonical contracts (build these first — everything speaks them)

Defined once in `BOT/bot/contracts.py` (dataclasses + JSON schema). Drawn from
`API-001` / `Botreview`, trimmed to MVP fields:

- **MarketCandle** — symbol, ts_utc, o/h/l/c/v, source, quality_flags, ingested_ts
- **TradeCandidate** — id, symbol, side, tf, setup (`orb_stack`), direction_score, entry,
  stop, tp1, tp2, regime, session, evidence{}, strategy_version, ts, idempotency_key
- **RiskDecision** — candidate_id, status (`approved`/`rejected`/`blocked`), reason_code,
  max_contracts, max_risk_dollars, stop_policy, target_policy, trace_id
- **OrderRequest / OrderEvent** — order state machine: created→validated→submitted→
  accepted→(partial)→filled / cancelled / rejected / expired / error
- **PositionState** — none→opening→open→reducing→closing→closed / mismatch / unknown
- **JournalEntry** — append-only, links candidate→risk→orders→fills→outcome (R, MFE, MAE)

Rejected candidates are journaled too (needed for replay diagnostics + the future ML layer).

---

## 4. The direction engine (example.txt, made concrete)

> "the most important part is to determine where price is going at all time."

**v1 (now), shared by Pine + the Python `_orb_signals`:** a candidate fires only when ALL hold:

- **Zone**: at the ORB edge (existing breakout level `Le`/`Se`).
- **Sequence**: long needs `close > close[1]` **and** `close[1] > close[2]` (101→102→103);
  short mirrors. Current candle the right colour + a strong full body (existing `strong_body`).
- **No chase**: price not already > `chase_atr`·ATR beyond the level (turn the existing
  `chase_max`/`chase_atr` guard **on**, default on per the user's rule).
- **No counter-trend**: never long while the trend gate is down (existing `eff_up`/`eff_down`).

Validation (F61, `research/orb_dir_seq.py`): the rising-sequence gate is **neutral on the shipped
close-confirm fill** (already implied by strong-body + continuation) but a **real graduate on the
wick/touch fill** — NQ +0.151→+0.261R (PF 1.26→1.47), QQQ +0.276→+0.448, SPY +0.257→+0.383; yrs+
13/17·9/9·8/9, OOS holds, survives 2× slip. Adopted default-ON. The no-chase guard was re-tested
and **left OFF** (it costs edge — F57/F60; the honest late confirmed entries are the winners).

**v2 (next, MBO):** add the Evidence order-flow stack from the XNAS L3 book — `QI`, `Δμ`, `ATI`,
`ACI`, `CD` and the sweep detector → an intrabar direction score that confirms the entry (long
needs the score one-sided bullish with persistence; short mirror) and an early-failure exit when
the imbalance flips. Inputs already built (`databento_local.mbo_cum_delta`, more to add). Gated as
a toggle, validated in the engine before it's trusted.

---

## 5. Phases (each ends with a test gate; nothing live until Phase 8)

- **Phase 0 — Data layer** ✅ *(done this session)*
  `bot/config.py`, `bot/market_data/databento_local.py` (CBBO ATM quotes + MBO cum-delta, reads
  D:, handles both `.zst` and the extracted `.csv` folders — an extraction job decompressed the
  OPRA `.zst` in place; XNAS still mid-extraction), `bot/market_data/databento_feed.py` (API
  puller, just add the key), `config/.env.example`. Verified against the live D: files.
- **Phase 1 — Contracts** — `bot/contracts.py` + JSON schemas + `IMPLEMENTATION_STATUS.md` updates.
- **Phase 2 — Market Truth gate** — canonical-candle validator (stale/gap/dup/bad-OHLC →
  **block**, fail closed). Tests: stale feed blocks, duplicate ts blocks.
- **Phase 3 — Strategy → TradeCandidate** — wrap `_orb_signals` + the direction gate; emit
  candidates (incl. rejected) over the local replay data. Test: deterministic replay checksum.
- **Phase 4 — Risk gate v1** — pure `decide(candidate, account) -> RiskDecision`, fail closed:
  no stop → reject; daily-loss / trailing-DD / max-contracts / kill-switch → block. One test per rule.
- **Phase 5 — Replay & paper execution** — replay broker + paper broker behind `brokers/base.py`;
  order + position state machines; fill model (slippage/commission from the engine). Tests:
  duplicate-order idempotency, partial fill, broker-disconnect pause.
- **Phase 6 — Alpaca paper adapter + live 1m feed** — same interface, real Alpaca *paper*
  account; `databento_feed.stream_live`. Still no live money.
- **Phase 7 — Journal + review** — append-only journal; reconcile broker truth; minimal
  status JSON / dashboard. Reuse `web/` journal surface.
- **Phase 8 — Live readiness gate** — fail-closed checklist; live impossible without the lock
  file + passing replay/paper records + explicit approval. Futures broker adapter slots in here.

---

## 6. Relationship to the Pine fix (running in parallel)

The Pine scripts and this BOT must stay in lockstep (memory: all-scripts-consistency). The
two fixes shipped alongside this plan:

1. **Marker placement** — every FILL / TP1 / TP2 / STOP / CALL / PUT marker anchored at its
   real price (not `location.above/belowbar`), across STACK / OPTIONS / AUTO. *(the recurring
   "FILL FILL / wrong-side" bug)*
2. **Direction gate** — the §4 v1 rule added to `engine/hs_backtest.py` (parity) and STACK,
   validated on QQQ + NQ before propagating to the other four scripts.

The engine is the **reference implementation** of the entry; Pine mirrors it; the BOT calls
the engine. One entry definition, three surfaces.

---

## 7. Out of scope for the MVP (kept in the spec docs as target state)

Multi-agent AI, the full ML platform, data lake, options-flow institutional features, forex/
crypto, multi-broker smart routing, and **live execution** — all deferred. The ML layer from
`example.txt` becomes real only after Phase 7 produces a labelled journal to learn from.
