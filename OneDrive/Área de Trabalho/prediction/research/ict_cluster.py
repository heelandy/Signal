#!/usr/bin/env python3
"""ICT cluster screen — 4 novel ICT concepts through the IDENTICAL exit + gauntlet as the ORB.
(OB/FVG/liquidity/MSS already tested via the SMC cluster = ORB-redundant/dead; these are the untested ones.)

  1 OTE (premium/discount retracement)  2 Silver Bullet (10-11 ET window)  3 Judas Swing (fade the open's false move)  4 SMT divergence (NQ vs ES)

    python research/ict_cluster.py NQ
"""
import sys, os, gc
sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "engine"))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import numpy as np, pandas as pd
import hs_db, hs_harness as H, hs_backtest as B, hs_validate as V
from smc_cluster import ci_lo, yr, oos, line, run as ext_run, T1, T2, CUT, EOD


def _perday_or(d):
    et = pd.to_datetime(d["ts"]).dt.tz_convert("America/New_York")
    mins = (et.dt.hour * 60 + et.dt.minute).to_numpy(); day = et.dt.date.to_numpy()
    df = pd.DataFrame({"day": day, "mins": mins, "h": d["high"].to_numpy(), "l": d["low"].to_numpy(), "c": d["close"].to_numpy()})
    w = df[(df["mins"] >= 570) & (df["mins"] < 600)]
    orh, orl, obull = {}, {}, {}
    for dd, g in w.groupby("day"):
        if len(g) < 2: continue
        Hh = g["h"].max(); Ll = g["l"].min(); orh[dd] = Hh; orl[dd] = Ll
        obull[dd] = bool(g.sort_values("mins")["c"].iloc[-1] > (Hh + Ll) / 2)
    return mins, day, orh, orl, obull


def sig_ote(d):                                     # premium/discount OTE: bullish day -> buy the 62-79% discount pullback; bearish -> sell premium
    mins, day, orh, orl, obull = _perday_or(d)
    hi, lo, c, o, st = (d[x].to_numpy() for x in ("high", "low", "close", "open", "st_state"))
    n = len(d); el = np.zeros(n, bool); es = np.zeros(n, bool)
    for i in range(n):
        dd = day[i]
        if dd not in orh or mins[i] < 600 or mins[i] >= 900: continue
        Hh, Ll = orh[dd], orl[dd]; rng = Hh - Ll
        if rng <= 0: continue
        if obull[dd]:                                # discount OTE zone (62-79% retrace from the OR high)
            zlo, zhi = Ll + 0.21 * rng, Ll + 0.38 * rng
            if lo[i] <= zhi and c[i] > zlo and c[i] > o[i] and st[i] == 1: el[i] = True
        else:
            zhi, zlo = Hh - 0.21 * rng, Hh - 0.38 * rng
            if hi[i] >= zlo and c[i] < zhi and c[i] < o[i] and st[i] == 2: es[i] = True
    return el, es


def sig_judas(d):                                   # Judas swing: OR edge is SWEPT then price closes back inside within the first ~90m -> fade
    mins, day, orh, orl, obull = _perday_or(d)
    hi, lo, c, o = (d[x].to_numpy() for x in ("high", "low", "close", "open"))
    n = len(d); el = np.zeros(n, bool); es = np.zeros(n, bool)
    swept_hi = {}; swept_lo = {}
    for i in range(n):
        dd = day[i]
        if dd not in orh or mins[i] < 600 or mins[i] >= 690: continue    # first ~90 min after OR close = the manipulation window
        Hh, Ll = orh[dd], orl[dd]
        if hi[i] > Hh: swept_hi[dd] = True
        if lo[i] < Ll: swept_lo[dd] = True
        if swept_hi.get(dd) and c[i] < Hh and c[i] < o[i]: es[i] = True   # swept the high, rejected back in -> SHORT (Judas up-swing)
        if swept_lo.get(dd) and c[i] > Ll and c[i] > o[i]: el[i] = True
    return el, es


def orb_trades(d):
    st = d["st_state"].to_numpy(); d["trend_up"] = (st == 1); d["trend_down"] = (st == 2)
    return B.backtest(d, "tp2_full", "both", False, "orb", 0, T1, T2, 570, 600, 0.0, CUT, "close", eod_min=EOD,
                      stop_mode="struct", entry_delay=0, chase_atr=1.0, strong_body=0.25, ft_confirm=True, or_mid_bias=True)


def main():
    sym = (sys.argv[1] if len(sys.argv) > 1 else "NQ").upper()
    con = hs_db.connect()
    d = H.compute_state(B._externals(con, hs_db.bars(con, "5m", "rth", sym=sym), sym), H.P()); d.attrs["sym"] = sym
    print(f"\n{'='*100}\n{sym}  ICT CLUSTER  (same exit/costs as the ORB, struct stop cap-4R)\n{'='*100}")
    line("0 ORB+OR-mid(ref)", orb_trades(d))
    for tag, fn in [("1 OTE", sig_ote), ("3 Judas", sig_judas)]:
        try:
            el, es = fn(d); line(tag, ext_run(d, el, es))
        except Exception as e:
            print(f"  {tag:20} ERROR {str(e)[:60]}")
    # 2 Silver Bullet = the ORB filtered to the 10:00-11:00 ET window
    tr = orb_trades(d).copy()
    hm = pd.to_datetime(tr["entry_time"], utc=True).dt.tz_convert("America/New_York")
    tr["hm"] = hm.dt.hour * 60 + hm.dt.minute
    line("2 SilverBullet", tr[(tr["hm"] >= 600) & (tr["hm"] < 660)])
    # 4 SMT divergence — NQ vs ES (rolling 12-bar extreme divergence)
    if sym in ("NQ", "ES"):
        other = "ES" if sym == "NQ" else "NQ"
        try:
            do = H.compute_state(B._externals(con, hs_db.bars(con, "5m", "rth", sym=other), other), H.P())
            a = d[["ts", "high", "low", "close", "st_state"]].copy(); b = do[["ts", "high", "low"]].rename(columns={"high": "oh", "low": "ol"})
            m = a.merge(b, on="ts", how="inner")
            hi, lo, oh, ol, st = (m[x].to_numpy(float) for x in ("high", "low", "oh", "ol", "st_state"))
            N = 12; rmax = pd.Series(hi).rolling(N).max().shift(1).to_numpy(); rmin = pd.Series(lo).rolling(N).min().shift(1).to_numpy()
            ormax = pd.Series(oh).rolling(N).max().shift(1).to_numpy(); ormin = pd.Series(ol).rolling(N).min().shift(1).to_numpy()
            el = (lo < rmin) & (ol >= ormin) & (m["close"].to_numpy() > m["close"].shift(1).to_numpy())    # sym new low, other NOT -> bullish SMT
            es = (hi > rmax) & (oh <= ormax) & (m["close"].to_numpy() < m["close"].shift(1).to_numpy())     # sym new high, other NOT -> bearish SMT
            dm = d.merge(m[["ts"]], on="ts", how="right").reset_index(drop=True); dm.attrs["sym"] = sym
            elf = np.nan_to_num(el).astype(bool); esf = np.nan_to_num(es).astype(bool)
            line(f"4 SMT(vs {other})", ext_run(dm, elf, esf))
        except Exception as e:
            print(f"  4 SMT               ERROR {str(e)[:70]}")
    else:
        print("  4 SMT               (futures-pair only — run NQ/ES)")
    con.close()
    print("  KEY: gate PASS = CIlo>0 & both sides>0 & >=70% yrs+ & OOS>0. exp=net R/trade after costs.")


if __name__ == "__main__":
    main()
