"""FULL GAUNTLET x2 (user 2026-07-07): the two alive research candidates face the 7 checks.

  TRAIL — chandelier-trail exit on the canonical 07.7 entries (F82 standout: QQQ OOS PF 2.30 /
          SPY 2.04, ~50% WR — the expectancy-first profile).
  HG    — the Holy-Grail a-priori entry (F79: ADX>=30 + EMA20 pullback continuation), house exit.

The 7 checks (the swing-gauntlet convention): (1) net expectancy > 0 · (2) bootstrap 90% CI-low
> 0 · (3) BOTH sides positive · (4) >= 70% of years positive · (5) OOS-30% avg > 0 ·
(6) 2x-ALL-frictions expectancy > 0 (net2 = 2*net - gross) · (7) PF >= 1.2.
PASS = 7/7, no exceptions — a pass earns a module lineage; a fail goes to the graveyard.

    .venv/Scripts/python research/gauntlet_trail_hg.py
Report -> BOT/data/ml/reports/gauntlet_trail_hg.json
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

from bot.strategy.orb_candidates import load_state, T1, T2, EOD, CUT  # noqa: E402
from geometry_tune2 import run_exit  # noqa: E402  (canonical call, trail mode)
from fresh_entry import signals as hg_signals  # noqa: E402

REPORT = ROOT / "BOT" / "data" / "ml" / "reports" / "gauntlet_trail_hg.json"


def checks(tr: pd.DataFrame) -> dict:
    r = tr["net_R"].to_numpy(float)
    g = tr["gross_R"].to_numpy(float)
    if len(r) < 40:
        return {"pass": False, "n": int(len(r)), "why": "n < 40"}
    rng = np.random.default_rng(7)
    boots = [rng.choice(r, len(r), replace=True).mean() for _ in range(800)]
    ci_lo = float(np.percentile(boots, 5))
    years = pd.to_datetime(tr["entry_time"]).dt.year
    yr = pd.Series(r).groupby(years.values).sum()
    sides = tr.groupby("direction")["net_R"].mean()
    cut = int(0.7 * len(r))
    w, lo = r[r > 0], r[r <= 0]
    out = {
        "n": int(len(r)),
        "c1_exp": round(float(r.mean()), 3),
        "c2_ci_lo": round(ci_lo, 3),
        "c3_sides": {k: round(float(v), 3) for k, v in sides.items()},
        "c4_years_pos": f"{int((yr > 0).sum())}/{len(yr)}",
        "c5_oos30": round(float(r[cut:].mean()), 3) if len(r) - cut > 5 else None,
        "c6_stress2x": round(float((2 * r - g).mean()), 3),
        "c7_pf": round(float(w.sum() / abs(lo.sum())), 2) if len(lo) and lo.sum() else None,
    }
    ok = [out["c1_exp"] > 0, out["c2_ci_lo"] > 0,
          all(v > 0 for v in out["c3_sides"].values()) and len(out["c3_sides"]) == 2,
          (yr > 0).mean() >= 0.70,
          out["c5_oos30"] is not None and out["c5_oos30"] > 0,
          out["c6_stress2x"] > 0,
          (out["c7_pf"] or 0) >= 1.2]
    out["checks_passed"] = f"{sum(ok)}/7"
    out["pass"] = all(ok)
    return out


def main():
    import hs_backtest as B
    out = {"generated_at": pd.Timestamp.now("UTC").isoformat(), "candidates": {}}
    REPORT.parent.mkdir(parents=True, exist_ok=True)
    for sym in ("QQQ", "SPY"):
        d = load_state(sym)
        # TRAIL: canonical entries, chandelier exit
        res = checks(run_exit(d, "trail", 1.5, 4.0))
        out["candidates"][f"trail_{sym}"] = res
        print(f"TRAIL {sym}: {res.get('checks_passed')} pass={res['pass']} "
              f"exp {res.get('c1_exp')} ci {res.get('c2_ci_lo')} yrs {res.get('c4_years_pos')} "
              f"oos {res.get('c5_oos30')} 2x {res.get('c6_stress2x')} pf {res.get('c7_pf')}", flush=True)
        # HOLY GRAIL: a-priori entry, house exit
        el, es_ = hg_signals(d)
        tr = B.backtest(d, "tp2_full", "both", False, "ext", 0, T1, T2, eod_min=EOD,
                        tod_end=CUT, stop_mode="struct", ext_long=el, ext_short=es_)
        res = checks(tr)
        out["candidates"][f"hg_{sym}"] = res
        print(f"HG    {sym}: {res.get('checks_passed')} pass={res['pass']} "
              f"exp {res.get('c1_exp')} ci {res.get('c2_ci_lo')} yrs {res.get('c4_years_pos')} "
              f"oos {res.get('c5_oos30')} 2x {res.get('c6_stress2x')} pf {res.get('c7_pf')}", flush=True)
        REPORT.write_text(json.dumps(out, indent=1), encoding="utf-8")
    verdict = {k: v["pass"] for k, v in out["candidates"].items()}
    print("VERDICT:", verdict)
    print(f"saved -> {REPORT}")


if __name__ == "__main__":
    main()
