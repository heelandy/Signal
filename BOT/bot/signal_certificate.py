"""SIGNAL CERTIFICATE + certify_and_fire() — the one firing door (Signal-Certificate plan §2/§4).

A candidate says "I see a possible trade." A CERTIFIED signal says "every required process was
proven." Only a certificate turns a candidate into an actionable signal; without one there is no
"ENTER" alert and no order. The nine mandatory gates each prove one thing; **UNKNOWN is treated
exactly like BLOCKED** (an unprovable gate is a failed gate — the fail-closed principle).

    from bot.signal_certificate import certify_and_fire
    result = certify_and_fire(candidate, ctx)     # ctx supplies the proofs; missing proof = blocked

The certificate is persisted (audit gate) BEFORE any alert fires; the alert carries its hash.
This module orchestrates existing services (risk.decide, approval, removals, evidence_manifest,
entry_group_id) — it adds the binding artifact, not new strategy logic (freeze-safe).
"""
from __future__ import annotations

import hashlib
import json
import sqlite3
import uuid
from pathlib import Path

from bot.config import BOT_ROOT
from bot.contracts import utcnow_iso

CERT_DB = BOT_ROOT / "data" / "certificates.db"
GATES = ("runtime", "data", "causality", "entry_logic", "profitability",
         "risk", "execution", "ml", "audit")


# ── the nine gates ─ each returns {"gate", "ok": True|False|None, "reason"}; None == UNKNOWN == block
def _g(name, ok, reason):
    return {"gate": name, "ok": ok, "reason": reason}


def _gate_runtime(c, ctx) -> dict:
    want = ctx.get("strategy_version")
    got = getattr(c, "strategy_version", None)
    if not got or not want:
        return _g("runtime", None, "strategy/config version unknown")
    if got != want:
        return _g("runtime", False, f"version mismatch: candidate {got} != running {want}")
    if not ctx.get("config_hash"):
        return _g("runtime", None, "config hash unknown")
    return _g("runtime", True, f"{got} (config {ctx['config_hash']})")


def _gate_data(c, ctx) -> dict:
    if ctx.get("data_qa_ok") is None or ctx.get("data_age_sec") is None:
        return _g("data", None, "data health unknown")
    if ctx.get("data_qa_ok") is not True:
        return _g("data", False, "data-QA red / incomplete / damaged")
    if ctx["data_age_sec"] > ctx.get("data_max_age_sec", 900):
        return _g("data", False, f"stale feed: {ctx['data_age_sec']}s old")
    return _g("data", True, f"fresh ({ctx['data_age_sec']}s), QA green")


def _gate_causality(c, ctx) -> dict:
    if ctx.get("closed_bar") is None:
        return _g("causality", None, "bar-close state unknown")
    if ctx.get("closed_bar") is not True:
        return _g("causality", False, "signal on a FORMING bar (lookahead)")
    return _g("causality", True, "closed-bar, point-in-time")


def _gate_entry_logic(c, ctx) -> dict:
    st = ctx.get("entry_state")
    if st is None:
        return _g("entry_logic", None, "entry state unknown")
    if st not in ("confirmed", "fired", "order_ready"):
        return _g("entry_logic", False, f"incomplete transition ({st})")
    return _g("entry_logic", True, f"state machine complete ({st})")


def _gate_profitability(c, ctx) -> dict:
    gid = ctx.get("entry_group_id")
    if not gid:
        return _g("profitability", None, "entry group unresolved")
    if ctx.get("removed"):
        return _g("profitability", False, f"entry group REMOVED ({gid})")
    ev = ctx.get("profitability_evidence")           # "certified" | "unproven" | "insufficient"
    if ev is None:
        return _g("profitability", None, f"no evidence for {gid}")
    if ev != "certified":
        return _g("profitability", False, f"{gid} evidence={ev} (not certified)")
    return _g("profitability", True, f"{gid} certified")


def _gate_risk(c, ctx) -> dict:
    rd = ctx.get("risk_decision")                    # a RiskDecision or None
    if rd is None:
        return _g("risk", None, "account truth / risk decision unknown")
    if not getattr(rd, "approved", False):
        return _g("risk", False, f"risk {getattr(rd, 'reason_code', '?')}")
    return _g("risk", True, f"approved qty {getattr(rd, 'max_qty', '?')}")


def _gate_execution(c, ctx) -> dict:
    if ctx.get("broker_reachable") is None or ctx.get("idempotency_ready") is None:
        return _g("execution", None, "broker/idempotency state unknown")
    if ctx.get("broker_reachable") is not True:
        return _g("execution", False, "broker unreachable")
    if ctx.get("halted"):
        return _g("execution", False, f"submissions halted: {ctx.get('halted')}")
    if ctx.get("idempotency_ready") is not True:
        return _g("execution", False, "idempotency not ready")
    return _g("execution", True, "broker reachable, idempotency ready")


def _gate_ml(c, ctx) -> dict:
    # ML NEVER blocks by abstaining — a silent fallback or a stale/incompatible model blocks.
    status = ctx.get("ml_status", "abstain")         # "score" | "abstain" | "stale" | "incompatible"
    if status in ("stale", "incompatible"):
        return _g("ml", False, f"model {status} — must abstain, not silently score")
    if status == "score" and ctx.get("ml_full_inputs") is not True:
        return _g("ml", False, "model scored on incomplete inputs (silent fallback)")
    return _g("ml", True, "valid score" if status == "score" else "ABSTAIN (honest)")


