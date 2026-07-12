"""A/B: the CANONICAL ENTRY STANDARD (2026-07-04) vs the pre-standard baseline, on the data drive.

Three variants per symbol (state frame computed ONCE, gates swapped per variant):
    baseline     — the old shipped replay config: plain-ORB gates (trend arrays True), no live
                   watch / cooldown / stale / retest (exactly the pre-standard emit_from_state).
    layer3_only  — plain-ORB gates + the Layer-3 execution standard (live WATCH at the OR mid,
                   cooldown 3, stale 24, pullback retest 0.5) — isolates the execution rules.
    standard     — the full canonical standard: Layer-1 Market Context (Structure+VWAP arm)
                   + Layer 3. What the BOT/Pine now trade.

Writes BOT/data/ml/reports/ab_entry_standard.json (the training dashboard reads it) and prints
a per-symbol table. Run from the repo root:

    .venv/Scripts/python research/ab_entry_standard.py QQQ SPY NQ ES
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
os.chdir(ROOT)                                   # hs_db uses repo-root-relative data/ paths

import hs_db, hs_harness as H, hs_backtest as B          # noqa: E402
from bot.strategy.asset_config import struct_lb          # noqa: E402
from bot.strategy.orb_state import ENTRY_STANDARD as ES  # noqa: E402
from bot.strategy.orb_candidates import ORS, ORE, CUT, EOD, T1, T2, DELAY, STRONG  # noqa: E402

REPORT = ROOT / "BOT" / "data" / "ml" / "reports"
REPORT.mkdir(parents=True, exist_ok=True)


def load(sym: str) -> pd.DataFrame:
    con = hs_db.connect()
    bars = B._externals(con, hs_db.bars(con, "5m", "rth", sym=sym), sym)
    con.close()
    d = H.compute_state(bars, H.P(struct_lb_fix=struct_lb(sym)))
    d.attrs["sym"] = sym
    return d


def set_plain(d):
    d["trend_up"] = True
    d["trend_down"] = True


def set_ctx(d):
    st = d["st_state"].to_numpy(); cl = d["close"].to_numpy(float)
    vw = d["vwap_sess"].to_numpy(float)
    with np.errstate(invalid="ignore"):
        d["trend_up"] = (st == 1) & (cl > vw)
        d["trend_down"] = (st == 2) & (cl < vw)


def run(d, watch: bool) -> pd.DataFrame:
    kw = dict(watch_live=True, cooldown_bars=ES.cooldown_bars, stale_bars=ES.stale_bars,
              retest_atr=ES.retest_atr) if watch else {}
    return B.backtest(d, "tp2_full", "both", False, "orb", 0, T1, T2, ORS, ORE, 0.0, CUT, "close",
                      eod_min=EOD, stop_mode="struct", entry_delay=DELAY,
                      strong_body=STRONG, ft_confirm=True, dir_seq=True, **kw)


def metrics(tr: pd.DataFrame) -> dict:
    if not len(tr):
        return {"trades": 0}
    r = tr["net_R"].to_numpy(float)
    wins, losses = r[r > 0], r[r <= 0]
    pf = float(wins.sum() / abs(losses.sum())) if len(losses) and losses.sum() != 0 else float("inf")
    eq = np.cumsum(r)
    dd = float((eq - np.maximum.accumulate(eq)).min())
    yr = pd.to_datetime(tr["entry_time"]).dt.year
    by_year = pd.Series(r).groupby(yr.to_numpy()).sum()
    return {"trades": int(len(r)), "win_pct": round(100 * float((r > 0).mean()), 1),
            "avg_net_r": round(float(r.mean()), 3), "total_r": round(float(r.sum()), 1),
            "pf": round(pf, 2) if pf != float("inf") else None, "max_dd_r": round(dd, 1),
            "years_pos": f"{int((by_year > 0).sum())}/{len(by_year)}"}


def main(syms: list[str]) -> dict:
    from bot.strategy.orb_candidates import STRATEGY_VERSION
    out = {"generated_at": pd.Timestamp.now("UTC").isoformat(), "symbols": {},
           # PHASE R (2026-07-11): the version is stamped LIVE (the old hardcoded "2026.07"
           # made ab_strategy_version_match false forever) + remediation lineage with the
           # frozen-span waiver (user decision: no historical refresh; QA documents staleness)
           "lineage": "remediation-2026-07-11 · corrected engine (Phases 1-3) · frozen-span waiver",
           "config": {"cooldown_bars": ES.cooldown_bars, "stale_bars": ES.stale_bars,
                      "retest_atr": ES.retest_atr, "strategy_version": STRATEGY_VERSION}}
    for sym in syms:
        print(f"\n=== {sym} ===", flush=True)
        try:
            d = load(sym)
        except Exception as e:
            out["symbols"][sym] = {"error": str(e)[:200]}
            print(f"  load failed: {e}")
            continue
        res = {}
        set_plain(d);  res["baseline"] = metrics(run(d, watch=False))
        set_plain(d);  res["layer3_only"] = metrics(run(d, watch=True))
        set_ctx(d);    res["standard"] = metrics(run(d, watch=True))
        out["symbols"][sym] = res
        for name, m in res.items():
            print(f"  {name:12} " + " | ".join(f"{k}={v}" for k, v in m.items()), flush=True)
    (REPORT / "ab_entry_standard.json").write_text(json.dumps(out, indent=1), encoding="utf-8")
    print(f"\nsaved -> {REPORT / 'ab_entry_standard.json'}")
    return out


if __name__ == "__main__":
    main([s.upper() for s in (sys.argv[1:] or ["QQQ", "SPY", "NQ", "ES"])])
