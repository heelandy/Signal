#!/usr/bin/env python3
"""ARM-TIMING study — does a 30-min arm delay beat the 60-min F38 "skip-first-hour", per session?
And per session, does the vol-expansion (wide-OR) feature add edge on top?

User ask: OR calc = 30 min, then arm 30 min later (total 1h open->arm) instead of the current 30-min
OR + 60-min delay (1h30 open->arm). Test it honestly per session before changing the F38 default.

Config = the FINAL validated entry (struct HH/HL gate + close-confirm + strong-body 0.25 + next-candle
follow-through + struct stop + cap-4R). 5m. Sessions: RTH (all), Asia + London (futures only).
Gauntlet gate = CIlo>0 AND both sides>0 AND >=70% yrs+ AND OOS>0.

    python research/orb_arm_timing.py NQ        (one symbol per process; loop from bash)
"""
import sys, os, gc
sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "engine"))
import numpy as np, pandas as pd
import hs_db, hs_harness as H, hs_backtest as B, hs_validate as V

T1, T2, SB = 1.0, 4.0, 0.25
FUT = ("NQ", "ES", "GC", "MNQ", "MES", "MGC")
_rng = np.random.default_rng(7)


def ci_lo(r, n=2000):
    return float(np.percentile(_rng.choice(r, size=(n, len(r)), replace=True).mean(axis=1), 5)) if len(r) >= 10 else float("nan")


def yr(tr):
    t = tr.copy(); t["y"] = pd.to_datetime(t["entry_time"], utc=True).dt.tz_convert("America/New_York").dt.year
    g = t.groupby("y")["net_R"].mean(); return int((g > 0).sum()), len(g)


def oos(tr):
    r = tr.sort_values("entry_time")["net_R"].to_numpy(); k = int(len(r) * 0.7)
    return (r[:k].mean(), r[k:].mean()) if (k >= 5 and len(r) - k >= 5) else (float("nan"), float("nan"))


def bt(d, ors, ore, cut, delay, tradeday, min_orw=0.0, eod=None):
    # cut = last-entry time (tod_end); eod = force-flat time. RTH flattens 15:58 (958) though last entry
    # is 15:00 (900); overnight sessions flatten AT their cut. Must be separate or RTH runners get chopped.
    eodm = cut if eod is None else eod
    st = d["st_state"].to_numpy(); d["trend_up"] = (st == 1); d["trend_down"] = (st == 2)
    return B.backtest(d, "tp2_full", "both", False, "orb", 0, T1, T2, ors, ore, 0.0, cut, "close",
                      tradeday=tradeday, eod_min=eodm, stop_mode="struct", entry_delay=delay,
                      strong_body=SB, ft_confirm=True, min_or_width=min_orw)


def report(tag, tr):
    r = tr["net_R"].to_numpy()
    if len(r) < 20:
        print(f"    {tag:30} n={len(r):>4}  (too few)"); return None
    L = tr.net_R[tr.direction == "long"].to_numpy(); S = tr.net_R[tr.direction == "short"].to_numpy()
    lo = ci_lo(r); p, ny = yr(tr); is_, oo = oos(tr)
    both = len(L) > 5 and L.mean() > 0 and len(S) > 5 and S.mean() > 0
    g = "PASS" if (lo > 0 and both and ny and p >= 0.7 * ny and oo > 0) else "----"
    print(f"    {tag:30} n={len(r):>4} exp {r.mean():+.3f} PF {V.pf(r):>4.2f} win {100*np.mean(r>0):>2.0f}% "
          f"CIlo {lo:+.3f} L{(L.mean() if len(L) else 0):+.2f} S{(S.mean() if len(S) else 0):+.2f} "
          f"yr+{p}/{ny} OOS{is_:+.2f}/{oo:+.2f} {g}")
    return r.mean()


def main():
    sym = (sys.argv[1] if len(sys.argv) > 1 else "NQ").upper()
    is_fut = sym in FUT
    con = hs_db.connect()
    print(f"\n{'#'*92}\n#  {sym}  ARM-TIMING  (30-min OR, delay = min after OR-close before ARM)  "
          f"{'FUTURES' if is_fut else 'EQUITY'}\n{'#'*92}")

    # ---- RTH (all instruments): rth-view bars, calendar coords (matches validated F62) ----
    d = H.compute_state(B._externals(con, hs_db.bars(con, "5m", "rth", sym=sym), sym), H.P()); d.attrs["sym"] = sym
    print(f"\n  RTH  09:30-10:00 OR  ({len(d):,} bars)     [arm = 10:00 / 10:30 / 11:00]")
    for dly in (0, 30, 60):
        report(f"delay {dly:>2}  (arm {10 if dly<60 else 11}:{'00' if dly in (0,60) else '30'})", bt(d, 570, 600, 900, dly, False, eod=958))
    print("    -- vol-expansion feature (wide-OR only, OR/ATR>=2.4) at the target delay 30 --")
    report("delay 30 + volexp2.4", bt(d, 570, 600, 900, 30, False, min_orw=2.4, eod=958))
    report("delay 60 + volexp2.4 (incumbent+feat)", bt(d, 570, 600, 900, 60, False, min_orw=2.4, eod=958))
    del d; gc.collect()

    # ---- Asia + London (futures only): full-view bars, trade-day coords ----
    if is_fut:
        d = H.compute_state(B._externals(con, hs_db.bars(con, "5m", "full", sym=sym), sym), H.P()); d.attrs["sym"] = sym
        # Asia: 30-min OR 19:00-19:30 (60-90) vs the CURRENT 60-min OR 19:00-20:00 (60-120); cut 03:00 (540)
        print(f"\n  ASIA  19:00-19:30 OR  (30-min)     [arm = 19:30 / 20:00 / 20:30]")
        for dly in (0, 30, 60):
            report(f"delay {dly:>2}", bt(d, 60, 90, 540, dly, True))
        report("delay 30 + volexp2.4", bt(d, 60, 90, 540, 30, True, min_orw=2.4))
        print("    -- incumbent for reference: CURRENT 60-min OR (19:00-20:00) + delay 60 --")
        report("60-min OR, delay 60 (current)", bt(d, 60, 120, 540, 60, True))

        # London: 30-min OR 03:00-03:30 (540-570); cut 08:00 (840)
        print(f"\n  LONDON  03:00-03:30 OR  (30-min)     [arm = 03:30 / 04:00 / 04:30]")
        for dly in (0, 30, 60):
            report(f"delay {dly:>2}", bt(d, 540, 570, 840, dly, True))
        report("delay 30 + volexp2.4", bt(d, 540, 570, 840, 30, True, min_orw=2.4))
        del d; gc.collect()
    con.close()
    print("\n  KEY: exp=net R/trade after costs. gate PASS needs CIlo>0 & both sides>0 & >=70% yrs+ & OOS>0.")


if __name__ == "__main__":
    main()
