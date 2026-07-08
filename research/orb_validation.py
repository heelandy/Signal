#!/usr/bin/env python3
"""
HIGHSTRIKE research — META / VALIDATION (Item 4). RESEARCH ONLY; reads the frozen engine's production
trade list. Two studies:

  A. FEATURE STUDY — for every taken trade, compute features known AT/BEFORE entry (no outcome leakage),
     then Spearman-correlate each with the trade's net_R. This finds *systematically* what predicts a
     good vs bad breakout instead of guessing one lever at a time. A feature is a real lead only if its
     sign is CONSISTENT across QQQ and NQ (one asset = noise). Categorical cuts (direction, day-of-week,
     regime) shown as expectancy tables.
  B. WALK-FORWARD — is the edge stable over time or one lucky regime? Per-year exp/PF/n, plus an
     out-of-sample split (first 70% of the calendar vs last 30%); both must stay positive.

    python research/orb_validation.py [SYM] [TF=15m]
"""
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "engine"))
import numpy as np, pandas as pd
import hs_backtest as B, hs_validate as V
from orb_optimize import state, metrics
from orb_entry_quality import day_levels, brk_for


def prod_trades(d, tf):
    return B.backtest(d, "scale_be", "both", False, "orb", 0, None, 4.0, 570, 600, brk_for(tf), 900, "stop")


def feature_table(d, tr):
    feat = d[["ts", "open", "high", "low", "close", "atr14", "vwap_sess"]].copy()
    feat["ts"] = pd.to_datetime(feat["ts"], utc=True)
    t = tr.copy(); t["entry_time"] = pd.to_datetime(t["entry_time"], utc=True)
    t = t.merge(feat, left_on="entry_time", right_on="ts", how="left", suffixes=("", "_bar"))
    et = t["entry_time"].dt.tz_convert("America/New_York")
    t["minute"] = et.dt.hour * 60 + et.dt.minute
    t["dow"] = et.dt.dayofweek
    t["year"] = et.dt.year
    t["date"] = et.dt.normalize().dt.tz_localize(None)
    t = t.merge(day_levels(d), on="date", how="left")
    sgn = np.where(t.direction == "long", 1.0, -1.0)
    rng = (t.high - t.low).replace(0, np.nan)
    t["entry_body"] = np.where(t.direction == "long", (t.close - t.low) / rng, (t.high - t.close) / rng)
    t["vwap_dist_atr"] = sgn * (t.entry_price - t.vwap_sess) / t.atr14   # + = entry is on the trade's side of VWAP
    t["atr_lvl"] = t.atr14
    t["dir_long"] = (t.direction == "long").astype(float)
    return t


NUMF = ["or_w_atr", "gap_atr", "atr_lvl", "minute", "vwap_dist_atr", "entry_body", "risk_pts", "dir_long"]


def run(sym, tf, store):
    d = state(sym, tf)
    tr = prod_trades(d, tf)
    t = feature_table(d, tr)
    print(f"\n{'='*72}\n{sym} {tf} — feature study (n={len(t)}, net_R outcome)\n{'='*72}")
    print("A) Spearman corr of each pre-entry feature with net_R (sign = helps if +):")
    cors = {}
    for f in NUMF:
        sub = t[[f, "net_R"]].dropna()
        c = sub[f].corr(sub["net_R"], method="spearman") if len(sub) > 30 else np.nan
        cors[f] = c
        print(f"  {f:16} corr={c:+.3f}  n={len(sub)}")
    store[sym] = cors
    print("B) Categorical expectancy:")
    for col, lbl in [("direction", "direction"), ("dow", "day-of-week (0=Mon)"), ("regime", "macro regime")]:
        print(f"  by {lbl}:")
        g = t.groupby(col)["net_R"].agg(["mean", "count"])
        for k, row in g.iterrows():
            print(f"    {str(k):14} exp={row['mean']:+.3f}  n={int(row['count'])}")
    # ---- walk-forward ----
    print("C) WALK-FORWARD — per-year stability:")
    g = t.groupby("year")["net_R"]
    yrs_pos = 0; yrs_tot = 0
    for y, r in g:
        rr = r.to_numpy()
        if len(rr) < 15:
            print(f"    {y}: n={len(rr):3} (thin)"); continue
        yrs_tot += 1; yrs_pos += rr.mean() > 0
        print(f"    {y}: n={len(rr):3} exp={rr.mean():+.3f} PF={V.pf(rr):.2f} win={100*np.mean(rr>0):4.1f}%")
    print(f"    -> {yrs_pos}/{yrs_tot} full years positive")
    # out-of-sample split by calendar
    t2 = t.sort_values("entry_time")
    cut = t2["entry_time"].quantile(0.70)
    ins = t2[t2.entry_time <= cut]["net_R"].to_numpy()
    oos = t2[t2.entry_time > cut]["net_R"].to_numpy()
    print(f"  OOS split @70%: IN  exp={ins.mean():+.3f} PF={V.pf(ins):.2f} n={len(ins)}  |  "
          f"OUT exp={oos.mean():+.3f} PF={V.pf(oos):.2f} n={len(oos)}  "
          f"-> {'HOLDS' if oos.mean() > 0 else 'FAILS oos'}")


def main():
    tf = sys.argv[2] if len(sys.argv) > 2 else "15m"
    syms = [sys.argv[1]] if len(sys.argv) > 1 else ["QQQ", "NQ", "SPY"]
    store = {}
    for s in syms:
        run(s, tf, store)
    if len(store) > 1:
        print(f"\n{'='*72}\nCROSS-ASSET feature consistency (a lead is real only if sign agrees):\n{'='*72}")
        feats = NUMF
        print(f"  {'feature':16} " + " ".join(f"{s:>8}" for s in store))
        for f in feats:
            vals = [store[s].get(f, np.nan) for s in store]
            signs = {np.sign(v) for v in vals if not np.isnan(v)}
            tag = "CONSISTENT" if len(signs) == 1 else "flips"
            print(f"  {f:16} " + " ".join(f"{v:+8.3f}" for v in vals) + f"   {tag}")


if __name__ == "__main__":
    main()
