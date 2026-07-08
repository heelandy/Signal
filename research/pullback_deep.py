"""PULLBACK DEEP-RESEARCH (the deferred 'purple' block, user 2026-07-06: "do the pullback last").
Cohort-tests every deferred refinement against the 07.6 live-identical baseline:

  min-depth            min_pullback_atr 0.25 / 0.50   (baseline 0.05)
  %OR-width depth      min_pullback_or  0.25 / 0.50   (NEW engine knob — OR-width ruler)
  impulse-midpoint     retest_mode="impulse_mid"
  VWAP-retest          retest_mode="vwap"
  microstructure       retest_reclaim=True            (NEW — retest bar must CLOSE back through)
  extension threshold  chase_atr 0.5 / 0.75 / 1.5     (NQ native 1.0)
  pullback timeout     pullback_timeout 0 / 4 / 16    (baseline 8)
  rel-volume confirm   vol_confirm_x 1.0 / 1.2        (baseline 0 = off)
  gap rules            gap_max_atr 2 / 4              (NEW — skip big-gap days)
  side risk budget     side_budget_r 1.0 / 2.0        (NEW — per-side daily loss stop)

The pullback machinery is only ACTIVE where chase_atr > 0 (07.6: NQ/MNQ 1.0; QQQ/SPY/ES 0),
so on QQQ/SPY/ES the retest refinements are additionally tested under a forced chase_atr=1.0
("pb_on_*") — the honest question there is whether a REFINED pullback beats the adopted no-cap.

    .venv/Scripts/python research/pullback_deep.py QQQ SPY NQ ES
Report -> BOT/data/ml/reports/pullback_deep.json
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

REPORT = ROOT / "BOT" / "data" / "ml" / "reports" / "pullback_deep.json"


def run_variant(d, **over):
    import hs_backtest as B
    a = asset_config(str(d.attrs.get("sym", "")))
    mode = resolve_ctx_mode(a)
    kw = dict(eod_min=EOD, stop_mode="struct", entry_delay=a.entry_delay,
              strong_body=STRONG, ft_confirm=a.ft_confirm, dir_seq=True,
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
    if not len(a):
        return {"n": 0}
    bk = set(b["entry_time"].astype(str)) if len(b) else set()
    x = a[~a["entry_time"].astype(str).isin(bk)]
    if not len(x):
        return {"n": 0}
    r = x["net_R"].to_numpy(float)
    return {"n": int(len(r)), "avg_r": round(float(r.mean()), 3),
            "total_r": round(float(r.sum()), 1)}


def variants_for(sym):
    a = asset_config(sym)
    v = {  # chase-independent knobs — live on every symbol
        "vcx_10":  dict(vol_confirm_x=1.0),
        "vcx_12":  dict(vol_confirm_x=1.2),
        "gap_2":   dict(gap_max_atr=2.0),
        "gap_4":   dict(gap_max_atr=4.0),
    }
    if a.max_entries > 1:                      # budget can only bind with re-entries
        v["sbud_1"] = dict(side_budget_r=1.0)
        v["sbud_2"] = dict(side_budget_r=2.0)
    if a.chase_atr > 0:                        # pullback machinery natively active (NQ/MNQ)
        v.update({
            "mdep_25":   dict(min_pullback_atr=0.25),
            "mdep_50":   dict(min_pullback_atr=0.50),
            "ordep_25":  dict(min_pullback_or=0.25),
            "ordep_50":  dict(min_pullback_or=0.50),
            "imid":      dict(retest_mode="impulse_mid"),
            "vwapr":     dict(retest_mode="vwap"),
            "reclaim":   dict(retest_reclaim=True),
            "pbt_0":     dict(pullback_timeout=0),
            "pbt_4":     dict(pullback_timeout=4),
            "pbt_16":    dict(pullback_timeout=16),
            "chase_50":  dict(chase_atr=0.5),
            "chase_75":  dict(chase_atr=0.75),
            "chase_150": dict(chase_atr=1.5),
        })
    else:                                      # QQQ/SPY/ES — refined pullback vs adopted no-cap
        v.update({
            "pb_on":         dict(chase_atr=1.0),
            "pb_on_imid":    dict(chase_atr=1.0, retest_mode="impulse_mid"),
            "pb_on_reclaim": dict(chase_atr=1.0, retest_reclaim=True),
            "pb_on_mdep25":  dict(chase_atr=1.0, min_pullback_atr=0.25),
        })
    return v


def main(syms):
    out = {"generated_at": pd.Timestamp.now("UTC").isoformat(), "baseline": "07.6 canonical",
           "symbols": {}}
    REPORT.parent.mkdir(parents=True, exist_ok=True)
    for sym in syms:
        print(f"=== PULLBACK DEEP {sym} ===", flush=True)
        d = load_state(sym)
        base = run_backtest(d)
        res = {"baseline": metrics(base)}
        b = res["baseline"]
        print(f"  baseline       n {b['n']:4} avg {b['avg_r']} PF {b['pf']} dd {b['max_dd_r']} oos {b['oos30']}")
        for name, over in variants_for(sym).items():
            tr = run_variant(d, **over)
            res[name] = {"over": {k: v for k, v in over.items()},
                         "metrics": metrics(tr),
                         "gained_vs_base": diff(tr, base),
                         "lost_vs_base": diff(base, tr)}
            m = res[name]["metrics"]; g = res[name]["gained_vs_base"]; L = res[name]["lost_vs_base"]
            print(f"  {name:14} n {m.get('n'):4} avg {m.get('avg_r')} PF {m.get('pf')} "
                  f"dd {m.get('max_dd_r')} oos {m.get('oos30')} | gained n{g.get('n')} "
                  f"avg {g.get('avg_r')} | lost n{L.get('n')} avg {L.get('avg_r')}", flush=True)
        out["symbols"][sym] = res
        REPORT.write_text(json.dumps(out, indent=1), encoding="utf-8")
    print(f"saved -> {REPORT}")


if __name__ == "__main__":
    main([s.upper() for s in (sys.argv[1:] or ["QQQ", "SPY", "NQ", "ES"])])
