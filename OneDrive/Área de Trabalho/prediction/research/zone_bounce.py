#!/usr/bin/env python3
"""ZONE-BOUNCE step 2 — the bounce-vs-reversal machine as an ENTRY family (F67 follow-up).

Step 1 passed honestly (scored MAJOR/STRONG zones beat random in-range levels on NQ + ES).
This is the deferred step 2: do zone REACTIONS make a tradeable ENTRY?

Rule (long; short = exact mirror):
  form   : zones from the first 90 completed RTH 1m bars (post-OR), MAJOR/STRONG only
  touch  : price comes DOWN into a zone (support test — prior close above the zone)
  trigger: the six-check ReversalStateMachine (sign=+1), fed from 40 bars before the touch,
           reaches REVERSAL_CANDIDATE or REVERSAL_CONFIRMED within 15 bars of the touch
  entry  : that bar's close · stop = zone edge − 0.5×ATR(form) · target = +2R · EOD flat
  one position at a time; costs 2 ticks + commission (futures) / 2c (equities) round trip.

Gauntlet (four-families gate): exp>0 net costs AND bootstrap CIlo>0 AND >=70% yrs+ AND
70/30 OOS>0 AND both sides>0.

    .venv/Scripts/python research/zone_bounce.py NQ ES QQQ
Report -> BOT/data/ml/reports/zone_bounce.json
"""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "engine"))
sys.path.insert(0, str(ROOT / "research"))
os.chdir(ROOT)

from orb_liquidity_zones import detect_zones, ReversalStateMachine, _atr  # noqa: E402

REPORT = ROOT / "BOT" / "data" / "ml" / "reports" / "zone_bounce.json"
COST = {"NQ": 0.65, "ES": 0.56, "QQQ": 0.02, "SPY": 0.02}   # round trip, instrument units
FORM_BARS, CONFIRM_WIN, LOOKBACK = 90, 15, 40


def day_trades(g: pd.DataFrame, sym: str) -> list:
    """All bounce trades for one RTH day of 1m bars (returns list of dicts with net R)."""
    if len(g) < FORM_BARS + 60:
        return []
    form, test = g.iloc[:FORM_BARS], g.iloc[FORM_BARS:].reset_index(drop=True)
    zs = [z for z in detect_zones(form, sym=sym) if z["label"] in ("MAJOR", "STRONG")]
    if not zs:
        return []
    atr = _atr(form["high"].to_numpy(float), form["low"].to_numpy(float),
               form["close"].to_numpy(float))
    if not np.isfinite(atr) or atr <= 0:
        return []
    o = test["open"].to_numpy(float); h = test["high"].to_numpy(float)
    lo = test["low"].to_numpy(float); c = test["close"].to_numpy(float)
    cost = COST.get(sym.upper(), 0.05)
    trades = []
    busy_until = -1
    for z in zs:
        touched = np.where((lo <= z["high"]) & (h >= z["low"]))[0]
        if not len(touched):
            continue
        i0 = int(touched[0])
        if i0 <= 1 or i0 <= busy_until:
            continue
        if c[i0 - 1] > z["high"]:            # approached from ABOVE -> support test -> long
            sign = 1
            stop = z["low"] - 0.5 * atr
        elif c[i0 - 1] < z["low"]:           # from BELOW -> resistance test -> short
            sign = -1
            stop = z["high"] + 0.5 * atr
        else:
            continue
        rsm = ReversalStateMachine(sign=sign)
        for k in range(max(0, i0 - LOOKBACK), i0):
            rsm.update(o[k], h[k], lo[k], c[k])
        ei = None
        for k in range(i0, min(i0 + CONFIRM_WIN, len(c))):
            st = rsm.update(o[k], h[k], lo[k], c[k])
            if sign * (c[k] - stop) <= 0:    # stopped out of the setup before confirming
                break
            if st in ("REVERSAL_CANDIDATE", "REVERSAL_CONFIRMED"):
                ei = k
                break
        if ei is None:
            continue
        entry = c[ei]
        risk = sign * (entry - stop)
        if risk <= 0.05 * atr:
            continue
        tgt = entry + sign * 2.0 * risk
        res = None
        for k in range(ei + 1, len(c)):
            adverse = lo[k] if sign == 1 else h[k]
            favor = h[k] if sign == 1 else lo[k]
            if sign * (adverse - stop) <= 0:
                res = -risk; busy_until = k; break
            if sign * (favor - tgt) >= 0:
                res = 2.0 * risk; busy_until = k; break
        if res is None:
            res = sign * (c[-1] - entry); busy_until = len(c)
        trades.append({"dir": sign, "r": (res - cost) / risk})
    return trades


