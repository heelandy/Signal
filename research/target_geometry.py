"""TARGET-GEOMETRY STUDY — can the current entries deliver the ULTIMATE GOAL?

Goal (user 2026-07-05): win rate 85% · PF 1.8-1.9 · max adverse 45 TICKS on futures / $4 on
equities. The math forces the exit shape:  PF = WR·W / ((1-WR)·L)  →  W/L = 1.85·0.15/0.85 ≈ 0.33.
So the target must sit around ONE-THIRD of the stop — a high-win-rate scalp exit, the inverse of
the 4R-cap runner. A driftless random walk already wins  L/(W+L) ≈ 75%  at that geometry, so the
entry must contribute ~10 extra points of win probability AFTER costs to reach 85%.

This study keeps the CANONICAL entries and sweeps the exit: stop fixed at the user's adverse
budget (45 ticks futures / $4 equities), TP ∈ {0.25, 0.33, 0.40, 0.50, 0.75, 1.00} × stop,
first-touch walk (stop-first on same-bar ambiguity), EOD flat, honest per-side costs.

    .venv/Scripts/python research/target_geometry.py QQQ SPY NQ ES
Report -> BOT/data/ml/reports/target_geometry.json
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

REPORT = ROOT / "BOT" / "data" / "ml" / "reports" / "target_geometry.json"
TP_FRACS = (0.25, 0.33, 0.40, 0.50, 0.75, 1.00)
# (stop in instrument units, tick size, round-trip cost in units: 2 ticks slip + commission)
SPEC = {"NQ": (45 * 0.25, 0.25, 2 * 0.25 + 0.15),   # 11.25 pts stop; ~$3 comm ≈ 0.15 pt
        "ES": (45 * 0.25, 0.25, 2 * 0.25 + 0.06),   # $3 comm ≈ 0.06 pt on ES ($50/pt)
        "QQQ": (4.0, 0.01, 0.04),                    # $4 stop; ~2c slip + free comm
        "SPY": (4.0, 0.01, 0.04)}


def study(sym: str) -> dict:
    stop_u, tick, cost_u = SPEC[sym.upper()]
    d = load_state(sym)
    tr = run_backtest(d).reset_index(drop=True)
    # compare as datetime64[ns] on BOTH sides — pandas 3.0 stores bars as datetime64[us], so
    # int64 epochs come out in different units (µs vs ns) and searchsorted silently misses all
    ts64 = pd.to_datetime(d["ts"], utc=True).to_numpy("datetime64[ns]")
    h = d["high"].to_numpy(float); lo = d["low"].to_numpy(float); c = d["close"].to_numpy(float)
    et_date = pd.to_datetime(d["ts"]).dt.tz_convert("America/New_York").dt.date.to_numpy()
    entries = []
    for _, t in tr.iterrows():
        ets = pd.Timestamp(t["entry_time"])
        ets = ets.tz_localize("UTC") if ets.tz is None else ets.tz_convert("UTC")
        i = int(np.searchsorted(ts64, ets.as_unit("ns").to_datetime64()))
        if i < len(ts64):
            entries.append((i, 1 if t["direction"] == "long" else -1, float(t["entry_price"])))
    if not entries:
        return {"error": f"no trade timestamps matched the bar index ({len(tr)} trades)"}
    out = {"entries": len(entries), "stop_units": stop_u, "tick": tick,
           "round_trip_cost_units": cost_u, "grid": {}}
    for frac in TP_FRACS:
        tp_u = round(frac * stop_u, 4)
        rs = []
        for i, sign, entry in entries:
            sl = entry - sign * stop_u
            tp = entry + sign * tp_u
            res = None
            for k in range(i + 1, min(i + 400, len(c))):
                if et_date[k] != et_date[i]:
                    res = sign * (c[k - 1] - entry)
                    break
                adverse = lo[k] if sign == 1 else h[k]
                favor = h[k] if sign == 1 else lo[k]
                if sign * (adverse - sl) <= 0:      # stop first on ambiguity (conservative)
                    res = -stop_u; break
                if sign * (favor - tp) >= 0:
                    res = tp_u; break
            if res is None:
                res = sign * (c[min(i + 399, len(c) - 1)] - entry)
            rs.append((res - cost_u) / stop_u)      # net R in stop units
        r = np.asarray(rs, float)
        wins, losses = r[r > 0], r[r <= 0]
        pf = float(wins.sum() / abs(losses.sum())) if len(losses) and losses.sum() != 0 else None
        eq = np.cumsum(r)
        dd_r = float((eq - np.maximum.accumulate(eq)).min())
        out["grid"][f"tp_{frac:.2f}x"] = {
            "tp_units": tp_u, "n": int(len(r)),
            "win_pct": round(100 * float((r > 0).mean()), 1),
            "pf": round(pf, 2) if pf else None,
            "avg_r": round(float(r.mean()), 4), "total_r": round(float(r.sum()), 1),
            "max_dd_r": round(dd_r, 1),
            "max_dd_units": round(dd_r * stop_u, 2),
            "meets_goal": bool((r > 0).mean() >= 0.85 and pf and 1.8 <= pf)}
    return out


def main(syms):
    out = {"generated_at": pd.Timestamp.now("UTC").isoformat(),
           "goal": {"win_rate": 0.85, "pf": [1.8, 1.9], "stop": "45 ticks futures / $4 equities",
                    "implied_tp_over_sl": 0.33,
                    "random_walk_baseline_wr_at_0.33": 0.754},
           "symbols": {}}
    REPORT.parent.mkdir(parents=True, exist_ok=True)
    for sym in syms:
        print(f"=== GEOMETRY {sym} ===", flush=True)
        try:
            out["symbols"][sym] = study(sym)
        except Exception as e:
            out["symbols"][sym] = {"error": str(e)[:200]}
            print(f"  ERROR {e}")
            continue
        for k, v in out["symbols"][sym]["grid"].items():
            print(f"  {k}: WR {v['win_pct']}% PF {v['pf']} avg {v['avg_r']:+.4f}R "
                  f"dd {v['max_dd_units']}u {'<<< MEETS GOAL' if v['meets_goal'] else ''}", flush=True)
        REPORT.write_text(json.dumps(out, indent=1), encoding="utf-8")
    print(f"saved -> {REPORT}")
    return out


if __name__ == "__main__":
    main([s.upper() for s in (sys.argv[1:] or ["QQQ", "SPY", "NQ", "ES"])])
