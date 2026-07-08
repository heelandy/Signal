"""Signal decision + outcome tracker (TLJ-001).

The user marks each signal Taken or Skipped. The system then TRACKS where price actually went —
which of stop / TP1 / TP2 hit first — by walking forward bars from the data router. This builds the
real performance record of the signal engine (taken trades) and a what-if record (skipped).

    from bot.tracker import record_decision, track_outcomes, list_decisions
    record_decision(signal_dict, taken=True)     # user clicked Take
    track_outcomes()                              # update open ones (stop/tp1/tp2 first)
"""
from __future__ import annotations

import json
import sqlite3
import uuid
from pathlib import Path

import pandas as pd

from bot.config import BOT_ROOT
from bot.contracts import utcnow_iso

DB = BOT_ROOT / "data" / "highstrike.db"
_EQUITY_RTH = {"SPY", "QQQ", "IWM", "DIA", "NVDA", "TSLA", "AAPL", "MSFT", "AMZN", "META", "GOOGL", "AMD", "NFLX", "AVGO"}  # close 2:30pm ET (user rule); futures excluded

_SCHEMA = """
CREATE TABLE IF NOT EXISTS decisions(
  id TEXT PRIMARY KEY, candidate_id TEXT, symbol TEXT, side TEXT, family TEXT, session TEXT,
  entry REAL, stop REAL, tp1 REAL, tp2 REAL, taken INTEGER, decided_at TEXT, signal_at TEXT,
  outcome TEXT DEFAULT 'open', outcome_at TEXT, result_r REAL, json TEXT);
"""


def _con():
    DB.parent.mkdir(parents=True, exist_ok=True)   # fresh checkout has no data/ (it's git-ignored)
    c = sqlite3.connect(str(DB), check_same_thread=False)
    # scan thread + API thread + paper autotrade all write this DB — WAL keeps readers unblocked
    # and busy_timeout retries instead of throwing "database is locked" (PAPER_TO_LIVE prereq)
    c.execute("PRAGMA journal_mode=WAL")
    c.execute("PRAGMA busy_timeout=5000")
    c.executescript(_SCHEMA); c.commit()
    for col in ("mfe_r", "mae_r"):                    # study: max favorable / adverse excursion (R) — best-effort migrate
        try:
            c.execute(f"ALTER TABLE decisions ADD COLUMN {col} REAL"); c.commit()
        except Exception:
            pass
    return c


def _levels_ok(sig: dict) -> str | None:
    """JOURNAL INTEGRITY GUARD (user 2026-07-07: 'make sure data are not corrupt with same-bar
    entry/tp/stop — we've dealt with that since the start'). A row whose geometry is impossible
    never enters the journal: entry/stop must differ and sit on the correct sides; TPs must be
    beyond the entry in the trade direction. Returns the reason when bad, None when clean."""
    try:
        e, s = float(sig["entry"]), float(sig["stop"])
        sgn = 1 if str(sig.get("side")) == "long" else -1
        if not (e > 0 and s > 0) or e == s:
            return "entry/stop equal or non-positive"
        if sgn * (e - s) <= 0:
            return "stop on the wrong side of entry"
        for k in ("tp1", "tp2"):
            v = sig.get(k)
            if v is not None and sgn * (float(v) - e) <= 0:
                return f"{k} on the wrong side of entry"
        t1, t2 = sig.get("tp1"), sig.get("tp2")     # user 2026-07-08: TP1==TP2 is corruption —
        if t1 is not None and t2 is not None and abs(float(t1) - float(t2)) < 1e-9:
            return "tp1 and tp2 identical (single-target lineages must set tp2=None)"
    except Exception:
        return "levels missing/non-numeric"
    return None


