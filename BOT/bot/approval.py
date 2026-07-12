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
    """What has actually been produced for this rule version. Since remediation Phase 6
    (2026-07-11) this is ENFORCED by approve() for the paper/live stages — a gate, not
    information."""
    ev = {}
    qa = REPORTS / "dataqa.json"
    ev["data_qa_report"] = qa.exists()
    if qa.exists():
        try:
            d = json.loads(qa.read_text(encoding="utf-8"))
            ev["data_qa_all_ok"] = all(s.get("ok") for s in d.get("symbols", {}).values())
            # TRADED-BOOK scope (2026-07-12, live-persister decision): the paper study trades
            # QQQ/SPY only; NQ/ES/GC carry LEGACY short-day damage that forward accrual can
            # never dilute (fixed numerators over decade denominators). The paper/live gate
            # judges the symbols the approval actually trades; all_ok stays visible/honest.
            traded = ("QQQ", "SPY")
            symd = d.get("symbols", {})
            ev["data_qa_traded_ok"] = all(
                symd.get(s, {}).get("ok") is True for s in traded)
            ev["store_fingerprint"] = d.get("store_fingerprint")
        except Exception:
            ev["data_qa_all_ok"] = False
    ab = REPORTS / "ab_entry_standard.json"
    ev["backtest_ab_report"] = ab.exists()
    if ab.exists():
        try:
            d = json.loads(ab.read_text(encoding="utf-8"))
            ev["ab_strategy_version_match"] = d.get("config", {}).get("strategy_version") == strategy_version
            ev["ab_lineage"] = d.get("lineage")            # pre-remediation reports are visible
        except Exception:
            ev["ab_strategy_version_match"] = False
    ev["training_runs"] = len(list(REPORTS.glob("ml_*.json"))) + len(list(REPORTS.glob("nn_*.json")))
    # LIVE-stage predicates (completion pass 2026-07-12): measured fills, forward consistency,
    # reconciliation-clean, and the TV parity marker are now enforced INSIDE approve('live') —
    # previously only the phase-78 auto-advance checked them.
    try:
        from bot.phase78 import fills_scorecard, reconciliation_clean
        fs = fills_scorecard()
        ev["paper_fills_n"] = fs["overall"].get("n", 0)
        ev["paper_fills_min_ok"] = ev["paper_fills_n"] >= 60
        ev["forward_paper_ok"] = fs.get("consistent") is True
        ev["reconciliation_clean"] = reconciliation_clean().get("ok") is True
    except Exception:
        ev["paper_fills_min_ok"] = False
        ev["forward_paper_ok"] = False
        ev["reconciliation_clean"] = False
    pm = REPORTS / "parity_tv.json"                # written by the TV bar-replay diff (user step);
    ev["parity_tv_green"] = False                  # absent/red = live approval refused
    if pm.exists():
        try:
            ev["parity_tv_green"] = json.loads(pm.read_text(encoding="utf-8")).get("ok") is True
        except Exception:
            pass
    return ev


# the predicates a stage must satisfy (Phase 6). Live inherits paper's; phase-8 readiness
# (measured fills, reconciliation-clean, forward scorecard) is enforced by phase78.evaluate,
# which is the only caller that requests a 'live' stage.
_REQUIRED = {"paper": ("data_qa_traded_ok", "ab_strategy_version_match"),
             "live": ("data_qa_traded_ok", "ab_strategy_version_match",
                      "paper_fills_min_ok", "forward_paper_ok",
                      "reconciliation_clean", "parity_tv_green")}


def _staleness(recs: dict) -> bool:
    """Auto-invalidation (Phase 6): an approval pins the store fingerprint it was granted
    against — if the store has since changed, downstream approvals are STALE until
    re-evidenced. Legacy records without a snapshot are honored (flagged 'legacy') until
    Phase R re-decides them."""
    cur = evidence("").get("store_fingerprint")
    for s in ("paper", "live"):
        snap = (recs.get(s) or {}).get("evidence") or {}
        pinned = snap.get("store_fingerprint")
        if pinned and cur and pinned != cur:
            return True
    return False


def status(strategy_version: str) -> dict:
    recs = _load().get(strategy_version, {})
    stale = _staleness(recs)
    return {"strategy_version": strategy_version,
            "stages": {s: recs.get(s) for s in STAGES},
            "paper_approved": bool(recs.get("paper")) and not stale,
            "stale": stale,
            "legacy": bool(recs.get("paper")) and not (recs.get("paper") or {}).get("evidence"),
            "evidence": evidence(strategy_version)}


def approve(strategy_version: str, stage: str, approved_by: str = "user", notes: str = "",
            override: bool = False) -> dict:
    """Record a MANUAL approval. Stages are ordered: replay needs research, paper needs replay.
    PHASE 6 (2026-07-11): paper/live additionally require GREEN evidence — refused otherwise.
    `override=True` bypasses the predicates but is written into the record FOREVER (visible on
    every approval screen and in the audit trail); the evidence snapshot rides with the record
    either way, pinning the exact store fingerprint the approval was granted against."""
    from bot.contracts import utcnow_iso
    if stage not in STAGES:
        raise ValueError(f"stage must be one of {STAGES}")
    d = _load()
    recs = d.setdefault(strategy_version, {})
    idx = STAGES.index(stage)
    if idx > 0 and not recs.get(STAGES[idx - 1]):
        raise ValueError(f"stage '{stage}' requires '{STAGES[idx - 1]}' to be approved first")
    rec = {"approved_by": approved_by, "at": utcnow_iso(), "notes": notes}
    if stage in _REQUIRED:
        ev = evidence(strategy_version)
        red = [k for k in _REQUIRED[stage] if ev.get(k) is not True]
        if red and not override:
            raise ValueError(f"stage '{stage}' refused — RED evidence: {red} "
                             f"(pass override=True to record a deliberate, visible exception)")
        rec["evidence"] = ev
        if override:
            rec["override"] = True
    recs[stage] = rec
    _save(d)
    from bot.audit import log as _audit
    _audit("approval", stage=stage, strategy_version=strategy_version,
           by=approved_by, notes=notes, override=bool(override and stage in _REQUIRED))
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
    """Arm check (autotrade toggle + ExecutionService submit path). PHASE 6: a STALE approval
    (store fingerprint drifted since it was granted) is refused until re-evidenced — legacy
    records without a snapshot stay honored until Phase R re-decides them."""
    recs = _load().get(strategy_version, {})
    return bool(recs.get("paper")) and not _staleness(recs)


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
