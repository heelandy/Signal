#!/usr/bin/env python3
"""
F51 — INVESTIGATE the struct-stop expectancy inflation flagged in F50. Symptom: on the prod stack the
backtest shows 85-94% win, hold median 1 bar. Hypothesis: the structure stop is PINNED to the
MIN_STOP_ATR=0.5 floor on most trades, so TP1 (1R = 0.5 ATR) is trivially hit on the very next bar before
the equally-tiny 0.5-ATR stop → cheap wins + inflated PF, and a 0.5-ATR stop is noise-tight in LIVE.

We (a) measure the stop distribution (% pinned to the floor, risk in ATR), (b) sweep MIN_STOP_ATR to a
realistic floor and watch win%/hold/exp normalise, (c) report the instant-resolve rate (hold<=1 bar).
This decides whether to widen the production min-stop. NQ+QQQ 5m RTH, prod config (struct gate + OB +
time gate + cap 2.0), scale_be exit (bounded).

    python research/orb_stop_floor.py [SYM ...]
"""
import sys, os, gc
sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "engine"))
import numpy as np, pandas as pd
import hs_db, hs_harness as H, hs_backtest as B, hs_validate as V

ORS, ORE, CUT, T1, T2, EOD = 570, 600, 900, 1.0, 4.0, 958
FLOORS = [0.5, 0.75, 1.0, 1.25, 1.5]


def run(d, vcap=2.0):
    st = d["st_state"].to_numpy()
    obl = d["in_bull_ob"].shift(1).fillna(False).to_numpy().astype(bool)
    obs = d["in_bear_ob"].shift(1).fillna(False).to_numpy().astype(bool)
    d["trend_up"] = (st == 1) & obl
    d["trend_down"] = (st == 2) & obs
    et = pd.to_datetime(d["ts"]).dt.tz_convert("America/New_York")
    sk = ((et.dt.hour * 60 + et.dt.minute).to_numpy()) < 660
    return B.backtest(d, "scale_be", "both", False, "orb", 0, T1, T2, ORS, ORE, 0.0, CUT, "stop",
                      eod_min=EOD, vwap_cap=vcap, skip_mask=sk, stop_mode="struct")


def main():
    syms = [s.upper() for s in (sys.argv[1:] or ["NQ", "QQQ"])]
    con = hs_db.connect()
    base_floor = B.MIN_STOP_ATR
    for sym in syms:
        bars = B._externals(con, hs_db.bars(con, "5m", "rth", sym=sym), sym)
        d = H.compute_state(bars, H.P()); d.attrs["sym"] = sym
        del bars; gc.collect()
        atr_ref = d.set_index(pd.to_datetime(d["ts"], utc=True))["atr14"]
        print(f"\n######## {sym} 5m STACK (RTH) — MIN_STOP_ATR floor sweep ########")
        print(f"  {'floor':>6} {'n':>4} {'exp R':>7} {'PF':>6} {'win%':>5} {'holdMed':>7} {'hold<=1%':>8} "
              f"{'riskATRmed':>10} {'%atFloor':>8}")
        for fl in FLOORS:
            B.MIN_STOP_ATR = fl
            tr = run(d); r = tr["net_R"].to_numpy()
            if not len(r):
                print(f"  {fl:>6.2f}  (no trades)"); continue
            et = pd.to_datetime(tr["entry_time"], utc=True)
            atr_at = atr_ref.reindex(et).to_numpy()
            risk_atr = tr["risk_pts"].to_numpy() / atr_at                     # stop distance in ATR
            at_floor = 100 * np.mean(risk_atr <= fl + 0.03)                   # ~pinned to the floor
            hold = tr["hold_bars"].to_numpy()
            print(f"  {fl:>6.2f} {len(r):>4} {r.mean():>+7.3f} {V.pf(r):>6.2f} {100*np.mean(r>0):>5.0f} "
                  f"{np.median(hold):>7.0f} {100*np.mean(hold <= 1):>8.0f} "
                  f"{np.nanmedian(risk_atr):>10.2f} {at_floor:>7.0f}%")
            del tr; gc.collect()
        del d; gc.collect()
    B.MIN_STOP_ATR = base_floor
    con.close()
    print("\nIf win% + PF drop toward realistic levels as the floor widens while exp stays ~flat/positive,")
    print("the edge is real but the 0.5-ATR floor was inflating win-rate via trivial TP1; widen the prod floor.")


if __name__ == "__main__":
    main()
