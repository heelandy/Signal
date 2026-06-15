# production/ — change log

Structured record of changes to the live Pine set. Newest first. See `../research/RESEARCH_NOTES.md`
for the F-number research behind each item.

---

## 2026-06-15 — uncommitted working tree (review before commit)

Covers everything since the last commit (`47d7181 Options review`). All five touched scripts still
need a **TradingView compile-check**; STACK confirmed compiling. After reload, **set "EVAL: ledger start"
to your eval's first day** on every chart running EVAL (else the ledger counts all history → instant
TARGET ✓ / suppressed signals).

### HIGHSTRIKE_ORB_STACK.pine (primary)
- **EVAL ledger anchor** (`eval_anchor` + `ev_live`): signal-sim PnL before the anchor is ignored — fixes
  the "TARGET ✓ the moment EVAL is enabled" bug. Ledger/halt flags gated on `time >= eval_anchor`.
- **Regime-B block is now session-scoped** (`block_b_ses`: Off / **London only** (default) / All sessions),
  blocking B only during London hours (trade-day `o_now` 540-930 = 03:00-09:30 ET). RTH+Asia trade B. (F31/F31f)
- **Day throttle** (`eval_cap` 5 / `eval_lock` 2): suppresses signals after N/day or N losers; resets daily.
  Free in backtest (F31e). Display layer — AUTO is the real enforcer (throttle not yet in AUTO).
- **cap-4R exit toggle**: new exit mode "Full → cap @ TP2 (struct stop)" — full position to the TP2 R-cap
  (default 4R) on the structure stop, no scale/trail. Walk-forward-graduated (F34b/c). Trail stays default.
- **Event times + chart markers**: ENTRY/STOP/TP1/TP2 dashboard rows show fill/hit time; chart gets TP1/TP2
  diamonds, STOP ✕, eval-TARGET flag.
- **Per-ticker size readout**: ENTRY rows append suggested contracts (`risk_dlr` / stop-dist / `syminfo.pointvalue`),
  auto-adjusting per security.
- **Fix (review)**: in full/cap mode a trade that ticked TP1 then stopped out displayed green "TP1 HIT" — now
  shows "STOP HIT" (`if not l_t1h or is_full`, scoped to the stop branch so a cap win is never mislabeled).

### HIGHSTRIKE_ORB_AUTO.pine (automation twin)
- **EVAL ledger anchor + ev_live re-baseline** of `start_eq`/`peak_eq`/halt flags (mirrors STACK).
- **Regime-B block session-scoped** (`block_b_ses`, identical 540-930 trade-day window) — replaced the old
  all-sessions `block_b` bool.
- **cap-4R**: "Fixed TP bracket (broker-held)" default bumped 2R → **4R** (the graduated cap); tooltip updated.
  Bracket = full position, broker-held struct stop + 4R TP, no trail.
- **Eval-buffer formulas** aligned to STACK (daily/trailing halt `−math.max(limit − eval_buf, 0)`).

### HIGHSTRIKE_ORB_OPTIONS.pine (options translator)
- **Regime-B block session-scoped** (`block_b_ses`) — replaced old `block_b` bool. NOTE: this script's
  `o_now` is **wall-clock**, so London hours = **180-570** (not STACK/AUTO's 540-930). RTH-only ⇒ London-only
  never blocks B here (B trades all RTH). (review fix)
- **Dashboard split + state machine**: TP2, per-side WAIT/ARMED/FILLED/NEAR TP1/TP1/TP2/STOP states,
  STRAT row, Black-Scholes COST estimate row (IV/DTE inputs; ~approximation, no chain access).

### HIGHSTRIKE_ORB_V1_STRATEGY.pine (legacy strategy)
- **EVAL ledger anchor + ev_live**; eval-buffer formulas + `eval_buf` input aligned to AUTO/STACK
  (replaced the old `trail_buf`, added the `math.max(…,0)` clamps).
- **cap-4R**: "Full to TP2" mode already ran at TP2 R = 4 (= the graduated cap); tooltip clarified
  (the "2R/-1R" sublabel is legacy).
- *Still on the old all-sessions `block_b` bool — block_b_ses propagation PENDING (also V1_INDICATOR).*

### README.md
- Minor wording.

### New research scripts (`../research/`, untracked)
F31 regime-B (`orb_regimeb_entries/oos.py`, `orb_prop_eval_b/throttle/mixed.py`), F32 1m
(`orb_1m.py`, `orb_1m_robust.py`), F33 RANGE (`orb_range_block/eval.py`, `orb_f33_debug.py`),
F34 config validation (`orb_config_validate.py`, `orb_cap_walkforward.py`, `orb_eval_cap.py`),
F35 projection feasibility (`orb_projection_test.py`), confirmation entries (`orb_confirm_entry.py`),
gold (`orb_gold.py`, `orb_gold_walkforward.py`).

### Known-pending (not in this commit)
- block_b_ses → V1_STRATEGY + V1_INDICATOR (consistency rule; mind each file's clock convention).
- Day-throttle enforcement → AUTO (currently STACK display-only).
- Forward paper-test of fills (the live-adoption gate).
- Low-pri cleanups: dedupe London 540/930 magic numbers; gate throttle counters by `ev_live`;
  consolidate duplicated research helpers.
