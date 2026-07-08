#!/usr/bin/env python3
"""ICHIMOKU KINKO HYO — tested BOTH ways per protocol: (A) STANDALONE new edge (cloud-break + TK-cross entries
through the validated exit) and (B) ADDITIVE to the current ORB stack (price-vs-cloud / cloud-color / daily-cloud
HTF as a confirmation gate, WITH the dropped-cohort control so we know if it just removes winners).

Ichimoku (canonical 9/26/52) is computed on a CONTINUOUS 5m series (resampled from the on-disk 1m, all sessions)
so the 52-bar cloud is always defined — then mapped causally onto the RTH 5m ORB frame (merge_asof backward, no
lookahead: Senkou A/B are shifted +26 so the cloud at t uses only data from t-26). Daily cloud uses the PRIOR day.

  tenkan=(9H+9L)/2  kijun=(26H+26L)/2  spanA=((tenkan+kijun)/2).shift(26)  spanB=(52H+52L)/2 .shift(26)
  above_cloud = close>max(spanA,spanB)   green_cloud = spanA>spanB   tk_bull = tenkan>kijun

    python research/orb_ichimoku.py NQ QQQ ES GC
"""
import sys, os, gc
sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "engine"))
import numpy as np, pandas as pd
import hs_db, hs_harness as H, hs_backtest as B, hs_validate as V

DATA = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "data")
_rng = np.random.default_rng(7)
def ci_lo(r):
    return float(np.percentile(_rng.choice(r, size=(1000, len(r)), replace=True).mean(axis=1), 5)) if len(r) >= 10 else float("nan")
def yr(tr):
    t = tr.copy(); t["y"] = pd.to_datetime(t["entry_time"], utc=True).dt.tz_convert("America/New_York").dt.year
    g = t.groupby("y")["net_R"].mean(); return int((g > 0).sum()), len(g)
def line(tag, tr, ref_n=None):
    if tr is None or len(tr) < 20:
        print(f"  {tag:24} n={0 if tr is None else len(tr):>4}  (too few)"); return
    r = tr["net_R"].to_numpy(); L = tr.net_R[tr.direction == "long"].to_numpy(); S = tr.net_R[tr.direction == "short"].to_numpy()
    lo = ci_lo(r); p, ny = yr(tr)
    both = len(L) > 5 and L.mean() > 0 and len(S) > 5 and S.mean() > 0
    g = "PASS" if (lo > 0 and both and ny and p >= 0.7 * ny) else "----"
    keep = f" keep {100*len(r)/ref_n:>3.0f}%" if ref_n else ""
    print(f"  {tag:24} n={len(r):>4} exp {r.mean():+.3f} PF {V.pf(r):>4.2f} win {100*np.mean(r>0):>2.0f}% "
          f"CIlo {lo:+.3f} L{(L.mean() if len(L) else 0):+.2f} S{(S.mean() if len(S) else 0):+.2f} yr+{p}/{ny}{keep} {g}")

def ichimoku(df, t=9, k=26, s=52):
    hi, lo, cl = df["high"], df["low"], df["close"]
    ten = (hi.rolling(t).max() + lo.rolling(t).min()) / 2
    kij = (hi.rolling(k).max() + lo.rolling(k).min()) / 2
    spanA = ((ten + kij) / 2).shift(k)                                   # +k ahead => at t uses t-k data (causal)
    spanB = ((hi.rolling(s).max() + lo.rolling(s).min()) / 2).shift(k)
    return ten, kij, spanA, spanB

def cont5(sym):
    p = os.path.join(DATA, f"{sym.lower()}_continuous_1m.parquet")
    if not os.path.exists(p):
        return None
    df = pd.read_parquet(p)
    tcol = "ts_et" if "ts_et" in df.columns else ("ts" if "ts" in df.columns else df.columns[0])
    df = df.rename(columns={tcol: "ts"}); df["ts"] = pd.to_datetime(df["ts"], utc=True)
    df = df.set_index("ts").sort_index()
    agg = {"open": "first", "high": "max", "low": "min", "close": "last"}
    if "volume" in df: agg["volume"] = "sum"
    c5 = df.resample("5min", label="right", closed="right").agg(agg).dropna(subset=["close"])
    dday = df.resample("1D", label="right", closed="right").agg(agg).dropna(subset=["close"])
    return c5.reset_index(), dday.reset_index()

