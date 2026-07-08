"""THE MAIN BOSS — worker orchestrator (docs/BOSS_WORKERS_PLAN.md §4, user 2026-07-06:
"we will have a Main Boss that looks over, with multiple Workers").

The Boss supervises, it never trades its own opinion:
  * CONTRACT REGISTRY — each worker's frozen spec + acceptance band travels with it (below).
  * CONFORMANCE WATCH — rolling live scorecard per worker (tracker decisions, window n>=30):
    WR below (band floor − 10pts) or DD beyond budget → the worker is DISARMED (audit-logged);
    the others are untouched. Re-arm = a fresh green window or a manual /api/boss/arm.
  * RISK ALLOCATION — the shared budget stays with bot.risk (0.25%/trade · daily · trailing);
    the Boss adds the CORRELATION BUCKET rule: same-direction fires on correlated symbols in
    the same cycle are ONE macro bet — only the highest-grade fire sizes full, the rest stand
    down to zero for that cycle.
  * CONFLICT RULE — opposite-direction fires on correlated symbols: highest grade wins, the
    other side stands down this cycle.

Workers ship DISARMED until their lineage's paper approval exists; the OBSOLETE ones are
registered but never armable (visible on the dashboard graveyard — nothing silently deleted).
"""
from __future__ import annotations

import json
from pathlib import Path

from bot.config import BOT_ROOT

STATE = BOT_ROOT / "data" / "boss.json"
GRADE_RANK = {"A+": 4, "A": 3, "B": 2, "C": 1, None: 0}
BUCKETS = {"tech_index": ("QQQ", "SPY", "NQ", "MNQ", "ES", "MES"),  # one macro bet when aligned
           "metals": ("GC", "MGC")}

# ── the worker contracts (frozen by the discovery rounds; bands from BOSS_WORKERS_PLAN) ──
# b = tight-target multiple (TP = b x risk); tier = the selectivity filter adopted in F80.
WORKERS = {
    "worker-q": {"symbol": "QQQ", "lineage": "worker-q-0.1", "b": 0.40, "tier": "slope_strong",
                 "spec": "ORB 07.7 stack · target 0.40x stop · slope-STRONG tier",
                 "band": {"wr_min": 75.0, "pf_min": 1.7, "dd_budget_r": -8.0}},
    "worker-s": {"symbol": "SPY", "lineage": "worker-s-0.1", "b": 0.33, "tier": None,
                 "spec": "ORB 07.7 stack · target 0.33x stop",
                 "band": {"wr_min": 75.0, "pf_min": 1.7, "dd_budget_r": -8.0}},
    "worker-n": {"symbol": "NQ", "lineage": "worker-n-0.1", "b": 0.30, "tier": "early_only",
                 "spec": "ORB 07.7 stack · target 0.30x stop · early-only tier",
                 "band": {"wr_min": 78.0, "pf_min": 1.7, "dd_budget_r": -10.0}},
    "worker-e": {"symbol": "ES", "lineage": "worker-e-0.1", "b": 0.40, "tier": None,
                 "obsolete": True,
                 "spec": "OBSOLETE 2026-07-06: PF < 1 at every tight-target cell/tier "
                         "(worker_specs/worker_cohorts) + 2x-slip fragility — signals only",
                 "band": {"wr_min": 75.0, "pf_min": 1.7, "dd_budget_r": -10.0}},
    "worker-g": {"symbol": "GC", "lineage": "worker-g-0.1", "b": 0.45, "tier": None,
                 "obsolete": True,
                 "spec": "OBSOLETE 2026-07-06: IS PF 0.07-0.25 at every cell (F30 edge not "
                         "reproduced) — paper ladder as SIGNALS-ONLY per user rule",
                 "band": {"wr_min": 75.0, "pf_min": 1.7, "dd_budget_r": -10.0}},
}


def _now() -> str:
    from bot.contracts import utcnow_iso
    return utcnow_iso()


def _load() -> dict:
    from bot.config import read_json
    return read_json(STATE)


