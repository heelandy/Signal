"""WORKER LOSER-VETO — step 4 of docs/BOSS_WORKERS_PLAN.md.

ONE pooled model (QQQ+SPY+NQ, symbol one-hots) learns P(loser) over the tight-target trade
stream from the 59-feature PIT snapshots; per worker the veto is judged with its adopted tier:

  worker Q: b=0.40 + slope-STRONG tier    worker S: b=0.33 (no tier)    worker N: b=0.30 + early-only

Honesty: model + thresholds fit on IS (first 70% per symbol) ONLY; OOS judges. Deploy gate
(plan §2): veto cost <= 25% of signals, OOS WR lift >= +3pts OR OOS PF band reached, and the
2x-cost stress (net2 = 2*net - gross, doubles ALL frictions) must keep PF >= 1.4.

    .venv/Scripts/python research/worker_veto.py
Report -> BOT/data/ml/reports/worker_veto.json
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
from bot.ml.registry import FeatureStore  # noqa: E402
from bot.ml.dataset import _store_name, _version_slug  # noqa: E402
from bot.ml.features_pit import FEATURE_COLUMNS  # noqa: E402
from worker_cohorts import masks_for, run_cell, split_stats  # noqa: E402
from worker_specs import stats, in_band  # noqa: E402

REPORT = ROOT / "BOT" / "data" / "ml" / "reports" / "worker_veto.json"
WORKERS = {"QQQ": {"b": 0.40, "tier": "slope_strong"},
           "SPY": {"b": 0.33, "tier": None},
           "NQ":  {"b": 0.30, "tier": "early_only"}}
MAX_COST = 0.25          # veto may remove at most 25% of signals
SYMS = list(WORKERS)


def joined_trades(sym: str, b: float, skip_mask=None):
    """Tight-target trades joined to their PIT feature rows by entry minute (ns-normalized)."""
    d = load_state(sym)
    tr = run_cell(d, b, skip_mask=skip_mask)
    ds = FeatureStore().load(_store_name(sym, "5m"), _version_slug())
    ds = ds.copy()
    ds["_k"] = pd.to_datetime(ds["ts"], utc=True).astype("datetime64[ns, UTC]")
    tr = tr.copy()
    tr["_k"] = pd.to_datetime(tr["entry_time"], utc=True).astype("datetime64[ns, UTC]")
    cols = [c for c in FEATURE_COLUMNS if c in ds.columns]
    j = tr.merge(ds[["_k", *cols]], on="_k", how="left")
    have = j[cols].notna().any(axis=1)
    return j, cols, float(have.mean())


def xmat(j: pd.DataFrame, cols: list[str], sym: str) -> np.ndarray:
    X = j[cols].to_numpy(float)
    med = np.nanmedian(X, axis=0)
    X = np.where(np.isfinite(X), X, np.where(np.isfinite(med), med, 0.0))
    hot = np.zeros((len(j), len(SYMS)))
    hot[:, SYMS.index(sym)] = 1.0
    return np.hstack([X, hot])


def main():
    import lightgbm as lgb
    out = {"generated_at": pd.Timestamp.now("UTC").isoformat(), "workers": WORKERS,
           "pooled_train": {}, "verdicts": {}}
    REPORT.parent.mkdir(parents=True, exist_ok=True)

    # ── pooled training set: BASE streams (no tier), IS 70% per symbol ──
    packs = {}
    Xtr, ytr = [], []
    for sym, w in WORKERS.items():
        j, cols, match = joined_trades(sym, w["b"])
        cut = int(0.7 * len(j))
        packs[sym] = {"j": j, "cols": cols, "cut": cut}
        Xtr.append(xmat(j.iloc[:cut], cols, sym))
        ytr.append((j["net_R"].to_numpy(float)[:cut] <= 0).astype(int))
        out["pooled_train"][sym] = {"n": len(j), "is_n": cut, "feature_match": round(match, 3)}
        print(f"{sym}: {len(j)} trades, feature match {match:.1%}", flush=True)
    X, y = np.vstack(Xtr), np.concatenate(ytr)
    model = lgb.LGBMClassifier(n_estimators=200, learning_rate=0.05, max_depth=3,
                               subsample=0.9, colsample_bytree=0.9, verbose=-1, random_state=7)
    model.fit(X, y)
    print(f"pooled veto trained on {len(y)} IS trades (loser rate {y.mean():.1%})", flush=True)

    # ── per-worker judgment: tier stream, veto threshold from IS, OOS judges ──
    for sym, w in WORKERS.items():
        d = load_state(sym)
        mask = masks_for(d).get(w["tier"]) if w["tier"] else None
        j, cols, match = joined_trades(sym, w["b"], skip_mask=mask)
        p = model.predict_proba(xmat(j, cols, sym))[:, 1]
        r = j["net_R"].to_numpy(float)
        g = j["gross_R"].to_numpy(float)
        cut = int(0.7 * len(j))
        base_is, base_oos = stats(r[:cut]), stats(r[cut:])
        base_stress = stats((2 * r - g)[cut:])           # 2x ALL frictions on the base stream
        base_band = in_band(base_is, dd_scale=2.33) and in_band(base_oos)
        # threshold: IS-only grid over quantiles; constraint cost<=25%; maximize IS PF with WR>=75
        best = None
        for q in np.arange(0.55, 0.96, 0.05):
            tau = float(np.quantile(p[:cut], q))
            keep_is = p[:cut] < tau
            if keep_is.mean() < 1 - MAX_COST:
                continue
            s = stats(r[:cut][keep_is])
            if s.get("n", 0) < 30 or s.get("pf") is None:
                continue
            score = (s["pf"], s["wr"] >= 75)
            if best is None or (score[1], score[0]) > (best[3], best[2]):
                best = (tau, q, s["pf"], s["wr"] >= 75)
        res = {"base": {"is": base_is, "oos": base_oos, "stress2x_oos": base_stress,
                        "band": base_band, "stress_ok": (base_stress.get("pf") or 0) >= 1.4},
               "feature_match": round(match, 3)}
        if best is None:
            res["verdict"] = "no admissible threshold on IS (cost cap) — veto NOT deployable"
        else:
            tau = best[0]
            keep = p < tau
            v_is, v_oos = stats(r[:cut][keep[:cut]]), stats(r[cut:][keep[cut:]])
            # 2x-cost stress on the OOS vetoed stream: net2 = 2*net - gross
            r2 = (2 * r - g)[cut:][keep[cut:]]
            s2 = stats(r2)
            cost = 1 - float(keep.mean())
            band = in_band(v_is, dd_scale=2.33) and in_band(v_oos)
            res["veto"] = {"tau": round(tau, 4), "cost": round(cost, 3),
                           "is": v_is, "oos": v_oos, "stress2x_oos": s2,
                           "band": band, "stress_ok": (s2.get("pf") or 0) >= 1.4,
                           "wr_lift_oos": round((v_oos.get("wr") or 0) - (base_oos.get("wr") or 0), 1)}
            res["verdict"] = ("BAND + STRESS PASS — freezable" if band and res["veto"]["stress_ok"]
                              else "band not reached" if not band else "band but FAILS 2x stress")
        out["verdicts"][sym] = res
        b = res.get("veto", {})
        print(f"{sym}: base OOS wr {base_oos.get('wr')} pf {base_oos.get('pf')} | veto "
              f"cost {b.get('cost')} OOS wr {(b.get('oos') or {}).get('wr')} "
              f"pf {(b.get('oos') or {}).get('pf')} dd {(b.get('oos') or {}).get('dd')} "
              f"stress2x pf {(b.get('stress2x_oos') or {}).get('pf')} -> {res['verdict']}", flush=True)
        REPORT.write_text(json.dumps(out, indent=1), encoding="utf-8")
    print(f"saved -> {REPORT}")


if __name__ == "__main__":
    main()
