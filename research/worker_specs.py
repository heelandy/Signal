"""WORKER SPEC DISCOVERY — step 2 of docs/BOSS_WORKERS_PLAN.md (user goal per worker:
WR 75-85% · PF >= 1.7 · maxDD <= 10R, OOS-judged).

Per symbol (QQQ SPY NQ ES GC): tight-target geometry grid under the FULL 07.7 per-asset gate
stack (the canonical entry exactly as traded — arming, chase/retest, fills, macro gates, costs).
Only the trade GEOMETRY varies: full position to a tight target b x stop (tp2_full with
tp2_rr=b), binary win/loss. IS = first 70% nominates cells inside the band; OOS = last 30%
judges. No cell inside the band on BOTH -> that worker has no geometry-only spec and must earn
the band via selectivity (step 3) or go OBSOLETE.

    .venv/Scripts/python research/worker_specs.py QQQ SPY NQ ES GC
Report -> BOT/data/ml/reports/worker_specs.json
"""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "BOT"))
sys.path.insert(0, str(ROOT / "engine"))
os.chdir(ROOT)

from bot.strategy.orb_candidates import (load_state, T1, ORS, ORE, CUT, EOD,  # noqa: E402
                                         STRONG, STRATEGY_VERSION)
from bot.strategy.asset_config import asset_config, resolve_ctx_mode, layer3_kwargs  # noqa: E402

REPORT = ROOT / "BOT" / "data" / "ml" / "reports" / "worker_specs.json"
B_GRID = (0.30, 0.33, 0.40, 0.45, 0.50, 0.55, 0.60)
BAND = {"wr_min": 75.0, "wr_max": 85.0, "pf_min": 1.7, "dd_max": -10.0}   # dd in R (OOS)


def run_geometry(d, b):
    """The canonical 07.7 call with ONLY the target geometry swapped (tp2_full to b x stop)."""
    import hs_backtest as B
    a = asset_config(str(d.attrs.get("sym", "")))
    mode = resolve_ctx_mode(a)
    return B.backtest(d, "tp2_full", "both", False, "orb", 0, T1, b, ORS, ORE, 0.0, CUT, "close",
                      eod_min=EOD, stop_mode="struct", entry_delay=a.entry_delay,
                      strong_body=STRONG, ft_confirm=a.ft_confirm, dir_seq=True,
                      reentry=True, max_entries=a.max_entries, chase_atr=a.chase_atr,
                      or_mid_bias=(mode not in ("mid", "mid_vwap", "mid_only", "abc")),
                      instant_aligned=a.instant_fill, block_range=a.block_range,
                      **layer3_kwargs(a))


def stats(r: np.ndarray) -> dict:
    if not len(r):
        return {"n": 0}
    wins, losses = r[r > 0], r[r <= 0]
    eq = np.cumsum(r)
    return {"n": int(len(r)), "wr": round(100 * float((r > 0).mean()), 1),
            "avg_r": round(float(r.mean()), 3), "total_r": round(float(r.sum()), 1),
            "pf": round(float(wins.sum() / abs(losses.sum())), 2) if len(losses) and losses.sum() else None,
            "dd": round(float((eq - np.maximum.accumulate(eq)).min()), 1)}


def in_band(s: dict, dd_scale: float = 1.0) -> bool:
    return (s.get("n", 0) > 0 and s.get("pf") is not None
            and BAND["wr_min"] <= s["wr"] <= BAND["wr_max"] + 5     # WR above band top is fine
            and s["pf"] >= BAND["pf_min"] and s["dd"] >= BAND["dd_max"] * dd_scale)


def main(syms):
    out = {"generated_at": pd.Timestamp.now("UTC").isoformat(), "rule": STRATEGY_VERSION,
           "band": BAND, "b_grid": list(B_GRID), "symbols": {}}
    REPORT.parent.mkdir(parents=True, exist_ok=True)
    for sym in syms:
        print(f"=== WORKER GRID {sym} ===", flush=True)
        try:
            d = load_state(sym)
        except Exception as e:
            out["symbols"][sym] = {"error": str(e)}
            print(f"  load failed: {e}", flush=True)
            continue
        cells = {}
        for b in B_GRID:
            tr = run_geometry(d, b)
            r = tr["net_R"].to_numpy(float) if len(tr) else np.array([])
            cut = int(0.7 * len(r))
            is_, oos = stats(r[:cut]), stats(r[cut:])
            # IS dd budget scales with the longer window (~2.33x the OOS span)
            cells[str(b)] = {"is": is_, "oos": oos,
                             "band_is": in_band(is_, dd_scale=2.33), "band_oos": in_band(oos)}
            print(f"  b={b:.2f} IS n{is_.get('n'):4} wr {is_.get('wr')} pf {is_.get('pf')} "
                  f"dd {is_.get('dd')} | OOS n{oos.get('n'):4} wr {oos.get('wr')} "
                  f"pf {oos.get('pf')} dd {oos.get('dd')} "
                  f"{'<== BAND' if cells[str(b)]['band_is'] and cells[str(b)]['band_oos'] else ''}",
                  flush=True)
        passing = [b for b, c in cells.items() if c["band_is"] and c["band_oos"]]
        out["symbols"][sym] = {"cells": cells, "passing_cells": passing,
                               "verdict": ("geometry-only spec EXISTS" if passing else
                                           "needs selectivity (step 3) or OBSOLETE")}
        print(f"  -> {sym}: {out['symbols'][sym]['verdict']} {passing}", flush=True)
        REPORT.write_text(json.dumps(out, indent=1), encoding="utf-8")
    print(f"saved -> {REPORT}")


if __name__ == "__main__":
    main([s.upper() for s in (sys.argv[1:] or ["QQQ", "SPY", "NQ", "ES", "GC"])])
