"""EVIDENCE MANIFEST (Signal-Certificate T1, 2026-07-12).

Every approved run pins ONE immutable manifest; every number in approvals/operator views must
resolve to it. The manifest binds the strategy version to the exact FROZEN evidence it was granted
against — data cutoff, evidence fingerprint, engine/simulator versions, cost assumptions, and the
hashes of the report/dataset artifacts — so a daily operational-bar append (which grows the store
but not the evidence range) can never silently change what an approval means.

    from bot.evidence_manifest import build_manifest, manifest_hash
    m = build_manifest("orb-standard-2026.07.7")
"""
from __future__ import annotations

import hashlib
import json
import subprocess
from pathlib import Path

from bot.config import BOT_ROOT

REPORTS = BOT_ROOT / "data" / "ml" / "reports"
ENGINE_VERSION = "corrected-2026.07.11"          # remediation Phases 1-3 (lookahead/sim/economics)
SIMULATOR_VERSION = "bar-event-2026.07.11"        # BAR-EVENT ORDERING POLICY (hs_backtest docstring)
TRADED_SYMS = ("QQQ", "SPY")                      # the actionable book (NQ/ES/GC are context-only)


def _git_commit() -> str | None:
    try:
        out = subprocess.run(["git", "rev-parse", "--short", "HEAD"], cwd=str(BOT_ROOT.parent),
                             capture_output=True, text=True, timeout=5)
        rev = out.stdout.strip()
        dirty = subprocess.run(["git", "status", "--porcelain"], cwd=str(BOT_ROOT.parent),
                               capture_output=True, text=True, timeout=5).stdout.strip()
        return f"{rev}{'-dirty' if dirty else ''}" if rev else None
    except Exception:
        return None


def _hash_file(p: Path) -> str | None:
    try:
        return hashlib.sha256(p.read_bytes()).hexdigest()[:16]
    except Exception:
        return None


def _read_json(p: Path) -> dict:
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except Exception:
        return {}


def _cost_assumptions() -> dict:
    """Per-symbol economics the evidence was scored under (the contract registry, not guesses)."""
    out = {}
    try:
        import sys
        sys.path.insert(0, str(BOT_ROOT.parent / "engine"))
        import hs_contracts
        for s in TRADED_SYMS:
            spec = hs_contracts.spec(s)
            out[s] = {"point_value": spec.point_value, "tick": spec.tick,
                      "commission": spec.commission, "slip_ticks": spec.slip_ticks}
    except Exception as e:
        out = {"error": str(e)[:80]}
    return out


def build_manifest(strategy_version: str, syms=TRADED_SYMS, tf: str = "5m", sess: str = "rth",
                   waiver: str | None = None) -> dict:
    """Assemble the immutable evidence manifest from the on-disk reports + code/version state."""
    qa = _read_json(REPORTS / "dataqa.json")
    ab = _read_json(REPORTS / "ab_entry_standard.json")
    spans = {s: (qa.get("symbols", {}).get(s, {}) or {}).get("span") for s in syms}
    m = {
        "strategy_version": strategy_version,
        "git_commit": _git_commit(),
        "evidence_fingerprint": qa.get("evidence_fingerprint"),
        "evidence_cutoff": qa.get("evidence_cutoff"),
        "store_fingerprint": qa.get("store_fingerprint"),      # operational, for display only
        "symbols": list(syms), "timeframe": tf, "session": sess,
        "spans": spans,
        "engine_version": ENGINE_VERSION, "simulator_version": SIMULATOR_VERSION,
        "cost_assumptions": _cost_assumptions(),
        "report_hash": _hash_file(REPORTS / "dataqa.json"),
        "ab_report_hash": _hash_file(REPORTS / "ab_entry_standard.json"),
        "ab_lineage": (ab.get("lineage") if isinstance(ab, dict) else None),
        "dataset_hash": _hash_file(REPORTS / "entry_matrix_backtest_rows.json"),
        "qa_all_ok": qa.get("all_ok"),
        "qa_traded_ok": all((qa.get("symbols", {}).get(s, {}) or {}).get("ok") is True for s in syms),
        "waiver": waiver,
        "generated_at": __import__("time").strftime("%Y-%m-%dT%H:%M:%SZ", __import__("time").gmtime()),
    }
    m["manifest_hash"] = manifest_hash(m)
    return m


def manifest_hash(m: dict) -> str:
    """Hash of the FROZEN-EVIDENCE IDENTITY only — two manifests over the same frozen evidence hash
    identically. Deliberately EXCLUDES report_hash/dataset_hash/generated_at/store_fingerprint:
    those move on a daily operational append, and the whole point of T1 is that such an append must
    NOT change what an approval means. Code/commit + engine/sim + cost assumptions ARE included —
    a change to any of those legitimately re-identifies the evidence."""
    keys = ("strategy_version", "git_commit", "evidence_fingerprint", "evidence_cutoff",
            "symbols", "timeframe", "session", "engine_version", "simulator_version",
            "cost_assumptions", "waiver")
    blob = json.dumps({k: m.get(k) for k in keys}, sort_keys=True, default=str)
    return hashlib.sha256(blob.encode()).hexdigest()[:16]


if __name__ == "__main__":
    print(json.dumps(build_manifest("orb-standard-2026.07.7"), indent=1, default=str))