def record_decision(sig: dict, taken: bool, auto: bool = False) -> dict:
    """Persist a take/skip. auto=True = SHADOW auto-track of an acceptable signal: dedup by candidate_id
    (so the 60s scan records each signal ONCE) and never clobber a manual decision on the same candidate."""
    bad = _levels_ok(sig)
    if bad:                                        # corrupt geometry never enters the journal
        try:
            from bot.audit import log as _audit
            _audit("journal_reject", reason=bad, symbol=sig.get("symbol"),
                   family=sig.get("family"), auto=auto)
        except Exception:
            pass
        return {"error": f"journal integrity: {bad}", "symbol": sig.get("symbol")}
    if auto and not (sig.get("generated_at") or sig.get("signal_at")):
        # BAR IDENTITY IS MANDATORY for auto rows — the degenerate-key/never-resolving bug class
        # (2026-07-07) can never regress: no bar time, no journal row.
        return {"error": "journal integrity: auto row without bar identity (generated_at)",
                "symbol": sig.get("symbol")}
    if not sig.get("cat"):                          # 3-category tag (user 2026-07-08): eq / ft / op —
        try:                                        # shared journal, training slices by category
            from bot.strategy.asset_config import asset_category
            sig["cat"] = asset_category(sig.get("symbol"), sig.get("family"))
        except Exception:
            pass
    cid = sig.get("candidate_id") or sig.get("id")
    con = _con()
    if cid:
        row = con.execute("SELECT id FROM decisions WHERE candidate_id=? LIMIT 1", (cid,)).fetchone()
        if row:
            if auto:                                   # auto never clobbers — one row per candidate
                con.close(); return {"dup": True, "symbol": sig.get("symbol")}
            # MANUAL on an existing candidate = ONE-TIME TRIGGER (user 2026-07-07: a second Take/
            # Skip click must not duplicate the trade in the journal) — UPDATE the same row (the
            # latest click wins take-vs-skip); outcome/results stay, they belong to the candidate.
            con.execute("UPDATE decisions SET taken=?, decided_at=?, json=? WHERE id=?",
                        [1 if taken else 0, utcnow_iso(), json.dumps(sig), row[0]])
            con.commit(); con.close()
            return {"id": row[0], "taken": taken, "symbol": sig.get("symbol"), "updated": True}
    rid = str(uuid.uuid4())
    con.execute(
        "INSERT OR REPLACE INTO decisions(id,candidate_id,symbol,side,family,session,entry,stop,tp1,tp2,"
        "taken,decided_at,signal_at,outcome,json) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
        [rid, sig.get("candidate_id") or sig.get("id") or rid, sig["symbol"], sig["side"],
         sig.get("family"), sig.get("session"), sig["entry"], sig["stop"], sig.get("tp1"), sig.get("tp2"),
         1 if taken else 0, utcnow_iso(), sig.get("generated_at") or sig.get("signal_at"), "open", json.dumps(sig)])
    con.commit(); con.close()
    return {"id": rid, "taken": taken, "symbol": sig["symbol"]}


