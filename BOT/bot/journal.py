"""Append-only journal — the audit trail. Every candidate, risk decision, order event, and trade
outcome is written as one JSON line, never mutated. This is the source for review, reconciliation,
metrics, and the future ML labels.

    from bot.journal import Journal
    j = Journal()                      # default BOT/data/journal.jsonl
    j.record(candidate); j.record(decision); j.record(entry)
    j.metrics()                        # {trades, win_pct, total_R, exp_R, ...}
"""
from __future__ import annotations

import json
from pathlib import Path

from bot.config import BOT_ROOT
from bot.contracts import utcnow_iso

DEFAULT_PATH = BOT_ROOT / "data" / "journal.jsonl"


class Journal:
    def __init__(self, path: Path | str = DEFAULT_PATH):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)

    def record(self, obj) -> None:
        """Append any contract object (must have .to_dict()) tagged with its type."""
        row = {"type": type(obj).__name__, "logged_at": utcnow_iso(), **obj.to_dict()}
        with self.path.open("a", encoding="utf-8") as f:
            f.write(json.dumps(row) + "\n")

    def read(self, type_name: str | None = None) -> list[dict]:
        if not self.path.exists():
            return []
        rows = [json.loads(ln) for ln in self.path.read_text(encoding="utf-8").splitlines() if ln.strip()]
        return [r for r in rows if type_name is None or r["type"] == type_name]

    def metrics(self) -> dict:
        js = self.read("JournalEntry")
        rs = [r["net_r"] for r in js if r.get("net_r") is not None]
        if not rs:
            return {"trades": 0}
        wins = [r for r in rs if r > 0]
        gross_w = sum(wins); gross_l = -sum(r for r in rs if r <= 0)
        return {
            "trades": len(rs),
            "win_pct": round(100 * len(wins) / len(rs), 1),
            "exp_R": round(sum(rs) / len(rs), 3),
            "total_R": round(sum(rs), 1),
            "profit_factor": round(gross_w / gross_l, 2) if gross_l else float("inf"),
            "exit_mix": {k: sum(1 for r in js if r.get("exit_reason") == k)
                         for k in {r.get("exit_reason") for r in js if r.get("exit_reason")}},
        }


if __name__ == "__main__":   # self-test against a temp journal
    import tempfile
    from bot.contracts import TradeCandidate, JournalEntry, Mode, ExitReason
    p = Path(tempfile.mkdtemp()) / "j.jsonl"
    j = Journal(p)
    c = TradeCandidate(symbol="QQQ", side="long", timeframe="5m", setup="orb_stack",
                       entry=100, stop=99, tp2=104, strategy_version="t")
    j.record(c)
    for r in (4.0, -1.0, 4.0, -1.0, 0.5):
        j.record(JournalEntry(candidate_id=c.candidate_id, symbol="QQQ", side="long", mode=Mode.REPLAY,
                              net_r=r, exit_reason=(ExitReason.TP2 if r > 0 else ExitReason.STOP)))
    assert len(j.read()) == 6 and len(j.read("JournalEntry")) == 5
    m = j.metrics()
    assert m["trades"] == 5 and m["total_R"] == 6.5, m
    print("journal OK:", m)
