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

_SCHEMA = """
CREATE TABLE IF NOT EXISTS decisions(
  id TEXT PRIMARY KEY, candidate_id TEXT, symbol TEXT, side TEXT, family TEXT, session TEXT,
  entry REAL, stop REAL, tp1 REAL, tp2 REAL, taken INTEGER, decided_at TEXT, signal_at TEXT,
  outcome TEXT DEFAULT 'open', outcome_at TEXT, result_r REAL, json TEXT);
"""


def _con():
    c = sqlite3.connect(str(DB), check_same_thread=False)
    c.executescript(_SCHEMA); c.commit()
    return c


def record_decision(sig: dict, taken: bool) -> dict:
    """Persist the user's take/skip on a signal. Returns the stored row id."""
    rid = str(uuid.uuid4())
    con = _con()
    con.execute(
        "INSERT OR REPLACE INTO decisions(id,candidate_id,symbol,side,family,session,entry,stop,tp1,tp2,"
        "taken,decided_at,signal_at,outcome,json) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
        [rid, sig.get("candidate_id") or sig.get("id") or rid, sig["symbol"], sig["side"],
         sig.get("family"), sig.get("session"), sig["entry"], sig["stop"], sig.get("tp1"), sig.get("tp2"),
         1 if taken else 0, utcnow_iso(), sig.get("generated_at") or sig.get("signal_at"), "open", json.dumps(sig)])
    con.commit(); con.close()
    return {"id": rid, "taken": taken, "symbol": sig["symbol"]}


def _walk(bars: pd.DataFrame, signal_at: str, side: str, entry, stop, tp1, tp2) -> tuple[str, float]:
    """First-touch outcome from the signal bar forward. Returns (outcome, result_R)."""
    ts = pd.to_datetime(bars["ts_et"], utc=True)
    start = pd.Timestamp(signal_at)
    start = start.tz_localize("UTC") if start.tz is None else start.tz_convert("UTC")
    fwd = bars[ts > start]
    if fwd.empty:
        return "open", 0.0
    sign = 1 if side == "long" else -1
    risk = abs(entry - stop)
    hi, lo = fwd["high"].to_numpy(float), fwd["low"].to_numpy(float)
    tp1_hit = False
    for j in range(len(fwd)):
        hit_stop = lo[j] <= stop if sign == 1 else hi[j] >= stop
        hit_tp1 = hi[j] >= tp1 if sign == 1 else lo[j] <= tp1
        hit_tp2 = hi[j] >= tp2 if sign == 1 else lo[j] <= tp2
        if hit_stop and not tp1_hit:
            return "stop", -1.0
        if hit_tp2:
            return "tp2", sign * (tp2 - entry) / risk
        if hit_tp1 and not tp1_hit:
            tp1_hit = True
        if hit_stop and tp1_hit:                      # came back to stop after TP1
            return "tp1_then_stop", round(sign * (stop - entry) / risk, 2)
    if tp1_hit:
        return "tp1_open", round(sign * (tp1 - entry) / risk, 2)   # TP1 hit, TP2 not yet, still open
    return "open", 0.0


def track_outcomes(provider=None) -> list[dict]:
    """Update every OPEN decision with its first-touch outcome (pulls recent bars per symbol)."""
    from bot.market_data.providers import get_bars
    con = _con()
    rows = con.execute("SELECT id,symbol,side,entry,stop,tp1,tp2,signal_at FROM decisions "
                       "WHERE outcome IN ('open','tp1_open')").fetchall()
    bars_cache, updated = {}, []
    for rid, sym, side, entry, stop, tp1, tp2, sig_at in rows:
        if sym not in bars_cache:
            try:
                bars_cache[sym] = get_bars(sym, "5m", period="5d", provider=provider)
            except Exception:
                bars_cache[sym] = pd.DataFrame()
        bars = bars_cache[sym]
        if not len(bars) or not sig_at:
            continue
        outcome, r = _walk(bars, sig_at, side, entry, stop, tp1 or entry, tp2 or entry)
        if outcome not in ("open",):
            con.execute("UPDATE decisions SET outcome=?, result_r=?, outcome_at=? WHERE id=?",
                        [outcome, r, utcnow_iso(), rid])
            updated.append({"symbol": sym, "outcome": outcome, "r": r})
    con.commit(); con.close()
    return updated


def list_decisions(limit: int = 100) -> list[dict]:
    con = _con()
    cols = ["id", "symbol", "side", "family", "session", "entry", "stop", "tp1", "tp2", "taken",
            "decided_at", "outcome", "result_r"]
    rows = con.execute(f"SELECT {','.join(cols)} FROM decisions ORDER BY decided_at DESC LIMIT ?", (limit,)).fetchall()
    con.close()
    return [dict(zip(cols, r)) | {"taken": bool(r[cols.index("taken")])} for r in rows]


def summary() -> dict:
    d = [x for x in list_decisions(1000) if x["taken"] and x["result_r"] is not None and x["outcome"] != "open"]
    if not d:
        return {"taken_closed": 0}
    rs = [x["result_r"] for x in d]
    from collections import Counter
    return {"taken_closed": len(d), "total_R": round(sum(rs), 1),
            "win_pct": round(100 * sum(r > 0 for r in rs) / len(rs), 1),
            "outcomes": dict(Counter(x["outcome"] for x in d))}


if __name__ == "__main__":   # self-test with a synthetic long that hits TP1 then TP2
    import numpy as np
    rid = record_decision({"candidate_id": "t1", "symbol": "QQQ", "side": "long", "family": "breakout",
                           "entry": 100.0, "stop": 99.0, "tp1": 101.5, "tp2": 104.0,
                           "generated_at": "2026-06-29T14:00:00+00:00"}, taken=True)
    ts = pd.date_range("2026-06-29 14:00", periods=10, freq="5min", tz="UTC").tz_convert("America/New_York")
    bars = pd.DataFrame({"ts_et": ts, "open": 100, "high": [100, 101, 102, 104, 104, 104, 104, 104, 104, 104],
                         "low": [99.5] * 10, "close": 102})
    out, r = _walk(bars, "2026-06-29T14:00:00+00:00", "long", 100, 99, 101.5, 104)
    assert out == "tp2" and abs(r - 4.0) < 1e-6, (out, r)
    print(f"walk: synthetic long -> {out} ({r:+.1f}R)  | decision {rid['id'][:8]} recorded")
    print("tracker OK")
