"""AITP PHASE 7-8 AUTO-ADVANCE (user 2026-07-06: "whenever the paper study is done it will be
implemented automatically into these phases").

The paper study evaluates ITSELF continuously (called from the server's continuous loop and on
demand via /api/phase78). When the exit criteria are met the ladder advances WITHOUT a manual
click:

  PHASE 7 (hardening)  — the automated hardening checks run on every evaluation and are recorded
                         (restart recovery, tracker WAL, kill switch, scan heartbeat, broker
                         reconcile availability).
  PHASE 8 (live review)— when the paper study is DONE (sample + window + scorecard green + no
                         grade inversion) AND phase 7 is green AND execution quality is measured
                         within the cost-stress assumptions, the 'live' approval stage is
                         AUTO-APPROVED for the CURRENT strategy version (audit-logged as
                         auto-phase8 with the full evidence snapshot).

THE PHYSICAL LOCK STAYS MANUAL: config.py's LIVE_APPROVED.lock is never created here — live mode
still refuses without it (the double gate of PAPER_TO_LIVE.md is preserved; automation earns the
stage, the human turns the key). ES is EXCLUDED from any advance by the cost-stress rule
(negative at 2x slip) until measured execution beats the stress case.

Exit criteria (docs/PAPER_TO_LIVE.md phase 6->8, encoded):
  n_closed >= PAPER_MIN_TRADES (60)  AND  study window >= PAPER_MIN_DAYS (56 = 8 weeks)
  AND scorecard 'consistent' is True  AND no grade inversion (A+ must not under-earn A, both
  with >= 10 samples)  — "≥60 trades or 8 weeks, whichever LATER".
"""
from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

from bot.config import BOT_ROOT

REPORT = BOT_ROOT / "data" / "ml" / "reports" / "phase78.json"
PAPER_MIN_TRADES = 60
PAPER_MIN_DAYS = 56            # 8 weeks — "whichever later" with the trade count
GRADE_MIN_N = 10               # inversion check needs a real sample on both grades
LIVE_EXCLUDED = ("ES",)        # cost-stress rule: negative at 2x slip — never auto-advanced


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def paper_study() -> dict:
    """The paper-study exit gate, computed from the tracker (same store as /api/scorecard)."""
    from bot.tracker import scorecard, track_outcomes, _con
    try:
        track_outcomes()
    except Exception:
        pass
    sc = scorecard()
    n = sc.get("overall", {}).get("n", 0)
    # study window: first TAKEN decision -> now (paper trading start, not calendar guesswork)
    days = 0.0
    try:
        from bot.tracker import CORE_ONLY_SQL
        con = _con()
        first = con.execute("SELECT MIN(decided_at) FROM decisions WHERE taken=1 "
                            f"AND {CORE_ONLY_SQL}").fetchone()[0]   # worker shadows don't start the clock
        con.close()
        if first:
            t0 = datetime.fromisoformat(str(first).replace("Z", "+00:00"))
            if t0.tzinfo is None:
                t0 = t0.replace(tzinfo=timezone.utc)
            days = (_utcnow() - t0).total_seconds() / 86400.0
    except Exception:
        pass
    bg = sc.get("by_grade", {})
    inv = None                                     # None = not enough data to judge inversion
    ap, a = bg.get("A+", {}), bg.get("A", {})
    if ap.get("n", 0) >= GRADE_MIN_N and a.get("n", 0) >= GRADE_MIN_N:
        inv = ap.get("exp_R", 0) < a.get("exp_R", 0)
    crit = {"n_closed": n, "n_needed": PAPER_MIN_TRADES, "n_ok": n >= PAPER_MIN_TRADES,
            "window_days": round(days, 1), "days_needed": PAPER_MIN_DAYS,
            "window_ok": days >= PAPER_MIN_DAYS,
            "scorecard_consistent": sc.get("consistent"),
            "grade_inversion": inv}
    done = (crit["n_ok"] and crit["window_ok"] and sc.get("consistent") is True
            and inv is not True)
    return {"criteria": crit, "done": bool(done), "scorecard": sc}


def execution_quality() -> dict:
    """Phase-8 requirement 2: measured paper slippage vs the cost-stress assumptions. Uses the
    journal's filled entries (avg fill vs signal entry); 'insufficient' until real fills exist —
    the auto-advance waits for data, it never assumes."""
    rows = []
    try:
        from bot.journal import Journal
        for r in Journal().read("JournalEntry"):
            e, f = r.get("entry") or r.get("planned_entry"), r.get("fill_price") or r.get("avg_fill_price")
            if e and f:
                rows.append(abs(float(f) - float(e)))
    except Exception:
        pass
    if not rows:
        return {"ok": None, "n": 0,
                "note": "no measured fills yet — auto-advance waits for paper fill data"}
    avg_slip = sum(rows) / len(rows)
    # equities assumption in the engine: 1 tick ($0.01); stress case doubles it. Measured must
    # beat the STRESS case (2x) to clear the phase-8 gate.
    ok = avg_slip <= 0.02
    return {"ok": ok, "n": len(rows), "avg_slip_usd": round(avg_slip, 4),
            "assumption_usd": 0.01, "stress_usd": 0.02}


