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
    if not FILE.exists():
        return {}                                        # clean first run
    try:
        return json.loads(FILE.read_text(encoding="utf-8"))
    except Exception as e:
        # FAIL LOUD, not silent (bug hunt W5): a corrupt approvals file used to return {} silently
        # — trading was blocked (safe) but the operator was never told, and a later approve() would
        # CLOBBER the unreadable file. Keep the safe empty result (nothing is approved) but page.
        try:
            from bot.alerts import alert
            alert(f"approvals.json CORRUPT ({str(e)[:80]}) — treating as NO approvals (paper "
                  f"trading blocked); inspect before re-approving", level="critical", source="approval")
        except Exception:
            pass
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
            # Signal-Certificate T1: pin the FROZEN evidence fingerprint (immutable across daily
            # bar appends), not the growing store fingerprint. store_fingerprint stays for display.
            ev["evidence_fingerprint"] = d.get("evidence_fingerprint")
            ev["evidence_cutoff"] = d.get("evidence_cutoff")
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
    """Auto-invalidation. An approval pins the FROZEN evidence fingerprint (Signal-Certificate T1,
    2026-07-12) it was granted against — if the immutable evidence range changes, downstream
    approvals are STALE until re-evidenced. Daily live-bar appends AFTER the evidence cutoff move
    the operational store_fingerprint but NOT the evidence_fingerprint, so they no longer wrongly
    invalidate a fresh approval. LEGACY records (pinned only a store_fingerprint, pre-T1) keep the
    old store-compare until re-issued."""
    cur = evidence("")
    cur_efp = cur.get("evidence_fingerprint")
    cur_sfp = cur.get("store_fingerprint")
    for s in ("paper", "live"):
        snap = (recs.get(s) or {}).get("evidence") or {}
        pinned_efp = snap.get("evidence_fingerprint")
        if pinned_efp:                                    # T1 record: compare the FROZEN fingerprint
            if cur_efp and pinned_efp != cur_efp:
                return True
        else:                                             # legacy record: pre-T1 store-fingerprint
            pinned_sfp = snap.get("store_fingerprint")
            if pinned_sfp and cur_sfp and pinned_sfp != cur_sfp:
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
        try:                                              # Signal-Certificate T1: pin the immutable
            from bot.evidence_manifest import build_manifest   # evidence manifest with the record
            rec["manifest"] = build_manifest(strategy_version,
                                             waiver="frozen-span" if override else None)
        except Exception as e:
            # MANIFEST IS MANDATORY for required stages (completion-order step 3, 2026-07-14):
            # a silent construction failure used to mint an approval with NO manifest — the exact
            # unaccountable-approval class T1 exists to kill. Refuse; override records the error
            # FOREVER (visible on every approval screen), never hides it.
            if not override:
                raise ValueError(f"stage '{stage}' refused — evidence manifest construction "
                                 f"FAILED ({e}); fix the reports or pass override=True to record "
                                 f"a deliberate, visible exception") from e
            rec["manifest_error"] = str(e)
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
