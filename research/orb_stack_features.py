#!/usr/bin/env python3
"""
RESEARCH — FIND NEW ORTHOGONAL EDGE (F38 hunt). F36/F37 proved that any trend/extension cull just rides the
VWAP-cap frontier. So run F15's feature-separation study but on the STACK'S RESIDUAL TRADES (post HH/HL gate +
post VWAP-cap k2) — the already-adopted leads are factored out, so whatever still separates winners from losers
is a candidate ORTHOGONAL axis. A feature is a lead only if its Spearman sign vs net_R is CONSISTENT across
NQ+QQQ+SPY. Top lead then gets the honest signal-level skip + the F37 additivity/frontier-lift control.

Features (causal — prior bar where the entry-bar value wouldn't be known at an intrabar fill):
  tod_min     time-of-day of the breakout (mins since midnight ET)
  mins_brk    minutes from OR close (600) to entry  (fast vs slow break)
  or_w_atr    opening-range width / ATR
  gap_dir     overnight gap in ATR, SIGNED by trade direction (+ = with-gap, - = against-gap)
  adx         local trend strength (prior bar)
  atr_pct     ATR as % of price (vol level)
  compress    ATR(7)/ATR(28) prior bar  (<1 squeeze / >1 expansion)
  vix_lvl     VIX 5d sma at entry date
  vix_chg     VIX 5d change %
  pdlvl_brk   entry distance beyond PRIOR-DAY high(long)/low(short) in ATR (+ = already broke the PD level)
  vwap_ext    signed VWAP extension in ATR (the adopted cap axis — included as a control, should be flat now)
  risk_pts    stop distance (vol proxy)
  dir_long    direction asymmetry

    python research/orb_stack_features.py [SYM ...]      (default NQ QQQ SPY)
"""
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "engine"))
import numpy as np, pandas as pd
import hs_db, hs_harness as H, hs_backtest as B, hs_validate as V

ORS, ORE, CUT, T1, T2, EOD, KCAP = 570, 600, 900, 1.0, 4.0, 958, 2.0
NUMF = ["tod_min", "mins_brk", "or_w_atr", "gap_dir", "adx", "atr_pct", "compress",
        "vix_lvl", "vix_chg", "pdlvl_brk", "vwap_ext", "risk_pts", "dir_long"]


def stack_trades(d):
    st = d["st_state"].to_numpy(); d["trend_up"] = st == 1; d["trend_down"] = st == 2
    return B.backtest(d, "scale_be", "both", False, "orb", 0, T1, T2, ORS, ORE, 0.0, CUT, "stop",
                      eod_min=EOD, vwap_cap=KCAP)


def feature_table(d, tr):
    et = pd.to_datetime(d["ts"]).dt.tz_convert("America/New_York")
    date = et.dt.normalize().dt.tz_localize(None)
    mins = (et.dt.hour * 60 + et.dt.minute).to_numpy()
    tr_ = H.true_range(d["high"], d["low"], d["close"])
    af, asl = H.rma(tr_, 7), H.rma(tr_, 28)
    f = pd.DataFrame({"ts": pd.to_datetime(d["ts"], utc=True), "date": date.to_numpy(),
                      "open": d["open"].to_numpy(), "high": d["high"].to_numpy(), "low": d["low"].to_numpy(),
                      "close": d["close"].to_numpy(), "atr14": d["atr14"].to_numpy(),
                      "vwap_sess": d["vwap_sess"].to_numpy(), "mins": mins,
                      "adx": d["adx"].shift(1).to_numpy(), "atr_pct": d["atr_pct"].shift(1).to_numpy(),
                      "compress": (af / asl).shift(1).to_numpy(),
                      "vix_lvl": d["vix_sma5"].to_numpy(),
                      "vix_chg": np.where(d["vix_prev5"].to_numpy() > 0,
                                          (d["vix_sma5"] - d["vix_prev5"]).to_numpy() / d["vix_prev5"].to_numpy() * 100, np.nan)})
    # per-day opening range + prior-day RTH hi/lo + prior RTH close (gap)
    inor = (mins >= ORS) & (mins < ORE); rthm = (mins >= ORS) & (mins < 960)
    dd = pd.DataFrame({"date": date.to_numpy(), "h": d["high"].to_numpy(), "l": d["low"].to_numpy(),
                       "o": d["open"].to_numpy(), "c": d["close"].to_numpy(), "atr": d["atr14"].to_numpy()})
    org = dd[inor].groupby("date").agg(orh=("h", "max"), orl=("l", "min"), atr_or=("atr", "last"), opn=("o", "first"))
    rth = dd[rthm].groupby("date").agg(rthh=("h", "max"), rthl=("l", "min"), rthc=("c", "last"))
    g = org.join(rth)
    g["or_w_atr"] = (g.orh - g.orl) / g.atr_or
    g["pdh"] = g.rthh.shift(1); g["pdl"] = g.rthl.shift(1)
    g["gap_atr"] = (g.opn - g.rthc.shift(1)) / g.atr_or
    g = g[["or_w_atr", "pdh", "pdl", "gap_atr"]].reset_index()

    t = tr.copy(); t["entry_time"] = pd.to_datetime(t["entry_time"], utc=True)
    t = t.merge(f, left_on="entry_time", right_on="ts", how="left")
    t["date"] = t["entry_time"].dt.tz_convert("America/New_York").dt.normalize().dt.tz_localize(None)
    t = t.merge(g, on="date", how="left")
    et2 = t["entry_time"].dt.tz_convert("America/New_York")
    sgn = np.where(t.direction == "long", 1.0, -1.0)
    t["tod_min"] = et2.dt.hour * 60 + et2.dt.minute
    t["mins_brk"] = t["tod_min"] - ORE
    t["dow"] = et2.dt.dayofweek; t["year"] = et2.dt.year
    t["gap_dir"] = sgn * t.gap_atr
    pdlvl = np.where(t.direction == "long", t.pdh, t.pdl)
    t["pdlvl_brk"] = sgn * (t.entry_price - pdlvl) / t.atr14
    t["vwap_ext"] = sgn * (t.entry_price - t.vwap_sess) / t.atr14
    t["dir_long"] = (t.direction == "long").astype(float)
    return t


