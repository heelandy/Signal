#!/usr/bin/env python3
"""SMC / price-action cluster screen — 8 strategies through the IDENTICAL exit + costs as the validated ORB
(struct stop, cap-4R, EOD-flat, asset-aware costs) via the engine's `ext` entry hook, so results are directly
comparable. RTH 5m first-pass. Gauntlet gate = CIlo>0 AND both sides>0 AND >=70% yrs+ AND OOS>0.

  1 Order Block · 2 FVG (return-to-gap) · 3 Liquidity Grab · 4 False-break Fade · 5 MSS · 6 Breaker · 7 S/R · 9 Vol-POC

    python research/smc_cluster.py NQ        (one symbol per process; loop from bash)
"""
import sys, os, gc
sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "engine"))
import numpy as np, pandas as pd
import hs_db, hs_harness as H, hs_backtest as B, hs_validate as V

T1, T2, CUT, EOD = 1.0, 4.0, 900, 958
_rng = np.random.default_rng(7)


def ci_lo(r, n=2000):
    return float(np.percentile(_rng.choice(r, size=(n, len(r)), replace=True).mean(axis=1), 5)) if len(r) >= 10 else float("nan")


def yr(tr):
    t = tr.copy(); t["y"] = pd.to_datetime(t["entry_time"], utc=True).dt.tz_convert("America/New_York").dt.year
    g = t.groupby("y")["net_R"].mean(); return int((g > 0).sum()), len(g)


def oos(tr):
    r = tr.sort_values("entry_time")["net_R"].to_numpy(); k = int(len(r) * 0.7)
    return (r[:k].mean(), r[k:].mean()) if (k >= 5 and len(r) - k >= 5) else (float("nan"), float("nan"))


def _sh(a, k=1):
    out = np.empty_like(a, dtype=float); out[:k] = np.nan; out[k:] = a[:-k]; return out


# ---- signal generators: return (entry_long, entry_short) boolean arrays ----
def sig_orderblock(d):                              # enter on ENTERING an OB zone, in the aligned trend
    st = d["st_state"].to_numpy(); obl = d["in_bull_ob"].to_numpy().astype(bool); obs = d["in_bear_ob"].to_numpy().astype(bool)
    pol = np.concatenate([[False], obl[:-1]]); pos = np.concatenate([[False], obs[:-1]])
    return (obl & ~pol & (st == 1)), (obs & ~pos & (st == 2))


def sig_fvg(d):                                     # canonical: enter when price RETURNS into the last unfilled gap, with trend
    hi, lo, c, o, st = d["high"].to_numpy(), d["low"].to_numpy(), d["close"].to_numpy(), d["open"].to_numpy(), d["st_state"].to_numpy()
    n = len(d); el = np.zeros(n, bool); es = np.zeros(n, bool)
    bull = None; bear = None                        # (bottom, top) of the most-recent unfilled gap
    for i in range(2, n):
        if hi[i - 2] < lo[i]: bull = (hi[i - 2], lo[i])          # bullish FVG: gap above candle1.high
        if lo[i - 2] > hi[i]: bear = (hi[i], lo[i - 2])          # bearish FVG
        if bull and lo[i] <= bull[1] and lo[i] >= bull[0] and c[i] > o[i] and st[i] == 1:
            el[i] = True; bull = None                            # filled -> take it, retire the zone
        if bear and hi[i] >= bear[0] and hi[i] <= bear[1] and c[i] < o[i] and st[i] == 2:
            es[i] = True; bear = None
    return el, es


def sig_liqgrab(d):                                 # sweep a swing level then reject back = stop-hunt reversal (counter)
    hi, lo, c = d["high"].to_numpy(), d["low"].to_numpy(), d["close"].to_numpy()
    sph, spl = _sh(d["sph"].to_numpy()), _sh(d["spl"].to_numpy())
    el = (lo < spl) & (c > spl)                     # swept below swing low, closed back above -> long
    es = (hi > sph) & (c < sph)                     # swept above swing high, closed back below -> short
    return np.nan_to_num(el).astype(bool), np.nan_to_num(es).astype(bool)


def sig_fade(d, N=20):                              # failed breakout of the rolling N-bar extreme (fade)
    hi, lo, c = d["high"].to_numpy(), d["low"].to_numpy(), d["close"].to_numpy()
    rmax = _sh(pd.Series(hi).rolling(N).max().to_numpy()); rmin = _sh(pd.Series(lo).rolling(N).min().to_numpy())
    el = (lo < rmin) & (c > rmin); es = (hi > rmax) & (c < rmax)
    return np.nan_to_num(el).astype(bool), np.nan_to_num(es).astype(bool)


def sig_mss(d):                                     # market-structure shift: st_state flips -> trade the new trend
    st = d["st_state"].to_numpy(); p = np.concatenate([[0], st[:-1]])
    return (st == 1) & (p != 1), (st == 2) & (p != 2)


def sig_breaker(d):                                 # failed OB = breaker: OB against the prevailing trend -> trade the trend
    st = d["st_state"].to_numpy(); obl = d["in_bull_ob"].to_numpy().astype(bool); obs = d["in_bear_ob"].to_numpy().astype(bool)
    pos = np.concatenate([[False], obs[:-1]]); pol = np.concatenate([[False], obl[:-1]])
    return (obs & ~pos & (st == 1)), (obl & ~pol & (st == 2))   # bear-OB failing in uptrend -> long; mirror


