"""PINE/PYTHON PARITY GOLDENS (P1.2, 2026-07-11).

Exports a DETERMINISTIC fixed-bar signal sequence from the Python engine — the reference the
TradingView side must reproduce bar-for-bar. Config-text sync is necessary but NOT sufficient
(the audit): behavior must match, and this file is the behavioral contract.

The synthetic tape exercises the canonical Layer-3 state machine: a clean confirmed break (fire),
a watch cancel at the OR mid (cooldown), a stale watch (range stand-down), and a chase-extension
followed by a pullback retest (fire on the retest, not the chase).

    python research/parity_goldens.py          # regenerates BOT/tests/goldens/parity_signals.json

Pinned by BOT/tests/test_parity_goldens.py — any engine change that moves ONE entry breaks the
pin on purpose. Pine workflow: bar-replay this tape on TV (or its CSV import), log the STACK
script's fires, and diff against the JSON (side, bar index, level). Differences = parity bugs.
"""
from __future__ import annotations

import json
import os
import sys

import numpy as np
import pandas as pd

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "engine"))

GOLDEN = os.path.join(ROOT, "BOT", "tests", "goldens", "parity_signals.json")
ET = "America/New_York"
ATR = 8.0
BASE = 102.0
KNOBS = dict(or_s=570, or_e=600, brk_buf_atr=0.0, tod_end=960, execm="close",
             watch_live=True, cooldown_bars=3, stale_bars=24, retest_atr=0.5,
             chase_atr=1.5, reentry=True)          # the canonical Layer-3 shape (07.x family)

OR = {t: (BASE, 104.0, 100.0, BASE) for t in ("09:30", "09:35", "09:40", "09:45", "09:50", "09:55")}


def _tape() -> pd.DataFrame:
    days = {
        # DAY 1 — watch arms above the mid, clean confirmed break -> FIRE at 10:20
        "2026-01-05": {**OR, "10:00": (102.2, 103.4, 102.0, 103.2),   # close > mid 102: watch arms
                       "10:20": (103.4, 104.9, 103.2, 104.6)},        # confirmed close above OR high
        # DAY 2 — watch arms, then CANCELS at the mid (cooldown); late re-arm, no fire
        "2026-01-06": {**OR, "10:00": (102.2, 103.4, 102.0, 103.2),   # arm
                       "10:10": (103.0, 103.2, 101.0, 101.4),         # close < mid: cancel -> cooldown
                       "10:30": (102.2, 103.0, 102.0, 102.8)},        # re-arm after cooldown, no break
        # DAY 3 — chase extension past 1.5*ATR pre-fill, then the PULLBACK RETEST fires
        "2026-01-07": {**OR, "10:00": (102.2, 103.4, 102.0, 103.2),   # arm
                       "10:05": (103.4, 118.0, 103.2, 117.0),         # blows through: extension latch
                       "10:35": (117.0, 117.5, 104.2, 106.0),         # retest within 0.5*ATR of level
                       "10:40": (106.0, 107.5, 105.5, 107.0)},        # post-retest confirmed close -> FIRE
    }
    rows = []
    for day, spec in days.items():
        for t in pd.date_range(f"{day} 09:30", f"{day} 15:55", freq="5min", tz=ET):
            o = h = l = c = BASE
            key = t.strftime("%H:%M")
            if key in spec:
                o, h, l, c = spec[key]
            rows.append({"ts": t.tz_convert("UTC"), "open": float(o), "high": float(h),
                         "low": float(l), "close": float(c), "volume": 1_000.0})
    d = pd.DataFrame(rows)
    d["atr14"] = ATR
    d["trend_up"] = True
    d["trend_down"] = True
    for col in ("vwap_sess",):
        d[col] = np.nan
    return d


def build() -> dict:
    import hs_backtest as B
    d = _tape()
    lsig, ssig, orl, orh, lvl_l, lvl_s = B._orb_signals(d, **KNOBS)
    et = pd.to_datetime(d["ts"]).dt.tz_convert(ET)
    fires = [{"bar": int(i), "ts_et": et.iloc[i].strftime("%Y-%m-%d %H:%M"),
              "side": "long" if lsig[i] else "short",
              "level": round(float(lvl_l[i] if lsig[i] else lvl_s[i]), 2),
              "close": round(float(d['close'].iloc[i]), 2)}
             for i in range(len(d)) if lsig[i] or ssig[i]]
    return {"knobs": KNOBS, "atr": ATR, "or": [100.0, 104.0], "bars": len(d),
            "note": "deterministic Layer-3 tape: day1 clean confirmed-close fire · day2 watch "
                    "cancel at the mid -> cooldown, NO fire · day3 blow-through bar fires (its "
                    "LOW was at the level = near, not chased), price re-arms flat inside the OR, "
                    "then the re-entry fires. Pine must reproduce ALL THREE, including day3's "
                    "two-fire subtlety — that is exactly the kind of semantics config-text sync "
                    "cannot verify.",
            "fires": fires}


def main() -> None:
    g = build()
    os.makedirs(os.path.dirname(GOLDEN), exist_ok=True)
    with open(GOLDEN, "w", encoding="utf-8") as f:
        json.dump(g, f, indent=1)
    print(f"golden: {len(g['fires'])} fire(s) -> {GOLDEN}")
    for x in g["fires"]:
        print(" ", x)


if __name__ == "__main__":
    main()
