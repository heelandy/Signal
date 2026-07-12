"""ENTRY PROFITABILITY MATRIX (remediation Phase E.2, 2026-07-11) — the main research artifact.

Answers the product's second question: "has this EXACT type of entry produced reliable profit
after costs?" Hierarchy per cell: symbol → side → session → entry family → grade → regime,
computed on demand from the journals — never a hand-maintained table.

HONESTY RULES (Phase U rules 3/6, enforced here):
  * `matrix(evidence=...)` serves ONE evidence type per call — backtest | shadow | paper | live.
    Mixing is refused with a ValueError (never averaged away).
  * Cells under the sample floor (default n < 30) carry verdict INSUFFICIENT SAMPLE and no
    stats — a -0.48R cell with n=9 must not look like a verdict.
  * Every response carries its lineage. Backtest rows come from the CORRECTED engine
    (Phases 1-3) on the frozen store span (pre-R waiver, user's no-refresh decision) and are
    rebuilt explicitly via build_backtest_rows(), not on page load.
  * REMOVED groups stay visible with their evidence link (removed != deleted).
"""
from __future__ import annotations

import json
import sqlite3
from pathlib import Path

import numpy as np

from bot.config import BOT_ROOT

EVIDENCE = ("backtest", "shadow", "paper", "live")
FLOOR = 30
BT_ROWS = BOT_ROOT / "data" / "ml" / "reports" / "entry_matrix_backtest_rows.json"
DIMS = ("symbol", "side", "session", "family", "grade", "regime")


# ── row loaders (one evidence type each; every row: DIMS + net_r + day) ─────

def _rows_backtest() -> tuple[list[dict], str]:
    try:
        d = json.loads(BT_ROWS.read_text(encoding="utf-8"))
        return d["rows"], d.get("lineage", "?")
    except Exception:
        return [], "no backtest rows built yet — run build_backtest_rows()"


def _rows_shadow() -> tuple[list[dict], str]:
    from bot.tracker import DB
    rows = []
    con = sqlite3.connect(str(DB))
    try:
        for sym, side, fam, sess, r, j, at in con.execute(
                "SELECT symbol, side, family, session, result_r, json, decided_at FROM decisions "
                "WHERE outcome != 'open' AND result_r IS NOT NULL"):
            blob = {}
            try:
                blob = json.loads(j or "{}") or {}
            except Exception:
                pass
            rows.append({"symbol": str(sym).upper(), "side": side or "—",
                         "session": sess or "—", "family": fam or "—",
                         "grade": blob.get("grade") or "—",
                         "regime": blob.get("regime") or blob.get("macro_regime") or "—",
                         "net_r": float(r), "day": str(at or "")[:10]})
    finally:
        con.close()
    return rows, "tracker shadow journal (theoretical first-touch outcomes)"


def _rows_paper() -> tuple[list[dict], str]:
    """Round trips realized from the Phase-5 execution record. Attribution: each realized event
    joins the latest prior entry order for its symbol (best-effort until volumes grow)."""
    from bot.execution.service import DB_PATH
    rows = []
    try:
        con = sqlite3.connect(str(DB_PATH))
        orders = con.execute(
            "SELECT symbol, side, session, family, grade, planned_entry, stop, created_at "
            "FROM exec_orders WHERE state NOT IN ('FAILED','REJECTED') ORDER BY created_at"
        ).fetchall()
        from bot.execution.service import ExecutionService  # reuse the replay math

        class _Stub:                                          # replay needs only the db handle
            pass
        svc = _Stub()
        svc.db = con
        _, realized = ExecutionService._replay_fills(svc)
        from bot.risk import POINT_VALUE
        for at, pnl in realized:
            best = None
            for o in orders:
                if str(o[7]) <= str(at):
                    best = o
            if best is None:
                continue
            sym, side, sess, fam, grade, planned, stop, _ = best
            pv = POINT_VALUE.get(str(sym).upper(), 1.0)
            risk = abs(float(planned) - float(stop)) * pv if planned and stop else None
            rows.append({"symbol": str(sym).upper(), "side": side or "—",
                         "session": sess or "—", "family": fam or "—", "grade": grade or "—",
                         "regime": "—", "net_r": (pnl / risk) if risk else 0.0,
                         "day": str(at)[:10]})
        con.close()
    except Exception:
        pass
    return rows, "execution.db broker paper fills (measured)"


def _rows_live() -> tuple[list[dict], str]:
    return [], "live is HARD-LOCKED — no live fills exist"


_LOADERS = {"backtest": _rows_backtest, "shadow": _rows_shadow,
            "paper": _rows_paper, "live": _rows_live}


# ── the matrix ───────────────────────────────────────────────────────────────