def main():
    syms = [s.upper() for s in (sys.argv[1:] or ["NQ", "QQQ", "ES", "GC"])]
    con = hs_db.connect()
    for sym in syms:
        cc = cont5(sym)
        if cc is None:
            print(f"{sym}: no 1m parquet — skipped"); continue
        c5, dday = cc
        ten, kij, sA, sB = ichimoku(c5)
        c5["above"] = (c5["close"] > np.maximum(sA, sB)).astype(float)   # 1 above cloud / 0 else
        c5["below"] = (c5["close"] < np.minimum(sA, sB)).astype(float)
        c5["green"] = (sA > sB).astype(float)                            # bullish cloud color
        c5["tk_bull"] = (ten > kij).astype(float)
        c5["cbrk_up"] = ((c5["close"] > np.maximum(sA, sB)) & (c5["close"].shift(1) <= np.maximum(sA, sB).shift(1))).astype(float)
        c5["cbrk_dn"] = ((c5["close"] < np.minimum(sA, sB)) & (c5["close"].shift(1) >= np.minimum(sA, sB).shift(1))).astype(float)
        c5["tkx_up"] = ((ten > kij) & (ten.shift(1) <= kij.shift(1))).astype(float)
        c5["tkx_dn"] = ((ten < kij) & (ten.shift(1) >= kij.shift(1))).astype(float)
        # daily cloud (PRIOR day only, no lookahead)
        dt, dk, dA, dB = ichimoku(dday, 9, 26, 52)
        dday["dbull"] = (dday["close"] > np.maximum(dA, dB)).shift(1).astype(float)
        dday["dbear"] = (dday["close"] < np.minimum(dA, dB)).shift(1).astype(float)
        dday["d"] = pd.to_datetime(dday["ts"]).dt.tz_convert("America/New_York").dt.date

        lb = 3 if sym in ("NQ", "ES", "GC") else 5
        d = H.compute_state(B._externals(con, hs_db.bars(con, "5m", "rth", sym=sym), sym), H.P(struct_lb_fix=lb))
        d.attrs["sym"] = sym
        # causal map: each RTH 5m bar gets the most recent continuous-5m Ichimoku (backward merge).
        # both keys forced to datetime64[ns, UTC] (engine ts is us/ET, resample is ns/UTC — merge_asof needs a match)
        cols = ["above", "below", "green", "tk_bull", "cbrk_up", "cbrk_dn", "tkx_up", "tkx_dn"]
        d["mk"] = pd.to_datetime(d["ts"], utc=True).astype("datetime64[ns, UTC]")
        c5m = c5[["ts"] + cols].copy()
        c5m["mk"] = pd.to_datetime(c5m["ts"], utc=True).astype("datetime64[ns, UTC]")
        d = pd.merge_asof(d.sort_values("mk"), c5m.drop(columns=["ts"]).sort_values("mk"),
                          on="mk", direction="backward", tolerance=pd.Timedelta("6min"))
        d["_dt"] = pd.to_datetime(d["mk"]).dt.tz_convert("America/New_York").dt.date
        d = d.merge(dday[["d", "dbull", "dbear"]], left_on="_dt", right_on="d", how="left")
        d = d.drop(columns=["mk", "_dt", "d"], errors="ignore")
        for cxx in cols + ["dbull", "dbear"]:
            d[cxx] = d[cxx].fillna(0.0)
        d.attrs["sym"] = sym                     # merge_asof/merge dropped attrs; struct-stop backtest reads it
        n = len(d)
        abv = d["above"].to_numpy() > 0; blw = d["below"].to_numpy() > 0
        grn = d["green"].to_numpy() > 0; tkb = d["tk_bull"].to_numpy() > 0
        db = d["dbull"].to_numpy() > 0; ds = d["dbear"].to_numpy() > 0

        bt = lambda el, es, **k: B.backtest(d, "tp2_full", "both", False, "ext", 0, 1.0, 4.0, 570, 600, 0.0, 900,
                                            "close", eod_min=958, stop_mode="struct", ext_long=el, ext_short=es)
        def orb(tu, td):
            d2 = d.copy(); d2["trend_up"] = tu; d2["trend_down"] = td
            return B.backtest(d2, "tp2_full", "both", False, "orb", 0, 1.0, 4.0, 570, 600, 0.0, 900, "close",
                              eod_min=958, stop_mode="struct", entry_delay=0, chase_atr=1.0, strong_body=0.25,
                              ft_confirm=True, dir_seq=True, or_mid_bias=True, min_or_width=2.4)

        print(f"\n{'='*104}\n{sym} — ICHIMOKU 9/26/52  (RTH 5m; cloud from continuous 5m, causal)\n{'='*104}")
        print(" A) STANDALONE (new edge, validated exit):")
        line("cloud-break", bt(d["cbrk_up"].to_numpy() > 0, d["cbrk_dn"].to_numpy() > 0))
        line("TK-cross (above cloud)", bt((d["tkx_up"].to_numpy() > 0) & abv, (d["tkx_dn"].to_numpy() > 0) & blw))
        line("in-cloud-dir (above/below)", bt(abv & (d["cbrk_up"].to_numpy() > 0) | (d["tkx_up"].to_numpy() > 0) & abv,
                                              blw & (d["cbrk_dn"].to_numpy() > 0) | (d["tkx_dn"].to_numpy() > 0) & blw))
        base = orb(np.ones(n, bool), np.ones(n, bool))
        bn = len(base)
        print(" B) ADDITIVE to ORB (filter; dropped-cohort control):")
        line("ORB baseline (ref)", base)
        f_cloud = orb(abv, blw)
        line("ORB + price>cloud", f_cloud, bn)
        line("ORB + cloud-color", orb(grn, ~grn), bn)
        line("ORB + TK-side", orb(tkb, ~tkb), bn)
        line("ORB + daily-cloud HTF", orb(db, ds), bn)
        # were the dropped trades winners? (ORB baseline minus the price>cloud cohort)
        bset = set(zip(pd.to_datetime(base["entry_time"]).astype("int64"), base["direction"])) if len(base) else set()
        fset = set(zip(pd.to_datetime(f_cloud["entry_time"]).astype("int64"), f_cloud["direction"])) if len(f_cloud) else set()
        drop = base[[ (t, dr) not in fset for t, dr in zip(pd.to_datetime(base["entry_time"]).astype("int64"), base["direction"]) ]]
        line("  DROPPED by price>cloud", drop)
        del d, c5, cc; gc.collect()
    con.close()
    print("\nKEY: STANDALONE graduates only on full gauntlet (exp+CIlo>0, both sides, >=70% yr). ADDITIVE graduates only if a "
          "filter RAISES exp/CIlo over the ORB baseline AND the DROPPED cohort is worse than what's kept (removing losers, "
          "not winners). If price>cloud ~= OR-mid/dir-seq we already have, expect redundancy (no unique lift).")

if __name__ == "__main__":
    main()
