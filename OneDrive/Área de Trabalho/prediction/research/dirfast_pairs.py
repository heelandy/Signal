"""DIR-FAST pairs test (user 2026-07-05) — which 2-item ARMING pair earns the most?

ORMID is obligatory (the watch machine enforces the OR-mid side), so the 4-item pool
(ORMID, VWAP, SLOPE, STRUCT) reduces to 3 candidate pairs + the no-pair baseline:

    mid_vwap    OR-mid + VWAP side            (the user's chosen new standard)
    mid_slope   OR-mid + slope direction      (EMA9 vs EMA20 as the causal slope proxy)
    mid_struct  OR-mid + swing-structure state
    mid_only    OR-mid alone (baseline — watch machine only)

Per symbol: full-history metrics + last-30% OOS window (selection must hold forward).
All runs use the adopted Layer-3 standard incl. per-asset overrides + pullback refinements.

    .venv/Scripts/python research/dirfast_pairs.py QQQ SPY NQ ES
Report -> BOT/data/ml/reports/dirfast_pairs.json (Training Lab reads it via the sweep panel dir).
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

import hs_backtest as B                                              # noqa: E402
from bot.strategy.asset_config import asset_config                   # noqa: E402
from bot.strategy.orb_candidates import (load_state, ORS, ORE, CUT, EOD, T1, T2, DELAY,  # noqa: E402
                                         STRONG)
from bot.strategy.orb_state import ENTRY_STANDARD as ES              # noqa: E402

REPORT = ROOT / "BOT" / "data" / "ml" / "reports" / "dirfast_pairs.json"
# full ORMID-anchored family (user 2026-07-05): 3 pairs + 3 TRIPLES + all-four + baseline = 8
PAIRS = ("mid_vwap", "mid_slope", "mid_struct",
         "mid_vwap_struct", "mid_vwap_slope", "mid_struct_slope", "mid_all", "mid_only")


def _set_pair(d, pair: str):
    """Compose the arming condition from its members (v=VWAP side, s=EMA-slope, t=structure)."""
    cl = d["close"].to_numpy(float)
    with np.errstate(invalid="ignore"):
        vw = d["vwap_sess"].to_numpy(float)
        v_up, v_dn = cl > vw, cl < vw
        e9 = d["ema9"].to_numpy(float); e20 = d["ema20"].to_numpy(float)
        s_up, s_dn = e9 > e20, e9 < e20
        st = d["st_state"].to_numpy()
        t_up, t_dn = st == 1, st == 2
        combo = {"mid_vwap": (v_up, v_dn), "mid_slope": (s_up, s_dn), "mid_struct": (t_up, t_dn),
                 "mid_vwap_struct": (v_up & t_up, v_dn & t_dn),
                 "mid_vwap_slope": (v_up & s_up, v_dn & s_dn),
                 "mid_struct_slope": (t_up & s_up, t_dn & s_dn),
                 "mid_all": (v_up & t_up & s_up, v_dn & t_dn & s_dn)}
        if pair in combo:
            d["trend_up"], d["trend_down"] = combo[pair]
        else:
            d["trend_up"] = True
            d["trend_down"] = True


def _run(d, sym):
    a = asset_config(sym)
    return B.backtest(d, "tp2_full", "both", False, "orb", 0, T1, T2, ORS, ORE, 0.0, CUT, "close",
                      eod_min=EOD, stop_mode="struct", entry_delay=DELAY, strong_body=STRONG,
                      ft_confirm=True, dir_seq=True, watch_live=True,
                      cooldown_bars=a.cooldown_bars if a.cooldown_bars is not None else ES.cooldown_bars,
                      stale_bars=a.stale_bars if a.stale_bars is not None else ES.stale_bars,
                      retest_atr=a.retest_atr if a.retest_atr is not None else ES.retest_atr,
                      retest_mode=ES.retest_mode, min_pullback_atr=ES.min_pullback_atr,
                      pullback_timeout=ES.pullback_timeout, vol_confirm_x=ES.vol_confirm_x)


def _m(r):
    if not len(r):
        return {"n": 0, "avg_r": None, "total_r": 0.0, "pf": None}
    wins, losses = r[r > 0], r[r <= 0]
    pf = float(wins.sum() / abs(losses.sum())) if len(losses) and losses.sum() != 0 else None
    return {"n": int(len(r)), "win_pct": round(100 * float((r > 0).mean()), 1),
            "avg_r": round(float(r.mean()), 3), "total_r": round(float(r.sum()), 1),
            "pf": round(pf, 2) if pf else None}


def main(syms):
    prev = {}
    if REPORT.exists():
        try:
            prev = json.loads(REPORT.read_text(encoding="utf-8")).get("symbols", {})
        except Exception:
            prev = {}
    out = {"generated_at": pd.Timestamp.now("UTC").isoformat(), "pairs": list(PAIRS),
           "symbols": prev}
    REPORT.parent.mkdir(parents=True, exist_ok=True)
    for sym in syms:
        print(f"=== DIR-FAST PAIRS {sym} ===", flush=True)
        d = load_state(sym)
        cutoff = pd.Timestamp(d["ts"].iloc[int(0.70 * len(d))])
        res = {}
        for pair in PAIRS:
            _set_pair(d, pair)
            tr = _run(d, sym)
            r = tr["net_R"].to_numpy(float)
            et = pd.to_datetime(tr["entry_time"]) if len(tr) else pd.Series([], dtype="datetime64[ns]")
            oos = (et >= cutoff).to_numpy() if len(tr) else np.array([], bool)
            res[pair] = {"full": _m(r), "oos": _m(r[oos])}
            print(f"  {pair:10} full {res[pair]['full']} | OOS {res[pair]['oos']}", flush=True)
        ranked = sorted((p for p in PAIRS if res[p]["oos"]["avg_r"] is not None and
                         res[p]["full"]["n"] >= 100),
                        key=lambda p: -res[p]["oos"]["avg_r"])
        res["winner_oos"] = ranked[0] if ranked else None
        out["symbols"][sym] = res
        print(f"  WINNER (OOS avg R, n>=100 full): {res['winner_oos']}", flush=True)
        REPORT.write_text(json.dumps(out, indent=1), encoding="utf-8")
    print(f"saved -> {REPORT}")
    return out


if __name__ == "__main__":
    main([s.upper() for s in (sys.argv[1:] or ["QQQ", "SPY", "NQ", "ES"])])
