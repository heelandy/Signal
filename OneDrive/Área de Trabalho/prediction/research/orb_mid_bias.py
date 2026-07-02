#!/usr/bin/env python3
"""OR-MID BIAS filter test — does trading only WITH the opening-range's own bias help?
Bias per day = the OR closed in its UPPER half (close of the 09:55 bar > OR-mid) => day biased LONG; lower
half => biased SHORT. Filter keeps trades ALIGNED with that bias, drops counter-bias. Same validated ORB
config (delay-0, chase-cap, struct stop, cap-4R). Gauntlet + ADDITIVITY (are the DROPPED trades the losers?).

    python research/orb_mid_bias.py NQ        (one symbol per process)
"""
import sys, os, gc
sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "engine"))
import numpy as np, pandas as pd
import hs_db, hs_harness as H, hs_backtest as B, hs_validate as V

_rng = np.random.default_rng(7)
def ci_lo(r, n=1500):
    return float(np.percentile(_rng.choice(r, size=(n, len(r)), replace=True).mean(axis=1), 5)) if len(r) >= 10 else float("nan")
def yr(tr):
    t = tr.copy(); t["y"] = pd.to_datetime(t["entry_time"], utc=True).dt.tz_convert("America/New_York").dt.year
    g = t.groupby("y")["net_R"].mean(); return int((g > 0).sum()), len(g)
def oos(tr):
    r = tr.sort_values("entry_time")["net_R"].to_numpy(); k = int(len(r) * 0.7)
    return (r[:k].mean(), r[k:].mean()) if (k >= 5 and len(r) - k >= 5) else (float("nan"), float("nan"))
def line(tag, tr):
    r = tr["net_R"].to_numpy()
    if len(r) < 20: print(f"  {tag:22} n={len(r):>4}  (too few)"); return
    L = tr.net_R[tr.direction == "long"].to_numpy(); S = tr.net_R[tr.direction == "short"].to_numpy()
    lo = ci_lo(r); p, ny = yr(tr); is_, oo = oos(tr)
    both = len(L) > 5 and L.mean() > 0 and len(S) > 5 and S.mean() > 0
    g = "PASS" if (lo > 0 and both and ny and p >= 0.7 * ny and oo > 0) else "----"
    print(f"  {tag:22} n={len(r):>4} exp {r.mean():+.3f} PF {V.pf(r):>4.2f} win {100*np.mean(r>0):>2.0f}% "
          f"CIlo {lo:+.3f} L{(L.mean() if len(L) else 0):+.2f} S{(S.mean() if len(S) else 0):+.2f} yr+{p}/{ny} OOS{is_:+.2f}/{oo:+.2f} {g}")


def or_bias(d):
    """per-day OR-close bias: or_bull = (last OR-bar close > OR-mid). RTH OR 09:30-10:00 (570-600 ET min)."""
    et = pd.to_datetime(d["ts"]).dt.tz_convert("America/New_York")
    hm = (et.dt.hour * 60 + et.dt.minute).to_numpy()
    day = et.dt.date.to_numpy()
    df = pd.DataFrame({"day": day, "hm": hm, "h": d["high"].to_numpy(), "l": d["low"].to_numpy(), "c": d["close"].to_numpy()})
    w = df[(df["hm"] >= 570) & (df["hm"] < 600)]
    out = {}
    for dd, g in w.groupby("day"):
        if len(g) < 2:
            continue
        omid = (g["h"].max() + g["l"].min()) / 2.0
        oclose = g.sort_values("hm")["c"].iloc[-1]
        out[dd] = bool(oclose > omid)
    return out


def main():
    sym = (sys.argv[1] if len(sys.argv) > 1 else "NQ").upper()
    con = hs_db.connect()
    d = H.compute_state(B._externals(con, hs_db.bars(con, "5m", "rth", sym=sym), sym), H.P()); d.attrs["sym"] = sym
    con.close()
    st = d["st_state"].to_numpy(); d["trend_up"] = (st == 1); d["trend_down"] = (st == 2)
    tr = B.backtest(d, "tp2_full", "both", False, "orb", 0, 1.0, 4.0, 570, 600, 0.0, 900, "close", eod_min=958,
                    stop_mode="struct", entry_delay=0, chase_atr=1.0, strong_body=0.25, ft_confirm=True)
    bias = or_bias(d)
    tr = tr.copy()
    tr["day"] = pd.to_datetime(tr["entry_time"], utc=True).dt.tz_convert("America/New_York").dt.date
    tr["or_bull"] = tr["day"].map(bias)
    tr = tr[tr["or_bull"].notna()]                              # only days with a defined OR bias
    aligned = ((tr.direction == "long") & (tr.or_bull)) | ((tr.direction == "short") & (~tr.or_bull.astype(bool)))
    kept = tr[aligned]; dropped = tr[~aligned]
    print(f"\n{'='*96}\n{sym}  OR-MID BIAS filter (trade only WITH the OR's closing-half bias)\n{'='*96}")
    line("ALL (no bias)", tr)
    line("BIAS-aligned (kept)", kept)
    print(f"  --- ADDITIVITY: were the DROPPED (counter-bias) trades the losers? ---")
    line("DROPPED (counter-bias)", dropped)
    print("  KEY: bias helps only if KEPT beats ALL and DROPPED is the dead/negative cohort. gate PASS = "
          "CIlo>0 & both sides>0 & >=70% yrs+ & OOS>0.")
    del d; gc.collect()


if __name__ == "__main__":
    main()
