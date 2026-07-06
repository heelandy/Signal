"""Entry-parameter SWEEP — a separate training that varies the direction/entry knobs and finds
the best combination per symbol, with an overfitting guard.

Grid (54 combos): Layer-1 context gate ON/OFF x cooldown {0,3,5} x stale {0,12,24} x
pullback retest {0.25,0.5,0.75} ATR (watch gate always on — validated everywhere; chase 1.0).

Honesty rule: combos are RANKED on the FIRST 70% of history (in-sample) with a minimum-trades
floor, then JUDGED on the LAST 30% (out-of-sample) next to the adopted default config. A combo
only deserves adoption if its OOS beats the default's OOS — selection on IS alone is curve-fitting.
The state frame is computed ONCE per symbol; each combo only re-runs the signal/trade loop.

    .venv/Scripts/python research/sweep_entry_params.py QQQ SPY NQ ES
    .venv/Scripts/python research/sweep_entry_params.py QQQ --quick      # smoke grid (8 combos)

Report -> BOT/data/ml/reports/sweep_entry_params.json (Training Lab panel + kind=sweep runner).
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

import hs_db, hs_harness as H, hs_backtest as B          # noqa: E402
from bot.strategy.asset_config import struct_lb, asset_config  # noqa: E402
from bot.strategy.orb_candidates import ORS, ORE, CUT, EOD, T1, T2, DELAY, STRONG  # noqa: E402
from bot.strategy.orb_state import ENTRY_STANDARD as ES  # noqa: E402

REPORT = ROOT / "BOT" / "data" / "ml" / "reports" / "sweep_entry_params.json"
CUTOFF_FRAC = 0.70
MIN_IS_TRADES = 60


def grid(quick: bool = False, phase2: bool = False) -> list[dict]:
    if phase2:
        # PHASE-2 (2026-07-05): the knobs phase 1 never swept — retest TARGET mode, volume
        # confirmation, min-pullback depth, pullback timeout. cd/stale/retest stay at each
        # asset's ADOPTED values (the champion) so wins here are purely additive.
        return [{"mode": m, "volx": vx, "minpb": pb, "timeout": to}
                for m in ("edge", "impulse_mid", "vwap")
                for vx in (0.0, 1.2, 1.5)
                for pb in (0.05, 0.10)
                for to in (5, 8)]
    if quick:
        return [{"ctx": c, "cooldown": cd, "stale": 24, "retest": 0.5}
                for c in (True, False) for cd in (0, 3, 5, 8)]
    return [{"ctx": c, "cooldown": cd, "stale": st, "retest": rt}
            for c in (True, False) for cd in (0, 3, 5)
            for st in (0, 12, 24) for rt in (0.25, 0.5, 0.75)]


def load(sym: str, tf: str = "5m") -> pd.DataFrame:
    if tf != "5m":                    # multi-TF lineage: canonical loader resamples causally
        from bot.strategy.orb_candidates import load_state
        d = load_state(sym, tf)
        d.attrs["sym"] = sym
        return d
    con = hs_db.connect()
    bars = B._externals(con, hs_db.bars(con, "5m", "rth", sym=sym), sym)
    con.close()
    d = H.compute_state(bars, H.P(struct_lb_fix=struct_lb(sym)))
    d.attrs["sym"] = sym
    return d


def _ctx_arrays(d):
    st = d["st_state"].to_numpy(); cl = d["close"].to_numpy(float)
    vw = d["vwap_sess"].to_numpy(float)
    with np.errstate(invalid="ignore"):
        return (st == 1) & (cl > vw), (st == 2) & (cl < vw)


def run_combo(d, ctx_up, ctx_dn, p: dict) -> pd.DataFrame:
    """Missing keys fall back to the adopted standard (phase-2 combos fix cd/stale/retest and
    vary mode/volx/minpb/timeout instead)."""
    if p.get("ctx", True):
        d["trend_up"], d["trend_down"] = ctx_up, ctx_dn
    else:
        d["trend_up"] = True
        d["trend_down"] = True
    return B.backtest(d, "tp2_full", "both", False, "orb", 0, T1, T2, ORS, ORE, 0.0, CUT, "close",
                      eod_min=EOD, stop_mode="struct", entry_delay=DELAY,
                      strong_body=STRONG, ft_confirm=True, dir_seq=True,
                      watch_live=True, cooldown_bars=p.get("cooldown", ES.cooldown_bars),
                      stale_bars=p.get("stale", ES.stale_bars),
                      retest_atr=p.get("retest", ES.retest_atr),
                      retest_mode=p.get("mode", ES.retest_mode),
                      min_pullback_atr=p.get("minpb", ES.min_pullback_atr),
                      pullback_timeout=p.get("timeout", ES.pullback_timeout),
                      vol_confirm_x=p.get("volx", ES.vol_confirm_x))


def metrics(tr: pd.DataFrame) -> dict:
    if not len(tr):
        return {"trades": 0, "avg_r": None, "total_r": 0.0, "pf": None, "max_dd_r": 0.0}
    r = tr["net_R"].to_numpy(float)
    wins, losses = r[r > 0], r[r <= 0]
    pf = float(wins.sum() / abs(losses.sum())) if len(losses) and losses.sum() != 0 else None
    eq = np.cumsum(r)
    return {"trades": int(len(r)), "avg_r": round(float(r.mean()), 3),
            "total_r": round(float(r.sum()), 1),
            "pf": round(pf, 2) if pf else None,
            "max_dd_r": round(float((eq - np.maximum.accumulate(eq)).min()), 1)}


def sweep_symbol(sym: str, combos: list[dict], tf: str = "5m") -> dict:
    d = load(sym, tf)
    ctx_up, ctx_dn = _ctx_arrays(d)
    cutoff = pd.Timestamp(d["ts"].iloc[int(CUTOFF_FRAC * len(d))])
    rows = []
    _a = asset_config(sym)                        # per-asset adopted overrides ARE the default
    default_p = {"ctx": _a.ctx_gate,
                 "cooldown": _a.cooldown_bars if _a.cooldown_bars is not None else ES.cooldown_bars,
                 "stale": _a.stale_bars if _a.stale_bars is not None else ES.stale_bars,
                 "retest": _a.retest_atr if _a.retest_atr is not None else ES.retest_atr}
    for k, p in enumerate([default_p] + combos):
        p = {**default_p, **p}                # combos inherit the asset's ADOPTED baseline knobs
        tr = run_combo(d, ctx_up, ctx_dn, p)
        ets = pd.to_datetime(tr["entry_time"]) if len(tr) else pd.Series([], dtype="datetime64[ns]")
        m_is = metrics(tr[ets < cutoff] if len(tr) else tr)
        m_oos = metrics(tr[ets >= cutoff] if len(tr) else tr)
        rows.append({"params": p, "is": m_is, "oos": m_oos, "default": k == 0})
        print(f"  [{k:3}/{len(combos)}] {p} IS avg {m_is['avg_r']} n{m_is['trades']} | "
              f"OOS avg {m_oos['avg_r']} n{m_oos['trades']}", flush=True)
    default_row = rows[0]
    ranked = sorted((r for r in rows[1:] if r["is"]["trades"] >= MIN_IS_TRADES
                     and r["is"]["avg_r"] is not None),
                    key=lambda r: -r["is"]["avg_r"])
    best = ranked[0] if ranked else None
    verdict = None
    if best is not None:
        b_oos, d_oos = best["oos"].get("avg_r"), default_row["oos"].get("avg_r")
        if b_oos is not None and d_oos is not None:
            verdict = ("candidate — best-IS combo also beats the default OUT-OF-SAMPLE "
                       "(re-verify on the full gauntlet before adopting)"
                       if b_oos > d_oos else
                       "keep default — the best-IS combo does NOT hold out-of-sample (curve-fit)")
    return {"cutoff": str(cutoff)[:10], "min_is_trades": MIN_IS_TRADES,
            "default": default_row, "best_is": best, "top5_is": ranked[:5],
            "verdict": verdict, "n_ranked": len(ranked),
            # FULL DETAIL — exactly what was used and how (user requirement 2026-07-05)
            "used": {"symbol": sym, "timeframe": tf, "session": "rth",
                     "bars": int(len(d)),
                     "data_span": [str(d['ts'].iloc[0])[:10], str(d['ts'].iloc[-1])[:10]],
                     "rank_window": f"first {int(CUTOFF_FRAC*100)}% (in-sample, min {MIN_IS_TRADES} trades)",
                     "judge_window": f"last {100-int(CUTOFF_FRAC*100)}% (out-of-sample vs the default)",
                     "grid_dims": "ctx x cooldown{0,3,5} x stale{0,12,24} x retest{0.25,0.5,0.75}",
                     "fixed": "watch on · chase 1.0 ATR · strong-body 0.25 · ft-confirm · dir-seq · "
                              "OR-mid bias · vol-exp width · struct stop · 4R cap · EOD flat",
                     "cost_model": "per-asset commissions + slippage (engine defaults)"}}


def main(syms: list[str], quick: bool = False, phase2: bool = False, tf: str = "5m") -> dict:
    combos = grid(quick, phase2)
    tag = ("@p2" if phase2 else "") + (f"@{tf}" if tf != "5m" else "")
    prev = {}
    if REPORT.exists():                          # merge: per-symbol runs accumulate, never clobber
        try:
            prev = json.loads(REPORT.read_text(encoding="utf-8")).get("symbols", {})
        except Exception:
            prev = {}
    out = {"generated_at": pd.Timestamp.now("UTC").isoformat(), "grid_size": len(combos),
           "cutoff_frac": CUTOFF_FRAC, "symbols": prev}
    REPORT.parent.mkdir(parents=True, exist_ok=True)
    for sym in syms:
        print(f"\n=== SWEEP{tag} {sym} ({len(combos)} combos + default) ===", flush=True)
        try:
            out["symbols"][sym + tag] = sweep_symbol(sym, combos, tf)
        except Exception as e:
            out["symbols"][sym + tag] = {"error": str(e)[:200]}
            print(f"  ERROR {e}")
            continue
        s = out["symbols"][sym + tag]
        print(f"  DEFAULT {s['default']['params']} -> OOS avg {s['default']['oos']['avg_r']}")
        if s["best_is"]:
            print(f"  BEST-IS {s['best_is']['params']} -> OOS avg {s['best_is']['oos']['avg_r']}")
        print(f"  VERDICT: {s['verdict']}")
        REPORT.write_text(json.dumps(out, indent=1), encoding="utf-8")   # incremental per symbol
    print(f"\nsaved -> {REPORT}")
    return out


if __name__ == "__main__":
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    _tf = next((a.split("=", 1)[1] for a in sys.argv[1:] if a.startswith("--tf=")), "5m")
    main([s.upper() for s in (args or ["QQQ", "SPY", "NQ", "ES"])],
         quick="--quick" in sys.argv, phase2="--phase2" in sys.argv, tf=_tf)
