#!/usr/bin/env python3
"""
RESEARCH (F44 candidate) — STATISTICAL family (agenda item 4, lowest prior — most curve-fit-prone). Honest
SCREEN first on the stack's residual trades: day-of-week + month expectancy + two causal day-context
conditioners, with the hard cross-asset-consistency requirement (a 'stat edge' counts ONLY if the same
day/sign is best/worst across NQ+QQQ+SPY). F15 already flagged Friday as curve-fit. Escalate to the full
gate+additivity gauntlet ONLY if something is genuinely sign-consistent + strong.

  dow / month        — calendar seasonality (the classic curve-fit traps)
  pday_align         — does the breakout align with the PRIOR RTH day's direction? (sgn(dir)*sgn(prevret))
  pday_range_atr     — prior RTH day's range / ATR (was yesterday a big mover?)

    python research/orb_stack_stat.py
"""
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "engine"))
import numpy as np, pandas as pd
import hs_db, hs_harness as H, hs_backtest as B, hs_validate as V

ORS, ORE, CUT, T1, T2, EOD, KCAP = 570, 600, 900, 1.0, 4.0, 958, 2.0
DOW = ["Mon", "Tue", "Wed", "Thu", "Fri"]


def stack_trades(d):
    st = d["st_state"].to_numpy(); d["trend_up"] = st == 1; d["trend_down"] = st == 2
    return B.backtest(d, "scale_be", "both", False, "orb", 0, T1, T2, ORS, ORE, 0.0, CUT, "stop",
                      eod_min=EOD, vwap_cap=KCAP)


def day_ctx(d):
    et = pd.to_datetime(d["ts"]).dt.tz_convert("America/New_York")
    date = et.dt.normalize().dt.tz_localize(None); mins = et.dt.hour * 60 + et.dt.minute
    base = pd.DataFrame({"date": date.to_numpy(), "c": d["close"].to_numpy(), "h": d["high"].to_numpy(),
                         "l": d["low"].to_numpy(), "atr": d["atr14"].to_numpy(), "mins": mins.to_numpy()})
    rth = base[(base.mins >= ORS) & (base.mins < 960)].groupby("date").agg(
        rc=("c", "last"), rh=("h", "max"), rl=("l", "min"), atr=("atr", "last"))
    rth["pret"] = rth["rc"].pct_change().shift(1)                  # prior-day RTH return
    rth["prange"] = ((rth["rh"] - rth["rl"]) / rth["atr"]).shift(1)  # prior-day range / ATR
    return rth[["pret", "prange"]].reset_index()


def main():
    syms = [s.upper() for s in (sys.argv[1:] or ["NQ", "QQQ", "SPY"])]
    con = hs_db.connect(); dow_store = {}
    for sym in syms:
        bars = B._externals(con, hs_db.bars(con, "5m", "full", sym=sym), sym)
        d = H.compute_state(bars, H.P()); d.attrs["sym"] = sym
        tr = stack_trades(d)
        et = pd.to_datetime(tr["entry_time"], utc=True).dt.tz_convert("America/New_York")
        tr["dow"] = et.dt.dayofweek; tr["month"] = et.dt.month
        tr["date"] = et.dt.normalize().dt.tz_localize(None)
        tr = tr.merge(day_ctx(d), on="date", how="left")
        sgn = np.where(tr.direction == "long", 1.0, -1.0)
        tr["pday_align"] = sgn * np.sign(tr["pret"].to_numpy())
        print(f"\n{'='*66}\n{sym} 5m STACK — statistical screen (n={len(tr)})\n{'='*66}")
        print("  by day-of-week:")
        dd = {}
        for k, g in tr.groupby("dow"):
            dd[int(k)] = g.net_R.mean()
            print(f"    {DOW[int(k)]:4} exp={g.net_R.mean():+.3f} PF={V.pf(g.net_R.to_numpy()):.2f} n={len(g)}")
        dow_store[sym] = dd
        print("  prior-day alignment (breakout vs prior RTH day direction):")
        for k, g in tr.groupby("pday_align"):
            lbl = {1.0: "with prev day", -1.0: "against prev day", 0.0: "flat prev"}.get(k, str(k))
            print(f"    {lbl:18} exp={g.net_R.mean():+.3f} PF={V.pf(g.net_R.to_numpy()):.2f} n={len(g)}")
        for f in ("pret", "prange"):
            sub = tr[[f, "net_R"]].replace([np.inf, -np.inf], np.nan).dropna()
            c = sub[f].corr(sub["net_R"], method="spearman") if len(sub) > 30 else np.nan
            print(f"  corr({f:6}, net_R) = {c:+.3f}")
    con.close()

    print(f"\n{'='*66}\nCROSS-ASSET DoW consistency (real only if same day best/worst on all):\n{'='*66}")
    print(f"  {'day':4} " + " ".join(f"{s:>8}" for s in syms))
    for i in range(5):
        vals = [dow_store[s].get(i, np.nan) for s in syms]
        print(f"  {DOW[i]:4} " + " ".join(f"{v:+8.3f}" for v in vals))
    best = [max(dow_store[s], key=dow_store[s].get) for s in syms]
    worst = [min(dow_store[s], key=dow_store[s].get) for s in syms]
    print(f"  best day per asset:  {[DOW[b] for b in best]}  {'CONSISTENT' if len(set(best)) == 1 else 'flips -> curve-fit'}")
    print(f"  worst day per asset: {[DOW[w] for w in worst]}  {'CONSISTENT' if len(set(worst)) == 1 else 'flips -> curve-fit'}")


if __name__ == "__main__":
    main()