def _save(d: dict) -> None:
    from bot.config import write_json
    write_json(STATE, d)


def _worker_for(symbol: str) -> str | None:
    s = symbol.upper()
    for wid, w in WORKERS.items():
        if s == w["symbol"] or (s in ("MNQ",) and w["symbol"] == "NQ") \
                or (s in ("MES",) and w["symbol"] == "ES") or (s in ("MGC",) and w["symbol"] == "GC"):
            return wid
    return None


def _rolling(symbol: str, window: int = 30, family: str | None = None) -> dict:
    """Rolling live scorecard from the tracker (taken+closed, newest `window`). When `family` is
    given (a worker id), the window is that WORKER's shadow trades only — so each worker is judged
    on its OWN tight-target stream, not mixed with the core breakout rows on the same symbol."""
    try:
        from bot.tracker import _con
        con = _con()
        if family:
            rows = con.execute(
                "SELECT result_r FROM decisions WHERE taken=1 AND family=? AND outcome NOT IN "
                "('open') AND result_r IS NOT NULL ORDER BY decided_at DESC LIMIT ?",
                [family, window]).fetchall()
        else:
            rows = con.execute(
                "SELECT result_r FROM decisions WHERE taken=1 AND symbol=? AND outcome NOT IN "
                "('open') AND result_r IS NOT NULL ORDER BY decided_at DESC LIMIT ?",
                [symbol, window]).fetchall()
        con.close()
    except Exception:
        return {"n": 0}
    r = [float(x[0]) for x in rows]
    if not r:
        return {"n": 0}
    eq, peak, dd = 0.0, 0.0, 0.0
    for x in reversed(r):                      # chronological equity for the window DD
        eq += x
        peak = max(peak, eq)
        dd = min(dd, eq - peak)
    wins = sum(1 for x in r if x > 0)
    loss = sum(-x for x in r if x <= 0)
    return {"n": len(r), "wr": round(100 * wins / len(r), 1),
            "pf": round(sum(x for x in r if x > 0) / loss, 2) if loss else None,
            "dd_r": round(dd, 1)}


def conformance(wid: str) -> dict:
    """Band check on the worker's OWN rolling shadow window. None verdict until n>=30.
    `band_pass` = the FULL user band (WR + PF + DD) on the window — the promotion signal
    (user 2026-07-07: "workers that pass need to be notified" + an approve button)."""
    w = WORKERS[wid]
    roll = _rolling(w["symbol"], family=wid)
    verdict, band_pass = None, False
    if roll.get("n", 0) >= 30:
        band = w["band"]
        verdict = (roll["wr"] >= band["wr_min"] - 10.0
                   and roll["dd_r"] >= band["dd_budget_r"])
        band_pass = (roll["wr"] >= band["wr_min"] and (roll.get("pf") or 0) >= band["pf_min"]
                     and roll["dd_r"] >= band["dd_budget_r"])
    return {"rolling": roll, "conforms": verdict, "band_pass": band_pass}


def _et_hour(iso: str | None) -> int | None:
    if not iso:
        return None
    try:
        import pandas as pd
        return int(pd.Timestamp(iso).tz_convert("America/New_York").hour)
    except Exception:
        return None