def study(sym: str) -> dict:
    import hs_db
    con = hs_db.connect()
    try:
        df = con.execute(f"SELECT * FROM {sym.lower()}_1m ORDER BY 1").df()
    except Exception as e:
        con.close()
        return {"error": f"no continuous 1m view ({str(e)[:80]})"}
    con.close()
    tcol = next((x for x in ("ts_et", "ts_utc", "ts") if x in df.columns), df.columns[0])
    ts = pd.to_datetime(df[tcol], utc=(tcol != "ts_et"))
    ts = ts.dt.tz_convert("America/New_York") if ts.dt.tz is not None else ts
    df = df.assign(_d=ts.dt.date, _m=ts.dt.hour * 60 + ts.dt.minute, _y=ts.dt.year)
    rth = df[(df["_m"] >= 570) & (df["_m"] < 960)]
    rows = []
    for day, g in rth.groupby("_d"):
        for t in day_trades(g.reset_index(drop=True), sym):
            rows.append({**t, "year": pd.Timestamp(day).year, "day": str(day)})
    if len(rows) < 30:
        return {"error": f"only {len(rows)} trades"}
    r = np.array([t["r"] for t in rows])
    dirs = np.array([t["dir"] for t in rows])
    years = pd.Series(r).groupby([t["year"] for t in rows]).mean()
    yrs_ok = [(y, v) for y, v in years.items() if (np.array([t["year"] for t in rows]) == y).sum() >= 8]
    pos = sum(1 for _, v in yrs_ok if v > 0)
    cut = int(0.7 * len(r))
    rng = np.random.default_rng(7)
    ci = float(np.percentile(rng.choice(r, (2000, len(r)), replace=True).mean(1), 5))
    L, S = r[dirs == 1], r[dirs == -1]
    both = len(L) > 5 and L.mean() > 0 and len(S) > 5 and S.mean() > 0
    gate = bool(r.mean() > 0 and ci > 0 and yrs_ok and pos >= 0.7 * len(yrs_ok)
                and r[cut:].mean() > 0 and both)
    wins, losses = r[r > 0], r[r <= 0]
    return {"n": int(len(r)), "exp_r": round(float(r.mean()), 3),
            "pf": round(float(wins.sum() / abs(losses.sum())), 2) if len(losses) else None,
            "win_pct": round(100 * float((r > 0).mean()), 1), "ci_lo": round(ci, 3),
            "long_avg": round(float(L.mean()), 3) if len(L) else None,
            "short_avg": round(float(S.mean()), 3) if len(S) else None,
            "years_pos": f"{pos}/{len(yrs_ok)}",
            "oos30_avg": round(float(r[cut:].mean()), 3), "gate": "PASS" if gate else "fail"}


def main(syms):
    out = {"generated_at": pd.Timestamp.now("UTC").isoformat(),
           "rule": "MAJOR/STRONG zone touch + six-check reversal machine confirm -> bounce, "
                   "stop 0.5ATR beyond zone, 2R target, EOD flat", "symbols": {}}
    REPORT.parent.mkdir(parents=True, exist_ok=True)
    for sym in syms:
        print(f"=== ZONE BOUNCE {sym} ===", flush=True)
        out["symbols"][sym] = study(sym)
        s = out["symbols"][sym]
        print(f"  {s}" if "error" in s else
              f"  n {s['n']} exp {s['exp_r']:+.3f}R PF {s['pf']} win {s['win_pct']}% "
              f"CIlo {s['ci_lo']:+.3f} L{s['long_avg']}/S{s['short_avg']} yr+{s['years_pos']} "
              f"OOS {s['oos30_avg']:+.3f} -> {s['gate']}", flush=True)
        REPORT.write_text(json.dumps(out, indent=1), encoding="utf-8")
    print(f"saved -> {REPORT}")


if __name__ == "__main__":
    main([s.upper() for s in (sys.argv[1:] or ["NQ", "ES"])])
