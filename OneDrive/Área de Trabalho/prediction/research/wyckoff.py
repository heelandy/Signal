#!/usr/bin/env python3
"""Wyckoff SPRING / UPTHRUST test — false break of a consolidation-range extreme that reverses.
SPRING (long): price breaks BELOW the N-bar range low (sweeps stops) then CLOSES back above it, in a
RANGING regime (low efficiency-ratio = accumulation, not a trend). UPTHRUST (short) = the mirror.
Same exit/costs as the ORB (struct stop, cap-4R). Gauntlet + ADDITIVITY vs the ORB.

Variants: base (ER<0.35 range gate) · tighter range (ER<0.25) · +volume-spike on the sweep (Wyckoff 'test').

    python research/wyckoff.py NQ
"""
import sys, os, gc
sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "engine"))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import numpy as np, pandas as pd
import hs_db, hs_harness as H, hs_backtest as B, hs_validate as V
from smc_cluster import line, run as ext_run


def sig_wyckoff(d, N=30, er_max=0.35, vol_spike=False):
    hi, lo, c, o = (d[x].to_numpy(float) for x in ("high", "low", "close", "open"))
    rhi = pd.Series(hi).rolling(N).max().shift(1).to_numpy()
    rlo = pd.Series(lo).rolling(N).min().shift(1).to_numpy()
    cs = pd.Series(c)
    net = (cs - cs.shift(N)).abs()
    path = cs.diff().abs().rolling(N).sum()
    er = (net / path).to_numpy()                                  # efficiency ratio: low = ranging/consolidating
    is_range = er < er_max
    volok = np.ones(len(d), bool)
    if vol_spike and "volume" in d:
        v = d["volume"].to_numpy(float); va = pd.Series(v).rolling(20, min_periods=5).mean().to_numpy()
        volok = np.nan_to_num(v >= 1.3 * va)                      # the spring/upthrust bar on above-avg volume (the 'test')
    spring = (lo < rlo) & (c > rlo) & (c > o) & is_range & volok
    upthrust = (hi > rhi) & (c < rhi) & (c < o) & is_range & volok
    return np.nan_to_num(spring).astype(bool), np.nan_to_num(upthrust).astype(bool)


def orb_ref(d):
    st = d["st_state"].to_numpy(); d["trend_up"] = (st == 1); d["trend_down"] = (st == 2)
    return B.backtest(d, "tp2_full", "both", False, "orb", 0, 1.0, 4.0, 570, 600, 0.0, 900, "close", eod_min=958,
                      stop_mode="struct", entry_delay=0, chase_atr=1.0, strong_body=0.25, ft_confirm=True, or_mid_bias=True)


def main():
    sym = (sys.argv[1] if len(sys.argv) > 1 else "NQ").upper()
    con = hs_db.connect()
    d = H.compute_state(B._externals(con, hs_db.bars(con, "5m", "rth", sym=sym), sym), H.P()); d.attrs["sym"] = sym
    con.close()
    print(f"\n{'='*100}\n{sym}  WYCKOFF SPRING / UPTHRUST  (same exit/costs as the ORB)\n{'='*100}")
    line("0 ORB+OR-mid(ref)", orb_ref(d))
    for tag, kw in [("spring base(ER<.35)", dict(er_max=0.35)),
                    ("spring tight(ER<.25)", dict(er_max=0.25)),
                    ("spring +vol-test", dict(er_max=0.35, vol_spike=True))]:
        try:
            el, es = sig_wyckoff(d, **kw); line(tag, ext_run(d, el, es))
        except Exception as e:
            print(f"  {tag:22} ERROR {str(e)[:60]}")
    print("  KEY: gate PASS = CIlo>0 & both sides>0 & >=70% yrs+ & OOS>0.")
    del d; gc.collect()


if __name__ == "__main__":
    main()