def shadow_decisions(signals: list[dict]) -> list[dict]:
    """Build the per-worker SHADOW paper study: for every PAPER-APPROVED worker, turn each of its
    matching live signals into a tight-target what-if decision (same canonical entry/stop as the
    core signal — workers share the ARMED->WATCH->FILL entry — but TP = b x risk and the worker's
    selectivity tier applied). Tagged family=<worker id> so the tracker resolves and scores each
    worker separately (Alpaca nets one position per symbol, so real colliding brackets are
    impossible; the shadow study IS the multi-worker paper mechanism). The caller records these.

    OBSOLETE workers (E/G) are still shadowed when approved — signals-only means no REAL order,
    and the what-if data confirms they stay below band (or, on new data, earns a revival).
    DISARMED workers keep recording (that's how they earn re-arming) but their rows carry
    disarmed=true so the Boss can split benched evidence from live conformance (review fix)."""
    from bot.approval import paper_approved
    _armed = {k: bool(v.get("armed")) for k, v in _load().get("workers", {}).items()}
    out = []
    for s in signals:
        if not s.get("tradeable") or s.get("grade") not in ("A+", "A", "B"):
            continue
        if s.get("signal_state") == "invalid" or (s.get("bars_ago") or 0) < 1:
            continue
        wid = _worker_for(s.get("symbol", ""))
        if wid is None:
            continue
        w = WORKERS[wid]
        if not paper_approved(w["lineage"]):
            continue
        entry, stop, side = s.get("entry"), s.get("stop"), s.get("side")
        if entry is None or stop is None or side not in ("long", "short"):
            continue
        risk = abs(float(entry) - float(stop))
        if risk <= 0:
            continue
        # tier gate (F80): slope_strong ~ slope_grade A+/A (approx); early_only ~ before 12:00 ET
        tier = w.get("tier")
        c = s.get("candidate") or {}
        if tier == "slope_strong" and s.get("slope_grade") not in ("A+", "A"):
            continue
        if tier == "early_only":
            h = _et_hour(c.get("generated_at") or s.get("generated_at"))
            if h is not None and h >= 12:
                continue
        sgn = 1 if side == "long" else -1
        tp = round(float(entry) + sgn * risk * w["b"], 2)
        key = f"{wid}:{s.get('session')}:{side}:{c.get('generated_at') or ''}"
        # a worker is a SINGLE tight-target trade (TP = b x risk). tp2=None marks it single-target
        # so the walk/journal don't render TP1==TP2 (the corrupt-looking row) or resolve a trivial
        # "tp2" the instant the one target is hit (user 2026-07-08).
        out.append({"candidate_id": key, "symbol": s["symbol"], "side": side,
                    "family": wid, "session": s.get("session"), "entry": entry, "stop": stop,
                    "tp1": tp, "tp2": None, "grade": s.get("grade"),
                    "generated_at": c.get("generated_at"),
                    "tf": s.get("timeframe") or "5m",   # lineage tf tag (journal->training separation)
                    "pit_features": s.get("pit_features"), "worker": w["lineage"],
                    "disarmed": not _armed.get(wid, False),
                    "obsolete": bool(w.get("obsolete"))})
    return out


def evaluate() -> dict:
    """One Boss pass: conformance per worker + auto-disarm on breach. Called from the scan loop
    (hourly tick) and /api/boss. Manual arm/disarm survives via boss.json."""
    st = _load()
    st.setdefault("workers", {})
    out = {"generated_at": _now(), "workers": {}}
    for wid, w in WORKERS.items():
        ws = st["workers"].setdefault(wid, {"armed": False, "note": "awaits paper approval"})
        if w.get("obsolete"):
            ws.update({"armed": False, "note": "OBSOLETE — signals only, never armable"})
            conf = {"rolling": _rolling(w["symbol"]), "conforms": None}
        else:
            conf = conformance(wid)
            if ws.get("armed") and conf["conforms"] is False:
                ws.update({"armed": False,
                           "note": f"AUTO-DISARM {_now()[:16]} — rolling window broke the band "
                                   f"{conf['rolling']}"})
                try:
                    from bot.audit import log as _audit
                    _audit("boss_disarm", worker=wid, **conf["rolling"])
                except Exception:
                    pass
            # BAND-PASS NOTIFICATION (user 2026-07-07): a worker whose rolling window reaches the
            # FULL band is flagged once (audit + durable state) — the dashboard shows the badge
            # with the paper-approve button next to it.
            if conf.get("band_pass") and not ws.get("band_passed_at"):
                ws["band_passed_at"] = _now()
                try:
                    from bot.audit import log as _audit
                    _audit("boss_band_pass", worker=wid, **conf["rolling"])
                except Exception:
                    pass
        try:
            from bot.approval import paper_approved as _pa
            papered = _pa(w["lineage"])
        except Exception:
            papered = None
        out["workers"][wid] = {**w, "state": ws, "conformance": conf, "paper_approved": papered}
    _save(st)
    return out


