"""WORKER SELECTIVITY COHORTS — step 3 of docs/BOSS_WORKERS_PLAN.md.

The geometry grids (worker_specs.json) put every symbol's WR inside the 75-85 band at tight
targets but PF short of 1.7 — selectivity must now remove losers without gutting the stream.
Per symbol, on its TOP-2 grid cells (by OOS PF among cells with OOS WR >= 73): test each tier
ONE AT A TIME (IS nominates, OOS judges), then the combo of individually-passing tiers:

  slope_strong   |combined slope S| >= 0.30 at the signal bar (skip weak-slope fires)
  early_only     entry before 12:00 ET (skip afternoon)
  late_only      entry 12:00+ ET (skip morning) — mirror, only one can win
  wide_or        min_or_width 2.4 (the vol-expansion tier — grade-only in 07.7, tier here)

    .venv/Scripts/python research/worker_cohorts.py QQQ SPY NQ ES GC
Report -> BOT/data/ml/reports/worker_cohorts.json
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

from bot.strategy.orb_candidates import load_state  # noqa: E402
from bot.strategy.orb_state import slope_series  # noqa: E402
from worker_specs import run_geometry, stats, in_band, BAND  # noqa: E402

GRID_REPORT = ROOT / "BOT" / "data" / "ml" / "reports" / "worker_specs.json"
REPORT = ROOT / "BOT" / "data" / "ml" / "reports" / "worker_cohorts.json"
SLOPE_STRONG = 0.30
NOON = 720


def masks_for(d) -> dict:
    """skip_mask per tier (True = SKIP the signal at that bar)."""
    et = pd.to_datetime(d["ts"]).dt.tz_convert("America/New_York")
    mins = (et.dt.hour * 60 + et.dt.minute).to_numpy()
    S = np.asarray(slope_series(d["open"].to_numpy(float), d["close"].to_numpy(float),
                                d["atr14"].to_numpy(float)), float)
    weak = ~(np.abs(S) >= SLOPE_STRONG)          # NaN slope counts as weak (skip)
    return {"slope_strong": weak,
            "early_only": mins >= NOON,
            "late_only": mins < NOON}


def run_cell(d, b, skip_mask=None, min_or_width=0.0):
    """Canonical geometry call + optional tier mask/kwarg."""
    import hs_backtest as B
    from bot.strategy.asset_config import asset_config, resolve_ctx_mode, layer3_kwargs
    from bot.strategy.orb_candidates import T1, ORS, ORE, CUT, EOD, STRONG
    a = asset_config(str(d.attrs.get("sym", "")))
    mode = resolve_ctx_mode(a)
    return B.backtest(d, "tp2_full", "both", False, "orb", 0, T1, b, ORS, ORE, 0.0, CUT, "close",
                      eod_min=EOD, stop_mode="struct", entry_delay=a.entry_delay,
                      strong_body=STRONG, ft_confirm=a.ft_confirm, dir_seq=True,
                      reentry=True, max_entries=a.max_entries, chase_atr=a.chase_atr,
                      or_mid_bias=(mode not in ("mid", "mid_vwap", "mid_only", "abc")),
                      instant_aligned=a.instant_fill, block_range=a.block_range,
                      skip_mask=skip_mask, min_or_width=min_or_width,
                      **layer3_kwargs(a))


def split_stats(tr):
    r = tr["net_R"].to_numpy(float) if len(tr) else np.array([])
    cut = int(0.7 * len(r))
    return stats(r[:cut]), stats(r[cut:])


def top_cells(sym: str, k: int = 2) -> list[float]:
    rep = json.loads(GRID_REPORT.read_text(encoding="utf-8"))
    cells = rep["symbols"].get(sym, {}).get("cells", {})
    scored = [(float(b), c["oos"].get("pf") or 0.0) for b, c in cells.items()
              if c["oos"].get("n", 0) > 0 and (c["oos"].get("wr") or 0) >= 73.0]
    scored.sort(key=lambda x: -x[1])
    return [b for b, _ in scored[:k]] or [0.40]


def main(syms):
    out = {"generated_at": pd.Timestamp.now("UTC").isoformat(), "band": BAND, "symbols": {}}
    REPORT.parent.mkdir(parents=True, exist_ok=True)
    for sym in syms:
        print(f"=== COHORTS {sym} ===", flush=True)
        d = load_state(sym)
        mk = masks_for(d)
        res = {}
        for b in top_cells(sym):
            cell = {}
            base_is, base_oos = split_stats(run_cell(d, b))
            cell["base"] = {"is": base_is, "oos": base_oos}
            print(f"  b={b:.2f} base   IS wr {base_is.get('wr')} pf {base_is.get('pf')} "
                  f"| OOS wr {base_oos.get('wr')} pf {base_oos.get('pf')} dd {base_oos.get('dd')}",
                  flush=True)
            tiers = {n: dict(skip_mask=m) for n, m in mk.items()}
            tiers["wide_or"] = dict(min_or_width=2.4)
            passing = []
            for name, kw in tiers.items():
                t_is, t_oos = split_stats(run_cell(d, b, **kw))
                band = in_band(t_is, dd_scale=2.33) and in_band(t_oos)
                better = ((t_oos.get("pf") or 0) > (base_oos.get("pf") or 0)
                          and (t_is.get("pf") or 0) > (base_is.get("pf") or 0))
                cell[name] = {"is": t_is, "oos": t_oos, "band": band, "improves_both": better}
                if better:
                    passing.append(name)
                print(f"    {name:13} IS n{t_is.get('n'):4} wr {t_is.get('wr')} pf {t_is.get('pf')} "
                      f"| OOS n{t_oos.get('n'):4} wr {t_oos.get('wr')} pf {t_oos.get('pf')} "
                      f"dd {t_oos.get('dd')} {'BAND' if band else ''}{' +' if better else ''}",
                      flush=True)
            if len(passing) > 1:
                m = np.zeros(len(d), bool)
                mow = 0.0
                for name in passing:
                    if name == "wide_or":
                        mow = 2.4
                    else:
                        m = m | mk[name]
                c_is, c_oos = split_stats(run_cell(d, b, skip_mask=m, min_or_width=mow))
                cell["combo"] = {"tiers": passing, "is": c_is, "oos": c_oos,
                                 "band": in_band(c_is, dd_scale=2.33) and in_band(c_oos)}
                print(f"    COMBO {passing} IS wr {c_is.get('wr')} pf {c_is.get('pf')} | "
                      f"OOS n{c_oos.get('n')} wr {c_oos.get('wr')} pf {c_oos.get('pf')} "
                      f"dd {c_oos.get('dd')} {'<== BAND' if cell['combo']['band'] else ''}",
                      flush=True)
            res[str(b)] = cell
        out["symbols"][sym] = res
        REPORT.write_text(json.dumps(out, indent=1), encoding="utf-8")
    print(f"saved -> {REPORT}")


if __name__ == "__main__":
    main([s.upper() for s in (sys.argv[1:] or ["QQQ", "SPY", "NQ", "ES", "GC"])])
