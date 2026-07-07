"""EVOLUTION ENGINE — the always-learning loop (docs/BOSS_WORKERS_PLAN.md §4b, user 2026-07-06:
"the script needs to be always learning; from study and journaling, trades, exit/TP, a new
system can emerge").

Nightly (scan-loop tick) + on-demand (/api/evolve). Three miners over the evidence streams, an
honest split on every pattern, and DRAFTS — never adoptions:

  exit_tp    — per worker cell: winners' MFE vs the TP and losers' MAE vs the stop, from the
               canonical engine trades (mfe_R/mae_R ride every backtest row). If winners leave
               >= 0.25R on the table (median MFE − TP) on BOTH halves, draft a TP-revision.
  slices     — tracker taken+closed decisions (live/paper): DOW × session × grade cells with
               n >= 100 whose BOTH-halves expectancy clears the band -> draft a filter tier.
  rejects    — the reject store's missed_winner rates by block reason (n >= 200, both halves):
               a gate whose missed winners out-earn its blocked losers -> draft a gate review.

A draft = a written spec + the evidence, appended to data/evolve_drafts.json and audit-logged as
`evolve_draft`. Drafts enter the SAME promotion path as everything else (gauntlet -> module ->
ladder -> paper). The engine proposes; the gauntlet and the ladder judge.
"""
from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pandas as pd

from bot.config import BOT_ROOT

DRAFTS = BOT_ROOT / "data" / "evolve_drafts.json"
REPORT = BOT_ROOT / "data" / "ml" / "reports" / "evolve.json"
WORKER_CELLS = {"QQQ": 0.40, "SPY": 0.33, "NQ": 0.30}   # the discovery-round cells
MIN_LEFT_ON_TABLE = 0.25                                 # R, median, both halves


def _now() -> str:
    from bot.contracts import utcnow_iso
    return utcnow_iso()


def _load_drafts() -> list:
    from bot.config import read_json
    return read_json(DRAFTS, default=[])


def _draft(kind: str, slug: str, spec: str, evidence: dict) -> dict:
    """Append a draft (idempotent by slug — a rediscovered pattern refreshes its evidence)."""
    rows = _load_drafts()
    d = next((r for r in rows if r["slug"] == slug), None)
    if d is None:
        d = {"slug": slug, "id": f"emergent-{slug}-0.1", "kind": kind, "first_seen": _now()}
        rows.append(d)
    d.update({"spec": spec, "evidence": evidence, "updated": _now(), "status": "draft",
              "path": "gauntlet -> modules.py lineage -> approval ladder -> paper"})
    from bot.config import write_json
    write_json(DRAFTS, rows)
    try:
        from bot.audit import log as _audit
        _audit("evolve_draft", slug=slug, kind=kind)
    except Exception:
        pass
    return d


def mine_exit_tp() -> list[dict]:
    """Winners' MFE headroom above the worker TP, both halves — the exit/TP study."""
    from bot.strategy.orb_candidates import load_state
    import sys
    sys.path.insert(0, str(BOT_ROOT.parent / "research"))
    out = []
    try:
        from worker_cohorts import run_cell
    except Exception as e:
        return [{"error": f"research harness unavailable: {e}"}]
    for sym, b in WORKER_CELLS.items():
        try:
            tr = run_cell(load_state(sym), b)
        except Exception as e:
            out.append({"symbol": sym, "error": str(e)})
            continue
        if not len(tr):
            continue
        w = tr[tr["net_R"] > 0]
        cut = int(0.7 * len(tr))
        headroom = []
        for half in (tr.iloc[:cut], tr.iloc[cut:]):
            hw = half[half["net_R"] > 0]
            headroom.append(float((hw["mfe_R"] - b).median()) if len(hw) else np.nan)
        finding = {"symbol": sym, "tp": b, "n_wins": int(len(w)),
                   "median_mfe_headroom_is": round(headroom[0], 3),
                   "median_mfe_headroom_oos": round(headroom[1], 3)}
        if all(h == h and h >= MIN_LEFT_ON_TABLE for h in headroom):
            finding["draft"] = _draft(
                "exit_tp", f"{sym.lower()}-tp-headroom",
                f"{sym} worker cell TP {b}x: winners' median MFE runs {headroom[1]:.2f}R past "
                f"the TP on BOTH halves — test TP {b}+0.1 / a 2-stage exit in the next "
                f"worker-spec revision (worker-{sym[0].lower()}-0.2 candidate)",
                finding)["id"]
        out.append(finding)
    return out


