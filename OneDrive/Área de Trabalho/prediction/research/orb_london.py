#!/usr/bin/env python3
"""
HIGHSTRIKE F29 candidate — is there a tradable LONDON-session ORB edge on NQ/MNQ? (mirror of F22 Asia)
London opens ~03:00 ET. Tests the London-open OR windows × {production EMA breakout, the validated STRUCTURE
STACK, a fade} on NQ 5m + 15m, trade-day coords (18:00 ET = 0), US RTH benchmark. Same gate as Asia:
both sides>0 AND lower-90% CI>0 AND positive >=70% of years.

    python research/orb_london.py [TF ...]   (default 5m 15m)
"""
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "engine"))
import numpy as np, pandas as pd
import hs_db, hs_harness as H, hs_backtest as B, hs_validate as V
from orb_optimize import state

rng = np.random.default_rng(7)
T1, T2, KCAP = 1.0, 4.0, 2.0

# name, OR-open, OR-close, session cutoff/EOD  (trade-day mins, 18:00 ET = 0); London ~03:00 ET = 540
WINDOWS = [
    ("London 02:00-02:30 (pre)",  480, 510, 840),   # flat 08:00 ET (before RTH)
    ("London 03:00-03:30 (open)", 540, 570, 840),
    ("London 03:00-04:00 (1h)",   540, 600, 840),
    ("London 04:00-04:30",        600, 630, 840),
]
RTH = ("US RTH 09:30-10:00 (benchmark)", 930, 960, 1140)


def run(d, ors, ore, cut, variant):
    if variant == "stack":
        st = d["st_state"].to_numpy(); d["trend_up"] = st == 1; d["trend_down"] = st == 2
        execm, cap = "stop", KCAP
    else:
        d["trend_up"] = d["_tu"]; d["trend_down"] = d["_td"]
        execm, cap = ("fade" if variant == "fade" else "stop"), 0.0
    return B.backtest(d, "scale_be", "both", False, "orb", 0, T1, T2, ors, ore, 0.0, cut, execm,
                      tradeday=True, eod_min=cut, vwap_cap=cap)


def loci(r):
    return np.percentile(rng.choice(r, (3000, len(r)), replace=True).mean(1), 5) if len(r) else 0.0


def report(tag, tr):
    if tr is None or len(tr) < 30:
        print(f"    {tag:7} n={0 if tr is None else len(tr):>4}  (<30)"); return
    r = tr["net_R"].to_numpy()
    L = tr[tr.direction == "long"]["net_R"].to_numpy(); S = tr[tr.direction == "short"]["net_R"].to_numpy()
    both = len(L) > 5 and L.mean() > 0 and len(S) > 5 and S.mean() > 0
    lo = loci(r)
    t = tr.copy(); t["year"] = pd.to_datetime(t["entry_time"], utc=True).dt.tz_convert("America/New_York").dt.year
    yrs = [(int(y), g["net_R"].mean()) for y, g in t.groupby("year") if len(g) >= 8]
    pos = sum(1 for _, e in yrs if e > 0); tot = len(yrs)
    g = "PASS" if (both and lo > 0 and tot and pos >= 0.7 * tot) else "----"
    print(f"    {tag:7} n={len(r):>4} exp {r.mean():+.3f} PF {V.pf(r):>4.2f} win {100*np.mean(r>0):>2.0f}% "
          f"CI {lo:+.3f}  L {L.mean() if len(L) else 0:+.2f} S {S.mean() if len(S) else 0:+.2f}  yrs +{pos}/{tot}  {g}")


def main():
    tfs = [a for a in sys.argv[1:]] or ["5m", "15m"]
    for tf in tfs:
        d = state("NQ", tf)
        d["_tu"] = d["trend_up"].to_numpy().copy(); d["_td"] = d["trend_down"].to_numpy().copy()
        print(f"\n################  NQ {tf}  ({len(d):,} bars)  —  London ORB hunt  ################")
        for name, ors, ore, cut in WINDOWS:
            print(f"\n  {name}")
            for v in ("prod", "stack", "fade"):
                report(v, run(d, ors, ore, cut, v))
        name, ors, ore, cut = RTH
        print(f"\n  {name}")
        for v in ("prod", "stack"):
            report(v, run(d, ors, ore, cut, v))


if __name__ == "__main__":
    main()
