"""Replay-parity report (AITP-001 §13.6/§Phase-2) — do the CONTRACT-LAYER candidates match the
ENGINE's trades exactly?

The bot's TradeCandidates (orb_candidates.emit_from_state — what risk/execution/journal consume)
must be a 1:1 image of the engine backtest rows (same entry bars, sides, prices, stops). Any
mismatch = a silent divergence between what was validated and what would be traded. This report
re-derives both from ONE state frame and diffs them field by field.

    .venv/Scripts/python research/replay_parity.py QQQ SPY
Report -> BOT/data/ml/reports/replay_parity.json (Training Lab, run kind=parity).
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
os.chdir(ROOT)

from bot.strategy.orb_candidates import load_state, run_backtest, emit_from_state  # noqa: E402

REPORT = ROOT / "BOT" / "data" / "ml" / "reports" / "replay_parity.json"


def parity(sym: str) -> dict:
    d = load_state(sym)
    tr = run_backtest(d).reset_index(drop=True)
    cands = emit_from_state(d, sym)
    n_tr, n_c = len(tr), len(cands)
    checked = min(n_tr, n_c)
    mismatches = []
    for i in range(checked):
        row, c = tr.iloc[i], cands[i]
        ts_tr = pd.Timestamp(row["entry_time"])
        ts_tr = (ts_tr.tz_localize("UTC") if ts_tr.tz is None else ts_tr.tz_convert("UTC")).isoformat()
        sign = 1 if c.side.value == "long" else -1
        stop_expect = round(float(row["entry_price"]) - sign * float(row["risk_pts"]), 2)
        diffs = {}
        if str(row["direction"]) != c.side.value:
            diffs["side"] = [str(row["direction"]), c.side.value]
        if ts_tr != c.generated_at:
            diffs["entry_time"] = [ts_tr, c.generated_at]
        if abs(float(row["entry_price"]) - c.entry) > 0.011:
            diffs["entry"] = [float(row["entry_price"]), c.entry]
        if abs(stop_expect - c.stop) > 0.011:
            diffs["stop"] = [stop_expect, c.stop]
        if diffs:
            mismatches.append({"i": i, **diffs})
    rate = round(100.0 * (checked - len(mismatches)) / checked, 2) if checked else None
    return {"engine_trades": n_tr, "candidates": n_c, "checked": checked,
            "mismatches": len(mismatches), "match_pct": rate,
            "examples": mismatches[:5],
            "ok": bool(n_tr == n_c and not mismatches)}


def main(syms: list[str]) -> dict:
    prev = {}
    if REPORT.exists():
        try:
            prev = json.loads(REPORT.read_text(encoding="utf-8")).get("symbols", {})
        except Exception:
            prev = {}
    out = {"generated_at": pd.Timestamp.now("UTC").isoformat(), "symbols": prev}
    REPORT.parent.mkdir(parents=True, exist_ok=True)
    for sym in syms:
        try:
            out["symbols"][sym] = parity(sym)
        except Exception as e:
            out["symbols"][sym] = {"error": str(e)[:200]}
        s = out["symbols"][sym]
        print(f"{sym}: {s}", flush=True)
        REPORT.write_text(json.dumps(out, indent=1), encoding="utf-8")
    print(f"saved -> {REPORT}")
    return out


if __name__ == "__main__":
    main([s.upper() for s in (sys.argv[1:] or ["QQQ", "SPY"])])
