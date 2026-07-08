"""SWING FULL GAUNTLET — the 7-check adoption test for the daily swing module (mirrors the
intraday gauntlet's philosophy; a module trades live only after passing ALL checks here AND its
own approval ladder `swing-1d-0.x`).

Checks (per symbol):
  1. min_trades   — n >= 60 (enough evidence)
  2. positive     — full-history avg R > 0
  3. oos_positive — last-30% avg R > 0 (the judge window)
  4. slip_2x      — still positive with DOUBLED round-trip costs
  5. years        — >= 60% of calendar years net-positive over a >= 6-year span
  6. dd_sane      — max drawdown > -20R
  7. halves       — IS avg and OOS avg BOTH positive (no single-period fluke)

    .venv/Scripts/python research/swing_gauntlet.py QQQ SPY
Report -> BOT/data/ml/reports/swing_gauntlet.json
"""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "BOT"))
sys.path.insert(0, str(ROOT / "engine"))
sys.path.insert(0, str(ROOT / "research"))
os.chdir(ROOT)

from swing_rules import study  # noqa: E402

REPORT = ROOT / "BOT" / "data" / "ml" / "reports" / "swing_gauntlet.json"


def gauntlet(sym: str, mode: str = "pullback") -> dict:
    base = study(sym, mode=mode)
    if "error" in base:
        return base
    stress = study(sym, cost_mult=2.0, mode=mode)
    yrs = base.get("by_year", {})
    pos_years = sum(1 for v in yrs.values() if v > 0)
    checks = {
        "min_trades_60": base["n"] >= 60,
        "positive": base["avg_r"] > 0,
        "oos_positive": base["oos_avg_r"] is not None and base["oos_avg_r"] > 0,
        "slip_2x": stress["avg_r"] > 0 and (stress["oos_avg_r"] or 0) > 0,
        "years": len(yrs) >= 6 and pos_years / max(len(yrs), 1) >= 0.6,
        "dd_sane": base["max_dd_r"] > -20,
        "halves": base["is_avg_r"] > 0 and (base["oos_avg_r"] or 0) > 0,
    }
    return {"result": base, "stress_2x": {k: stress[k] for k in ("avg_r", "oos_avg_r", "pf")},
            "years_positive": f"{pos_years}/{len(yrs)}",
            "checks": checks, "passed": all(checks.values()),
            "score": f"{sum(checks.values())}/7"}


def main(syms):
    out = {"generated_at": pd.Timestamp.now("UTC").isoformat(),
           "module": "equities_swing (daily EMA20>50 pullback-reclaim, 1.5ATR/2R/20-bar)",
           "symbols": {}}
    REPORT.parent.mkdir(parents=True, exist_ok=True)
    for sym in syms:
        mode = "breakout" if sym.upper() in ("NQ", "MNQ", "ES", "GC") else "pullback"
        print(f"=== SWING GAUNTLET {sym} ({mode}) ===", flush=True)
        out["symbols"][sym] = {**gauntlet(sym, mode), "mode": mode}
        s = out["symbols"][sym]
        if "checks" in s:
            fails = [k for k, v in s["checks"].items() if not v]
            print(f"  {s['score']} {'PASS — adoption candidate' if s['passed'] else 'FAIL: ' + str(fails)}")
            print(f"  base avg {s['result']['avg_r']} OOS {s['result']['oos_avg_r']} "
                  f"dd {s['result']['max_dd_r']} | 2x-cost avg {s['stress_2x']['avg_r']} "
                  f"| years+ {s['years_positive']}", flush=True)
        else:
            print(f"  ERROR {s.get('error')}")
        REPORT.write_text(json.dumps(out, indent=1), encoding="utf-8")
    print(f"saved -> {REPORT}")


if __name__ == "__main__":
    main([s.upper() for s in (sys.argv[1:] or ["QQQ", "SPY"])])
