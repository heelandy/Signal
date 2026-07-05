"""Unified audit trail (AITP-001 §8.10) — ONE append-only JSONL for every governance/state event.

Everything that changes what the system is allowed to do lands here with who/when/what:
approvals + revokes, model registrations + promotions, paper-autotrade toggles, kill switch,
mode changes, training runs, continuous-training start/stop. Append-only by construction —
`log()` only ever opens the file in append mode; there is no delete/update API.

    from bot.audit import log, tail
    log("approval", stage="paper", by="user", strategy_version="orb-standard-2026.07")
    tail(50)                                  # newest-first for the dashboard
"""
from __future__ import annotations

import json
import threading
from pathlib import Path

from bot.config import BOT_ROOT

FILE = BOT_ROOT / "data" / "audit.jsonl"
_lock = threading.Lock()


def log(event: str, **fields) -> dict:
    """Append one audit record (thread-safe). Never raises into the caller — an audit failure
    must not break trading paths (it is reported in the record stream itself on next success)."""
    from bot.contracts import utcnow_iso
    rec = {"ts": utcnow_iso(), "event": event, **fields}
    try:
        with _lock:
            FILE.parent.mkdir(parents=True, exist_ok=True)
            with FILE.open("a", encoding="utf-8") as f:
                f.write(json.dumps(rec, default=str) + "\n")
    except Exception:
        pass
    return rec


def tail(n: int = 100, event: str | None = None) -> list[dict]:
    """Newest-first read of the last `n` records (optionally filtered by event type)."""
    if not FILE.exists():
        return []
    out = []
    try:
        lines = FILE.read_text(encoding="utf-8").splitlines()
    except Exception:
        return []
    for line in reversed(lines):
        try:
            rec = json.loads(line)
        except Exception:
            continue
        if event and rec.get("event") != event:
            continue
        out.append(rec)
        if len(out) >= n:
            break
    return out


if __name__ == "__main__":
    r = log("selftest", detail="audit smoke", by="cli")
    rows = tail(5)
    assert rows and rows[0]["event"] in ("selftest",), rows[:1]
    assert rows[0]["ts"] and rows[0]["detail"] == "audit smoke"
    print(f"audit OK — {FILE} has {len(FILE.read_text(encoding='utf-8').splitlines())} records")
