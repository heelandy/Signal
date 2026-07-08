"""DAILY-LEVEL SWEEP-REVERSAL — the one "daily sweep" reading never A/B'd (user 2026-07-07).

A-PRIORI SPEC (frozen before data; two declared cells, NO post-hoc tuning):
  LEVELS   prior day's RTH high (PDH) and low (PDL) — the external liquidity pools.
  SWEEP    intraday price breaches the level (high > PDH / low < PDL); track the sweep extreme.
  RECLAIM  the first CONFIRMED close back inside the prior-day range after the sweep — the
           failed break traps the breakout traders.
  ENTRY    fade at the reclaim close: SHORT after a PDH sweep-and-reclaim, LONG after a PDL
           sweep-and-reclaim. One trade per level per day. RTH only. Mirror-symmetric.
  CELLS    (1) any strict breach counts;  (2) sweep depth >= 0.25 x ATR beyond the level
           (robustness twin — declared up front, not searched).
  HARNESS  the platform's standard exit/stop/costs (ext hook: struct stop, tp2_full house
           geometry, EOD flat, per-asset frictions) — this is ENTRY research.
  JUDGE    IS 70% nominates, OOS 30% judges, 2x-ALL-frictions stress (net2 = 2*net - gross).
  PRIORS (honest): every reversal cousin died (fade F18/F19, zone-bounce, rangefade) and the
  pdsweep FILTER was dead as continuation confluence (F43) — this closes the last reading.

    .venv/Scripts/python research/daily_sweep_reversal.py QQQ SPY NQ ES
Report -> BOT/data/ml/reports/daily_sweep_reversal.json
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

from bot.strategy.orb_candidates import load_state, T1, T2, EOD, CUT  # noqa: E402  (harness)

REPORT = ROOT / "BOT" / "data" / "ml" / "reports" / "daily_sweep_reversal.json"
MIN_DEPTH_ATR = 0.25          # cell 2's declared depth qualifier


def signals(d: pd.DataFrame, min_depth_atr: float = 0.0):
    """PDH/PDL sweep -> reclaim fade signals (strictly causal, confirmed closes only)."""
    h = d["high"].to_numpy(float); l = d["low"].to_numpy(float); c = d["close"].to_numpy(float)
    atr = d["atr14"].to_numpy(float)
    et = pd.to_datetime(d["ts"]).dt.tz_convert("America/New_York")
    mins = (et.dt.hour * 60 + et.dt.minute).to_numpy()
    day = et.dt.date.to_numpy()
    rth = (et.dt.dayofweek.to_numpy() < 5) & (mins >= 570) & (mins < 960)
    # prior day's RTH high/low per calendar day
    df = pd.DataFrame({"day": day, "h": h, "l": l, "rth": rth})
    g = df[df["rth"]].groupby("day").agg(dh=("h", "max"), dl=("l", "min"))
    g = g.shift(1)                                     # PRIOR day's levels (causal)
    pdh = pd.Series(day).map(g["dh"]).to_numpy()
    pdl = pd.Series(day).map(g["dl"]).to_numpy()
    n = len(d)
    ext_l = np.zeros(n, bool); ext_s = np.zeros(n, bool)
    cur = None
    swept_hi = swept_lo = False
    ext_hi = ext_lo = np.nan
    done_s = done_l = False
    for i in range(n):
        if day[i] != cur:
            cur = day[i]
            swept_hi = swept_lo = done_s = done_l = False
            ext_hi = ext_lo = np.nan
        if not rth[i] or pdh[i] != pdh[i] or pdl[i] != pdl[i]:
            continue
        # SHORT side: sweep of PDH then reclaim below it
        if not done_s:
            if h[i] > pdh[i]:
                swept_hi = True
                ext_hi = h[i] if ext_hi != ext_hi else max(ext_hi, h[i])
            if swept_hi and c[i] < pdh[i]:
                deep = min_depth_atr <= 0 or (atr[i] == atr[i] and ext_hi == ext_hi
                                              and (ext_hi - pdh[i]) >= min_depth_atr * atr[i])
                if deep:
                    ext_s[i] = True; done_s = True
        # LONG side: sweep of PDL then reclaim above it
        if not done_l:
            if l[i] < pdl[i]:
                swept_lo = True
                ext_lo = l[i] if ext_lo != ext_lo else min(ext_lo, l[i])
            if swept_lo and c[i] > pdl[i]:
                deep = min_depth_atr <= 0 or (atr[i] == atr[i] and ext_lo == ext_lo
                                              and (pdl[i] - ext_lo) >= min_depth_atr * atr[i])
                if deep:
                    ext_l[i] = True; done_l = True
    return ext_l, ext_s


def stats(r: np.ndarray) -> dict:
    if not len(r):
        return {"n": 0}
    w, lo = r[r > 0], r[r <= 0]
    eq = np.cumsum(r)
    return {"n": int(len(r)), "wr": round(100 * float((r > 0).mean()), 1),
            "avg_r": round(float(r.mean()), 3), "total_r": round(float(r.sum()), 1),
            "pf": round(float(w.sum() / abs(lo.sum())), 2) if len(lo) and lo.sum() else None,
            "dd": round(float((eq - np.maximum.accumulate(eq)).min()), 1)}


def main(syms):
    import hs_backtest as B
    out = {"generated_at": pd.Timestamp.now("UTC").isoformat(),
           "spec": "PDH/PDL sweep -> confirmed reclaim -> fade; house exit/costs; two declared "
                   "cells (any-breach, depth>=0.25ATR); single-shot", "symbols": {}}
    REPORT.parent.mkdir(parents=True, exist_ok=True)
    for sym in syms:
        print(f"=== DAILY SWEEP-REVERSAL {sym} ===", flush=True)
        d = load_state(sym)
        res = {}
        for cell, depth in (("any_breach", 0.0), ("depth_0.25atr", MIN_DEPTH_ATR)):
            el, es_ = signals(d, depth)
            tr = B.backtest(d, "tp2_full", "both", False, "ext", 0, T1, T2, eod_min=EOD,
                            tod_end=CUT, stop_mode="struct", ext_long=el, ext_short=es_)
            r = tr["net_R"].to_numpy(float) if len(tr) else np.array([])
            g2 = tr["gross_R"].to_numpy(float) if len(tr) else np.array([])
            cut = int(0.7 * len(r))
            is_, oos = stats(r[:cut]), stats(r[cut:])
            stress = stats((2 * r - g2)[cut:])
            res[cell] = {"signals_l": int(el.sum()), "signals_s": int(es_.sum()),
                         "is": is_, "oos": oos, "stress2x_oos": stress}
            print(f"  {cell:14} sig L/S {el.sum():>4}/{es_.sum():<4} | IS n{is_.get('n'):4} "
                  f"wr {is_.get('wr')} pf {is_.get('pf')} dd {is_.get('dd')} | OOS n{oos.get('n'):4} "
                  f"wr {oos.get('wr')} pf {oos.get('pf')} dd {oos.get('dd')} | 2x pf {stress.get('pf')}",
                  flush=True)
        out["symbols"][sym] = res
        REPORT.write_text(json.dumps(out, indent=1), encoding="utf-8")
    print(f"saved -> {REPORT}")


if __name__ == "__main__":
    main([s.upper() for s in (sys.argv[1:] or ["QQQ", "SPY", "NQ", "ES"])])