def sig_sr(d, tol=0.0015):                          # bounce off the swing level (support long / resistance short), trend not opposing
    hi, lo, c, st = d["high"].to_numpy(), d["low"].to_numpy(), d["close"].to_numpy(), d["st_state"].to_numpy()
    sph, spl = _sh(d["sph"].to_numpy()), _sh(d["spl"].to_numpy())
    el = (lo <= spl * (1 + tol)) & (c > spl) & (st != 2)
    es = (hi >= sph * (1 - tol)) & (c < sph) & (st != 1)
    return np.nan_to_num(el).astype(bool), np.nan_to_num(es).astype(bool)


def sig_poc(d, tol=0.0015):                         # bounce off prior-day volume Point-of-Control
    et = pd.to_datetime(d["ts"]).dt.tz_convert("America/New_York"); day = et.dt.date.to_numpy()
    c = d["close"].to_numpy(); hi = d["high"].to_numpy(); lo = d["low"].to_numpy()
    vol = d["volume"].to_numpy().astype(float); st = d["st_state"].to_numpy()
    df = pd.DataFrame({"day": day, "c": c, "v": vol})
    poc_by_day = {}
    for dd, g in df.groupby("day"):
        if len(g) < 5: continue
        bins = np.linspace(g.c.min(), g.c.max(), 25)
        idx = np.clip(np.digitize(g.c.to_numpy(), bins) - 1, 0, len(bins) - 2)
        vb = np.bincount(idx, weights=g.v.to_numpy(), minlength=len(bins) - 1)
        poc_by_day[dd] = (bins[vb.argmax()] + bins[vb.argmax() + 1]) / 2
    days_sorted = sorted(poc_by_day)
    prevpoc = {days_sorted[i]: poc_by_day[days_sorted[i - 1]] for i in range(1, len(days_sorted))}
    poc = np.array([prevpoc.get(dd, np.nan) for dd in day])
    el = (lo <= poc * (1 + tol)) & (c > poc) & (st != 2)
    es = (hi >= poc * (1 - tol)) & (c < poc) & (st != 1)
    return np.nan_to_num(el).astype(bool), np.nan_to_num(es).astype(bool)


STRATS = [("1 OrderBlock", sig_orderblock), ("2 FVG", sig_fvg), ("3 LiqGrab", sig_liqgrab),
          ("4 Fade", sig_fade), ("5 MSS", sig_mss), ("6 Breaker", sig_breaker),
          ("7 S/R", sig_sr), ("9 VolPOC", sig_poc)]


def run(d, el, es):
    d["trend_up"] = True; d["trend_down"] = True     # SMC signals carry their own direction; keep macro/regime gate only
    return B.backtest(d, "tp2_full", "both", False, "ext", 0, T1, T2, 570, 600, 0.0, CUT, "close",
                      eod_min=EOD, stop_mode="struct", ext_long=el, ext_short=es)


def line(tag, tr):
    r = tr["net_R"].to_numpy()
    if len(r) < 25:
        print(f"  {tag:14} n={len(r):>4}  (too few)"); return
    L = tr.net_R[tr.direction == "long"].to_numpy(); S = tr.net_R[tr.direction == "short"].to_numpy()
    lo = ci_lo(r); p, ny = yr(tr); is_, oo = oos(tr)
    both = len(L) > 5 and L.mean() > 0 and len(S) > 5 and S.mean() > 0
    g = "PASS" if (lo > 0 and both and ny and p >= 0.7 * ny and (oo > 0)) else "----"
    print(f"  {tag:14} n={len(r):>4} exp {r.mean():+.3f} PF {V.pf(r):>4.2f} win {100*np.mean(r>0):>2.0f}% "
          f"CIlo {lo:+.3f} L{(L.mean() if len(L) else 0):+.2f}({len(L)}) S{(S.mean() if len(S) else 0):+.2f}({len(S)}) "
          f"yr+{p}/{ny} OOS{is_:+.2f}/{oo:+.2f} {g}")


def main():
    sym = (sys.argv[1] if len(sys.argv) > 1 else "NQ").upper()
    con = hs_db.connect()
    d = H.compute_state(B._externals(con, hs_db.bars(con, "5m", "rth", sym=sym), sym), H.P()); d.attrs["sym"] = sym
    con.close()
    print(f"\n{'='*104}\n{sym}  SMC CLUSTER  ({len(d):,} 5m RTH bars)  — same exit/costs as the ORB (struct stop, cap-4R)\n{'='*104}")
    # ORB baseline for reference
    st = d["st_state"].to_numpy(); d["trend_up"] = (st == 1); d["trend_down"] = (st == 2)
    orb = B.backtest(d, "tp2_full", "both", False, "orb", 0, T1, T2, 570, 600, 0.0, CUT, "close",
                     eod_min=EOD, stop_mode="struct", entry_delay=0, chase_atr=1.0, strong_body=0.25, ft_confirm=True)
    line("0 ORB (ref)", orb)
    for tag, fn in STRATS:
        try:
            el, es = fn(d); line(tag, run(d, el, es))
        except Exception as e:
            print(f"  {tag:14} ERROR {str(e)[:60]}")
    del d; gc.collect()
    print("  KEY: gate PASS = CIlo>0 & both sides>0 & >=70% yrs+ & OOS>0. exp=net R/trade after costs.")


if __name__ == "__main__":
    main()
