#!/usr/bin/env python3
"""
HIGHSTRIKE F30 candidate — does the ORB edge exist on GOLD (GC)? Fresh campaign, NO assumed transfer.
Tests gold-native session opens × {production EMA breakout, the validated STRUCTURE STACK, a fade} on
GC 5m + 15m, trade-day coords (18:00 ET = 0). Same gate as Asia/London: both sides>0 AND lower-90%
CI>0 AND positive >=70% of years.
⚠️ CAVEATS vs the index campaign: (1) the macro regime filter inside the engine is SPY/VIX-based —
equity-native; treat any pass as provisional until a gold-macro (DXY/real-yield) variant is checked.
(2) GC liquidity events differ: COMEX open 08:20 ET, London AM/PM fixes 05:30/10:00 ET, Shanghai open
21:00 ET — windows below cover them.

    python research/orb_gold.py [TF ...]   (default 5m 15m)
"""
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "engine"))
import numpy as np, pandas as pd
import hs_db, hs_harness as H, hs_backtest as B, hs_validate as V
from orb_optimize import state

rng = np.random.default_rng(7)
T1, T2, KCAP = 1.0, 4.0, 2.0

# name, OR-open, OR-close, session cutoff/EOD  (trade-day mins, 18:00 ET = 0)
WINDOWS = [
    ("Asia/Tokyo 19:00-20:00 ET",   60, 120, 540),    # flat 03:00 ET (the NQ Asia window)
    ("Shanghai/SGE 21:00-21:30",   180, 210, 540),    # China gold demand open
    ("London open 03:00-03:30",    540, 570, 840),    # flat 08:00 ET (the NQ London window)
    ("London AM fix 05:00-05:30",  660, 690, 840),    # OR into the 05:30 ET AM fix
    ("COMEX open 08:20-08:50",     860, 890, 1170),   # gold's own floor open; flat 13:30 ET
    ("US equity 09:30-10:00",      930, 960, 1260),   # the index flagship window; flat 15:00 ET
]


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
        d = state("GC", tf)
        d["_tu"] = d["trend_up"].to_numpy().copy(); d["_td"] = d["trend_down"].to_numpy().copy()
        print(f"\n################  GC {tf}  ({len(d):,} bars)  —  GOLD ORB hunt  ################")
        for name, ors, ore, cut in WINDOWS:
            print(f"\n  {name}")
            for v in ("prod", "stack", "fade"):
                report(v, run(d, ors, ore, cut, v))


if __name__ == "__main__":
    main()
