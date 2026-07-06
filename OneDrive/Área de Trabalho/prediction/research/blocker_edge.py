"""BLOCKER-EDGE STUDY (user 2026-07-06: "run tests against the blockers-by-design to find edge")
— PLUS the live≠backtest divergence this study exposed.

FINDING that triggered this: the canonical `run_backtest` never passed `chase_atr` (live 1.0)
or `min_or_width` (live 2.4) — both default OFF in the engine — so every 07.x validation number
includes trades the LIVE system refuses (today: QQQ blocked by the chase-cap, SPY by narrow-OR).

This study measures each blocker's cohort honestly under 07.4:
  A  canonical-as-validated (both gates OFF — what all our numbers were)
  B  + chase-cap 1.0 ATR (pullback/retest machine live)
  C  + narrow-OR filter 2.4 (vol-expansion gate)
  D  + both  (what LIVE actually trades)
Per variant: n/WR/avg/PF/DD/OOS30. Per blocker: the BLOCKED COHORT (trades in A missing from
the gated run, matched by entry_time) and its avg R — a NEGATIVE cohort means the blocker earns
its keep; POSITIVE means it costs edge and should be relaxed via gauntlet.

    .venv/Scripts/python research/blocker_edge.py QQQ SPY NQ ES
Report -> BOT/data/ml/reports/blocker_edge.json
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

from bot.strategy.orb_candidates import (load_state, T1, T2, ORS, ORE, CUT, EOD, DELAY,  # noqa: E402
                                         STRONG)
from bot.strategy.orb_state import ENTRY_STANDARD as ES  # noqa: E402
from bot.strategy.asset_config import asset_config  # noqa: E402

REPORT = ROOT / "BOT" / "data" / "ml" / "reports" / "blocker_edge.json"
OR_WIDTH_WIDE = 2.4


def run(d, chase: float, minw: float):
    import hs_backtest as B
    a = asset_config(str(d.attrs.get("sym", "")))
    return B.backtest(d, "tp2_full", "both", False, "orb", 0, T1, T2, ORS, ORE, 0.0, CUT, "close",
                      eod_min=EOD, stop_mode="struct", entry_delay=DELAY,
                      strong_body=STRONG, ft_confirm=True, dir_seq=True,
                      watch_live=ES.watch_gate,
                      cooldown_bars=a.cooldown_bars if a.cooldown_bars is not None else ES.cooldown_bars,
                      stale_bars=a.stale_bars if a.stale_bars is not None else ES.stale_bars,
                      retest_atr=a.retest_atr if a.retest_atr is not None else ES.retest_atr,
                      retest_mode=ES.retest_mode, min_pullback_atr=ES.min_pullback_atr,
                      pullback_timeout=ES.pullback_timeout, vol_confirm_x=ES.vol_confirm_x,
                      instant_aligned=a.instant_fill,
                      chase_atr=chase, min_or_width=minw)


def metrics(tr) -> dict:
    if not len(tr):
        return {"n": 0}
    r = tr["net_R"].to_numpy(float)
    wins, losses = r[r > 0], r[r <= 0]
    pf = float(wins.sum() / abs(losses.sum())) if len(losses) and losses.sum() != 0 else None
    eq = np.cumsum(r); cut = int(0.7 * len(r))
    return {"n": int(len(r)), "win_pct": round(100 * float((r > 0).mean()), 1),
            "avg_r": round(float(r.mean()), 3), "total_r": round(float(r.sum()), 1),
            "pf": round(pf, 2) if pf else None,
            "max_dd_r": round(float((eq - np.maximum.accumulate(eq)).min()), 1),
            "oos30": round(float(r[cut:].mean()), 3) if len(r) - cut > 5 else None}


def cohort(base, gated) -> dict:
    """Trades present in `base` but missing from `gated` (the BLOCKED cohort), by entry_time."""
    bk = set(gated["entry_time"].astype(str))
    blocked = base[~base["entry_time"].astype(str).isin(bk)]
    if not len(blocked):
        return {"n": 0}
    r = blocked["net_R"].to_numpy(float)
    return {"n": int(len(r)), "avg_r": round(float(r.mean()), 3),
            "total_r": round(float(r.sum()), 1),
            "win_pct": round(100 * float((r > 0).mean()), 1),
            "verdict": "blocker EARNS (cohort negative)" if r.mean() < 0 else
                       "blocker COSTS edge (cohort positive) — gauntlet a relax"}


def main(syms):
    out = {"generated_at": pd.Timestamp.now("UTC").isoformat(),
           "finding": "canonical run_backtest omitted chase_atr + min_or_width (live enforces "
                      "1.0 / 2.4) — every 07.x number included trades live refuses",
           "symbols": {}}
    REPORT.parent.mkdir(parents=True, exist_ok=True)
    for sym in syms:
        print(f"=== BLOCKER EDGE {sym} ===", flush=True)
        d = load_state(sym)
        A = run(d, 0.0, 0.0)
        B_ = run(d, ES.chase_atr, 0.0)
        C = run(d, 0.0, OR_WIDTH_WIDE)
        D = run(d, ES.chase_atr, OR_WIDTH_WIDE)
        res = {"A_canonical_no_gates": metrics(A), "B_plus_chase": metrics(B_),
               "C_plus_minwidth": metrics(C), "D_live_config": metrics(D),
               "chase_blocked_cohort": cohort(A, B_),
               "narrow_or_blocked_cohort": cohort(A, C),
               "live_vs_canonical_cohort": cohort(A, D)}
        out["symbols"][sym] = res
        for k in ("A_canonical_no_gates", "B_plus_chase", "C_plus_minwidth", "D_live_config"):
            m = res[k]
            print(f"  {k:22} n {m.get('n'):4} WR {m.get('win_pct')}% avg {m.get('avg_r')} "
                  f"PF {m.get('pf')} dd {m.get('max_dd_r')} oos {m.get('oos30')}", flush=True)
        for k in ("chase_blocked_cohort", "narrow_or_blocked_cohort"):
            c = res[k]
            print(f"  {k:24} n {c.get('n')} avg {c.get('avg_r')} -> {c.get('verdict', '—')}",
                  flush=True)
        REPORT.write_text(json.dumps(out, indent=1), encoding="utf-8")
    print(f"saved -> {REPORT}")


if __name__ == "__main__":
    main([s.upper() for s in (sys.argv[1:] or ["QQQ", "SPY", "NQ", "ES"])])