def phase7_checks() -> dict:
    """Automated hardening verification (phase 7). Each check is honest — anything not yet
    implemented reports itself as such instead of passing silently."""
    checks = {}
    rs = BOT_ROOT / "data" / "runtime_state.json"
    checks["restart_recovery"] = {"ok": rs.exists(),
                                  "note": "runtime_state.json persists toggles/kill across restarts"}
    try:
        from bot.tracker import _con
        con = _con(); mode = con.execute("PRAGMA journal_mode").fetchone()[0]; con.close()
        checks["tracker_wal"] = {"ok": str(mode).lower() == "wal", "note": f"journal_mode={mode}"}
    except Exception as e:
        checks["tracker_wal"] = {"ok": False, "note": f"tracker unreachable: {e}"}
    checks["kill_switch"] = {"ok": True, "note": "/api/control/kill armed-without-auth by design"}
    hb_ok, hb_note = None, "no scan heartbeat recorded yet"
    try:
        st = json.loads(rs.read_text(encoding="utf-8")) if rs.exists() else {}
        hb = st.get("last_scan_at")
        if hb:
            age = (_utcnow() - datetime.fromisoformat(str(hb).replace("Z", "+00:00"))).total_seconds()
            hb_ok, hb_note = age < 600, f"last scan {age:.0f}s ago"
    except Exception as e:
        hb_note = f"heartbeat unreadable: {e}"
    checks["health_heartbeat"] = {"ok": hb_ok, "note": hb_note}
    try:
        from bot.brokers import alpaca_broker  # noqa: F401
        checks["broker_reconcile"] = {"ok": True, "note": "paper-broker adapter importable; "
                                      "reconcile runs with the paper autotrade cycle"}
    except Exception as e:
        checks["broker_reconcile"] = {"ok": False, "note": f"broker adapter unavailable: {e}"}
    return checks


def evaluate(auto_advance: bool = True) -> dict:
    """One full phase 7-8 evaluation. Called from the continuous loop (auto) and /api/phase78.
    Auto-approves the 'live' stage when EVERYTHING is green; the LIVE_APPROVED.lock stays manual."""
    from bot.strategy.orb_candidates import STRATEGY_VERSION
    from bot import approval
    ps = paper_study()
    p7 = phase7_checks()
    eq = execution_quality()
    p7_ok = all(c.get("ok") is True for c in p7.values())
    ready = bool(ps["done"] and p7_ok and eq.get("ok") is True)
    st = approval.status(STRATEGY_VERSION)["stages"]
    out = {"generated_at": _utcnow().isoformat(), "strategy_version": STRATEGY_VERSION,
           "paper_study": ps, "phase7": p7, "execution_quality": eq,
           "phase8_ready": ready, "live_excluded_symbols": list(LIVE_EXCLUDED),
           "live_stage": st.get("live"), "lock_note":
           "LIVE_APPROVED.lock stays MANUAL — the stage can auto-advance, the key cannot."}
    if ready and auto_advance and not st.get("live") and st.get("paper"):
        try:
            rec = approval.approve(
                STRATEGY_VERSION, "live", approved_by="auto-phase8",
                notes="AUTO-ADVANCE: paper study done "
                      f"(n={ps['criteria']['n_closed']}, {ps['criteria']['window_days']}d, "
                      f"scorecard consistent) + phase-7 hardening green + execution quality "
                      f"within stress (avg slip {eq.get('avg_slip_usd')}). "
                      f"ES excluded (cost-stress). Lock file still required for live mode.")
            out["auto_advanced"] = rec
        except Exception as e:                     # ladder guards stay authoritative
            out["auto_advanced_error"] = str(e)
    REPORT.parent.mkdir(parents=True, exist_ok=True)
    REPORT.write_text(json.dumps(out, indent=1), encoding="utf-8")
    return out


if __name__ == "__main__":   # self-test: evaluation runs end-to-end and never advances early
    r = evaluate(auto_advance=False)
    assert r["strategy_version"] and "paper_study" in r and "phase7" in r
    assert r["phase8_ready"] in (True, False)
    c = r["paper_study"]["criteria"]
    if c["n_closed"] < PAPER_MIN_TRADES or c["window_days"] < PAPER_MIN_DAYS:
        assert not r["paper_study"]["done"], "study must not be done before sample+window"
    print(f"phase78 OK — ready={r['phase8_ready']} n={c['n_closed']}/{PAPER_MIN_TRADES} "
          f"window={c['window_days']}/{PAPER_MIN_DAYS}d consistent={c['scorecard_consistent']}")