def _gate_audit(c, ctx, persisted_ok: bool) -> dict:
    return _g("audit", bool(persisted_ok), "certificate persisted + hash verified"
              if persisted_ok else "certificate persistence FAILED")


def _cert_hash(fields: dict) -> str:
    keys = ("signal_id", "candidate_id", "strategy_version", "config_hash", "symbol", "side",
            "timeframe", "session", "signal_bar_ts", "entry_group_id", "entry", "stop", "tp2",
            "manifest_hash")
    blob = json.dumps({k: fields.get(k) for k in keys}, sort_keys=True, default=str)
    return hashlib.sha256(blob.encode()).hexdigest()[:20]


def certify(c, ctx: dict) -> dict:
    """Run the nine gates and build the immutable certificate. overall = ORDER_READY iff EVERY gate
    is True; any False OR None (UNKNOWN) → BLOCKED. Does not persist (that is the audit gate, run by
    certify_and_fire); the returned cert carries `audit` as pending until persisted."""
    gates = [_gate_runtime(c, ctx), _gate_data(c, ctx), _gate_causality(c, ctx),
             _gate_entry_logic(c, ctx), _gate_profitability(c, ctx), _gate_risk(c, ctx),
             _gate_execution(c, ctx), _gate_ml(c, ctx)]
    cert = {
        "signal_id": uuid.uuid4().hex[:16],
        "candidate_id": getattr(c, "candidate_id", None),
        "correlation_id": ctx.get("correlation_id"),
        "strategy_version": getattr(c, "strategy_version", None),
        "config_hash": ctx.get("config_hash"),
        "code_commit": ctx.get("code_commit"),
        "symbol": getattr(c, "symbol", None), "side": getattr(getattr(c, "side", None), "value", None),
        "timeframe": getattr(c, "timeframe", None), "session": ctx.get("session"),
        "signal_bar_ts": ctx.get("signal_bar_ts"),
        "data_provider": ctx.get("data_provider"), "data_age_sec": ctx.get("data_age_sec"),
        "feature_snapshot_hash": ctx.get("feature_snapshot_hash"),
        "entry_group_id": ctx.get("entry_group_id"),
        "profitability_evidence": ctx.get("profitability_evidence"),
        "entry": getattr(c, "entry", None), "stop": getattr(c, "stop", None),
        "tp1": getattr(c, "tp1", None), "tp2": getattr(c, "tp2", None),
        "rr": getattr(c, "rr", None),
        "manifest_hash": ctx.get("manifest_hash"),
        "ml_status": ctx.get("ml_status", "abstain"),
        "entry_state_history": ctx.get("entry_state_history"),
        "gates": gates,
        "created_at": utcnow_iso(), "expires_at": ctx.get("expires_at"),
    }
    cert["certificate_hash"] = _cert_hash(cert)
    hard = [g for g in gates if g["ok"] is not True]          # False or None (UNKNOWN=BLOCKED)
    cert["overall"] = "ORDER_READY" if not hard else "BLOCKED"
    cert["blocking"] = [{"gate": g["gate"], "reason": g["reason"]} for g in hard]
    return cert


def _persist(cert: dict) -> bool:
    try:
        CERT_DB.parent.mkdir(parents=True, exist_ok=True)
        con = sqlite3.connect(str(CERT_DB))
        con.execute("CREATE TABLE IF NOT EXISTS certificates("
                    "signal_id TEXT PRIMARY KEY, candidate_id TEXT, symbol TEXT, side TEXT, "
                    "overall TEXT, certificate_hash TEXT, created_at TEXT, json TEXT)")
        con.execute("INSERT OR REPLACE INTO certificates VALUES(?,?,?,?,?,?,?,?)",
                    (cert["signal_id"], cert.get("candidate_id"), cert.get("symbol"),
                     cert.get("side"), cert["overall"], cert["certificate_hash"],
                     cert["created_at"], json.dumps(cert, default=str)))
        con.commit()
        row = con.execute("SELECT certificate_hash FROM certificates WHERE signal_id=?",
                          (cert["signal_id"],)).fetchone()
        con.close()
        return bool(row and row[0] == cert["certificate_hash"])   # persisted + hash verified
    except Exception:
        return False


def certify_and_fire(c, ctx: dict, alert_fn=None, submit_fn=None) -> dict:
    """THE one firing door. Certify → PERSIST (audit gate) → only if ORDER_READY: alert + optional
    submit. A blocked candidate produces a persisted, auditable BLOCKED certificate and NO alert /
    NO order. Returns the certificate (with the audit gate resolved)."""
    cert = certify(c, ctx)
    persisted = _persist(cert)
    audit = _gate_audit(c, ctx, persisted)
    cert["gates"].append(audit)
    if audit["ok"] is not True:                       # audit failure re-blocks even an OK cert
        cert["overall"] = "BLOCKED"
        cert["blocking"].append({"gate": "audit", "reason": audit["reason"]})
    if cert["overall"] == "ORDER_READY":
        if alert_fn:
            try:
                alert_fn(f"ORDER READY {cert['symbol']} {cert['side']} — cert {cert['certificate_hash']} "
                         f"({cert['entry_group_id']})")
            except Exception:
                pass
        cert["fired"] = True
        if submit_fn:
            try:                                          # a submit that raises AFTER the alert must
                cert["submit_result"] = submit_fn(c)      # not propagate and kill the caller/scan beat
            except Exception as e:                        # — capture it into the cert; the OMS remains
                cert["submit_result"] = {"error": str(e)}  # the order-truth source (this is audit only)
    else:
        cert["fired"] = False
    return cert
