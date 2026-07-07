"""WORKER L2 CONFIRMATION — use the depth archive to CONFIRM the worker specs before real data
(user 2026-07-07: "use the l2/l3 data we had for training and confirmation; after we can remove
that information and wait for the real data").

For each worker cell (Q: QQQ 0.40x+slope · S: SPY 0.33x · N: NQ 0.30x+early), take its trades
inside the depth-covered window and read the L2 FLOW at the entry minute: does the book agree
with the fire, and do flow-agreed trades out-earn flow-opposed ones? Depth exists for QQQ only
(the archive is XNAS) — S and N report "no depth coverage" honestly rather than borrowing QQQ's
book.

HONESTY: the window is ~4 weeks — single-digit trade counts. This is CONFIRMATION READING, not
adoption evidence; the report says so on every line.

    .venv/Scripts/python research/worker_l2_confirm.py
Report -> BOT/data/ml/reports/worker_l2_confirm.json
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

from bot.strategy.orb_candidates import load_state  # noqa: E402
from bot.ml.registry import FeatureStore  # noqa: E402
from worker_cohorts import masks_for, run_cell  # noqa: E402

REPORT = ROOT / "BOT" / "data" / "ml" / "reports" / "worker_l2_confirm.json"
WORKERS = {"QQQ": {"b": 0.40, "tier": "slope_strong"},
           "SPY": {"b": 0.33, "tier": None},
           "NQ":  {"b": 0.30, "tier": "early_only"}}


def main():
    out = {"generated_at": pd.Timestamp.now("UTC").isoformat(),
           "note": "CONFIRMATION READ on ~4wk of depth — not adoption evidence. The archive is "
                   "temporary scaffolding (see data/mbo_bars_manifest.json for the removal seam).",
           "workers": {}}
    REPORT.parent.mkdir(parents=True, exist_ok=True)
    for sym, w in WORKERS.items():
        try:
            l2 = FeatureStore().load(f"l2feat_{sym}", "v1")
        except Exception:
            out["workers"][sym] = {"verdict": "no depth coverage for this symbol (XNAS archive "
                                              "is QQQ-only) — waits for real data"}
            print(f"{sym}: no depth store", flush=True)
            continue
        l2["minute"] = pd.to_datetime(l2["minute"], utc=True)
        d = load_state(sym)
        mask = masks_for(d).get(w["tier"]) if w["tier"] else None
        tr = run_cell(d, w["b"], skip_mask=mask)
        tr = tr.copy()
        tr["minute"] = pd.to_datetime(tr["entry_time"], utc=True).dt.floor("min")
        j = tr.merge(l2[["minute", "l2_flow_imb", "l2_quote_rate"]], on="minute", how="inner")
        if not len(j):
            out["workers"][sym] = {"verdict": "0 worker trades inside the depth window"}
            print(f"{sym}: no trades in window", flush=True)
            continue
        sgn = np.where(j["direction"] == "long", 1, -1)
        agreed = np.sign(j["l2_flow_imb"].to_numpy(float)) == sgn
        def _s(rs):
            r = np.asarray(rs, float)
            return {"n": int(len(r)), "wr": round(100 * float((r > 0).mean()), 1) if len(r) else None,
                    "avg_r": round(float(r.mean()), 3) if len(r) else None}
        res = {"trades_in_window": int(len(j)),
               "flow_agreed": _s(j["net_R"][agreed]),
               "flow_opposed": _s(j["net_R"][~agreed]),
               "confirmation": None}
        a, o = res["flow_agreed"], res["flow_opposed"]
        if a["n"] and o["n"]:
            res["confirmation"] = bool(a["avg_r"] > o["avg_r"])
        res["verdict"] = ("book AGREES with the worker's winners (directional confirm)"
                          if res["confirmation"] else
                          "book does NOT separate winners here (or n too small)" )
        out["workers"][sym] = res
        print(f"{sym}: window trades {len(j)} | agreed {a} | opposed {o} -> {res['verdict']}",
              flush=True)
    REPORT.write_text(json.dumps(out, indent=1), encoding="utf-8")
    print(f"saved -> {REPORT}")


if __name__ == "__main__":
    main()
