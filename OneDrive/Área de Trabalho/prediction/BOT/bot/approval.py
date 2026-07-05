"""Approval workflow (AITP-001 — Non-Negotiable Trading Gates + §16 Block Paper Until Approved).

Stage ladder per STRATEGY VERSION:  research -> replay -> paper  (live stays hard-locked by
config.py regardless of anything here). Each stage requires the previous one; approvals are
MANUAL, recorded with who/when/notes, and revocable. The paper-autotrade toggle refuses to arm
unless the CURRENT strategy version carries a `paper` approval — data reviewed, backtest done,
sustainability/profitability reviewed, risk rules approved, and the user's explicit sign-off.

Evidence is summarized automatically from what's on disk (data-QA report, A/B report, dataset,
test-suite marker) so the approval screen shows what has actually been done — but the DECISION is
always the user's click/CLI, never automatic.

    from bot.approval import status, approve, revoke, paper_approved
    approve("orb-standard-2026.07", "paper", approved_by="heelandy", notes="reviewed A/B + QA")
"""
from __future__ import annotations

import json
from pathlib import Path

from bot.config import BOT_ROOT

STAGES = ("research", "replay", "paper", "live")   # live ALSO needs config.py's LIVE_APPROVED.lock
FILE = BOT_ROOT / "data" / "approvals.json"
REPORTS = BOT_ROOT / "data" / "ml" / "reports"


def _load() -> dict:
    if FILE.exists():
        try:
            return json.loads(FILE.read_text(encoding="utf-8"))
        except Exception:
            return {}
    return {}


def _save(d: dict) -> None:
    FILE.parent.mkdir(parents=True, exist_ok=True)
    FILE.write_text(json.dumps(d, indent=1), encoding="utf-8")


def evidence(strategy_version: str) -> dict:
    """What has actually been produced for this rule version (informational, not a decision)."""
    ev = {}
    qa = REPORTS / "dataqa.json"
    ev["data_qa_report"] = qa.exists()
    if qa.exists():
        try:
            d = json.loads(qa.read_text(encoding="utf-8"))
            ev["data_qa_all_ok"] = all(s.get("ok") for s in d.get("symbols", {}).values())
        except Exception:
            ev["data_qa_all_ok"] = False
    ab = REPORTS / "ab_entry_standard.json"
    ev["backtest_ab_report"] = ab.exists()
    if ab.exists():
        try:
            d = json.loads(ab.read_text(encoding="utf-8"))
            ev["ab_strategy_version_match"] = d.get("config", {}).get("strategy_version") == strategy_version
        except Exception:
            ev["ab_strategy_version_match"] = False
    ev["training_runs"] = len(list(REPORTS.glob("ml_*.json"))) + len(list(REPORTS.glob("nn_*.json")))
    return ev


def status(strategy_version: str) -> dict:
    recs = _load().get(strategy_version, {})
    return {"strategy_version": strategy_version,
            "stages": {s: recs.get(s) for s in STAGES},
            "paper_approved": bool(recs.get("paper")),
            "evidence": evidence(strategy_version)}


def approve(strategy_version: str, stage: str, approved_by: str = "user", notes: str = "") -> dict:
    """Record a MANUAL approval. Stages are ordered: replay needs research, paper needs replay."""
    from bot.contracts import utcnow_iso
    if stage not in STAGES:
        raise ValueError(f"stage must be one of {STAGES}")
    d = _load()
    recs = d.setdefault(strategy_version, {})
    idx = STAGES.index(stage)
    if idx > 0 and not recs.get(STAGES[idx - 1]):
        raise ValueError(f"stage '{stage}' requires '{STAGES[idx - 1]}' to be approved first")
    recs[stage] = {"approved_by": approved_by, "at": utcnow_iso(), "notes": notes}
    _save(d)
    from bot.audit import log as _audit
    _audit("approval", stage=stage, strategy_version=strategy_version,
           by=approved_by, notes=notes)
    return recs[stage]


def revoke(strategy_version: str, stage: str) -> bool:
    """Revoking a stage also revokes every LATER stage (paper falls with replay, etc.)."""
    d = _load()
    recs = d.get(strategy_version, {})
    hit = False
    for s in STAGES[STAGES.index(stage):]:
        hit = bool(recs.pop(s, None)) or hit
    _save(d)
    if hit:
        from bot.audit import log as _audit
        _audit("approval_revoked", stage=stage, strategy_version=strategy_version)
    return hit


def paper_approved(strategy_version: str) -> bool:
    return bool(_load().get(strategy_version, {}).get("paper"))


if __name__ == "__main__":   # self-test on a scratch version key
    import tempfile, os
    v = "self-test-0.0"
    revoke(v, "research")
    assert not paper_approved(v)
    try:
        approve(v, "paper")
        raise AssertionError("paper must require replay first")
    except ValueError:
        pass
    approve(v, "research", notes="t")
    approve(v, "replay", notes="t")
    approve(v, "paper", notes="t")
    assert paper_approved(v) and status(v)["stages"]["paper"]["notes"] == "t"
    revoke(v, "replay")
    assert not paper_approved(v)          # paper falls with replay
    revoke(v, "research")
    print("approval workflow OK — staged, manual, revocable")
