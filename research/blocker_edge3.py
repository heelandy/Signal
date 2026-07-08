"""BLOCKER-EDGE ROUND 3 — cooldown, stale/RANGE, and the next-candle wait, cohort-tested
against the 07.5 baseline (user 2026-07-06: "test against cooldown, stale, next-candle").

NOTE: the earlier cooldown/stale adoptions (07.2 gauntlet: QQQ cd5/stale12 etc.) were validated
under the OLD canonical config — which F75 proved diverged from live on seven knobs — so this
re-test under the live-identical 07.5 baseline is the honest re-examination.

Variants per symbol (baseline = 07.5 canonical run_backtest):
  no_cooldown   cooldown_bars = 0      (looser — unblocked cohort measured)
  no_stale      stale_bars    = 0      (looser — the RANGE stand-down never triggers)
  no_ftconfirm  ft_confirm    = False  (fill the breakout candle even UNALIGNED — no wait at all)
  always_wait   instant_aligned=False  (re-test of the 07.2 instant-fill rule: wait even aligned)
For the two fill-timing variants entry TIMES shift, so both directions are reported:
only-in-variant trades (gained) and only-in-base trades (lost).

    .venv/Scripts/python research/blocker_edge3.py QQQ SPY NQ ES
Report -> BOT/data/ml/reports/blocker_edge3.json
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

from bot.strategy.orb_candidates import (load_state, run_backtest, T1, T2, ORS, ORE, CUT,  # noqa: E402
                                         EOD, STRONG)
from bot.strategy.orb_state import ENTRY_STANDARD as ES  # noqa: E402
from bot.strategy.asset_config import asset_config, resolve_ctx_mode  # noqa: E402

REPORT = ROOT / "BOT" / "data" / "ml" / "reports" / "blocker_edge3.json"


def run_variant(d, **over):
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
              instant_aligned=a.instant_fill, block_range=a.block_range)
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


def diff(a, b):
    """Trades in `a` missing from `b` by entry_time."""
    bk = set(b["entry_time"].astype(str))
    x = a[~a["entry_time"].astype(str).isin(bk)]
    if not len(x):
        return {"n": 0}
    r = x["net_R"].to_numpy(float)
    return {"n": int(len(r)), "avg_r": round(float(r.mean()), 3),
            "total_r": round(float(r.sum()), 1)}


def main(syms):
    out = {"generated_at": pd.Timestamp.now("UTC").isoformat(), "baseline": "07.5 canonical",
           "symbols": {}}
    REPORT.parent.mkdir(parents=True, exist_ok=True)
    for sym in syms:
        print(f"=== BLOCKER EDGE 3 {sym} ===", flush=True)
        d = load_state(sym)
        base = run_backtest(d)
        variants = {"no_cooldown": run_variant(d, cooldown_bars=0),
                    "no_stale": run_variant(d, stale_bars=0),
                    "no_ftconfirm": run_variant(d, ft_confirm=False),
                    "always_wait": run_variant(d, instant_aligned=False)}
        res = {"baseline": metrics(base)}
        for name, tr in variants.items():
            res[name] = {"metrics": metrics(tr),
                         "gained_vs_base": diff(tr, base),
                         "lost_vs_base": diff(base, tr)}
        out["symbols"][sym] = res
        b = res["baseline"]
        print(f"  baseline     n {b['n']:4} avg {b['avg_r']} PF {b['pf']} dd {b['max_dd_r']} oos {b['oos30']}")
        for name in variants:
            m = res[name]["metrics"]; g = res[name]["gained_vs_base"]; L = res[name]["lost_vs_base"]
            print(f"  {name:12} n {m.get('n'):4} avg {m.get('avg_r')} PF {m.get('pf')} "
                  f"dd {m.get('max_dd_r')} oos {m.get('oos30')} | gained n{g.get('n')} "
                  f"avg {g.get('avg_r')} | lost n{L.get('n')} avg {L.get('avg_r')}", flush=True)
        REPORT.write_text(json.dumps(out, indent=1), encoding="utf-8")
    print(f"saved -> {REPORT}")


if __name__ == "__main__":
    main([s.upper() for s in (sys.argv[1:] or ["QQQ", "SPY", "NQ", "ES"])])
