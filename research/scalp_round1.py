"""SCALPING ROUND 1 — feasibility A/B on real depth data (the scalp module was spec_only,
"blocked on L2"; unblocked 2026-07-07: the MBO archive gives BOTH the 1m bars and the minute
L2 flow features over the same window).

Base strategy (the registered spec_only candidate): 1m MICRO-ORB — opening range 09:30-09:35 ET,
first 1m CLOSE beyond the range fires (long above / short below), stop = opposite OR edge,
TP = 1x the OR width (1R symmetric), EOD-flat 10:30 (scalps don't marinate), one trade per side
per day. Costs: commission-free equity, 1-tick ($0.01) slippage per side; 2-tick stress shown.

The A/B (the whole point): does requiring the minute's L2 FLOW to agree improve it?
  filter F1: sign(l2_flow_imb at the break minute) matches the trade direction
  filter F2: F1 AND l2_quote_rate >= its trailing 30-min median (activity, not a dead tape)

HONESTY: ~22 trading days of depth — this is FEASIBILITY, not adoption evidence. No IS/OOS
split is meaningful at this n; the verdict is directional only and says so.

    .venv/Scripts/python research/scalp_round1.py QQQ
Report -> BOT/data/ml/reports/scalp_round1.json
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
os.chdir(ROOT)

REPORT = ROOT / "BOT" / "data" / "ml" / "reports" / "scalp_round1.json"
ET = "America/New_York"
SLIP = 0.01                      # per side; stress doubles it


def run(sym: str = "QQQ"):
    bars = pd.read_parquet(ROOT / "data" / f"{sym.lower()}_continuous_1m.parquet")
    from bot.ml.registry import FeatureStore
    l2 = FeatureStore().load(f"l2feat_{sym}", "v1")
    l2["minute"] = pd.to_datetime(l2["minute"], utc=True)
    et = pd.to_datetime(bars["ts_et"]).dt.tz_convert(ET)
    bars = bars.assign(_et=et, _d=et.dt.date, _m=et.dt.hour * 60 + et.dt.minute)
    lo, hi = l2["minute"].min(), l2["minute"].max()
    bars = bars.assign(_utc=pd.to_datetime(bars["ts_et"]).dt.tz_convert("UTC"))
    bars = bars[(bars["_utc"] >= lo) & (bars["_utc"] <= hi)].copy()   # depth-covered window only
    bars["minute"] = bars["_utc"].dt.floor("min")
    bars = bars.merge(l2[["minute", "l2_flow_imb", "l2_quote_rate"]], on="minute", how="left")
    bars["_roll_qr"] = bars["l2_quote_rate"].rolling(30, min_periods=10).median()
    trades = {"base": [], "f1": [], "f2": []}
    for day, g in bars.groupby("_d"):
        g = g.sort_values("_et").reset_index(drop=True)
        orr = g[(g["_m"] >= 570) & (g["_m"] < 575)]
        if len(orr) < 4:
            continue
        orh, orl = float(orr["high"].max()), float(orr["low"].min())
        width = orh - orl
        if width <= 0:
            continue
        scan = g[(g["_m"] >= 575) & (g["_m"] < 630)].reset_index(drop=True)
        done = set()
        for i, row in scan.iterrows():
            for side, lvl, stop in (("long", orh, orl), ("short", orl, orh)):
                if side in done:
                    continue
                brk = row["close"] > orh if side == "long" else row["close"] < orl
                if not brk:
                    continue
                done.add(side)
                sgn = 1 if side == "long" else -1
                entry = float(row["close"]) + sgn * SLIP
                tp = entry + sgn * width
                st = stop - sgn * SLIP
                risk = abs(entry - st)
                if risk <= 0:
                    continue
                after = scan.iloc[i + 1:]
                r = None
                for _, a in after.iterrows():
                    if (a["low"] <= st if side == "long" else a["high"] >= st):
                        r = -1.0
                        break
                    if (a["high"] >= tp if side == "long" else a["low"] <= tp):
                        r = (abs(tp - entry) - SLIP) / risk
                        break
                if r is None:
                    last = float(after["close"].iloc[-1]) if len(after) else entry
                    r = sgn * (last - entry - sgn * SLIP) / risk
                flow = row.get("l2_flow_imb")
                qr, qmed = row.get("l2_quote_rate"), row.get("_roll_qr")
                f1 = flow == flow and np.sign(flow) == sgn
                f2 = f1 and qr == qr and qmed == qmed and qr >= qmed
                trades["base"].append(r)
                if f1:
                    trades["f1"].append(r)
                if f2:
                    trades["f2"].append(r)
    def st_(rs):
        r = np.array(rs, float)
        if not len(r):
            return {"n": 0}
        w = r[r > 0]; l = r[r <= 0]
        return {"n": int(len(r)), "wr": round(100 * float((r > 0).mean()), 1),
                "avg_r": round(float(r.mean()), 3), "total_r": round(float(r.sum()), 1),
                "pf": round(float(w.sum() / abs(l.sum())), 2) if len(l) and l.sum() else None}
    out = {"generated_at": pd.Timestamp.now("UTC").isoformat(), "symbol": sym,
           "window": [str(lo)[:10], str(hi)[:10]],
           "note": "FEASIBILITY ONLY (~22 days) — directional read, not adoption evidence",
           "base": st_(trades["base"]), "flow_aligned_f1": st_(trades["f1"]),
           "flow_and_activity_f2": st_(trades["f2"])}
    REPORT.parent.mkdir(parents=True, exist_ok=True)
    REPORT.write_text(json.dumps(out, indent=1), encoding="utf-8")
    for k in ("base", "flow_aligned_f1", "flow_and_activity_f2"):
        print(k, out[k], flush=True)
    print(f"saved -> {REPORT}")


if __name__ == "__main__":
    run(sys.argv[1].upper() if len(sys.argv) > 1 else "QQQ")
