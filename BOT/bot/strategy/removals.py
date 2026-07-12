"""ENTRY-GROUP REMOVALS (remediation Phase E.3, 2026-07-11).

Pruning is a RULE CHANGE, not a dashboard toggle. The Entry Profitability Matrix NOMINATES a
losing group; a removal is adopted only after the standard cohort test (the F78 lesson: several
intuitive vetoes FAILED — the blocked cohort was profitable; a removal must show the blocked
cohort loses on BOTH history halves AND out of sample).

An ADOPTED removal (config/entry_removals.json):
  * cannot FIRE as tradeable in the live scan (signal stays visible, flagged removed=True), and
  * cannot SUBMIT through the ExecutionService (belt + braces) —
  * but its SHADOW journal keeps accruing: removed != deleted; a wrong removal stays detectable
    and reversible. Every record carries the evidence link + adoption date.

NOTE (no-refresh world, user 2026-07-11): the strategy-version bump + A/B regeneration that a
removal formally triggers is DEFERRED to Phase R's re-approval — bumping now would strand the
legacy paper approval and stop the fill study. The removal record carries version_bump_deferred.
"""
from __future__ import annotations

import json
from pathlib import Path

from bot.config import BOT_ROOT

FILE = BOT_ROOT / "config" / "entry_removals.json"


def _load() -> list[dict]:
    if not FILE.exists():
        return []                                        # no removals registry yet (legitimate)
    try:
        return json.loads(FILE.read_text(encoding="utf-8"))
    except Exception as e:
        # FAIL LOUD (bug hunt W5): a corrupt removals registry silently returned [] — the DANGEROUS
        # direction, since an ADOPTED (retired, money-losing) group would then read as not-removed
        # and TRADE AGAIN. Page the operator; the empty result is announced, never hidden.
        try:
            from bot.alerts import alert
            alert(f"entry_removals.json CORRUPT ({str(e)[:80]}) — removals CANNOT be enforced; a "
                  f"retired group could trade. Fix the registry.", level="critical", source="removals")
        except Exception:
            pass
        return []


def active() -> list[dict]:
    return [r for r in _load() if r.get("status") == "adopted"]


def is_removed(symbol: str, family: str = "", side: str | None = None,
               session: str | None = None, tf: str | None = None) -> dict | None:
    """The matching ADOPTED removal record, or None. A record field that is absent/null matches
    everything (a symbol-wide removal needs only {'symbol': 'ES'})."""
    sym = str(symbol).upper()
    for r in active():
        if str(r.get("symbol", "")).upper() != sym:
            continue
        if r.get("family") and str(r["family"]) != str(family):
            continue
        if r.get("side") and side and str(r["side"]) != str(side):
            continue
        if r.get("session") and session and str(r["session"]) != str(session):
            continue
        if r.get("tf") and tf and str(r["tf"]) != str(tf):
            continue
        return r
    return None


def adopt(record: dict) -> dict:
    """Persist an ADOPTED removal (call only after a passed cohort test — link the evidence)."""
    from bot.contracts import utcnow_iso
    need = {"symbol", "reason", "evidence"}
    missing = need - set(record)
    if missing:
        raise ValueError(f"removal record missing {sorted(missing)} — a removal without linked "
                         f"evidence is a dashboard toggle, not a rule change")
    rows = _load()
    rec = {**record, "status": "adopted", "adopted_at": utcnow_iso(),
           "version_bump_deferred": "Phase R re-approval (no-refresh world, 2026-07-11)"}
    rows.append(rec)
    FILE.parent.mkdir(parents=True, exist_ok=True)
    FILE.write_text(json.dumps(rows, indent=1), encoding="utf-8")
    try:
        from bot.audit import log as _audit
        _audit("entry_group_removed", **{k: v for k, v in rec.items() if k != "evidence"})
    except Exception:
        pass
    return rec