def _walk(bars: pd.DataFrame, signal_at: str, side: str, entry, stop, tp1, tp2, close_hm=None) -> tuple[str, float, float, float]:
    """First-touch outcome + excursions from the signal bar forward. Returns (outcome, result_R, mfe_R, mae_R).
    mfe_R = furthest price ran TOWARD target (R); mae_R = furthest AGAINST (toward stop), up to the outcome bar.
    close_hm = force-flat at this ET minute-of-day if still open (equities close 2:30pm = 870)."""
    ts = pd.to_datetime(bars["ts_et"], utc=True)
    start = pd.Timestamp(signal_at)
    start = start.tz_localize("UTC") if start.tz is None else start.tz_convert("UTC")
    fwd = bars[ts > start]
    if fwd.empty:
        return "open", 0.0, 0.0, 0.0
    sign = 1 if side == "long" else -1
    risk = abs(entry - stop) or 1e-9
    hi, lo = fwd["high"].to_numpy(float), fwd["low"].to_numpy(float)
    cl = fwd["close"].to_numpy(float)
    fet = pd.to_datetime(fwd["ts_et"]); fmin = (fet.dt.hour * 60 + fet.dt.minute).to_numpy()
    single = tp2 is None                                          # single-target lineage (workers): TP1 IS the exit
    tp1_hit = False; mfe = 0.0; mae = 0.0
    for j in range(len(fwd)):
        fav = (hi[j] - entry) if sign == 1 else (entry - lo[j])       # toward target
        adv = (entry - lo[j]) if sign == 1 else (hi[j] - entry)       # toward stop
        mfe = max(mfe, fav / risk); mae = max(mae, adv / risk)
        if close_hm is not None and fmin[j] >= close_hm:              # equity 2:30pm force-flat (before checking stop/tp)
            return ("eod_tp1" if tp1_hit else "eod"), round(sign * (cl[j] - entry) / risk, 2), round(mfe, 2), round(mae, 2)
        hit_stop = lo[j] <= stop if sign == 1 else hi[j] >= stop
        hit_tp1 = (tp1 is not None) and (hi[j] >= tp1 if sign == 1 else lo[j] <= tp1)
        hit_tp2 = (not single) and (hi[j] >= tp2 if sign == 1 else lo[j] <= tp2)
        # NOTE: validated exit is FULL-to-TP2 (no BE/trail). Trailing the stop to TP1/BE after TP1 was TESTED
        # and it HURTS equities (QQQ +0.419->+0.291, SPY +0.312->+0.241) by cutting runners that dip to TP1
        # before reaching TP2 — the give-back protection is outweighed. Kept full-to-TP2.
        # SAME-BAR AMBIGUITY (review 2026-07): when the stop AND a target are both inside one bar
        # the intrabar sequence is unknown — score the STOP first (conservative), never the target.
        if hit_stop and not tp1_hit:
            return "stop", -1.0, round(mfe, 2), round(mae, 2)
        if hit_stop and tp1_hit:                      # came back to stop after TP1 (give-back)
            return "tp1_then_stop", round(sign * (stop - entry) / risk, 2), round(mfe, 2), round(mae, 2)
        if single and hit_tp1:                         # single-target: the one target IS the exit
            return "tp1", round(sign * (tp1 - entry) / risk, 2), round(mfe, 2), round(mae, 2)
        if hit_tp2:
            return "tp2", sign * (tp2 - entry) / risk, round(mfe, 2), round(mae, 2)
        if hit_tp1 and not tp1_hit:
            tp1_hit = True
    if tp1_hit:
        return "tp1_open", round(sign * (tp1 - entry) / risk, 2), round(mfe, 2), round(mae, 2)
    return "open", 0.0, round(mfe, 2), round(mae, 2)


def _walk_trail(bars: pd.DataFrame, signal_at: str, side: str, entry, stop0, trail_mult: float,
                close_hm=None) -> tuple[str, float, float, float]:
    """CHANDELIER-TRAIL walk (trail-eq lineage, F84): the stop ratchets to close ∓ mult×ATR14
    and never loosens; exit on the trailed-stop touch or force-flat. R is measured against the
    INITIAL risk (entry↔stop0). Fixed-level _walk can't resolve a moving stop — this twin can."""
    ts = pd.to_datetime(bars["ts_et"], utc=True)
    start = pd.Timestamp(signal_at)
    start = start.tz_localize("UTC") if start.tz is None else start.tz_convert("UTC")
    fwd = bars[ts > start]
    if fwd.empty or len(bars) < 15:
        return "open", 0.0, 0.0, 0.0
    sign = 1 if side == "long" else -1
    risk = abs(entry - stop0) or 1e-9
    # ATR14 over the WHOLE fetched frame (so the walk's first bars have a warm ATR), then slice
    tr = np.maximum(bars["high"].to_numpy(float) - bars["low"].to_numpy(float),
                    np.maximum(abs(bars["high"].to_numpy(float) - bars["close"].shift(1).to_numpy(float)),
                               abs(bars["low"].to_numpy(float) - bars["close"].shift(1).to_numpy(float))))
    atr = pd.Series(tr).rolling(14, min_periods=5).mean().to_numpy()
    idx = fwd.index.to_numpy()
    hi, lo, cl = fwd["high"].to_numpy(float), fwd["low"].to_numpy(float), fwd["close"].to_numpy(float)
    fet = pd.to_datetime(fwd["ts_et"]); fmin = (fet.dt.hour * 60 + fet.dt.minute).to_numpy()
    stop = float(stop0); mfe = mae = 0.0
    pos = {v: k for k, v in enumerate(bars.index)}          # bar index -> position for atr lookup
    for j in range(len(fwd)):
        fav = (hi[j] - entry) if sign == 1 else (entry - lo[j])
        adv = (entry - lo[j]) if sign == 1 else (hi[j] - entry)
        mfe = max(mfe, fav / risk); mae = max(mae, adv / risk)
        hit = lo[j] <= stop if sign == 1 else hi[j] >= stop
        if hit:
            return "trail_exit", round(sign * (stop - entry) / risk, 2), round(mfe, 2), round(mae, 2)
        if close_hm is not None and fmin[j] >= close_hm:
            return "trail_eod", round(sign * (cl[j] - entry) / risk, 2), round(mfe, 2), round(mae, 2)
        a = atr[pos.get(idx[j], 0)]
        if a == a and a > 0:                                # ratchet AFTER the touch check (causal)
            stop = max(stop, cl[j] - trail_mult * a) if sign == 1 else min(stop, cl[j] + trail_mult * a)
    return "open", 0.0, round(mfe, 2), round(mae, 2)


