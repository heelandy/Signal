"""REVERSAL DETECTORS AS ENTRY FILTERS — the expectancy gauntlet (user ask, queued since 07.1).

The 8 reversal features (bot/strategy/reversals.py) ride in the PIT schema as MODEL inputs.
This study asks the harder question: do any of them work as a hard VETO — "skip the breakout
when a reversal signal fires AGAINST it"? For each detector: veto trades where the signed
detector opposes the trade side, then compare kept-vs-vetoed expectancy IS (first 70%) and
OOS (last 30%).

CANDIDATE (adopt via full gauntlet) only if OOS: kept avg-R > baseline avg-R, the vetoed cohort
is NEGATIVE (we are cutting real losers, not winners), and it vetoes >= 5% of trades.

    .venv/Scripts/python research/reversal_filters.py QQQ SPY NQ ES
Report -> BOT/data/ml/reports/reversal_filters.json
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

REPORT = ROOT / "BOT" / "data" / "ml" / "reports" / "reversal_filters.json"
# signed detectors: +1 = bullish reversal signal, -1 = bearish (0 = quiet)
DETECTORS = ["rsi_div", "macd_div", "macd_shrink", "vwap_slope_div",
             "capitulation_wick", "absorption"]


def _avg(r):
    return round(float(np.mean(r)), 4) if len(r) else None


def study(sym: str) -> dict:
    from bot.ml.dataset import load_or_build
    df = load_or_build(sym).reset_index(drop=True)
    if not len(df):
        return {"error": "empty dataset"}
    r = df["net_r"].to_numpy(float)
    side = df["side_long"].to_numpy(float) > 0
    cut = int(0.7 * len(df))
    out = {"n": int(len(df)), "baseline": {"is_avg_r": _avg(r[:cut]), "oos_avg_r": _avg(r[cut:])},
           "detectors": {}}
    for det in DETECTORS:
        if det not in df.columns:
            continue
        v = pd.to_numeric(df[det], errors="coerce").fillna(0).to_numpy(float)
        against = (side & (v < 0)) | (~side & (v > 0))     # reversal fires AGAINST the trade
        res = {}
        for tag, sl in (("is", slice(None, cut)), ("oos", slice(cut, None))):
            a, rr = against[sl], r[sl]
            res[tag] = {"n": int(len(rr)), "veto_n": int(a.sum()),
                        "kept_avg_r": _avg(rr[~a]), "veto_avg_r": _avg(rr[a]),
                        "base_avg_r": _avg(rr)}
        o = res["oos"]
        res["candidate"] = bool(
            o["veto_n"] >= max(5, 0.05 * o["n"]) and o["veto_avg_r"] is not None
            and o["veto_avg_r"] < 0 and o["kept_avg_r"] is not None
            and o["kept_avg_r"] > (o["base_avg_r"] or 0))
        out["detectors"][det] = res
    return out


def main(syms):
    out = {"generated_at": pd.Timestamp.now("UTC").isoformat(),
           "rule": "veto breakout when the signed detector opposes the side; "
                   "candidate = OOS kept>base AND veto cohort negative AND >=5% vetoed",
           "symbols": {}}
    REPORT.parent.mkdir(parents=True, exist_ok=True)
    for sym in syms:
        print(f"=== REVERSAL FILTERS {sym} ===", flush=True)
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
        print(f"  baseline OOS avg {s['baseline']['oos_avg_r']} (n {s['n']})")
        for det, res in s["detectors"].items():
            o = res["oos"]
            print(f"  {det:18} OOS kept {o['kept_avg_r']} | veto {o['veto_avg_r']} "
                  f"(n {o['veto_n']}) {'<<< CANDIDATE' if res['candidate'] else ''}", flush=True)
        REPORT.write_text(json.dumps(out, indent=1), encoding="utf-8")
    print(f"saved -> {REPORT}")


if __name__ == "__main__":
    main([s.upper() for s in (sys.argv[1:] or ["QQQ", "SPY", "NQ", "ES"])])
