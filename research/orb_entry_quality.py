#!/usr/bin/env python3
"""
HIGHSTRIKE research — ENTRY-QUALITY filters (Item 1). RESEARCH ONLY: imports the frozen engine,
changes no engine default and no Pine file. Three questions:

  1. close-confirm + STRONG-BODY  — the one real lead (Finding 12). Body is known only at bar close,
     so to USE it you must switch from stop-entry to CLOSE-CONFIRM (worse fills). Decisive test:
     does the body-quality gain offset the worse fill? Compare:
        A) stop-entry         (production)
        B) close-confirm      (cost of switching)
        C) close-confirm + strong-body  (post-hoc body filter, LEGITIMATE here — entry is at the
           close, so the body is known at fill time, no lookahead).
     Adopt only if C >= A on QQQ AND NQ (both sides > 0, CI > 0).
  2. OR-WIDTH filter  — bucket the taken trades by opening-range width (in ATR); skip degenerate days?
  3. GAP filter (equity)  — bucket SPY/QQQ trades by overnight gap (open vs prior close, in ATR).

    python research/orb_entry_quality.py [SYM] [TF=15m]
"""
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "engine"))
import numpy as np, pandas as pd
import hs_backtest as B
from orb_optimize import state, metrics

EQ = ("SPY", "QQQ")


def brk_for(tf):
    return 0.0 if tf in ("1m", "5m") else 0.25       # per-TF auto_tf production buffer


def bt(d, tf, execm):
    return B.backtest(d, "scale_be", "both", False, "orb", 0, None, 4.0, 570, 600, brk_for(tf), 900, execm)


def show(lbl, tr, base_n=None):
    m = metrics(tr)
    if m is None:
        print(f"  {lbl:24} (<30 trades)"); return None
    keep = f"  ({100*m['n']/base_n:.0f}% kept)" if base_n else ""
    both = "both+" if m["both"] else "ONE<0"
    print(f"  {lbl:24} n={m['n']:4} exp={m['exp']:+.3f} PF={m['pf']:.2f} win={m['win']:4.1f}% "
          f"maxDD={m['maxdd']:6.1f} CI={m['loCI']:+.3f} L={m['Lexp']:+.2f} S={m['Sexp']:+.2f} {both}{keep}")
    return m


def merge_bar(d, tr):
    feat = d[["ts", "open", "high", "low", "close", "atr14"]].copy()
    feat["ts"] = pd.to_datetime(feat["ts"], utc=True)
    t = tr.copy(); t["entry_time"] = pd.to_datetime(t["entry_time"], utc=True)
    return t.merge(feat, left_on="entry_time", right_on="ts", how="left", suffixes=("", "_bar"))


def day_levels(d):
    """Per-day opening-range (09:30-10:00 ET) width and overnight gap, both normalized by ATR."""
    et = pd.to_datetime(d["ts"]).dt.tz_convert("America/New_York")
    date = et.dt.normalize().dt.tz_localize(None)
    mins = (et.dt.hour * 60 + et.dt.minute).to_numpy()
    df = pd.DataFrame({"date": date.to_numpy(), "h": d["high"].to_numpy(), "l": d["low"].to_numpy(),
                       "o": d["open"].to_numpy(), "c": d["close"].to_numpy(),
                       "atr": d["atr14"].to_numpy(), "mins": mins})
    inor = (mins >= 570) & (mins < 600)
    g = df[inor].groupby("date").agg(orh=("h", "max"), orl=("l", "min"), atr_or=("atr", "last"),
                                     opn=("o", "first"))
    rth = df[(mins >= 570) & (mins < 960)].groupby("date").agg(rth_close=("c", "last"))
    g = g.join(rth)
    g["or_w_atr"] = (g["orh"] - g["orl"]) / g["atr_or"]
    g["prev_close"] = g["rth_close"].shift(1)
    g["gap_atr"] = (g["opn"] - g["prev_close"]) / g["atr_or"]
    return g[["or_w_atr", "gap_atr"]].reset_index()


