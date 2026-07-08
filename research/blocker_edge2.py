"""BLOCKER-EDGE ROUND 2 — the REMAINING gates, cohort-tested against the 07.5 baseline
(user 2026-07-06: "run backtest against the other blockers since misconfiguration was found").

Baseline = the new canonical run_backtest (07.5, live-identical). Each variant toggles ONE gate
OFF (or back to its old value) and reports the delta cohort:
  no_bias     equity frozen OR-mid day bias OFF        (07.5 has it ON for equities)
  no_reentry  single entry per side per session         (07.5 allows 2 eq / 3 fut with re-arm)
  delay60     old skip-first-hour arm delay             (07.5 = delay-0, user-adopted)
  no_regime2  local RANGE-regime (chop) block DISABLED  (engine hard-gate — both live+backtest)
Cohort sign decides: negative cohort = the gate earns; positive = it costs edge.

    .venv/Scripts/python research/blocker_edge2.py QQQ SPY NQ ES
Report -> BOT/data/ml/reports/blocker_edge2.json
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

from bot.strategy.orb_candidates import (load_state, run_backtest, T1, T2, ORS, ORE, CUT, EOD,  # noqa: E402
                                         STRONG)
from bot.strategy.orb_state import ENTRY_STANDARD as ES  # noqa: E402
from bot.strategy.asset_config import asset_config, resolve_ctx_mode  # noqa: E402

REPORT = ROOT / "BOT" / "data" / "ml" / "reports" / "blocker_edge2.json"


def run_variant(d, **over):
    """The 07.5 canonical call with keyword overrides."""
    import hs_backtest as B
    a = asset_config(str(d.attrs.get("sym", "")))
    mode = resolve_ctx_mode(a)
    kw = dict(eod_min=EOD, stop_mode="struct", entry_delay=a.entry_delay,
              strong_body=STRONG, ft_confirm=True, dir_seq=True,
              reentry=True, max_entries=a.max_entries, chase_atr=a.chase_atr,
              or_mid_bias=(mode not in ("mid", "mid_vwap", "mid_only", "abc")),
              watch_live=ES.watch_gate,
              cooldown_bars=a.cooldown_bars if a.cooldown_bars is not None else ES.cooldown_bars,
              stale_bars=a.stale_bars if a.stale_bars is not None else ES.stale_bars,
              retest_atr=a.retest_atr if a.retest_atr is not None else ES.retest_atr,
              retest_mode=ES.retest_mode, min_pullback_atr=ES.min_pullback_atr,
              pullback_timeout=ES.pullback_timeout, vol_confirm_x=ES.vol_confirm_x,
              instant_aligned=a.instant_fill)
    kw.update(over)
    return B.backtest(d, "tp2_full", "both", False, "orb", 0, T1, T2, ORS, ORE, 0.0, CUT,
                      "close", **kw)


def metrics(tr):
    if not len(tr):
        return {"n": 0}
    r = tr["net_R"].to_numpy(float)
    wins, losses = r[r > 0], r[r <= 0]
    eq = np.cumsum(r); cut = int(0.7 * len(r))
    return {"n": int(len(r)), "win_pct": round(100 * float((r > 0).mean()), 1),
            "avg_r": round(float(r.mean()), 3), "total_r": round(float(r.sum()), 1),
            "pf": round(float(wins.sum() / abs(losses.sum())), 2) if len(losses) and losses.sum() else None,
            "max_dd_r": round(float((eq - np.maximum.accumulate(eq)).min()), 1),
            "oos30": round(float(r[cut:].mean()), 3) if len(r) - cut > 5 else None}


def cohort(bigger, smaller):
    """Trades in `bigger` missing from `smaller` (the gated-away cohort)."""
    sk = set(smaller["entry_time"].astype(str))
    blocked = bigger[~bigger["entry_time"].astype(str).isin(sk)]
    if not len(blocked):
        return {"n": 0}
    r = blocked["net_R"].to_numpy(float)
    return {"n": int(len(r)), "avg_r": round(float(r.mean()), 3),
            "total_r": round(float(r.sum()), 1),
            "verdict": "gate EARNS (cohort negative)" if r.mean() < 0 else
                       "gate COSTS edge (cohort positive)"}


def main(syms):
    out = {"generated_at": pd.Timestamp.now("UTC").isoformat(), "baseline": "07.5 canonical",
           "symbols": {}}
    REPORT.parent.mkdir(parents=True, exist_ok=True)
    for sym in syms:
        print(f"=== BLOCKER EDGE 2 {sym} ===", flush=True)
        d = load_state(sym)
        base = run_backtest(d)
        a = asset_config(sym)
        mode = resolve_ctx_mode(a)
        variants = {}
        if mode not in ("mid", "mid_vwap", "mid_only", "abc"):     # bias only applies to equities
            variants["no_bias"] = run_variant(d, or_mid_bias=False)
        variants["no_reentry"] = run_variant(d, reentry=False, max_entries=1)
        variants["delay60"] = run_variant(d, entry_delay=60)
        d2 = d.copy()
        d2.attrs["sym"] = sym
        if "local_regime" in d2.columns:                           # unblock the chop regime
            d2["local_regime"] = np.where(d2["local_regime"].to_numpy() == 2, 1,
                                          d2["local_regime"].to_numpy())
            variants["no_regime2"] = run_variant(d2)
        res = {"baseline": metrics(base)}
        for name, tr in variants.items():
            m = metrics(tr)
            if name in ("no_bias", "no_regime2"):                  # variant is LOOSER than base
                c = cohort(tr, base)
                res[name] = {"metrics": m, "unblocked_cohort": c}
            else:                                                  # variant is TIGHTER than base
                c = cohort(base, tr)
                res[name] = {"metrics": m, "gated_cohort_in_base": c}
        out["symbols"][sym] = res
        b = res["baseline"]
        print(f"  baseline    n {b['n']:4} avg {b['avg_r']} PF {b['pf']} dd {b['max_dd_r']} oos {b['oos30']}")
        for name in ("no_bias", "no_reentry", "delay60", "no_regime2"):
            if name not in res:
                continue
            m = res[name]["metrics"]
            c = res[name].get("unblocked_cohort") or res[name].get("gated_cohort_in_base")
            print(f"  {name:11} n {m.get('n'):4} avg {m.get('avg_r')} PF {m.get('pf')} "
                  f"dd {m.get('max_dd_r')} oos {m.get('oos30')} | cohort n {c.get('n')} "
                  f"avg {c.get('avg_r')} -> {c.get('verdict', '—')}", flush=True)
        REPORT.write_text(json.dumps(out, indent=1), encoding="utf-8")
    print(f"saved -> {REPORT}")


if __name__ == "__main__":
    main([s.upper() for s in (sys.argv[1:] or ["QQQ", "SPY", "NQ", "ES"])])