def track_outcomes(provider=None) -> list[dict]:
    """Update every OPEN decision with its first-touch outcome (pulls recent bars per symbol)."""
    from bot.market_data.providers import get_bars
    con = _con()
    rows = con.execute("SELECT id,symbol,side,entry,stop,tp1,tp2,signal_at,"
                       "COALESCE(json_extract(json,'$.tf'),'5m'),"
                       "json_extract(json,'$.exit_mode'),"
                       "COALESCE(json_extract(json,'$.trail_atr'),2.0) FROM decisions "
                       "WHERE outcome IN ('open','tp1_open')").fetchall()
    bars_cache, updated = {}, []
    for rid, sym, side, entry, stop, tp1, tp2, sig_at, tf, exit_mode, trail_mult in rows:
        if sym not in bars_cache:
            try:
                bars_cache[sym] = get_bars(sym, "5m", period="5d", provider=provider)
            except Exception:
                bars_cache[sym] = pd.DataFrame()
        bars = bars_cache[sym]
        if not len(bars) or not sig_at:
            continue
        close_hm = 870 if sym.upper() in _EQUITY_RTH else None       # equities force-flat 2:30pm ET (user rule)
        # SAME-BAR FIX (user catch 2026-07-07: "entry hit tp on same bar"): signal_at is the
        # signal bar's OPEN. The walk runs on 5m bars, so for a 15m-lineage row the 5m bars
        # INSIDE the signal candle (before the entry, which is the 15m CLOSE) must be excluded —
        # otherwise pre-entry price action fakes TP/stop hits. Shift the walk start to the
        # signal candle's close (tf−5 minutes past the open); 5m rows are unchanged (offset 0).
        _tfm = {"1m": 1, "5m": 5, "15m": 15, "30m": 30, "1h": 60}.get(str(tf), 5)
        walk_from = str(pd.Timestamp(sig_at) + pd.Timedelta(minutes=max(_tfm - 5, 0)))
        if str(exit_mode or "") == "trail":       # trail-eq lineage: moving stop needs its own walk
            outcome, r, mfe, mae = _walk_trail(bars, walk_from, side, entry, stop,
                                               float(trail_mult or 2.0), close_hm=close_hm)
        else:
            outcome, r, mfe, mae = _walk(bars, walk_from, side, entry, stop,
                                         tp1, tp2, close_hm=close_hm)  # None preserved (single-target)
        if outcome not in ("open",):
            con.execute("UPDATE decisions SET outcome=?, result_r=?, outcome_at=?, mfe_r=?, mae_r=? WHERE id=?",
                        [outcome, r, utcnow_iso(), mfe, mae, rid])
            updated.append({"symbol": sym, "outcome": outcome, "r": r})
    con.commit(); con.close()
    return updated


def list_decisions(limit: int = 100) -> list[dict]:
    con = _con()
    cols = ["id", "symbol", "side", "family", "session", "entry", "stop", "tp1", "tp2", "taken",
            "decided_at", "outcome", "result_r", "signal_at", "tf", "cat"]
    # tf/cat via SQLite's json_extract — pulling the WHOLE json blob (PIT snapshots + options plans)
    # for 1000 rows per poll was a review-flagged waste; the DB extracts one key instead.
    rows = con.execute(
        "SELECT id,symbol,side,family,session,entry,stop,tp1,tp2,taken,decided_at,outcome,"
        "result_r,signal_at,COALESCE(json_extract(json,'$.tf'),'5m'),json_extract(json,'$.cat') "
        "FROM decisions ORDER BY decided_at DESC LIMIT ?", (limit,)).fetchall()
    con.close()
    from bot.strategy.asset_config import asset_category, CATEGORY_ID
    out = []
    for r in rows:
        d = dict(zip(cols, r)) | {"taken": bool(r[cols.index("taken")])}
        d["cat"] = d.get("cat") or asset_category(d.get("symbol"), d.get("family"))  # backfill legacy rows
        d["cat_id"] = CATEGORY_ID.get(d["cat"], "id-eq")     # user-facing id-eq / id-ft / id-op
        out.append(d)
    return out