def run(sym, tf):
    d = state(sym, tf)
    print(f"\n{'='*78}\n{sym} {tf} — entry-quality research (buffer={brk_for(tf)} ATR, all-day, 4R/scale)\n{'='*78}")

    # ---------- 1 · close-confirm + strong-body (the decisive test) ----------
    tr_stop = bt(d, tf, "stop")
    tr_close = bt(d, tf, "close")
    print("1) STOP-ENTRY vs CLOSE-CONFIRM vs CLOSE-CONFIRM+STRONG-BODY")
    mA = show("A stop-entry (prod)", tr_stop)
    mB = show("B close-confirm", tr_close)
    tc = merge_bar(d, tr_close)
    rng = (tc.high - tc.low).replace(0, np.nan)
    body = np.where(tc.direction == "long", (tc.close - tc.low) / rng, (tc.high - tc.close) / rng)
    mC = show("C close-confirm+body>=.5", tc[body >= 0.5], base_n=len(tr_close))
    show("  (weak-body, for ref)", tc[body < 0.5], base_n=len(tr_close))
    if mA and mC:
        verdict = "ADOPT close-confirm+body" if (mC["exp"] >= mA["exp"] and mC["pf"] >= mA["pf"]
                                                 and mC["both"] and mC["loCI"] > 0) else "KEEP stop-entry"
        print(f"   -> C vs A: exp {mC['exp']:+.3f} vs {mA['exp']:+.3f}, PF {mC['pf']:.2f} vs {mA['pf']:.2f}"
              f"  ==> {verdict}")

    # ---------- 2 · OR-width filter ----------
    print("2) OR-WIDTH buckets (trades grouped by opening-range width in ATR)")
    dl = day_levels(d)
    ts_stop = tr_stop.copy()
    ts_stop["date"] = pd.to_datetime(ts_stop["entry_time"], utc=True).dt.tz_convert("America/New_York").dt.normalize().dt.tz_localize(None)
    ts_stop = ts_stop.merge(dl, on="date", how="left")
    qs = ts_stop["or_w_atr"].quantile([1/3, 2/3]).to_numpy()
    show(f"  narrow (<{qs[0]:.2f})", ts_stop[ts_stop.or_w_atr < qs[0]], base_n=len(tr_stop))
    show(f"  mid", ts_stop[(ts_stop.or_w_atr >= qs[0]) & (ts_stop.or_w_atr < qs[1])], base_n=len(tr_stop))
    show(f"  wide (>={qs[1]:.2f})", ts_stop[ts_stop.or_w_atr >= qs[1]], base_n=len(tr_stop))

    # ---------- 3 · gap filter (equity only) ----------
    if sym in EQ:
        print("3) GAP buckets (overnight open-vs-prior-close in ATR; equity only)")
        show("  with-gap (long&gap>0 / short&gap<0)",
             ts_stop[((ts_stop.direction == "long") & (ts_stop.gap_atr > 0.1)) |
                     ((ts_stop.direction == "short") & (ts_stop.gap_atr < -0.1))], base_n=len(tr_stop))
        show("  against-gap",
             ts_stop[((ts_stop.direction == "long") & (ts_stop.gap_atr < -0.1)) |
                     ((ts_stop.direction == "short") & (ts_stop.gap_atr > 0.1))], base_n=len(tr_stop))
        show("  flat-open (|gap|<=0.1)", ts_stop[ts_stop.gap_atr.abs() <= 0.1], base_n=len(tr_stop))


def main():
    tf = sys.argv[2] if len(sys.argv) > 2 else "15m"
    syms = [sys.argv[1]] if len(sys.argv) > 1 else ["QQQ", "NQ", "SPY"]
    for s in syms:
        run(s, tf)


if __name__ == "__main__":
    main()