def mine_slices(min_n: int = 100) -> list[dict]:
    """Tracker decisions: DOW x grade cells, both-halves positive expectancy -> filter drafts."""
    try:
        from bot.tracker import _con
        con = _con()
        rows = con.execute("SELECT symbol, result_r, decided_at, json FROM decisions "
                           "WHERE taken=1 AND outcome NOT IN ('open') AND result_r IS NOT NULL "
                           "ORDER BY decided_at").fetchall()
        con.close()
    except Exception as e:
        return [{"error": str(e)}]
    if len(rows) < min_n:
        return [{"note": f"{len(rows)} closed live/paper trades — slice mining arms at {min_n}"}]
    df = pd.DataFrame(rows, columns=["symbol", "r", "at", "json"])
    df["grade"] = df["json"].map(lambda j: (json.loads(j or "{}") or {}).get("grade"))
    df["dow"] = pd.to_datetime(df["at"], utc=True, format="ISO8601").dt.dayofweek
    out = []
    for (sym, g, dow), grp in df.groupby(["symbol", "grade", "dow"]):
        if len(grp) < min_n:
            continue
        cut = int(0.7 * len(grp))
        a, bhalf = grp["r"].iloc[:cut].astype(float), grp["r"].iloc[cut:].astype(float)
        if a.mean() > 0.3 and bhalf.mean() > 0.3:
            f = {"symbol": sym, "grade": g, "dow": int(dow), "n": len(grp),
                 "is_avg": round(a.mean(), 3), "oos_avg": round(bhalf.mean(), 3)}
            f["draft"] = _draft("slice", f"{sym.lower()}-g{g}-d{dow}",
                                f"{sym} grade-{g} DOW-{dow} live cell earns on both halves "
                                f"(n={len(grp)}) — candidate worker filter tier", f)["id"]
            out.append(f)
    return out or [{"note": "no live slice clears the bar yet (honest — data accrues daily)"}]


def mine_rejects(min_n: int = 200) -> list[dict]:
    """Reject store: block reasons whose missed winners out-earn their blocked losers."""
    from bot.ml.registry import FeatureStore
    out = []
    for sym in WORKER_CELLS:
        try:
            from bot.ml.dataset import _version_slug
            df = FeatureStore().load(f"rejects_{sym}", _version_slug())
        except Exception:
            continue
        if "block_reason" not in df.columns or "hyp_net_r" not in df.columns:
            continue
        df = df.sort_values("ts")
        for reason, grp in df.groupby("block_reason"):
            if len(grp) < min_n:
                continue
            cut = int(0.7 * len(grp))
            h1 = grp["hyp_net_r"].iloc[:cut].astype(float)
            h2 = grp["hyp_net_r"].iloc[cut:].astype(float)
            if h1.mean() > 0.15 and h2.mean() > 0.15:
                f = {"symbol": sym, "reason": str(reason), "n": int(len(grp)),
                     "is_hyp": round(h1.mean(), 3), "oos_hyp": round(h2.mean(), 3)}
                f["draft"] = _draft("gate_review", f"{sym.lower()}-{reason}",
                                    f"{sym} gate '{reason}' blocks setups that would earn "
                                    f"+{h2.mean():.2f}R OOS (n={len(grp)}) — cohort-test the "
                                    f"gate under the current rule before trusting", f)["id"]
                out.append(f)
    return out or [{"note": "no reject gate clears the bar (or stores use other column names)"}]


def run(deep: bool = False) -> dict:
    """One evolution pass. deep=True includes the exit/TP miner (runs backtests — nightly only)."""
    rep = {"generated_at": _now(),
           "slices": mine_slices(), "rejects": mine_rejects(),
           "drafts_total": len(_load_drafts())}
    if deep:
        rep["exit_tp"] = mine_exit_tp()
    rep["drafts_total"] = len(_load_drafts())
    from bot.config import write_json
    write_json(REPORT, rep)
    return rep


if __name__ == "__main__":
    import sys
    r = run(deep="--deep" in sys.argv)
    print(json.dumps({k: (v if isinstance(v, (int, str)) else v[:3] if isinstance(v, list) else v)
                      for k, v in r.items()}, indent=1)[:2000])
    print("evolve OK")