def summary() -> dict:
    d = [x for x in list_decisions(1000) if x["taken"] and x["result_r"] is not None
         and x["outcome"] != "open" and is_core_family(x.get("family"))]
    if not d:
        return {"taken_closed": 0}
    rs = [x["result_r"] for x in d]
    from collections import Counter
    return {"taken_closed": len(d), "total_R": round(sum(rs), 1),
            "win_pct": round(100 * sum(r > 0 for r in rs) / len(rs), 1),
            "outcomes": dict(Counter(x["outcome"] for x in d))}


def perf_summary() -> dict:
    """Performance of the tracked (auto-shadow + manual) taken signals — the live record for the
    Performance panel. Same closed-decision source the scorecard uses, in R (first-touch outcomes)."""
    import numpy as np
    d = [x for x in list_decisions(3000) if x["taken"] and x.get("result_r") is not None and x["outcome"] != "open"]
    if not d:
        return {"trades": 0}
    rs = np.array([float(x["result_r"]) for x in d])
    w = float(rs[rs > 0].sum()); l = float(-rs[rs < 0].sum())
    cum = np.cumsum(rs); dd = float((cum - np.maximum.accumulate(cum)).min())
    return {"trades": int(len(rs)), "exp_R": round(float(rs.mean()), 3), "total_R": round(float(rs.sum()), 1),
            "win_pct": round(100 * float((rs > 0).mean())), "profit_factor": round(w / l, 2) if l > 0 else 99.0,
            "max_dd_pct": round(dd, 1)}


def integrity() -> dict:
    """JOURNAL INTEGRITY AUDIT (continuous — hourly tick + /api/journal/integrity + the training
    lab's journal panel). Hunts the corruption classes we've fought since the start:
      dupes         — >1 row for the same (family, symbol, side, tf, signal bar) — the same-bar
                      double-entry class. Cross-LINEAGE same-bar rows (breakout@5m vs @15m vs
                      worker-*) are BY DESIGN and reported separately as info, not corruption.
      bad_levels    — rows whose entry/stop/TP geometry is impossible (also blocked at write).
      no_bar_id     — rows without signal_at (can never resolve; the starvation class).
    """
    con = _con()
    rows = con.execute("SELECT id, symbol, side, family, signal_at, entry, stop, tp1, tp2, json "
                       "FROM decisions").fetchall()
    con.close()
    seen: dict = {}
    dupes, bad, no_id, cross = [], [], [], {}
    for rid, sym, side, fam, sig_at, e, s, t1, t2, raw in rows:
        try:
            tf = (json.loads(raw or "{}") or {}).get("tf") or "5m"
        except Exception:
            tf = "5m"
        if not sig_at:
            no_id.append(rid[:6])
        r = _levels_ok({"symbol": sym, "side": side, "entry": e, "stop": s, "tp1": t1, "tp2": t2})
        if r:
            bad.append({"id": rid[:6], "symbol": sym, "family": fam, "reason": r})
        key = (fam, sym, side, tf, sig_at or "")
        if key in seen:
            dupes.append({"id": rid[:6], "dup_of": seen[key][:6], "symbol": sym,
                          "family": fam, "tf": tf, "signal_at": sig_at})
        else:
            seen[key] = rid
        if sig_at:                                 # same bar across lineages = intentional, info only
            cross.setdefault((sym, side, sig_at), set()).add(f"{fam}@{tf}")
    multi = {f"{k[0]} {k[1]} {k[2][:16]}": sorted(v) for k, v in cross.items() if len(v) > 1}
    ok = not dupes and not bad and not no_id
    return {"ok": ok, "rows": len(rows), "dupes": dupes, "bad_levels": bad,
            "missing_bar_identity": no_id,
            "same_bar_lineages_info": multi,
            "note": "same-bar rows across DIFFERENT lineages (5m/15m/worker) are separate "
                    "studies by design — only same-lineage duplicates are corruption"}