def main():
    syms = [s.upper() for s in (sys.argv[1:] or ["NQ", "QQQ", "SPY"])]
    con = hs_db.connect(); store = {}; tables = {}
    for sym in syms:
        bars = B._externals(con, hs_db.bars(con, "5m", "full", sym=sym), sym)
        d = H.compute_state(bars, H.P()); d.attrs["sym"] = sym
        tr = stack_trades(d); t = feature_table(d, tr); tables[sym] = t
        print(f"\n{'='*74}\n{sym} 5m STACK residual trades — feature separation (n={len(t)})\n{'='*74}")
        cors = {}
        for ftr in NUMF:
            sub = t[[ftr, "net_R"]].replace([np.inf, -np.inf], np.nan).dropna()
            c = sub[ftr].corr(sub["net_R"], method="spearman") if len(sub) > 30 else np.nan
            cors[ftr] = c
            print(f"  {ftr:10} corr={c:+.3f}  n={len(sub)}")
        store[sym] = cors
    con.close()

    print(f"\n{'='*74}\nCROSS-ASSET sign consistency (a lead is real ONLY if the sign agrees on all):\n{'='*74}")
    print(f"  {'feature':10} " + " ".join(f"{s:>8}" for s in syms) + "   verdict")
    leads = []
    for ftr in NUMF:
        vals = [store[s].get(ftr, np.nan) for s in syms]
        ok = [v for v in vals if not np.isnan(v)]
        signs = {np.sign(v) for v in ok if abs(v) >= 0.02}      # ignore near-zero (noise) for the sign vote
        consistent = len(signs) == 1 and len(ok) == len(syms)
        strength = np.mean([abs(v) for v in ok]) if ok else 0
        tag = "LEAD" if consistent and strength >= 0.05 else ("consistent-weak" if consistent else "flips")
        if tag == "LEAD":
            leads.append((ftr, np.mean(ok)))
        print(f"  {ftr:10} " + " ".join(f"{v:+8.3f}" for v in vals) + f"   {tag}")
    print(f"\n  >> candidate orthogonal LEADS (sign-consistent, |corr|>=0.05): "
          f"{', '.join(f'{f}({c:+.2f})' for f, c in sorted(leads, key=lambda x: -abs(x[1]))) or 'NONE'}")

    # categorical expectancy on the pooled trades (time-of-day + regime + dow), per asset
    print(f"\n{'='*74}\nCATEGORICAL expectancy (pooled per asset) — time-of-day / regime / dow:\n{'='*74}")
    for sym in syms:
        t = tables[sym]
        tod = pd.cut(t.tod_min, [569, 660, 720, 810, 900, 960],
                     labels=["0930-1100", "1100-1200", "1200-1330", "1330-1500", "1500-1600"])
        print(f"\n  -- {sym}: by time-of-day of breakout --")
        for k, gg in t.groupby(tod, observed=True):
            print(f"     {str(k):12} exp={gg.net_R.mean():+.3f} PF={V.pf(gg.net_R.to_numpy()):.2f} n={len(gg)}")


if __name__ == "__main__":
    main()
