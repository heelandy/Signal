#!/usr/bin/env python3
"""
F53 — RANGE-DAY FADE: the regime-complementary strategy. The ORB stack SKIPS local_regime==2 (chop/low-ADX)
bars; this harvests them by FADING VWAP extension back to VWAP on exactly those bars. Mean-reversion, intraday.

Rules (short mirror of long): on a regime-2 RTH bar, if (close - vwap_sess)/atr >= k (stretched above VWAP),
SHORT at the close; target = the live session VWAP (cover when price returns to it), stop = entry + m*ATR,
flat at EOD. One position at a time, entries only in a mid-session window (time to revert).

Fills are conservative (your fill note): entry at the signal bar's CLOSE (market, no lookahead); VWAP-cover
fill at VWAP (a buy-limit that can only fill better on a gap); stop fill at the WORSE of {stop, next open}.

Gauntlet: exp R > 0 net of costs, bootstrap CI>0, both sides>0, >=70% yrs +, 70/30 OOS-out>0.

    python research/strat_rangefade.py [SYM ...]      (default NQ QQQ SPY ES)
"""
import sys, os, gc
sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "engine"))
import numpy as np, pandas as pd
import hs_db, hs_harness as H, hs_backtest as B, hs_validate as V
from hs_contracts import spec as _CS

rng = np.random.default_rng(7)
EQ = {"QQQ", "SPY"}


def cost_pts(sym):
    return (2 * 0.01) if sym in EQ else (2 * _CS(sym).tick * _CS(sym).slip_ticks * B.SLIP_MULT + 2 * _CS(sym).commission / _CS(sym).point_value)


def fade(d, k=1.5, m=1.5, win=(600, 870), eod=955):
    o, h, l, c = (d[x].to_numpy() for x in ("open", "high", "low", "close"))
    vw = d["vwap_sess"].to_numpy(); atr = d["atr14"].to_numpy(); reg = d["local_regime"].to_numpy()
    et = pd.to_datetime(d["ts"]).dt.tz_convert("America/New_York")
    mins = (et.dt.hour * 60 + et.dt.minute).to_numpy()
    daykey = (et.dt.year * 10000 + et.dt.month * 100 + et.dt.day).to_numpy()
    sym = d.attrs["sym"]; n = len(c); cR = cost_pts(sym)
    tr = []; i = 0
    while i < n:
        if reg[i] == 2 and atr[i] > 0 and not np.isnan(vw[i]) and win[0] <= mins[i] < win[1]:
            ext = (c[i] - vw[i]) / atr[i]
            side = -1 if ext >= k else (1 if ext <= -k else 0)
            if side != 0:
                entry = c[i]; risk = m * atr[i]
                stop = entry - side * risk; j = None; x = None
                for t in range(i + 1, n):
                    if daykey[t] != daykey[i] or mins[t] >= eod:           # EOD flat at the open
                        x = o[t]; j = t; break
                    hit_stop = (h[t] >= stop) if side == -1 else (l[t] <= stop)
                    hit_tgt = (l[t] <= vw[t]) if side == -1 else (h[t] >= vw[t])  # back to VWAP
                    if hit_stop and hit_tgt:                                # ambiguous bar -> stop first (conservative)
                        x = (max(stop, o[t]) if side == -1 else min(stop, o[t])); j = t; break
                    if hit_stop:
                        x = (max(stop, o[t]) if side == -1 else min(stop, o[t])); j = t; break  # gap-aware
                    if hit_tgt:
                        x = vw[t]; j = t; break                             # cover at VWAP
                if x is None: x = c[-1]; j = n - 1
                r = (side * (x - entry) - cR) / risk
                tr.append((et.iloc[i], side, r)); i = j + 1; continue
        i += 1
    return tr


def loci(r):
    return np.percentile(rng.choice(r, (2000, len(r)), replace=True).mean(1), 5) if len(r) > 1 else 0.0


def report(tag, tr):
    if len(tr) < 30:
        print(f"  {tag:16} n={len(tr)} (<30, skip)"); return
    df = pd.DataFrame(tr, columns=["dt", "dir", "R"]); r = df["R"].to_numpy()
    df["year"] = df["dt"].dt.year
    yrs = [(y, g["R"].mean()) for y, g in df.groupby("year") if len(g) >= 10]
    pos = sum(1 for _, e in yrs if e > 0); tot = len(yrs); neg = [int(y) for y, e in yrs if e <= 0]
    df = df.sort_values("dt"); kk = int(len(df) * 0.7); OUT = df.iloc[kk:]["R"].mean()
    L = df[df.dir == 1]["R"]; S = df[df.dir == -1]["R"]
    both = len(L) > 5 and L.mean() > 0 and len(S) > 5 and S.mean() > 0
    lo = loci(r)
    g = "PASS" if (r.mean() > 0 and lo > 0 and tot and pos >= 0.7 * tot and OUT > 0 and both) else "fail"
    print(f"  {tag:16} n={len(r):>4} expR {r.mean():+.3f} PF {V.pf(r):>4.2f} win {100*np.mean(r>0):>2.0f}% "
          f"CI {lo:+.3f} both={'Y' if both else 'n'} yr+{pos}/{tot} OOS {OUT:+.3f} {g}{'  NEG'+str(neg) if neg else ''}")


def main():
    syms = [s.upper() for s in (sys.argv[1:] or ["NQ", "QQQ", "SPY", "ES"])]
    con = hs_db.connect()
    for sym in syms:
        bars = B._externals(con, hs_db.bars(con, "5m", "rth", sym=sym), sym)
        d = H.compute_state(bars, H.P()); d.attrs["sym"] = sym; del bars; gc.collect()
        print(f"\n######## {sym} 5m RTH — range-day VWAP fade (regime==2 only) ########")
        for k in (1.5, 2.0):
            for m in (1.0, 1.5):
                report(f"k{k} stop{m}ATR", fade(d, k, m))
        del d; gc.collect()
    con.close()
    print("\nPASS = exp R>0 net costs AND CI>0 AND both sides>0 AND >=70% yrs+ AND OOS-out>0.")


if __name__ == "__main__":
    main()