def study() -> dict:
    """FIRST-TOUCH STUDY — what hit first (stop vs TP) + how far price ran (MFE/MAE), the signal for tuning
    stops & targets to make the system more accurate. Aggregates closed tracked signals."""
    import numpy as np
    from collections import Counter
    con = _con()
    rows = con.execute("SELECT outcome, result_r, mfe_r, mae_r FROM decisions "
                       "WHERE taken=1 AND outcome NOT IN ('open') AND result_r IS NOT NULL "
                       # CORE ONLY (user catch 2026-07-07: study said 14 closed vs scorecard 10):
                       # worker rows carry 0.3-0.4R targets — mixing them corrupts a study that
                       # tunes the CORE 4R geometry. Same population as the scorecard now.
                       f"AND {CORE_ONLY_SQL}").fetchall()
    con.close()
    if not rows:
        return {"n": 0, "hints": []}
    n = len(rows); oc = Counter(r[0] for r in rows)
    mfe = np.array([r[2] for r in rows if r[2] is not None], float)
    mae = np.array([r[3] for r in rows if r[3] is not None], float)
    win_mae = np.array([r[3] for r in rows if r[1] and r[1] > 0 and r[3] is not None], float)
    tp2p = oc.get("tp2", 0) / n; stopf = oc.get("stop", 0) / n; give = oc.get("tp1_then_stop", 0) / n
    med_mfe = float(np.median(mfe)) if len(mfe) else None
    hints = []
    if med_mfe is not None and med_mfe < 2.0 and tp2p < 0.25:
        hints.append(f"TP2 (4R) reached only {round(100*tp2p)}% (median MFE {med_mfe:.1f}R) — a NEARER target or a trail likely banks more.")
    if stopf > 0.5:
        hints.append(f"stop hit first on {round(100*stopf)}% — stop may be too tight or entries too early.")
    if give > 0.12:
        hints.append(f"{round(100*give)}% gave back after TP1 — NOTE: tested trail/BE-to-TP1, it HURT equities (cut runners), so full-to-TP2 kept.")
    if len(win_mae) and float(np.median(win_mae)) < 0.5:
        hints.append(f"winners rarely dip past {float(np.median(win_mae)):.1f}R against you — a tighter stop may hold the edge at less risk.")
    return {"n": n, "first_touch": dict(oc),
            "tp2_pct": round(100 * tp2p),
            "tp1_first_pct": round(100 * (oc.get("tp1_open", 0) + oc.get("tp1_then_stop", 0)) / n),
            "stop_first_pct": round(100 * stopf), "tp1_then_stop_pct": round(100 * give),
            "mfe_med": round(med_mfe, 2) if med_mfe is not None else None,
            "mfe_avg": round(float(mfe.mean()), 2) if len(mfe) else None,
            "mae_med": round(float(np.median(mae)), 2) if len(mae) else None,
            "win_pct": round(100 * sum(1 for r in rows if r[1] and r[1] > 0) / n), "hints": hints}


# Backtested reference for the CORE breakout under honest fills (F64, 2026-06-29). It MUST describe the
# model _walk actually scores: full position, fixed structure stop, first-touch — stop and tp1_then_stop
# both = -1R (NO breakeven move), tp2 = +4R. That is F64's "full-to-4R cap, no scale" (QQQ +0.264, ~42%
# reach TP2). This is what live GRADE-A signals should reproduce — the live==backtest gate before sizing up.
BACKTEST_REF = {"exp_R": 0.24, "win_pct": 42.0,
                "note": "F64 full position -> 4R cap, no scale / no BE (QQQ +0.26R, NQ/SPY similar)"}
