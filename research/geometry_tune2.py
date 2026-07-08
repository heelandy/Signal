"""GEOMETRY TUNE 2 — grid the FIRST-TOUCH-STUDY hints on FULL history vs the goal band
(user 2026-07-07: "adjust based on the screenshot while keeping or gridding to go HIGHER than
the goal"). The live study (14 trades — a HINT, never a judge) said: median MFE 0.4R, 71%
stop-first, winners rarely dip — i.e. bank near, maybe trail. Those exact ideas, gridded
honestly on all history under the full 07.7 stack, IS nominates / OOS judges:

  tp2_full  b in {0.30,0.33,0.40,0.45,0.50}          (reference — the worker cells)
  scale_be  tp1 in {0.35,0.45} x scale_frac in {0.5,0.75} x tp2 in {1.0,2.0}
            (bank most at the near target, runner to BE then tp2 — 'a trail likely banks more')
  trail     ATR chandelier (ride, no cap)

GOAL: WR 75-85+ AND PF >= 1.7 AND DD within budget on BOTH halves; cells ABOVE goal ranked
first. Champion/challenger training is untouched — this tunes trade GEOMETRY only.

    .venv/Scripts/python research/geometry_tune2.py QQQ SPY NQ
Report -> BOT/data/ml/reports/geometry_tune2.json
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

from bot.strategy.orb_candidates import (load_state, ORS, ORE, CUT, EOD, STRONG)  # noqa: E402
from bot.strategy.asset_config import asset_config, resolve_ctx_mode, layer3_kwargs  # noqa: E402
from worker_specs import stats, in_band, BAND  # noqa: E402

REPORT = ROOT / "BOT" / "data" / "ml" / "reports" / "geometry_tune2.json"


def run_exit(d, mode, t1, t2, sf=0.5):
    import hs_backtest as B
    a = asset_config(str(d.attrs.get("sym", "")))
    m = resolve_ctx_mode(a)
    return B.backtest(d, mode, "both", False, "orb", 0, t1, t2, ORS, ORE, 0.0, CUT, "close",
                      eod_min=EOD, stop_mode="struct", entry_delay=a.entry_delay,
                      strong_body=STRONG, ft_confirm=a.ft_confirm, dir_seq=True,
                      reentry=True, max_entries=a.max_entries, chase_atr=a.chase_atr,
                      or_mid_bias=(m not in ("mid", "mid_vwap", "mid_only", "abc")),
                      instant_aligned=a.instant_fill, block_range=a.block_range,
                      scale_frac=sf, **layer3_kwargs(a))


def main(syms):
    out = {"generated_at": pd.Timestamp.now("UTC").isoformat(), "band": BAND,
           "note": "first-touch hints gridded on FULL history; live n=14 is a hint, not a judge",
           "symbols": {}}
    REPORT.parent.mkdir(parents=True, exist_ok=True)
    cells = ([("tp2_full", None, b, 0.5, f"tp2_full b={b}") for b in (0.30, 0.33, 0.40, 0.45, 0.50)]
             + [("scale_be", t1, t2, sf, f"scale_be tp1={t1} sf={sf} tp2={t2}")
                for t1 in (0.35, 0.45) for sf in (0.5, 0.75) for t2 in (1.0, 2.0)]
             + [("trail", None, 4.0, 0.5, "trail (chandelier)")])
    for sym in syms:
        print(f"=== TUNE2 {sym} ===", flush=True)
        d = load_state(sym)
        res = {}
        for mode, t1, t2, sf, name in cells:
            tr = run_exit(d, mode, t1 if t1 is not None else 1.5, t2, sf)
            r = tr["net_R"].to_numpy(float) if len(tr) else np.array([])
            cut = int(0.7 * len(r))
            is_, oos = stats(r[:cut]), stats(r[cut:])
            both = in_band(is_, dd_scale=2.33) and in_band(oos)
            above = (both and (oos.get("pf") or 0) >= BAND["pf_min"] + 0.1)   # HIGHER than goal
            res[name] = {"is": is_, "oos": oos, "in_band_both": both, "above_goal": above}
            print(f"  {name:32} IS wr {is_.get('wr')} pf {is_.get('pf')} dd {is_.get('dd')} | "
                  f"OOS wr {oos.get('wr')} pf {oos.get('pf')} dd {oos.get('dd')} "
                  f"{'<== ABOVE GOAL' if above else '<== BAND' if both else ''}", flush=True)
        winners = [k for k, v in res.items() if v["in_band_both"]]
        out["symbols"][sym] = {"cells": res, "in_band": winners,
                               "verdict": (f"{len(winners)} cell(s) at/above goal" if winners
                                           else "no cell reaches the goal on both halves")}
        print(f"  -> {sym}: {out['symbols'][sym]['verdict']}", flush=True)
        REPORT.write_text(json.dumps(out, indent=1), encoding="utf-8")
    print(f"saved -> {REPORT}")


if __name__ == "__main__":
    main([s.upper() for s in (sys.argv[1:] or ["QQQ", "SPY", "NQ"])])