def _cell_stats(rs: list[float], days: list[str]) -> dict:
    r = np.asarray(rs, float)
    wins, losses = r[r > 0], r[r <= 0]
    eq = np.concatenate([[0.0], np.cumsum(r)])
    streak = mx = 0
    for x in r:
        streak = streak + 1 if x < 0 else 0
        mx = max(mx, streak)
    uniq_days = sorted(set(days))
    weeks = max(len(uniq_days) / 5.0, 1e-9)
    try:
        from hs_validate import block_boot_ci                 # day-block CI (Phase 2 policy 9)
        lo, hi = block_boot_ci(r, np.asarray(days), B=800)
    except Exception:
        lo = hi = None
    pf = float(wins.sum() / abs(losses.sum())) if len(losses) and losses.sum() != 0 else float("inf")
    return {"n": int(len(r)), "win_pct": round(100 * len(wins) / len(r), 1),
            "exp_R": round(float(r.mean()), 4), "pf": round(pf, 3),
            "total_R": round(float(r.sum()), 1),
            "avg_win": round(float(wins.mean()), 3) if len(wins) else None,
            "avg_loss": round(float(losses.mean()), 3) if len(losses) else None,
            "max_dd_R": round(float((eq - np.maximum.accumulate(eq)).min()), 1),
            "max_consec_losses": int(mx), "trades_per_week": round(len(r) / weeks, 2),
            "ci90": [round(lo, 4), round(hi, 4)] if lo is not None else None}


def matrix(evidence: str, floor: int = FLOOR) -> dict:
    """The Entry Profitability Matrix for ONE evidence type. Deterministic: same journal ->
    identical cells (TE.1). Mixing evidence types is refused (TE.2)."""
    ev = str(evidence or "").lower()
    if ev not in EVIDENCE:
        raise ValueError(f"evidence must be exactly one of {EVIDENCE} — mixing evidence types "
                         f"(or 'all') is refused: backtest, shadow, paper fills and live fills "
                         f"are different truths and never share a cell")
    import sys
    import os
    eng = os.path.join(str(BOT_ROOT.parent), "engine")
    if eng not in sys.path:
        sys.path.insert(0, eng)
    rows, lineage = _LOADERS[ev]()
    groups: dict[tuple, list] = {}
    for r in rows:
        k = tuple(str(r.get(d, "—")) for d in DIMS)
        groups.setdefault(k, []).append(r)
    cells = []
    for k in sorted(groups):
        rs = groups[k]
        cell = dict(zip(DIMS, k))
        from bot.strategy.removals import is_removed
        rm = is_removed(cell["symbol"], cell["family"], cell["side"], cell["session"])
        if rm:
            cell["removed"] = {"reason": rm.get("reason"), "adopted_at": rm.get("adopted_at")}
        if len(rs) < floor:
            cell.update({"n": len(rs), "verdict": "INSUFFICIENT SAMPLE",
                         "note": f"n < {floor} — not a verdict either way"})
        else:
            cell.update(_cell_stats([x["net_r"] for x in rs], [x["day"] for x in rs]))
        cells.append(cell)
    from bot.strategy.removals import active
    return {"evidence": ev, "lineage": lineage, "floor": floor,
            "dims": list(DIMS), "cells": cells, "removed_groups": active(),
            "note": "one evidence type per call — never mixed (Phase E honesty rules)"}


def nominations(evidence: str = "backtest", floor: int = FLOOR) -> list[dict]:
    """Cells the matrix NOMINATES for removal review: enough sample, negative expectancy, and
    the CI's upper bound below +0.05R. A nomination is NOT a removal — the cohort test decides."""
    out = []
    for c in matrix(evidence, floor)["cells"]:
        if c.get("verdict") == "INSUFFICIENT SAMPLE" or c.get("removed"):
            continue
        hi = (c.get("ci90") or [None, None])[1]
        if c["exp_R"] < 0 and (hi is None or hi < 0.05):
            out.append({**{d: c[d] for d in DIMS}, "n": c["n"], "exp_R": c["exp_R"],
                        "pf": c["pf"], "ci90": c.get("ci90"),
                        "next_step": "cohort test (both halves + OOS) before any removal"})
    return out


# ── backtest rows builder (explicit, engine-heavy — never on page load) ─────

def build_backtest_rows(runs=(("QQQ", "5m"), ("SPY", "5m"), ("NQ", "5m"), ("ES", "5m"),
                              ("QQQ", "15m"), ("SPY", "15m"))) -> dict:
    """Canonical corrected-engine trades → per-trade matrix rows, persisted with lineage."""
    from bot.strategy.orb_candidates import load_state, run_backtest, STRATEGY_VERSION
    rows = []
    for sym, tf in runs:
        d = load_state(sym, tf, "rth")
        tr = run_backtest(d)
        for _, t in tr.iterrows():
            rows.append({"symbol": sym, "side": t["direction"], "session": "rth",
                         "family": f"orb@{tf}", "grade": "—",
                         "regime": str(t.get("regime", "—")),
                         "net_r": float(t["net_R"]), "day": str(t["entry_time"])[:10]})
    out = {"lineage": f"corrected engine (Phases 1-3) · frozen store span (pre-R waiver) · "
                      f"{STRATEGY_VERSION}",
           "generated_at": __import__("time").strftime("%Y-%m-%dT%H:%M:%SZ", __import__("time").gmtime()),
           "rows": rows}
    BT_ROWS.parent.mkdir(parents=True, exist_ok=True)
    BT_ROWS.write_text(json.dumps(out), encoding="utf-8")
    return {"rows": len(rows), "path": str(BT_ROWS)}


if __name__ == "__main__":
    print(build_backtest_rows())
