"""WORKER-CONTRACT SYNC (2026-07-07) — the worker truth lives in three hand-synced places:
bot/boss.py WORKERS (the executable contract), bot/strategy/modules.py (the registry the
UI/approvals read), and research/worker_veto.py WORKERS (the discovery cells). The F75 lesson
(hand-synced tables drift silently) got the Pine↔config test; this is the same lock for workers.
The research file is parsed via AST (importing it would chdir + load the engine)."""
import ast
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from bot.boss import WORKERS
from bot.strategy.modules import STRATEGY_MODULES

ROOT = Path(__file__).resolve().parents[2]


def _research_workers() -> dict:
    """AST-extract the WORKERS dict from research/worker_veto.py without importing it."""
    tree = ast.parse((ROOT / "research" / "worker_veto.py").read_text(encoding="utf-8"))
    for node in ast.walk(tree):
        if isinstance(node, ast.Assign) and any(
                isinstance(t, ast.Name) and t.id == "WORKERS" for t in node.targets):
            return ast.literal_eval(node.value)
    raise AssertionError("WORKERS dict not found in research/worker_veto.py")


def test_boss_matches_modules_registry():
    mods = {m["strategy_version"]: m for m in STRATEGY_MODULES
            if str(m.get("strategy_version", "")).startswith("worker-")}
    assert set(mods) == {w["lineage"] for w in WORKERS.values()}, \
        "modules.py worker lineages != boss.WORKERS lineages"
    for wid, w in WORKERS.items():
        m = mods[w["lineage"]]
        assert w["symbol"] in m["symbols"], f"{wid}: symbol {w['symbol']} not in modules entry"
        # obsolete in the Boss contract <=> status 'obsolete' in the registry
        assert bool(w.get("obsolete")) == (m["status"] == "obsolete"), \
            f"{wid}: obsolete flag drifted (boss {w.get('obsolete')} vs modules {m['status']})"


def test_boss_matches_research_cells():
    rw = _research_workers()
    for sym, cell in rw.items():
        wid = next((k for k, w in WORKERS.items() if w["symbol"] == sym), None)
        assert wid, f"research cell {sym} has no boss worker"
        w = WORKERS[wid]
        assert abs(w["b"] - cell["b"]) < 1e-9, \
            f"{wid}: target b drifted (boss {w['b']} vs research {cell['b']})"
        assert w.get("tier") == cell.get("tier"), \
            f"{wid}: tier drifted (boss {w.get('tier')} vs research {cell.get('tier')})"


def test_bands_are_sane():
    for wid, w in WORKERS.items():
        band = w["band"]
        assert 50 <= band["wr_min"] <= 95 and band["pf_min"] >= 1.0 and band["dd_budget_r"] < 0, \
            f"{wid}: band values out of sane range {band}"
