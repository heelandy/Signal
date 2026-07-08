"""GOAL-DRIVEN TARGET GEOMETRY — TP1 fixed at 1.5R, SOLVE TP2 from the goal (user 2026-07-08).

The user wants the geometry to CALCULATE the target from the goal, not hardcode 4R. TP1 = 1.5R is
fixed; this sweeps a PARTIAL-EXIT model — scale out fraction `f` of the position at TP1, ride the
remainder to TP2 = m x R (m swept), original stop — and finds the (m, f) that lands inside the
goal band per symbol.

Why a scale-out lifts win-rate: a trade that tags TP1 then stops nets  f*1.5 - (1-f)*1  R, which is
POSITIVE for f >= 0.4 (f=0.5 -> +0.25R). So banking at 1.5R turns would-be losers into small wins
(win-rate up) while the runner to TP2 carries the profit factor. That is the mechanism behind
WR 75-85 with PF 1.6-1.8.

    python research/target_from_goal.py QQQ SPY NQ ES
Report -> BOT/data/ml/reports/target_from_goal.json
"""
from __future__ import annotations

import json
import os
import sys
from itertools import product
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "BOT"))
sys.path.insert(0, str(ROOT / "engine"))
os.chdir(ROOT)

from bot.strategy.orb_candidates import load_state, run_backtest  # noqa: E402

REPORT = ROOT / "BOT" / "data" / "ml" / "reports" / "target_from_goal.json"
TP1_R = 1.5                                   # FIXED (user)
TP2_MULTS = (2.0, 2.5, 3.0, 3.5, 4.0, 5.0, 6.0)
SPLITS = (0.3, 0.4, 0.5, 0.6, 0.7)            # fraction banked at TP1
BAND = {"win": (75.0, 85.0), "pf": (1.6, 1.8), "dd_r": 11.0}   # goal (DD in R at 1u/trade)


def _walk_trade(i, sign, entry, risk, m, f, ts_date, h, lo, c):
    """Blended R for a scale-out: bank f at TP1=1.5R (then remainder rides to TP2=m*R on the
    ORIGINAL stop), else full stop / EOD close. First-touch, stop-first on same-bar ambiguity."""
    sl = entry - sign * risk
    tp1 = entry + sign * TP1_R * risk
    tp2 = entry + sign * m * risk
    tp1_hit = False
    for k in range(i + 1, min(i + 400, len(c))):
        if ts_date[k] != ts_date[i]:                          # EOD force-flat
            close_r = sign * (c[k - 1] - entry) / risk
            return (f * TP1_R + (1 - f) * close_r) if tp1_hit else close_r
        adverse = lo[k] if sign == 1 else h[k]
        favor = h[k] if sign == 1 else lo[k]
        if sign * (adverse - sl) <= 0:                        # stop (conservative on ambiguity)
            return (f * TP1_R + (1 - f) * (-1.0)) if tp1_hit else -1.0
        if not tp1_hit and sign * (favor - tp1) >= 0:
            tp1_hit = True
        if tp1_hit and sign * (favor - tp2) >= 0:             # runner reaches TP2
            return f * TP1_R + (1 - f) * m
    close_r = sign * (c[min(i + 399, len(c) - 1)] - entry) / risk
    return (f * TP1_R + (1 - f) * close_r) if tp1_hit else close_r


CLOSER_TARGETS = (0.33, 0.40, 0.45, 0.50, 0.60, 0.75, 1.00)   # single target as a fraction of 1R stop


def _walk_single(i, sign, entry, risk, T, ts_date, h, lo, c):
    """First-touch single target T*R (stop 1R). Win = reaches T before stop. The high-WR scalp."""
    sl = entry - sign * risk
    tp = entry + sign * T * risk
    for k in range(i + 1, min(i + 400, len(c))):
        if ts_date[k] != ts_date[i]:
            return sign * (c[k - 1] - entry) / risk
        adverse = lo[k] if sign == 1 else h[k]
        favor = h[k] if sign == 1 else lo[k]
        if sign * (adverse - sl) <= 0:
            return -1.0
        if sign * (favor - tp) >= 0:
            return T
    return sign * (c[min(i + 399, len(c) - 1)] - entry) / risk


