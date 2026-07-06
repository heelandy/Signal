"""A/B — OR_MID-OBLIGATORY arming (user rule 2026-07-05) vs the adopted ctx pair gates.

User (twice): "OR_MID IS OBLIGATORY" — arming needs the OR-mid side ONLY; VWAP/STRUCT/SLOPE
grade the signal (C/B/A/A+) but must not block or delay it. Screenshot evidence: NQ short broke
the OR low with MID agreeing while VWAP disagreed -> no arm, no fill under mid_vwap gating.

A = adopted per-asset pair gate (futures mid_vwap: VWAP side array + mid via watch machine;
    equities struct_vwap). B = mid-only (arrays all-True; the watch machine's OR-mid close is
    the one obligatory arm condition). Same exits, costs, per-asset Layer-3 knobs.

    .venv/Scripts/python research/ab_midonly.py QQQ SPY NQ ES
Report -> BOT/data/ml/reports/ab_midonly.json
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

from bot.strategy.orb_candidates import load_state, run_backtest  # noqa: E402

REPORT = ROOT / "BOT" / "data" / "ml" / "reports" / "ab_midonly.json"


def metrics(tr: pd.DataFrame) -> dict:
    if not len(tr):
        return {"trades": 0}
    r = tr["net_R"].to_numpy(float)
    wins, losses = r[r > 0], r[r <= 0]
    pf = float(wins.sum() / abs(losses.sum())) if len(losses) and losses.sum() != 0 else None
    eq = np.cumsum(r)
    cut = int(0.7 * len(r))
    return {"trades": int(len(r)), "win_pct": round(100 * float((r > 0).mean()), 1),
            "avg_r": round(float(r.mean()), 3), "total_r": round(float(r.sum()), 1),
            "pf": round(pf, 2) if pf else None,
            "max_dd_r": round(float((eq - np.maximum.accumulate(eq)).min()), 1),
            "oos30_avg_r": round(float(r[cut:].mean()), 3) if len(r) - cut > 5 else None}


def main(syms):
    out = {"generated_at": pd.Timestamp.now("UTC").isoformat(), "symbols": {}}
    REPORT.parent.mkdir(parents=True, exist_ok=True)
    for sym in syms:
        print(f"=== MID-ONLY A/B {sym} ===", flush=True)
        d = load_state(sym)                       # A: adopted pair gate arrays
        a = metrics(run_backtest(d))
        d["trend_up"] = True                      # B: mid-only — watch machine is the gate
        d["trend_down"] = True
        b = metrics(run_backtest(d))
        out["symbols"][sym] = {"pair_gate": a, "mid_only": b}
        print(f"  A pair : n {a.get('trades')} WR {a.get('win_pct')}% avg {a.get('avg_r')} "
              f"PF {a.get('pf')} dd {a.get('max_dd_r')} oos30 {a.get('oos30_avg_r')}")
        print(f"  B mid  : n {b.get('trades')} WR {b.get('win_pct')}% avg {b.get('avg_r')} "
              f"PF {b.get('pf')} dd {b.get('max_dd_r')} oos30 {b.get('oos30_avg_r')}", flush=True)
        REPORT.write_text(json.dumps(out, indent=1), encoding="utf-8")
    print(f"saved -> {REPORT}")


if __name__ == "__main__":
    main([s.upper() for s in (sys.argv[1:] or ["QQQ", "SPY", "NQ", "ES"])])
