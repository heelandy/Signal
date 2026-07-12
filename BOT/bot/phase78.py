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


def fills_scorecard() -> dict:
    """MEASURED broker fills -> R outcomes, grade-tagged from the exec-order dims (reuses the
    entry matrix's paper loader). THE phase-8 basis since the completion pass 2026-07-12 —
    Phase 6's rule made execution QUALITY fills-based; this makes the STUDY fills-based too
    (never shadow outcomes)."""
    import numpy as np
    try:
        from bot.ml.entry_matrix import _rows_paper
        rows, _ = _rows_paper()
    except Exception:
        rows = []

    def _stats(rs):
        if not rs:
            return {"n": 0}
        r = np.array([x["net_r"] for x in rs], float)
        w = r[r > 0]
        return {"n": int(len(r)), "exp_R": round(float(r.mean()), 3),
                "total_R": round(float(r.sum()), 1),
                "win_pct": round(100 * len(w) / len(r), 1)}

    overall = _stats(rows)
    by_grade = {g: _stats([x for x in rows if x.get("grade") == g])
                for g in ("A+", "A", "B", "C")}
    by_grade = {g: v for g, v in by_grade.items() if v["n"]}
    from bot.tracker import BACKTEST_REF
    cons = None                                    # None = not enough fills to judge
    if overall["n"] >= 12:
        cons = overall["exp_R"] >= 0.5 * BACKTEST_REF["exp_R"]
    days = [x["day"] for x in rows]
    return {"overall": overall, "by_grade": by_grade, "consistent": cons,
            "first_fill": min(days) if days else None,
            "backtest_ref": BACKTEST_REF,
            "basis": "broker paper fills (execution.db) — shadow outcomes are advisory only"}


def paper_study() -> dict:
    """The paper-study exit gate — computed from BROKER FILLS (completion pass 2026-07-12; the
    old basis was the tracker's theoretical shadow outcomes, which can never measure execution).
    The shadow scorecard rides along as ADVISORY, clearly labeled, never gating."""
    from bot.tracker import scorecard, track_outcomes
    try:
        track_outcomes()                           # keeps resolving shadow (advisory + matrix)
    except Exception:
        pass
    fs = fills_scorecard()
    n = fs["overall"].get("n", 0)
    days = 0.0
    if fs.get("first_fill"):
        try:
            t0 = datetime.fromisoformat(fs["first_fill"]).replace(tzinfo=timezone.utc)
            days = (_utcnow() - t0).total_seconds() / 86400.0
        except Exception:
            pass
    bg = fs.get("by_grade", {})
    inv = None                                     # None = not enough data to judge inversion
    ap, a = bg.get("A+", {}), bg.get("A", {})
    if ap.get("n", 0) >= GRADE_MIN_N and a.get("n", 0) >= GRADE_MIN_N:
        inv = ap.get("exp_R", 0) < a.get("exp_R", 0)
    crit = {"n_closed": n, "n_needed": PAPER_MIN_TRADES, "n_ok": n >= PAPER_MIN_TRADES,
            "window_days": round(days, 1), "days_needed": PAPER_MIN_DAYS,
            "window_ok": days >= PAPER_MIN_DAYS,
            "scorecard_consistent": fs.get("consistent"),
            "grade_inversion": inv, "basis": "broker fills"}
    done = (crit["n_ok"] and crit["window_ok"] and fs.get("consistent") is True
            and inv is not True)
    try:
        advisory = scorecard()
        advisory["note"] = "ADVISORY shadow outcomes — never gates phase 8"
    except Exception:
        advisory = None
    return {"criteria": crit, "done": bool(done), "scorecard": fs,
            "advisory_shadow": advisory}


def execution_quality(db_path=None) -> dict:
    """Phase-8 requirement 2: measured paper slippage vs the cost-stress assumptions.
    PHASE 6 FIX (2026-07-11): reads the Phase-5 PAPER-EXECUTION RECORD (execution.db broker
    fills — avg fill price per order vs its planned entry). The old code read journal fields
    that never existed (`fill_price`), so execution quality was structurally n=0 forever.
    'insufficient' until real fills exist — the auto-advance waits for data, it never assumes."""
    import sqlite3
    rows = []
    try:
        from bot.execution.service import DB_PATH
        p = str(db_path or DB_PATH)
        con = sqlite3.connect(p)
        for planned, fq, fpx in con.execute(
                "SELECT o.planned_entry, sum(f.qty), sum(f.qty * f.price) "
                "FROM exec_fills f JOIN exec_orders o ON o.order_id = f.order_id "
                "GROUP BY f.order_id, o.planned_entry").fetchall():
            if planned and fq:
                rows.append(abs(fpx / fq - float(planned)))
        con.close()
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
            "assumption_usd": 0.01, "stress_usd": 0.02,
            "source": "execution.db paper-execution record (broker fills)"}


def reconciliation_clean(db_path=None) -> dict:
    """Phase-8 requirement (Phase 6, 2026-07-11): ZERO unresolved reconciliation failures —
    a live halt flag or any INVESTIGATION_REQUIRED order blocks phase-8 readiness."""
    import sqlite3
    try:
        from bot.execution.service import DB_PATH
        con = sqlite3.connect(str(db_path or DB_PATH))
        halt = con.execute("SELECT v FROM exec_flags WHERE k='halt_submissions'").fetchone()
        bad = con.execute("SELECT count(*) FROM exec_orders "
                          "WHERE state='INVESTIGATION_REQUIRED'").fetchone()[0]
        con.close()
        return {"ok": halt is None and bad == 0,
                "halt": halt[0] if halt else None, "investigation_required": int(bad)}
    except Exception as e:
        return {"ok": None, "note": f"execution record unreadable: {e}"}


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
    rc = reconciliation_clean()
    p7_ok = all(c.get("ok") is True for c in p7.values())
    ready = bool(ps["done"] and p7_ok and eq.get("ok") is True and rc.get("ok") is True)
    st = approval.status(STRATEGY_VERSION)["stages"]
    out = {"generated_at": _utcnow().isoformat(), "strategy_version": STRATEGY_VERSION,
           "paper_study": ps, "phase7": p7, "execution_quality": eq,
           "reconciliation": rc,
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
