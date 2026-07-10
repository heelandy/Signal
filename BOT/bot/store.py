"""SQLite persistence (DBA-001/DBS-001 minimal) — real DB behind the journal.

One file `BOT/data/highstrike.db` with the core tables (candidates, risk_decisions, orders,
order_events, journal). `record(obj)` routes any contract object to its table (append-only +
full JSON kept). Used by the API/dashboard for queries the JSONL journal can't do efficiently.

    from bot.store import Store
    db = Store(); db.record(candidate); db.record(risk_decision)
    db.recent("candidates", 20); db.metrics()
"""
from __future__ import annotations

import json
import sqlite3
from pathlib import Path

from bot.config import BOT_ROOT
from bot.contracts import (TradeCandidate, RiskDecision, OrderRequest, OrderEvent, JournalEntry)

DEFAULT_DB = BOT_ROOT / "data" / "highstrike.db"

_SCHEMA = """
CREATE TABLE IF NOT EXISTS candidates(candidate_id TEXT PRIMARY KEY, symbol TEXT, side TEXT, setup TEXT,
  entry REAL, stop REAL, tp2 REAL, regime TEXT, session TEXT, strategy_version TEXT, generated_at TEXT, json TEXT);
CREATE TABLE IF NOT EXISTS risk_decisions(trace_id TEXT PRIMARY KEY, candidate_id TEXT, status TEXT,
  reason_code TEXT, max_qty INTEGER, max_risk_dollars REAL, decided_at TEXT, json TEXT);
CREATE TABLE IF NOT EXISTS orders(order_id TEXT PRIMARY KEY, candidate_id TEXT, symbol TEXT, side TEXT,
  qty INTEGER, order_type TEXT, limit_price REAL, stop_price REAL, take_profit REAL, created_at TEXT, json TEXT);
CREATE TABLE IF NOT EXISTS order_events(rowid INTEGER PRIMARY KEY AUTOINCREMENT, order_id TEXT, state TEXT,
  filled_qty INTEGER, avg_fill_price REAL, broker_order_id TEXT, ts TEXT, json TEXT);
CREATE TABLE IF NOT EXISTS journal(entry_id TEXT PRIMARY KEY, candidate_id TEXT, symbol TEXT, side TEXT,
  mode TEXT, net_r REAL, exit_reason TEXT, opened_at TEXT, closed_at TEXT, json TEXT);
CREATE INDEX IF NOT EXISTS ix_cand_sym ON candidates(symbol);
CREATE INDEX IF NOT EXISTS ix_jrnl_sym ON journal(symbol);
"""


