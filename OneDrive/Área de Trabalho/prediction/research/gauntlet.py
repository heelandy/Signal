"""FULL GAUNTLET — the re-verify step every sweep candidate must pass before adoption.

Runs a CANDIDATE parameter set head-to-head against the ADOPTED DEFAULT on the full history and
records EVERYTHING that was used and how (data span/bars/timeframe, exact parameters of both
configs, fill rules, cost model, split dates) so the report is self-explanatory.

The seven checks (ALL must pass for ADOPT_CANDIDATE):
    1. min_trades      >= 150 full-history trades (and >= 50 in the OOS window)
    2. oos_beats_default   candidate OOS avg R > default OOS avg R (the sweep's claim, re-verified)
    3. oos_positive        candidate OOS avg R > 0
    4. slip_2x_survives    candidate stays positive when ALL costs are doubled
    5. years_consistent    candidate's positive-year fraction >= default's − 10 pts
    6. sides_not_inverted  neither long nor short side is materially negative (>= −0.05 avg R, n>=30)
    7. dd_not_worse        candidate max drawdown (R) not >20% worse than default's

    python research/gauntlet.py QQQ --ctx=1 --cooldown=0 --stale=12 --retest=0.25 \
           [--mode=edge --minpb=0.05 --timeout=8 --volx=0 --tf=5m]

Report -> BOT/data/ml/reports/gauntlet.json (merged per run; Training Lab section + kind=gauntlet).
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

import hs_backtest as B                                             # noqa: E402
from bot.strategy.asset_config import asset_config                  # noqa: E402
from bot.strategy.orb_candidates import (load_state, ORS, ORE, CUT, EOD, T1, T2, DELAY,  # noqa: E402
                                         STRONG, STRATEGY_VERSION)
from bot.strategy.orb_state import ENTRY_STANDARD as ES             # noqa: E402

REPORT = ROOT / "BOT" / "data" / "ml" / "reports" / "gauntlet.json"
CUTOFF_FRAC = 0.70


def _params_default(sym: str) -> dict:
    """The REAL adopted config for this asset — per-asset overrides included (fix 2026-07-05:
    comparing a candidate against the global defaults understated SPY's adopted baseline)."""
    a = asset_config(sym)
    return {"ctx": a.ctx_gate,
            "cooldown": a.cooldown_bars if a.cooldown_bars is not None else ES.cooldown_bars,
            "stale": a.stale_bars if a.stale_bars is not None else ES.stale_bars,
            "retest": a.retest_atr if a.retest_atr is not None else ES.retest_atr,
            "mode": ES.retest_mode, "minpb": ES.min_pullback_atr,
            "timeout": ES.pullback_timeout, "volx": ES.vol_confirm_x}


def _run(d, p: dict) -> pd.DataFrame:
    if p["ctx"]:
        st = d["st_state"].to_numpy(); cl = d["close"].to_numpy(float)
        vw = d["vwap_sess"].to_numpy(float)
        with np.errstate(invalid="ignore"):
            d["trend_up"] = (st == 1) & (cl > vw)
            d["trend_down"] = (st == 2) & (cl < vw)
    else:
        d["trend_up"] = True
        d["trend_down"] = True
    return B.backtest(d, "tp2_full", "both", False, "orb", 0, T1, T2, ORS, ORE, 0.0, CUT, "close",
                      eod_min=EOD, stop_mode="struct", entry_delay=DELAY, strong_body=STRONG,
                      ft_confirm=True, dir_seq=True, watch_live=True,
                      cooldown_bars=int(p["cooldown"]), stale_bars=int(p["stale"]),
                      retest_atr=float(p["retest"]), retest_mode=str(p["mode"]),
                      min_pullback_atr=float(p["minpb"]), pullback_timeout=int(p["timeout"]),
                      vol_confirm_x=float(p["volx"]))


def _m(r: np.ndarray) -> dict:
    if not len(r):
        return {"n": 0, "avg_r": None, "total_r": 0.0, "pf": None, "max_dd_r": 0.0,
                "win_pct": None}
    wins, losses = r[r > 0], r[r <= 0]
    pf = float(wins.sum() / abs(losses.sum())) if len(losses) and losses.sum() != 0 else None
    eq = np.cumsum(r)
    return {"n": int(len(r)), "win_pct": round(100 * float((r > 0).mean()), 1),
            "avg_r": round(float(r.mean()), 3), "total_r": round(float(r.sum()), 1),
            "pf": round(pf, 2) if pf else None,
            "max_dd_r": round(float((eq - np.maximum.accumulate(eq)).min()), 1)}


def _profile(tr: pd.DataFrame, cutoff) -> dict:
    r = tr["net_R"].to_numpy(float)
    gross = tr["gross_R"].to_numpy(float)
    et = pd.to_datetime(tr["entry_time"])
    if et.dt.tz is None:
        et = et.dt.tz_localize("UTC")
    oos = et >= cutoff
    yr = pd.Series(r).groupby(et.dt.year.to_numpy()).sum()
    sides = {s: _m(r[(tr["direction"] == s).to_numpy()]) for s in ("long", "short")}
    return {"full": _m(r), "is": _m(r[~oos.to_numpy()]), "oos": _m(r[oos.to_numpy()]),
            "slip_2x": _m(gross - 2 * (gross - r)),
            "years_pos": f"{int((yr > 0).sum())}/{len(yr)}",
            "years_pos_frac": round(float((yr > 0).mean()), 3) if len(yr) else None,
            "by_side": sides}


def gauntlet(sym: str, cand: dict, tf: str = "5m") -> dict:
    d = load_state(sym, tf)
    cutoff = pd.Timestamp(d["ts"].iloc[int(CUTOFF_FRAC * len(d))])
    if cutoff.tz is None:
        cutoff = cutoff.tz_localize("UTC")
    default = _params_default(sym)
    prof_c = _profile(_run(d, cand), cutoff)
    prof_d = _profile(_run(d, default), cutoff)
    checks = {}
    checks["min_trades"] = prof_c["full"]["n"] >= 150 and prof_c["oos"]["n"] >= 50
    co, do_ = prof_c["oos"]["avg_r"], prof_d["oos"]["avg_r"]
    checks["oos_beats_default"] = co is not None and do_ is not None and co > do_
    checks["oos_positive"] = co is not None and co > 0
    checks["slip_2x_survives"] = (prof_c["slip_2x"]["avg_r"] or 0) > 0
    fc, fd = prof_c["years_pos_frac"], prof_d["years_pos_frac"]
    checks["years_consistent"] = fc is not None and fd is not None and fc >= fd - 0.10
    checks["sides_not_inverted"] = all(
        (s["n"] < 30) or (s["avg_r"] is not None and s["avg_r"] >= -0.05)
        for s in prof_c["by_side"].values())
    dd_c, dd_d = prof_c["full"]["max_dd_r"], prof_d["full"]["max_dd_r"]
    checks["dd_not_worse"] = dd_c >= dd_d * 1.2 if dd_d < 0 else True   # dd is negative
    verdict = "ADOPT_CANDIDATE" if all(checks.values()) else "KEEP_DEFAULT"
    return {
        "generated_at": pd.Timestamp.now("UTC").isoformat(),
        "verdict": verdict, "checks": checks,
        # ── FULL DETAIL: exactly what was used and how ──
        "used": {
            "symbol": sym, "timeframe": tf, "session": "rth",
            "bars": int(len(d)),
            "data_span": [str(d['ts'].iloc[0])[:10], str(d['ts'].iloc[-1])[:10]],
            "is_oos_split": {"cutoff_frac": CUTOFF_FRAC, "cutoff_date": str(cutoff)[:10],
                             "rank_window": "first 70% (in-sample)",
                             "judge_window": "last 30% (out-of-sample)"},
            "strategy_version": STRATEGY_VERSION,
            "fill_rules": "close-confirm strong body 0.25 + next-candle continuation (F59c) + "
                          "direction sequence (F61) + OR-mid day bias + vol-expansion width; "
                          "struct stop (F25b) min/max ATR per asset; full->4R cap exit (F34b); "
                          "EOD flat 15:58",
            "cost_model": "per-asset commissions + slippage ticks (engine); slip_2x doubles ALL costs",
            "or_window": "09:30-10:00 ET (RTH)",
        },
        "candidate": {"params": cand, "results": prof_c},
        "default": {"params": default, "results": prof_d},
    }


def main(argv: list[str]) -> dict:
    args = [a for a in argv if not a.startswith("--")]
    sym = (args[0] if args else "QQQ").upper()
    kv = dict(a[2:].split("=", 1) for a in argv if a.startswith("--") and "=" in a)
    tf = kv.pop("tf", "5m")
    cand = _params_default(sym)
    cast = {"ctx": lambda v: v in ("1", "true", "True"), "cooldown": int, "stale": int,
            "retest": float, "mode": str, "minpb": float, "timeout": int, "volx": float}
    for k, v in kv.items():
        if k in cast:
            cand[k] = cast[k](v)
    print(f"=== GAUNTLET {sym} tf={tf} candidate={cand} ===", flush=True)
    rep = gauntlet(sym, cand, tf)
    prev = {}
    if REPORT.exists():
        try:
            prev = json.loads(REPORT.read_text(encoding="utf-8")).get("runs", {})
        except Exception:
            prev = {}
    key = f"{sym}@{tf}"
    prev[key] = rep
    REPORT.parent.mkdir(parents=True, exist_ok=True)
    REPORT.write_text(json.dumps({"runs": prev}, indent=1), encoding="utf-8")
    print(f"  VERDICT: {rep['verdict']}")
    for k, ok in rep["checks"].items():
        print(f"    {'PASS' if ok else 'FAIL'}  {k}")
    print(f"  candidate OOS {rep['candidate']['results']['oos']} ")
    print(f"  default   OOS {rep['default']['results']['oos']}")
    print(f"saved -> {REPORT}")
    return rep


if __name__ == "__main__":
    main(sys.argv[1:])
