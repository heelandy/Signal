#!/usr/bin/env python3
"""
F54 — SUPERVISED ML / learned combiner: can a gradient-boosted classifier on engineered OHLCV+VIX features
predict NEXT-DAY direction OUT-OF-SAMPLE better than the base rate (the majority "up" class)? Equities drift
up, so a model that always says "up" wins ~54%; the ML must BEAT that and produce a tradeable timing edge.

Honesty rails:
- every feature is causal (computed from bars <= t); target = sign of close[t+1]/close[t]-1.
- WALK-FORWARD: for each test year Y, train ONLY on data < Y, predict Y. No in-sample evaluation, ever.
- report OOS directional accuracy vs the base rate, and the trading gauntlet (enter close[t]->exit close[t+1],
  net of costs), and the buy&hold benchmark. Edge counts only if accuracy > base rate AND the strategy passes.

    python research/strat_ml.py [SYM ...]      (default NQ ES QQQ SPY GC)
"""
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "engine"))
import numpy as np, pandas as pd
import hs_db, hs_validate as V
from sklearn.ensemble import HistGradientBoostingClassifier

EQ = {"QQQ", "SPY"}


def rsi(c, n):
    s = pd.Series(c); d = s.diff()
    up = d.clip(lower=0).rolling(n, min_periods=n).mean(); dn = (-d.clip(upper=0)).rolling(n, min_periods=n).mean()
    return (100 - 100 / (1 + up / dn.replace(0, np.nan))).to_numpy()


def features(d, vix):
    c, h, l, o, v = (d[x].to_numpy(float) for x in ("close", "high", "low", "open", "volume"))
    s = pd.Series(c); f = pd.DataFrame(index=d.index)
    for n in (1, 2, 3, 5, 10):
        f[f"r{n}"] = s.pct_change(n)
    f["rsi2"] = rsi(c, 2); f["rsi14"] = rsi(c, 14)
    for n in (5, 20, 50, 200):
        f[f"sma{n}d"] = c / s.rolling(n).mean() - 1
    tr = np.maximum(h - l, np.maximum(np.abs(h - np.r_[c[0], c[:-1]]), np.abs(l - np.r_[c[0], c[:-1]])))
    f["atr_pct"] = pd.Series(tr).rolling(14).mean().to_numpy() / c
    f["rng_pct"] = (h - l) / c
    f["gap"] = o / np.r_[c[0], c[:-1]] - 1
    f["vol_z"] = v / pd.Series(v).rolling(20).mean().to_numpy() - 1
    f["dow"] = pd.to_datetime(d["ts"], utc=True).dt.dayofweek.to_numpy()
    m = d.merge(vix, left_on=pd.to_datetime(d["ts"], utc=True).dt.normalize().dt.tz_localize(None),
                right_on="date", how="left")
    f["vix"] = m["vix_close"].to_numpy(); f["vix_rel"] = m["vix_close"].to_numpy() / m["vix_sma5"].to_numpy() - 1
    f["ret_fwd"] = s.shift(-1) / s - 1                              # TARGET return (next day)
    f["dt"] = pd.to_datetime(d["ts"], utc=True)
    return f


def run(sym, d, vix, band=0.0):
    f = features(d, vix).dropna(subset=["ret_fwd"]).copy()
    Xcols = [c for c in f.columns if c not in ("ret_fwd", "dt")]
    f["y"] = (f["ret_fwd"] > 0).astype(int)
    f["year"] = f["dt"].dt.year
    cost = (2 * 0.01) / d["close"].mean() if sym in EQ else (2 * 0.25 * 2 + 2 * 0.52 / 2.0) / d["close"].mean()
    years = sorted(f["year"].unique())
    start = years[min(4, len(years) - 1)]                          # need >=4y to train the first fold
    rows = []
    for Y in [y for y in years if y >= start]:
        tr = f[f["year"] < Y]; te = f[f["year"] == Y]
        if len(tr) < 250 or len(te) < 20: continue
        clf = HistGradientBoostingClassifier(max_depth=3, max_iter=200, learning_rate=0.05,
                                             l2_regularization=1.0, random_state=7)
        clf.fit(tr[Xcols], tr["y"])
        p = clf.predict_proba(te[Xcols])[:, 1]
        sig = np.where(p > 0.5 + band, 1, np.where(p < 0.5 - band, -1, 0))
        te = te.assign(p=p, sig=sig)
        rows.append(te)
    if not rows: return
    R = pd.concat(rows)
    traded = R[R["sig"] != 0]
    acc = np.mean((R["p"] > 0.5).astype(int) == R["y"])            # raw directional accuracy (all days)
    base = max(R["y"].mean(), 1 - R["y"].mean())                   # majority-class base rate
    strat = traded["sig"] * traded["ret_fwd"] - cost
    bh = R["ret_fwd"].mean()
    yrs = [(y, (g["sig"] * g["ret_fwd"] - cost).mean()) for y, g in traded.groupby("year") if len(g) >= 10]
    pos = sum(1 for _, e in yrs if e > 0); tot = len(yrs)
    sh = strat.mean() / strat.std() * np.sqrt(252) if strat.std() > 0 else 0
    g = "PASS" if (acc > base + 0.005 and strat.mean() > 0 and tot and pos >= 0.7 * tot) else "fail"
    print(f"  {sym:4} OOS acc {100*acc:.1f}% vs base {100*base:.1f}%  | traded {len(traded)}/{len(R)} "
          f"ret/t {100*strat.mean():+.3f}% Sharpe {sh:+.2f} yr+{pos}/{tot} | B&H/day {100*bh:+.3f}% {g}")


def main():
    syms = [s.upper() for s in (sys.argv[1:] or ["NQ", "ES", "QQQ", "SPY", "GC"])]
    con = hs_db.connect()
    vix = con.execute("SELECT date, sma5 AS vix_sma5, close AS vix_close FROM vix_daily ORDER BY date").df()
    vix["date"] = pd.to_datetime(vix["date"])
    print("walk-forward (train years<Y, predict Y); edge only if OOS acc > base rate AND strat passes:")
    for sym in syms:
        d = hs_db.bars(con, "1d", "rth", sym=sym).sort_values("ts").reset_index(drop=True)
        run(sym, d, vix)
    con.close()
    print("\nNOTE: acc <= base rate = the model adds NO directional info over 'predict the majority class'.")


if __name__ == "__main__":
    main()
