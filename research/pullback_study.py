"""PULLBACK VALIDATION — does enabling/tuning the WATCH->PULLBACK retest HOLD the goal metrics?

Finding (2026-07-08): the pullback is NOT broken — it is implemented in both the live FSM
(orb_state) and the engine (hs_backtest `chase_atr`/`retest_atr`). It just rarely fires because
it is OFF for equities (chase_atr=0) and set to 1.5xATR on NQ/MNQ, where a >1.5-ATR pre-fill
extension is uncommon. "Working on it while keeping the goal metrics" = sweep chase_atr in the
engine and confirm the expectancy/PF/WR/DD do not degrade before enabling it wider.

This runs the canonical backtest per symbol at chase_atr in {0 (off), 0.75, 1.0, 1.5} (with the
matching retest) and prints the goal metrics, so adoption is evidence-based (the research law: OOS
judges, gates never loosen).

    python research/pullback_study.py NQ QQQ SPY ES
Report -> BOT/data/ml/reports/pullback_study.json
"""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "engine"))
sys.path.insert(0, str(ROOT / "BOT"))
os.chdir(ROOT)

import hs_backtest as B  # noqa: E402
import hs_db  # noqa: E402
import hs_harness as H  # noqa: E402
import hs_validate as V  # noqa: E402

REPORT = ROOT / "BOT" / "data" / "ml" / "reports" / "pullback_study.json"
CHASE_GRID = (0.0, 0.75, 1.0, 1.5)          # 0 = pullback OFF (current equities)


def _metrics(tr) -> dict:
    r = tr["net_R"].to_numpy(float) if len(tr) else np.array([])
    if not len(r):
        return {"n": 0}
    return {"n": int(len(r)), "exp_R": round(float(r.mean()), 3), "pf": round(float(V.pf(r)), 2),
            "win_pct": round(100 * float((r > 0).mean()), 1), "maxdd_R": round(float(V.maxdd(r)), 1)}


def study(sym: str, tf: str = "5m") -> dict:
    con = hs_db.connect()
    bars = B._externals(con, hs_db.bars(con, tf, "full", sym=sym), sym)
    d = H.compute_state(bars, H.P()); d.attrs["sym"] = sym
    d = B.attach_mtf(con, sym, d)
    out = {"tf": tf, "grid": {}}
    for ch in CHASE_GRID:
        # canonical 07.7 entry + the pullback retest at chase=ch (retest 0.5xATR, edge target)
        tr = B.backtest(d, "orb", "both", False, "orb", 0, watch_live=True, dir_seq=True,
                        strong_body=0.15, cooldown_bars=2, stale_bars=12,
                        chase_atr=ch, retest_atr=(0.5 if ch > 0 else 0.0), retest_mode="edge")
        out["grid"][f"chase_{ch}"] = _metrics(tr)
    base = out["grid"].get("chase_0.0", {})
    # best pullback setting that HOLDS or beats the off-baseline on expectancy AND doesn't worsen DD
    holds = {k: v for k, v in out["grid"].items() if k != "chase_0.0" and v.get("n")
             and v.get("exp_R", -9) >= base.get("exp_R", 0) - 0.01
             and v.get("maxdd_R", -99) >= base.get("maxdd_R", -99) - 0.5}
    out["baseline_off"] = base
    out["pullback_holds_metrics"] = bool(holds)
    out["best_pullback"] = (max(holds.items(), key=lambda kv: kv[1].get("exp_R", -9))[0]
                            if holds else None)
    return out


def main(syms):
    out = {"generated_at": pd.Timestamp.now("UTC").isoformat(),
           "note": "chase_0.0 = pullback OFF (current equities). A setting that holds exp & DD is safe to enable.",
           "symbols": {}}
    REPORT.parent.mkdir(parents=True, exist_ok=True)
    for sym in syms:
        print(f"=== {sym} ===", flush=True)
        try:
            out["symbols"][sym] = study(sym)
        except Exception as e:
            out["symbols"][sym] = {"error": str(e)[:200]}
            print("  ERROR", str(e)[:200]); continue
        for k, v in out["symbols"][sym]["grid"].items():
            print(f"  {k}: n={v.get('n')} exp {v.get('exp_R')}R PF {v.get('pf')} "
                  f"WR {v.get('win_pct')}% DD {v.get('maxdd_R')}R", flush=True)
        b = out["symbols"][sym]
        print(f"  -> pullback holds metrics: {b['pullback_holds_metrics']} "
              f"(best {b['best_pullback']})", flush=True)
        REPORT.write_text(json.dumps(out, indent=1), encoding="utf-8")
    print("saved ->", REPORT)


if __name__ == "__main__":
    for s in (sys.stdout, sys.stderr):
        try:
            s.reconfigure(encoding="utf-8", errors="backslashreplace")
        except Exception:
            pass
    main([s.upper() for s in (sys.argv[1:] or ["NQ", "QQQ", "SPY", "ES"])])
