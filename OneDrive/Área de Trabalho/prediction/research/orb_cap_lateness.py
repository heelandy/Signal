#!/usr/bin/env python3
"""
F50 — the "earlier-entry knob": how much does TIGHTENING the VWAP-cap k reduce entry LATENESS, and what
does it cost? The user perceives ORB fills as "mid-range / too late". The VWAP-cap (F16) IS the anti-late
lever: it skips breakouts already > k·ATR beyond session VWAP. Lower k = entries closer to VWAP (earlier
in the move) but fewer trades. This quantifies the frontier on the PRODUCTION stack config:

  struct gate (st_state) + OB confluence (F41, prior-bar) + time gate (skip <11:00, F38) + struct stop
  (F25b) + trail exit (F27b) — i.e. exactly what HIGHSTRIKE_ORB_STACK.pine trades — varying ONLY vwap_cap.

Per trade we also report LATENESS = signed entry extension beyond prior-bar session VWAP, in ATR
(= the engine's cap metric), and mean MAE_R (initial adverse heat) — both proxies for "how late/extended".

    python research/orb_cap_lateness.py [SYM ...]            (default NQ QQQ)
"""
import sys, os, gc
sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "engine"))
import numpy as np, pandas as pd
import hs_db, hs_harness as H, hs_backtest as B, hs_validate as V

ORS, ORE, CUT, T1, T2, EOD = 570, 600, 900, 1.0, 4.0, 958
CAPS = [99.0, 2.0, 1.7, 1.5, 1.3, 1.1]      # 99 = effectively no cap (full lateness baseline)


def run(d, vcap):
    """F45 stack base: struct gate, OB confluence (prior bar), time gate <11:00, struct stop, scale_be exit
    (50% @1R then runner->BE->4R; bounded per trade so expectancy is comparable, not trail-inflated)."""
    st = d["st_state"].to_numpy()
    obl = d["in_bull_ob"].shift(1).fillna(False).to_numpy().astype(bool)
    obs = d["in_bear_ob"].shift(1).fillna(False).to_numpy().astype(bool)
    d["trend_up"] = (st == 1) & obl
    d["trend_down"] = (st == 2) & obs
    et = pd.to_datetime(d["ts"]).dt.tz_convert("America/New_York")
    sk = ((et.dt.hour * 60 + et.dt.minute).to_numpy()) < 660           # F38 skip the first hour after OR
    return B.backtest(d, "scale_be", "both", False, "orb", 0, T1, T2, ORS, ORE, 0.0, CUT, "stop",
                      eod_min=EOD, vwap_cap=vcap, skip_mask=sk, stop_mode="struct")


def lateness(d, tr):
    """Signed entry extension beyond prior-bar session VWAP, in ATR (the cap metric), merged onto trades."""
    ref = d[["ts", "vwap_sess", "atr14"]].copy()
    ref["vs_prev"] = ref["vwap_sess"].shift(1)
    ref["ts"] = pd.to_datetime(ref["ts"], utc=True)
    t = tr.copy(); t["entry_time"] = pd.to_datetime(t["entry_time"], utc=True)
    m = t.merge(ref[["ts", "vs_prev", "atr14"]], left_on="entry_time", right_on="ts", how="left")
    ext = np.where(m["direction"] == "long",
                   (m["entry_price"] - m["vs_prev"]) / m["atr14"],
                   (m["vs_prev"] - m["entry_price"]) / m["atr14"])
    return ext[np.isfinite(ext)]


def main():
    syms = [s.upper() for s in (sys.argv[1:] or ["NQ", "QQQ"])]
    con = hs_db.connect()
    for sym in syms:
        bars = B._externals(con, hs_db.bars(con, "5m", "rth", sym=sym), sym)   # RTH bars: 3.5x lighter, same frontier
        d = H.compute_state(bars, H.P()); d.attrs["sym"] = sym
        del bars; gc.collect()
        print(f"\n######## {sym} 5m STACK (RTH) — VWAP-cap 'earlier entry' frontier ########")
        print(f"  {'k':>5} {'n':>5} {'exp R':>7} {'PF':>5} {'win%':>5} {'maxDD':>7}  "
              f"{'extMean':>7} {'extMed':>7} {'extMax':>7} {'MAE_R':>6}")
        base_n = None
        for k in CAPS:
            tr = run(d, k); r = tr["net_R"].to_numpy()
            if not len(r):
                print(f"  {k:>5.1f}  (no trades)"); continue
            ext = lateness(d, tr); mae = tr["mae_R"].to_numpy()
            if base_n is None:
                base_n = len(r)
            kept = 100 * len(r) / base_n
            klbl = "none" if k >= 99 else f"{k:.1f}"
            tag = "  <- PROD" if abs(k - 2.0) < 1e-9 else (f"  ({kept:.0f}% of uncapped)" if k < 99 else "")
            print(f"  {klbl:>5} {len(r):>5} {r.mean():>+7.3f} {V.pf(r):>5.2f} {100*np.mean(r>0):>5.0f} "
                  f"{V.maxdd(r):>+7.0f}  {ext.mean():>7.2f} {np.median(ext):>7.2f} {ext.max():>7.2f} "
                  f"{mae.mean():>+6.2f}{tag}")
            del tr; gc.collect()
        del d; gc.collect()
    con.close()
    print("\nextMean/Med/Max = entry distance beyond prior-bar session VWAP in ATR (lateness; cap bounds extMax).")
    print("MAE_R = mean initial adverse heat. Lower ext + lower |MAE| = earlier/better-located entry.")


if __name__ == "__main__":
    main()
