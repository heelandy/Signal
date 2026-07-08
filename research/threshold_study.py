"""THRESHOLD-USAGE STUDY — is a sub-gate model already useful as a TOP-BUCKET FILTER?

Even an uncalibrated 0.55-AUC model can add expectancy if trading only its highest-confidence
candidates beats trading everything. This study retrains the best pooled model with purged
walk-forward, then evaluates OUT-OF-SAMPLE expected R at P(win) cutoffs — trades kept, avg R,
total R, and the lift vs taking every rule-valid trade.

    .venv/Scripts/python research/threshold_study.py ALL
Report -> BOT/data/ml/reports/threshold_study.json (Training Lab reads it; run kind=threshold).
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

from bot.ml.dataset import build_pooled, load_or_build, to_xy       # noqa: E402
from bot.ml.models import model_zoo, IsotonicCalibrator            # noqa: E402
from bot.ml.validation import purged_walk_forward                  # noqa: E402

REPORT = ROOT / "BOT" / "data" / "ml" / "reports" / "threshold_study.json"
CUTS = (0.35, 0.40, 0.45, 0.50, 0.55, 0.60)


def main(sym: str = "ALL") -> dict:
    df = build_pooled() if sym.upper() == "ALL" else load_or_build(sym)
    X, y, net_r, _ = to_xy(df)
    zoo = model_zoo()
    best_name, best_auc, best_wf = None, -1, None
    for name, factory in zoo.items():
        wf = purged_walk_forward(X, y, factory, n_splits=5, embargo=5)
        if wf["oos_auc"] == wf["oos_auc"] and wf["oos_auc"] > best_auc:
            best_name, best_auc, best_wf = name, wf["oos_auc"], wf
    wf = best_wf
    calib = IsotonicCalibrator().fit(wf["oos_p"], wf["oos_y"])
    p = np.clip(calib.transform(wf["oos_p"]), 0, 1)
    r = net_r[wf["oos_idx"]]
    base = {"n": int(len(r)), "avg_r": round(float(r.mean()), 3),
            "total_r": round(float(r.sum()), 1)}
    rows = []
    for cut in CUTS:
        m = p >= cut
        if m.sum() < 25:
            rows.append({"cutoff": cut, "n": int(m.sum()), "note": "too few trades"})
            continue
        rows.append({"cutoff": cut, "n": int(m.sum()),
                     "kept_pct": round(100 * float(m.mean()), 1),
                     "avg_r": round(float(r[m].mean()), 3),
                     "total_r": round(float(r[m].sum()), 1),
                     "avg_r_lift": round(float(r[m].mean() - r.mean()), 3)})
    out = {"generated_at": pd.Timestamp.now("UTC").isoformat(), "sym": sym.upper(),
           "model": best_name, "oos_auc": best_auc, "oos_samples": base,
           "cutoffs": rows,
           "verdict": ("USEFUL AS FILTER — best cutoff lifts avg R OOS"
                       if any(x.get("avg_r_lift", 0) and x["avg_r_lift"] > 0.05 and x["n"] >= 50
                              for x in rows)
                       else "no reliable top-bucket lift yet")}
    REPORT.parent.mkdir(parents=True, exist_ok=True)
    REPORT.write_text(json.dumps(out, indent=1), encoding="utf-8")
    print(f"model {best_name} OOS AUC {best_auc} | base {base}")
    for x in rows:
        print(f"  cut {x['cutoff']}: {x}")
    print(f"VERDICT: {out['verdict']}\nsaved -> {REPORT}")
    return out


if __name__ == "__main__":
    main(sys.argv[1] if len(sys.argv) > 1 else "ALL")
