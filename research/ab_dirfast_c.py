"""A/B — DIR-FAST C + the A∨B∨C arming rule (user 2026-07-05) vs the adopted per-asset gates.

DIR-FAST C (designed from the user's slope research, orb_state.slope_engine):
  C aligned = the COMBINED SLOPE ENGINE strong read — S = 0.50·Sc/ATR + 0.30·Sm/ATR + 0.20·BP
  at |S| >= 0.30 toward the side (the spec's STRONG band).
The A∨B∨C rule: a side ARMS when ANY engine aligns —
  A = VWAP side (the obligatory OR-mid rides in the watch machine for everyone)
  B = swing-structure state
  C = slope strong
i.e. it blocks only when EVERY engine disagrees or is neutral.

Per asset this cuts both ways: FUTURES today arm on mid alone (A∨B∨C adds a veto when all three
disagree); EQUITIES today require STRUCT AND VWAP (A∨B∨C relaxes to any-of-three). The evidence
decides per asset, as always.

    .venv/Scripts/python research/ab_dirfast_c.py QQQ SPY NQ ES
Report -> BOT/data/ml/reports/ab_dirfast_c.json
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
from bot.strategy.orb_state import slope_series, SLOPE_STRONG  # noqa: E402

REPORT = ROOT / "BOT" / "data" / "ml" / "reports" / "ab_dirfast_c.json"


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
        print(f"=== DIR-FAST C A/B {sym} ===", flush=True)
        d = load_state(sym)                       # A: the adopted per-asset gate
        a = metrics(run_backtest(d))
        st = d["st_state"].to_numpy(); cl = d["close"].to_numpy(float)
        vw = d["vwap_sess"].to_numpy(float)
        S = slope_series(d["open"].to_numpy(float), cl, d["atr14"].to_numpy(float))
        with np.errstate(invalid="ignore"):
            d["trend_up"] = (cl > vw) | (st == 1) | (S >= SLOPE_STRONG)
            d["trend_down"] = (cl < vw) | (st == 2) | (S <= -SLOPE_STRONG)
        b = metrics(run_backtest(d))
        out["symbols"][sym] = {"adopted": a, "abc": b}
        print(f"  adopted: n {a.get('trades')} WR {a.get('win_pct')}% avg {a.get('avg_r')} "
              f"PF {a.get('pf')} dd {a.get('max_dd_r')} oos30 {a.get('oos30_avg_r')}")
        print(f"  A|B|C  : n {b.get('trades')} WR {b.get('win_pct')}% avg {b.get('avg_r')} "
              f"PF {b.get('pf')} dd {b.get('max_dd_r')} oos30 {b.get('oos30_avg_r')}", flush=True)
        REPORT.write_text(json.dumps(out, indent=1), encoding="utf-8")
    print(f"saved -> {REPORT}")


if __name__ == "__main__":
    main([s.upper() for s in (sys.argv[1:] or ["QQQ", "SPY", "NQ", "ES"])])