MIN_SAMPLE = 12
# CORE-ONLY filter (user 2026-07-07: worker entries live in the journal lab but must NOT corrupt
# the paper-trade analytics): worker/emergent shadow lineages trade a DIFFERENT geometry, so the
# live-vs-backtest scorecard, summary and phase-7/8 paper study judge CORE families only. Workers
# are judged by the Boss on their own family-filtered windows.
CORE_ONLY_SQL = ("(family IS NULL OR (family NOT LIKE 'worker-%' "
                 "AND family NOT LIKE 'emergent-%' AND family NOT LIKE 'trail-%' "
                 "AND family NOT LIKE 'options-native-%'))")


def is_core_family(fam) -> bool:
    f = str(fam or "")
    return not (f.startswith("worker-") or f.startswith("emergent-")
                or f.startswith("trail-") or f.startswith("options-native-"))


def _stats(rs: list[float]) -> dict:
    n = len(rs)
    if not n:
        return {"n": 0}
    mean = sum(rs) / n
    var = sum((r - mean) ** 2 for r in rs) / (n - 1) if n > 1 else 0.0
    se = (var / n) ** 0.5 if n > 1 else 0.0
    return {"n": n, "exp_R": round(mean, 3), "se": round(se, 3), "total_R": round(sum(rs), 1),
            "win_pct": round(100 * sum(r > 0 for r in rs) / n, 1),
            "lo": round(mean - 1.96 * se, 3), "hi": round(mean + 1.96 * se, 3)}


def scorecard() -> dict:
    """LIVE-vs-BACKTEST gate: do taken signals realise the backtested edge? Broken down by grade.
    Grade comes from the persisted signal JSON (grade A = production-faithful, what should match)."""
    con = _con()
    rows = con.execute("SELECT result_r, outcome, json FROM decisions "
                       "WHERE taken=1 AND outcome NOT IN ('open') AND result_r IS NOT NULL "
                       f"AND {CORE_ONLY_SQL}").fetchall()
    con.close()
    closed = []
    for r, _o, j in rows:
        try:
            g = (json.loads(j or "{}") or {}).get("grade")
        except Exception:
            g = None
        closed.append((float(r), g))
    overall = _stats([r for r, _g in closed])
    by_grade = {g: _stats([r for r, gg in closed if gg == g]) for g in ("A+", "A", "B", "C")
                if any(gg == g for _r, gg in closed)}
    ref = BACKTEST_REF
    target = by_grade.get("A") or overall          # judge on grade-A if we have it, else the whole book
    verdict, ok = "insufficient sample (need %d taken+closed)" % MIN_SAMPLE, None
    if target.get("n", 0) >= MIN_SAMPLE:
        if target["hi"] >= ref["exp_R"]:           # backtest expectancy inside/below the live CI upper bound
            verdict, ok = "live CONSISTENT with backtest", True
        elif target["exp_R"] > 0:
            verdict, ok = "live positive but BELOW backtest (check fills/slippage)", False
        else:
            verdict, ok = "live NOT matching backtest (negative) — do not scale up", False
    return {"overall": overall, "by_grade": by_grade, "backtest_ref": ref,
            "verdict": verdict, "consistent": ok, "min_sample": MIN_SAMPLE,
            "judged_on": "grade A" if "A" in by_grade else "all taken trades"}


if __name__ == "__main__":   # self-test with a synthetic long that hits TP1 then TP2
    import numpy as np
    rid = record_decision({"candidate_id": "t1", "symbol": "QQQ", "side": "long", "family": "breakout",
                           "entry": 100.0, "stop": 99.0, "tp1": 101.5, "tp2": 104.0,
                           "generated_at": "2026-06-29T14:00:00+00:00"}, taken=True)
    ts = pd.date_range("2026-06-29 14:00", periods=10, freq="5min", tz="UTC").tz_convert("America/New_York")
    bars = pd.DataFrame({"ts_et": ts, "open": 100, "high": [100, 101, 102, 104, 104, 104, 104, 104, 104, 104],
                         "low": [99.5] * 10, "close": 102})
    out, r, _mfe, _mae = _walk(bars, "2026-06-29T14:00:00+00:00", "long", 100, 99, 101.5, 104)
    assert out == "tp2" and abs(r - 4.0) < 1e-6, (out, r)
    print(f"walk: synthetic long -> {out} ({r:+.1f}R)  | decision {rid['id'][:8]} recorded")
    print("tracker OK")
