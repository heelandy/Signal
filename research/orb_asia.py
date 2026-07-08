#!/usr/bin/env python3
"""
HIGHSTRIKE research — is there a tradable ASIA-session ORB edge on NQ/MNQ? (Finding 22 candidate)

Prior result (orb_sessions.py, README): the edge lives in US RTH; Asia did NOT qualify with the
production EMA-trend stop-breakout. This re-opens the question with the two things that changed since:
  1) the validated STRUCTURE STACK (HH/HL st_state trend gate + VWAP-extension cap k=2.0, Findings 20-21)
  2) a FADE / mean-reversion variant — Asia is typically a low-vol RANGE, where breakouts bleed and
     the reclaim of a swept OR edge is the more natural edge.

Trade-day coords (18:00 ET = 0). Asia windows open ~19:00-21:00 ET (Tokyo). Trades are force-flat at
the session end (CUT) via the engine's now trade-day-aware EOD logic. NQ == MNQ in price/structure
(MNQ is the micro; same bars, ~1/10 the $/pt and lower fees) -> a NQ-validated edge is the MNQ edge.

Gate (ship only if ALL hold): both sides > 0  AND  lower-90% bootstrap CI > 0  AND  positive most years.

    python research/orb_asia.py [TF ...]      (default: 15m 5m)
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
    ("Asia 18:00-18:30 (Globex reopen)",   0,  30, 480),   # flat 02:00 ET
    ("Asia 19:00-19:30 (Tokyo open)",     60,  90, 540),   # flat 03:00 ET
    ("Asia 19:00-20:00 (Tokyo open 1h)",  60, 120, 540),
    ("Asia 20:00-20:30",                 120, 150, 540),
    ("Asia 20:00-21:00",                 120, 180, 600),   # flat 04:00 ET
]
RTH = ("US RTH 09:30-10:00 (benchmark)", 930, 960, 1140)   # 13:00 ET cutoff


def run(d, ors, ore, cut, variant):
    """variant: 'prod' (EMA trend, stop) | 'stack' (st_state trend + VWAP-cap, stop) | 'fade' (reclaim, EMA trend)."""
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
        n = 0 if tr is None else len(tr)
        print(f"    {tag:7} n={n:>4}  (<30 trades — too few qualify)"); return
    r = tr["net_R"].to_numpy()
    L = tr[tr.direction == "long"]["net_R"].to_numpy(); S = tr[tr.direction == "short"]["net_R"].to_numpy()
    both = len(L) > 5 and L.mean() > 0 and len(S) > 5 and S.mean() > 0
    lo = loci(r)
    t = tr.copy()
    t["year"] = pd.to_datetime(t["entry_time"], utc=True).dt.tz_convert("America/New_York").dt.year
    yrs = [(int(y), g["net_R"].mean()) for y, g in t.groupby("year") if len(g) >= 8]
    pos = sum(1 for _, e in yrs if e > 0); tot = len(yrs)
    g = "PASS" if (both and lo > 0 and tot and pos >= 0.7 * tot) else "----"
    print(f"    {tag:7} n={len(r):>4} exp {r.mean():+.3f} PF {V.pf(r):>4.2f} win {100*np.mean(r>0):>2.0f}% "
          f"DD {V.maxdd(r):>+5.0f} CI {lo:+.3f}  L {L.mean() if len(L) else 0:+.2f}({len(L)}) "
          f"S {S.mean() if len(S) else 0:+.2f}({len(S)})  yrs +{pos}/{tot}  {g}")


def main():
    tfs = [a for a in sys.argv[1:]] or ["15m", "5m"]
    for tf in tfs:
        d = state("NQ", tf)
        d["_tu"] = d["trend_up"].to_numpy().copy(); d["_td"] = d["trend_down"].to_numpy().copy()
        print(f"\n################  NQ {tf}  ({len(d):,} bars)  —  Asia ORB hunt  ################")
        print(f"  gate: both sides>0 AND loCI>0 AND positive >=70% of years   (T1={T1}R T2={T2}R, brk 0)")
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
