"""Backtest report matrix (AITP-001 §7 + §8 cost modeling) — the canonical entry sliced every way
that matters, plus a REALISTIC-COST STRESS including the frictions the base model skips.

Slices per symbol: year · macro regime · day-of-week · entry hour · side.
Cost stress: base → 2x slippage → +1 tick latency → +2 ticks latency → 90% partial fills
(fills that only get 90% of intended size keep FULL per-order costs — the honest direction).

    .venv/Scripts/python research/backtest_report.py QQQ SPY NQ ES
Report -> BOT/data/ml/reports/backtest_matrix.json (Training Lab panel, run kind=report).
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

REPORT = ROOT / "BOT" / "data" / "ml" / "reports" / "backtest_matrix.json"
# per-symbol friction units for the stress model (tick size, $/point, ticks of base slip)
FRICTION = {"NQ": (0.25, 20.0), "ES": (0.25, 50.0), "GC": (0.10, 100.0),
            "QQQ": (0.01, 1.0), "SPY": (0.01, 1.0)}


def _m(r: np.ndarray) -> dict:
    if not len(r):
        return {"n": 0}
    wins, losses = r[r > 0], r[r <= 0]
    pf = float(wins.sum() / abs(losses.sum())) if len(losses) and losses.sum() != 0 else None
    return {"n": int(len(r)), "win_pct": round(100 * float((r > 0).mean()), 1),
            "avg_r": round(float(r.mean()), 3), "total_r": round(float(r.sum()), 1),
            "pf": round(pf, 2) if pf else None}


def matrix(sym: str) -> dict:
    d = load_state(sym)
    tr = run_backtest(d).reset_index(drop=True)
    if not len(tr):
        return {"error": "no trades"}
    r = tr["net_R"].to_numpy(float)
    et = pd.to_datetime(tr["entry_time"])
    if et.dt.tz is None:
        et = et.dt.tz_localize("UTC")
    et = et.dt.tz_convert("America/New_York")
    out = {"overall": _m(r), "slices": {}}
    dims = {"year": et.dt.year.astype(str), "regime": tr["regime"].astype(str),
            "dow": et.dt.day_name().str[:3], "hour": et.dt.hour.astype(str).radd("h"),
            "side": tr["direction"].astype(str)}
    for dim, vals in dims.items():
        out["slices"][dim] = {str(k): _m(r[(vals == k).to_numpy()])
                              for k in sorted(vals.unique())}
    # ── cost stress (partial fills + latency): net_R degraded by extra frictions in R units ──
    tick, pv = FRICTION.get(sym.upper(), (0.01, 1.0))
    risk_pts = tr["risk_pts"].to_numpy(float)
    tick_r = np.where(risk_pts > 0, tick / risk_pts, 0.0)      # one tick expressed in R per trade
    gross = tr["gross_R"].to_numpy(float)
    base_cost = gross - r                                       # the model's existing cost in R
    stress = {
        "base": r,
        "slip_x2": gross - 2 * base_cost,
        "latency_1_tick": r - 2 * 1 * tick_r,                   # entry + exit each late by 1 tick
        "latency_2_ticks": r - 2 * 2 * tick_r,
        # 90% partial fill: only 90% of size earns R, but per-order costs don't shrink
        "partial_fill_90pct": 0.9 * gross - base_cost,
    }
    out["cost_stress"] = {k: _m(np.asarray(v, float)) for k, v in stress.items()}
    return out


def main(syms: list[str]) -> dict:
    prev = {}
    if REPORT.exists():
        try:
            prev = json.loads(REPORT.read_text(encoding="utf-8")).get("symbols", {})
        except Exception:
            prev = {}
    out = {"generated_at": pd.Timestamp.now("UTC").isoformat(), "symbols": prev}
    REPORT.parent.mkdir(parents=True, exist_ok=True)
    for sym in syms:
        print(f"=== REPORT {sym} ===", flush=True)
        try:
            out["symbols"][sym] = matrix(sym)
        except Exception as e:
            out["symbols"][sym] = {"error": str(e)[:200]}
            print(f"  ERROR {e}")
            continue
        s = out["symbols"][sym]
        print(f"  overall {s['overall']} | stress base {s['cost_stress']['base']['avg_r']} -> "
              f"2xslip {s['cost_stress']['slip_x2']['avg_r']} -> "
              f"lat2t {s['cost_stress']['latency_2_ticks']['avg_r']} -> "
              f"partial90 {s['cost_stress']['partial_fill_90pct']['avg_r']}", flush=True)
        REPORT.write_text(json.dumps(out, indent=1), encoding="utf-8")
    print(f"saved -> {REPORT}")
    return out


if __name__ == "__main__":
    main([s.upper() for s in (sys.argv[1:] or ["QQQ", "SPY", "NQ", "ES"])])