def study(sym: str) -> dict:
    d = load_state(sym)
    tr = run_backtest(d).reset_index(drop=True)
    ts64 = pd.to_datetime(d["ts"], utc=True).to_numpy("datetime64[ns]")
    h, lo, c = d["high"].to_numpy(float), d["low"].to_numpy(float), d["close"].to_numpy(float)
    ts_date = pd.to_datetime(d["ts"]).dt.tz_convert("America/New_York").dt.date.to_numpy()
    trades = []
    for _, t in tr.iterrows():
        risk = float(t.get("risk_pts", 0))
        if risk <= 0:
            continue
        ets = pd.Timestamp(t["entry_time"])
        ets = ets.tz_localize("UTC") if ets.tz is None else ets.tz_convert("UTC")
        i = int(np.searchsorted(ts64, ets.as_unit("ns").to_datetime64()))
        if i < len(ts64):
            trades.append((i, 1 if t["direction"] == "long" else -1, float(t["entry_price"]), risk))
    if len(trades) < 30:
        return {"error": f"only {len(trades)} trades"}
    # CLOSER single-target sweep (the high-WR path — what actually reaches the goal band)
    closer = []
    for T in CLOSER_TARGETS:
        r = np.array([_walk_single(i, s, e, rk, T, ts_date, h, lo, c) for i, s, e, rk in trades])
        wins, losses = r[r > 0], r[r <= 0]
        pf = float(wins.sum() / abs(losses.sum())) if losses.sum() < 0 else None
        eq = np.cumsum(r); dd = float(-(eq - np.maximum.accumulate(eq)).min())
        win = round(100 * float((r > 0).mean()), 1)
        closer.append({"target_R": T, "win_pct": win, "pf": round(pf, 2) if pf else None,
                       "expectancy_R": round(float(r.mean()), 3), "max_dd_r": round(dd, 1),
                       "in_band": bool(BAND["win"][0] <= win <= BAND["win"][1] and pf is not None
                                       and BAND["pf"][0] <= pf <= BAND["pf"][1] and dd <= BAND["dd_r"])})
    closer.sort(key=lambda x: (not x["in_band"], -(x["expectancy_R"] or -9)))
    cells = []
    for m, f in product(TP2_MULTS, SPLITS):
        r = np.array([_walk_trade(i, s, e, rk, m, f, ts_date, h, lo, c) for i, s, e, rk in trades])
        wins, losses = r[r > 0], r[r <= 0]
        pf = float(wins.sum() / abs(losses.sum())) if losses.sum() < 0 else None
        eq = np.cumsum(r)
        dd = float(-(eq - np.maximum.accumulate(eq)).min())
        win = round(100 * float((r > 0).mean()), 1)
        in_band = (BAND["win"][0] <= win <= BAND["win"][1] and pf is not None
                   and BAND["pf"][0] <= pf <= BAND["pf"][1] and dd <= BAND["dd_r"])
        cells.append({"tp1_R": TP1_R, "tp2_R": m, "scale_out_at_tp1": f, "n": int(len(r)),
                      "win_pct": win, "pf": round(pf, 2) if pf else None,
                      "avg_r": round(float(r.mean()), 3), "expectancy_R": round(float(r.mean()), 3),
                      "max_dd_r": round(dd, 1), "in_band": bool(in_band)})
    # rank: in-band first, then by expectancy
    cells.sort(key=lambda x: (not x["in_band"], -(x["avg_r"] or -9)))
    best = next((x for x in cells if x["in_band"]), cells[0])
    closer_best = next((x for x in closer if x["in_band"]), closer[0])
    return {"trades": len(trades), "scale_out_best": best, "in_band_count": sum(c["in_band"] for c in cells),
            "closer_target_best": closer_best, "closer_grid": closer, "top": cells[:5]}


def main(syms):
    out = {"generated_at": pd.Timestamp.now("UTC").isoformat(), "tp1_R_fixed": TP1_R,
           "goal": BAND, "note": "TP1=1.5R fixed; TP2 (tp2_R) + scale_out_at_tp1 SOLVED from the goal",
           "symbols": {}}
    REPORT.parent.mkdir(parents=True, exist_ok=True)
    for sym in syms:
        print(f"=== {sym} ===", flush=True)
        try:
            out["symbols"][sym] = study(sym)
        except Exception as e:
            out["symbols"][sym] = {"error": str(e)[:200]}
            print("  ERROR", e); continue
        b = out["symbols"][sym].get("scale_out_best", {})
        cb = out["symbols"][sym].get("closer_target_best", {})
        print(f"  RUNNER (TP1=1.5R + TP2={b.get('tp2_R')}R, scale {b.get('scale_out_at_tp1')}): "
              f"WR {b.get('win_pct')} PF {b.get('pf')} exp {b.get('avg_r')}R  {'IN-BAND' if b.get('in_band') else '(low WR)'}", flush=True)
        print(f"  CLOSER (single target {cb.get('target_R')}R, stop 1R): "
              f"WR {cb.get('win_pct')} PF {cb.get('pf')} exp {cb.get('expectancy_R')}R DD {cb.get('max_dd_r')}R"
              f"  {'<<< IN-BAND' if cb.get('in_band') else '(closest)'}", flush=True)
        REPORT.write_text(json.dumps(out, indent=1), encoding="utf-8")
    print("saved ->", REPORT)


if __name__ == "__main__":
    main([s.upper() for s in (sys.argv[1:] or ["QQQ", "SPY", "NQ", "ES"])])