def allowed(symbol: str) -> bool:
    """The paper/live gate hook: may this symbol's worker place orders this cycle?"""
    wid = _worker_for(symbol)
    if wid is None:
        return True                            # not a worker symbol — outside Boss scope
    if WORKERS[wid].get("obsolete"):
        return False
    return bool(_load().get("workers", {}).get(wid, {}).get("armed"))


def arm(wid: str, on: bool = True, by: str = "user") -> dict:
    if wid not in WORKERS:
        return {"error": f"unknown worker {wid}"}
    if on and WORKERS[wid].get("obsolete"):
        return {"error": f"{wid} is OBSOLETE — re-arm requires a fresh full gauntlet on new data"}
    st = _load()
    st.setdefault("workers", {})[wid] = {"armed": bool(on),
                                         "note": f"{'armed' if on else 'disarmed'} by {by} {_now()[:16]}"}
    _save(st)
    try:
        from bot.audit import log as _audit
        _audit("boss_arm" if on else "boss_manual_disarm", worker=wid, by=by)
    except Exception:
        pass
    return st["workers"][wid]


def allocate(signals: list[dict]) -> list[dict]:
    """CORRELATION-BUCKET pass over one scan cycle's tradeable fires: within a bucket,
    same-direction fires keep only the highest grade at full size (others -> stand_down);
    opposite-direction fires: highest grade wins, loser stands down. Annotates in place.

    GOAL-MET PRIORITY (user 2026-07-07: "whenever one script is making the equivalent of the
    goal or more, its signal will be priority — champion/challenger still remain, we're looking
    for better numbers"): a signal whose worker has BAND-PASSED (rolling window at/above the
    goal) is tagged priority=True, outranks grade for the bucket lead, and sorts first on the
    dashboard. Training/champion-challenger are untouched — priority routes signals, not models."""
    st = _load().get("workers", {})

    def _goal_met(s) -> bool:
        wid = _worker_for(s.get("symbol", ""))
        w = WORKERS.get(wid) if wid else None
        return bool(wid and w and not w.get("obsolete")
                    and st.get(wid, {}).get("band_passed_at"))

    for s in signals:
        s.setdefault("boss", "solo")
        if s.get("tradeable") and _goal_met(s):
            s["priority"] = True
    for bucket, syms in BUCKETS.items():
        group = [s for s in signals if s.get("symbol", "").upper() in syms and s.get("tradeable")]
        if len(group) <= 1:
            continue
        best = max(group, key=lambda s: (1 if s.get("priority") else 0,
                                         GRADE_RANK.get(s.get("grade"), 0)))
        for s in group:
            s["boss"] = ("lead:" + bucket) if s is best else ("stand_down:" + bucket +
                                                              " (one macro bet — priority/grade rank)")
    signals.sort(key=lambda s: not s.get("priority", False))     # stable: goal-met first
    return signals


if __name__ == "__main__":   # self-test: registry sanity + bucket allocation + obsolete lock
    assert _worker_for("MNQ") == "worker-n" and _worker_for("QQQ") == "worker-q"
    r = arm("worker-g", True)
    assert "error" in r and "OBSOLETE" in r["error"]
    sig = [{"symbol": "QQQ", "grade": "A+", "tradeable": True, "side": "long"},
           {"symbol": "NQ", "grade": "B", "tradeable": True, "side": "long"},
           {"symbol": "GC", "grade": "A", "tradeable": True, "side": "long"}]
    out = allocate(sig)
    assert out[0]["boss"].startswith("lead") and out[1]["boss"].startswith("stand_down")
    assert out[2]["boss"] == "solo"            # alone in its bucket
    ev = evaluate()
    assert set(ev["workers"]) == set(WORKERS)
    print("boss OK — registry, obsolete lock, bucket allocation, conformance evaluated")
