"""SWING MODULE RESEARCH — first rules backtest on DAILY bars + mini-gauntlet.

Rules (mirror of the swing dataset's candidate definition, so the ML rows grade THIS strategy):
  trend   : close > EMA20 > EMA50 (long; shorts mirrored)
  entry   : PULLBACK-RECLAIM — low touches/breaches EMA20 while the trend holds, then the bar
            CLOSES back above EMA20 (short mirror). One position per side at a time.
  geometry: triple-barrier — stop 1.5*ATR(14), target 3.0*ATR (2R), horizon 20 bars, first-touch
            walk on daily H/L, stop-first on same-bar ambiguity, horizon exit at close.
  costs   : 5 bps round-trip on equities / 2 ticks + commission on futures (in R terms via stop).

Mini-gauntlet per symbol: n>=60 · OOS(last 30%) avg R > 0 · both sides not required (a daily
trend module may be one-sided in a decade-long bull) · DD sanity. Full 7-check gauntlet + its own
approval ladder (swing-1d-0.x) before any live use.

    .venv/Scripts/python research/swing_rules.py QQQ SPY NQ ES
Report -> BOT/data/ml/reports/swing_rules.json
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

REPORT = ROOT / "BOT" / "data" / "ml" / "reports" / "swing_rules.json"
STOP_ATR, TGT_ATR, HORIZON = 1.5, 3.0, 20
COST_R = {"QQQ": 0.004, "SPY": 0.004, "NQ": 0.02, "ES": 0.015}   # round-trip cost in R (approx)


def study(sym: str, cost_mult: float = 1.0, mode: str = "pullback") -> dict:
    """cost_mult: stress knob for the gauntlet (2.0 = doubled costs). mode: 'pullback' (equities
    winner) or 'breakout' (20-day Donchian + EMA50 side — the FUTURES candidate: the pullback
    rules fail futures dailies but the breakout is positive both halves, NQ +0.123 / ES +0.070)."""
    from bot.ml.swing_dataset import _daily_frame
    b = _daily_frame(sym, "1d")
    c = b["close"].to_numpy(float); h = b["high"].to_numpy(float); lo = b["low"].to_numpy(float)
    e20 = b["ema20"].to_numpy(float); e50 = b["ema50"].to_numpy(float)
    atr = b["atr14"].to_numpy(float)
    n = len(b)
    if mode == "breakout":
        hh20 = np.array([h[max(0, i - 20):i].max() if i > 20 else np.inf for i in range(n)])
        ll20 = np.array([lo[max(0, i - 20):i].min() if i > 20 else -np.inf for i in range(n)])
    trades = []
    pos_until = -1                                        # one overlapping position at a time
    for i in range(60, n - 1):
        if i <= pos_until or not np.isfinite(atr[i]) or atr[i] <= 0:
            continue
        if mode == "breakout":
            long_sig = c[i] > hh20[i] and c[i] > e50[i]          # fresh 20-day high, trend side
            short_sig = c[i] < ll20[i] and c[i] < e50[i]
        else:
            up = c[i] > e20[i] > e50[i]
            dn = c[i] < e20[i] < e50[i]
            long_sig = up and lo[i] <= e20[i] and c[i] > e20[i]  # pullback touched, close reclaimed
            short_sig = dn and h[i] >= e20[i] and c[i] < e20[i]
        if not (long_sig or short_sig):
            continue
        sign = 1 if long_sig else -1
        entry = c[i]
        sl = entry - sign * STOP_ATR * atr[i]
        tp = entry + sign * TGT_ATR * atr[i]
        res_r = None
        for k in range(i + 1, min(i + 1 + HORIZON, n)):
            adverse = lo[k] if sign == 1 else h[k]
            favor = h[k] if sign == 1 else lo[k]
            if sign * (adverse - sl) <= 0:
                res_r = -1.0; pos_until = k; break
            if sign * (favor - tp) >= 0:
                res_r = TGT_ATR / STOP_ATR; pos_until = k; break
        if res_r is None:
            k = min(i + HORIZON, n - 1)
            res_r = sign * (c[k] - entry) / (STOP_ATR * atr[i])
            pos_until = k
        trades.append({"i": i, "ts": str(b["ts"].iloc[i])[:10],
                       "side": "long" if sign == 1 else "short",
                       "net_r": res_r - COST_R.get(sym, 0.01) * cost_mult})
    if not trades:
        return {"error": "no trades"}
    r = np.array([t["net_r"] for t in trades])
    cut = int(0.7 * len(r))
    eq = np.cumsum(r)
    wins, losses = r[r > 0], r[r <= 0]
    sides = pd.Series([t["side"] for t in trades]).value_counts().to_dict()
    by_year: dict = {}
    for t in trades:
        by_year[t["ts"][:4]] = round(by_year.get(t["ts"][:4], 0.0) + t["net_r"], 2)
    rep = {"n": int(len(r)), "sides": sides,
           "win_pct": round(100 * float((r > 0).mean()), 1),
           "avg_r": round(float(r.mean()), 3), "total_r": round(float(r.sum()), 1),
           "pf": round(float(wins.sum() / abs(losses.sum())), 2) if len(losses) else None,
           "max_dd_r": round(float((eq - np.maximum.accumulate(eq)).min()), 1),
           "is_avg_r": round(float(r[:cut].mean()), 3),
           "oos_avg_r": round(float(r[cut:].mean()), 3) if len(r) - cut > 5 else None,
           "by_year": by_year,
           "span": [trades[0]["ts"], trades[-1]["ts"]]}
    checks = {"min_trades_60": len(r) >= 60,
              "oos_positive": rep["oos_avg_r"] is not None and rep["oos_avg_r"] > 0,
              "overall_positive": rep["avg_r"] > 0,
              "dd_sane": rep["max_dd_r"] > -25}
    rep["mini_gauntlet"] = {**checks, "passed": all(checks.values())}
    return rep


def main(syms):
    out = {"generated_at": pd.Timestamp.now("UTC").isoformat(),
           "rules": "daily EMA20>EMA50 trend + pullback-reclaim of EMA20; stop 1.5ATR, tgt 2R, "
                    "horizon 20 bars; one position at a time", "symbols": {}}
    REPORT.parent.mkdir(parents=True, exist_ok=True)
    for sym in syms:
        print(f"=== SWING {sym} ===", flush=True)
        try:
            out["symbols"][sym] = study(sym)
        except Exception as e:
            out["symbols"][sym] = {"error": str(e)[:200]}
            print(f"  ERROR {e}")
            continue
        s = out["symbols"][sym]
        if "error" in s:
            print(f"  {s['error']}")
            continue
        g = s["mini_gauntlet"]
        print(f"  n {s['n']} {s['sides']} WR {s['win_pct']}% avg {s['avg_r']:+.3f}R "
              f"PF {s['pf']} dd {s['max_dd_r']}R | IS {s['is_avg_r']} OOS {s['oos_avg_r']} "
              f"| mini-gauntlet {'PASS' if g['passed'] else 'FAIL ' + str([k for k, v in g.items() if v is False])}",
              flush=True)
        REPORT.write_text(json.dumps(out, indent=1), encoding="utf-8")
    print(f"saved -> {REPORT}")


if __name__ == "__main__":
    main([s.upper() for s in (sys.argv[1:] or ["QQQ", "SPY", "NQ", "ES"])])