class Store:
    def __init__(self, path: Path | str = DEFAULT_DB):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.con = sqlite3.connect(str(self.path), check_same_thread=False)
        self.con.executescript(_SCHEMA)
        self.con.commit()

    def close(self) -> None:
        """Explicit lifecycle (warning sweep 2026-07-11): Store objects held their connection
        until GC — the 'unclosed database' ResourceWarnings in the suite. Close when done."""
        try:
            self.con.close()
        except Exception:
            pass

    def __del__(self):
        self.close()

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.close()

    def _ins(self, table, cols, vals):
        ph = ",".join("?" * len(vals))
        self.con.execute(f"INSERT OR REPLACE INTO {table}({','.join(cols)}) VALUES({ph})", vals)
        self.con.commit()

    def record(self, obj) -> None:
        d = obj.to_dict(); j = json.dumps(d)
        if isinstance(obj, TradeCandidate):
            self._ins("candidates", ["candidate_id", "symbol", "side", "setup", "entry", "stop", "tp2",
                                     "regime", "session", "strategy_version", "generated_at", "json"],
                      [obj.candidate_id, obj.symbol, d["side"], obj.setup, obj.entry, obj.stop, obj.tp2,
                       obj.regime, d.get("session"), obj.strategy_version, obj.generated_at, j])
        elif isinstance(obj, RiskDecision):
            self._ins("risk_decisions", ["trace_id", "candidate_id", "status", "reason_code", "max_qty",
                                         "max_risk_dollars", "decided_at", "json"],
                      [obj.trace_id, obj.candidate_id, d["status"], d["reason_code"], obj.max_qty,
                       obj.max_risk_dollars, obj.decided_at, j])
        elif isinstance(obj, OrderRequest):
            self._ins("orders", ["order_id", "candidate_id", "symbol", "side", "qty", "order_type",
                                 "limit_price", "stop_price", "take_profit", "created_at", "json"],
                      [obj.order_id, obj.candidate_id, obj.symbol, d["side"], obj.qty, d["order_type"],
                       obj.limit_price, obj.stop_price, obj.take_profit, obj.created_at, j])
        elif isinstance(obj, OrderEvent):
            self._ins("order_events", ["order_id", "state", "filled_qty", "avg_fill_price",
                                       "broker_order_id", "ts", "json"],
                      [obj.order_id, d["state"], obj.filled_qty, obj.avg_fill_price, obj.broker_order_id, obj.ts, j])
        elif isinstance(obj, JournalEntry):
            self._ins("journal", ["entry_id", "candidate_id", "symbol", "side", "mode", "net_r",
                                  "exit_reason", "opened_at", "closed_at", "json"],
                      [obj.entry_id, obj.candidate_id, obj.symbol, d["side"], d["mode"], obj.net_r,
                       d.get("exit_reason"), obj.opened_at, obj.closed_at, j])

    def recent(self, table: str, n: int = 20) -> list[dict]:
        order = {"candidates": "generated_at", "risk_decisions": "decided_at", "orders": "created_at",
                 "order_events": "ts", "journal": "closed_at"}.get(table, "rowid")
        cur = self.con.execute(f"SELECT json FROM {table} ORDER BY {order} DESC LIMIT ?", (n,))
        return [json.loads(r[0]) for r in cur.fetchall()]

    def metrics(self) -> dict:
        rs = [r[0] for r in self.con.execute("SELECT net_r FROM journal WHERE net_r IS NOT NULL").fetchall()]
        if not rs:
            return {"trades": 0}
        import numpy as np
        a = np.array(rs); w = a[a > 0]
        return {"trades": len(a), "win_pct": round(100 * float((a > 0).mean()), 1),
                "exp_R": round(float(a.mean()), 3), "total_R": round(float(a.sum()), 1),
                "profit_factor": round(float(w.sum() / -a[a <= 0].sum()), 2) if (a <= 0).any() else float("inf")}

    def counts(self) -> dict:
        return {t: self.con.execute(f"SELECT count(*) FROM {t}").fetchone()[0]
                for t in ("candidates", "risk_decisions", "orders", "order_events", "journal")}


if __name__ == "__main__":   # self-test against a temp DB
    import tempfile
    from bot.contracts import Mode, ExitReason
    db = Store(Path(tempfile.mkdtemp()) / "t.db")
    c = TradeCandidate(symbol="QQQ", side="long", timeframe="5m", setup="breakout",
                       entry=722, stop=719, tp2=734, strategy_version="f62")
    db.record(c)
    db.record(RiskDecision(candidate_id=c.candidate_id, status="approved", max_qty=50, max_risk_dollars=150))
    db.record(OrderRequest(candidate_id=c.candidate_id, symbol="QQQ", side="long", qty=50,
                           limit_price=722, stop_price=719, take_profit=734))
    for r in (4.0, -1.0, 4.0):
        db.record(JournalEntry(candidate_id=c.candidate_id, symbol="QQQ", side="long", mode=Mode.PAPER,
                              net_r=r, exit_reason=ExitReason.TP2 if r > 0 else ExitReason.STOP))
    assert db.counts()["candidates"] == 1 and db.counts()["journal"] == 3, db.counts()
    print("counts:", db.counts())
    print("metrics:", db.metrics())
    print("recent candidate:", db.recent("candidates", 1)[0]["symbol"], db.recent("candidates", 1)[0]["setup"])
    print("SQLite store OK")
