"""BACKUP + TESTED RESTORE (remediation Phase 7, 2026-07-11).

An untested backup is not a backup. `backup()` snapshots the state that cannot be regenerated —
SQLite stores, journals, approvals, runtime state — into a timestamped folder with a sha256
manifest; `verify()` checks every hash; `restore()` copies a verified snapshot into a target
root (a scratch directory for drills, the real data dir for disaster recovery — restoring over
live data is deliberately NOT the default).

    from bot.backup import backup, verify, restore
    b = backup()                     # -> BOT/data/backups/<UTC-stamp>/
    verify(b["path"])                # {"ok": True, ...}
    restore(b["path"], dst_root=...) # drill into a scratch dir; point at data/ only on purpose

The scan loop runs one backup per UTC day (beat 'backup'); the last verified drill is recorded
in the manifest of truth (docs/STATUS.md).
"""
from __future__ import annotations

import hashlib
import json
import shutil
import time
from pathlib import Path

from bot.config import BOT_ROOT

DATA = BOT_ROOT / "data"
DEFAULT_DST = DATA / "backups"
# state that cannot be regenerated (bar stores/reports rebuild from source; these do not)
TARGETS = ("highstrike.db", "execution.db", "journal.jsonl", "audit.jsonl", "alerts.jsonl",
           "approvals.json", "runtime_state.json", "boss.json", "evolve_drafts.json",
           "duel.json", "options_native_journal.jsonl", "options_native_open.jsonl")


def _sha(p: Path) -> str:
    h = hashlib.sha256()
    with p.open("rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def backup(src_root: Path | str = DATA, dst_root: Path | str = DEFAULT_DST) -> dict:
    src, dst_root = Path(src_root), Path(dst_root)
    stamp = time.strftime("%Y%m%dT%H%M%SZ", time.gmtime())
    dst = dst_root / stamp
    dst.mkdir(parents=True, exist_ok=True)
    manifest = {}
    for name in TARGETS:
        p = src / name
        if not p.exists():
            continue
        if name.endswith(".db"):
            _sqlite_copy(p, dst / name)                # consistent snapshot even mid-write (WAL)
        else:
            shutil.copy2(p, dst / name)
        manifest[name] = {"sha256": _sha(dst / name), "bytes": (dst / name).stat().st_size}
    (dst / "MANIFEST.json").write_text(json.dumps(
        {"created_at": stamp, "src_root": str(src), "files": manifest}, indent=1),
        encoding="utf-8")
    return {"ok": bool(manifest), "path": str(dst), "files": len(manifest)}


def _sqlite_copy(src: Path, dst: Path) -> None:
    import sqlite3
    try:
        s = sqlite3.connect(str(src))
        d = sqlite3.connect(str(dst))
        s.backup(d)
        d.close(); s.close()
    except Exception:
        shutil.copy2(src, dst)                          # not a live sqlite file: byte copy


def verify(path: Path | str) -> dict:
    p = Path(path)
    try:
        man = json.loads((p / "MANIFEST.json").read_text(encoding="utf-8"))
    except Exception as e:
        return {"ok": False, "error": f"no readable manifest: {e}"}
    bad = []
    for name, info in man.get("files", {}).items():
        f = p / name
        if not f.exists() or _sha(f) != info["sha256"]:
            bad.append(name)
    return {"ok": not bad, "checked": len(man.get("files", {})), "bad": bad,
            "created_at": man.get("created_at")}


def restore(path: Path | str, dst_root: Path | str) -> dict:
    """Copy a VERIFIED snapshot into dst_root. Refuses an unverifiable snapshot (fail closed)."""
    v = verify(path)
    if not v["ok"]:
        return {"ok": False, "error": f"snapshot failed verification: {v}"}
    p, dst = Path(path), Path(dst_root)
    dst.mkdir(parents=True, exist_ok=True)
    n = 0
    for name in json.loads((p / "MANIFEST.json").read_text(encoding="utf-8"))["files"]:
        shutil.copy2(p / name, dst / name)
        n += 1
    return {"ok": True, "restored": n, "to": str(dst)}


def prune(dst_root: Path | str = DEFAULT_DST, keep: int = 14) -> int:
    """Keep the newest `keep` snapshots; drop the rest."""
    root = Path(dst_root)
    if not root.exists():
        return 0
    snaps = sorted([d for d in root.iterdir() if d.is_dir()], key=lambda d: d.name)
    gone = 0
    for d in snaps[:-keep]:
        shutil.rmtree(d, ignore_errors=True)
        gone += 1
    return gone
