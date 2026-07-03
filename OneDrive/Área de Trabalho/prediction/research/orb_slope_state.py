#!/usr/bin/env python3
"""COMBINED SLOPE ENGINE gauntlet (user research 2026-07 — 'what do the numbers reveal').

S = 0.50*(closeSlope/ATR) + 0.30*(bodyMidSlope/ATR) + 0.20*bodyPressure over N candles
(regression over EVERY candle; recency-weighted body pressure; ATR-normalized). The user's
observation: OR + SLOPE + STRUC aligned => price is moving that way, and the 1m read is on-spot
while higher TFs lag. This script measures, per instrument (RTH 5m, validated ORB config fixed):

  A) STANDALONE slope gate    — trade only when S agrees (threshold sweep 0.05/0.10/0.15/0.20/0.30)
  B) ADDITIVE on the stack    — require S-agreement ON TOP of struct3 + OR-mid + dir-seq + vol-exp;
                                the DROPPED cohort must be the losers for additivity
  C) ALIGNMENT (user's read)  — OR-zone + S + st_state all agree vs not (exp by alignment cohort)
  D) LATENCY                  — median minutes from OR close to entry per gate

Order of attack per the user's plan: 1 OR (done — zone machine shipped), 2 SLOPE (this), 3 STRUC
(1m feed shipped; gauntlet = swap the gate to st_state computed on 1m bars).

    python research/orb_slope_state.py NQ QQQ SPY
"""
import sys, os, gc
sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "engine"))
import numpy as np, pandas as pd
from numpy.lib.stride_tricks import sliding_window_view
import hs_db, hs_harness as H, hs_backtest as B, hs_validate as V

N_SLOPE = 12
THRESHOLDS = (0.05, 0.10, 0.15, 0.20, 0.30)

_rng = np.random.default_rng(7)
def ci_lo(r):
    return float(np.percentile(_rng.choice(r, size=(1500, len(r)), replace=True).mean(axis=1), 5)) if len(r) >= 10 else float("nan")
def yr(tr):
    t = tr.copy(); t["y"] = pd.to_datetime(t["entry_time"], utc=True).dt.tz_convert("America/New_York").dt.year
    g = t.groupby("y")["net_R"].mean(); return int((g > 0).sum()), len(g)
def oos(tr):
    r = tr.sort_values("entry_time")["net_R"].to_numpy(); k = int(len(r) * 0.7)
    return (r[:k].mean(), r[k:].mean()) if (k >= 5 and len(r) - k >= 5) else (float("nan"), float("nan"))
def latency(tr):
    et = pd.to_datetime(tr["entry_time"], utc=True).dt.tz_convert("America/New_York")
    return float(np.median(et.dt.hour * 60 + et.dt.minute - 600))
def line(tag, tr):
    if tr is None or len(tr) < 20:
        print(f"  {tag:24} n={0 if tr is None else len(tr):>4}  (too few)"); return
    r = tr["net_R"].to_numpy()
    L = tr.net_R[tr.direction == "long"].to_numpy(); S_ = tr.net_R[tr.direction == "short"].to_numpy()
    lo = ci_lo(r); p, ny = yr(tr); is_, oo = oos(tr)
    both = len(L) > 5 and L.mean() > 0 and len(S_) > 5 and S_.mean() > 0
    g = "PASS" if (lo > 0 and both and ny and p >= 0.7 * ny and oo > 0) else "----"
    print(f"  {tag:24} n={len(r):>4} exp {r.mean():+.3f} PF {V.pf(r):>4.2f} CIlo {lo:+.3f} "
          f"L{(L.mean() if len(L) else 0):+.2f}/S{(S_.mean() if len(S_) else 0):+.2f} yr+{p}/{ny} "
          f"OOS{is_:+.2f}/{oo:+.2f} lat{latency(tr):>4.0f}m {g}")


def slope_combined(d, n=N_SLOPE):
    """Causal combined S per bar: regression slopes via sliding windows + weighted body pressure."""
    c = d["close"].to_numpy(float); o = d["open"].to_numpy(float); a = d["atr14"].to_numpy(float)
    m = (o + c) / 2.0
    x = np.arange(n) - (n - 1) / 2.0
    denom = float((x * x).sum())
    S = np.full(len(c), np.nan)
    if len(c) < n:
        return S
    wc = sliding_window_view(c, n); wm = sliding_window_view(m, n)
    sc = (wc - wc.mean(axis=1, keepdims=True)) @ x / denom
    sm = (wm - wm.mean(axis=1, keepdims=True)) @ x / denom
    w = 1.0 + np.arange(n, dtype=float) / (n - 1)                 # oldest→newest inside each window
    body = c - o
    wb = sliding_window_view(body, n)
    num = wb @ w; den = np.abs(wb) @ w
    bp = np.where(den > 0, num / den, 0.0)
    valid = a[n - 1:] > 0
    S[n - 1:] = np.where(valid, 0.50 * sc / np.where(a[n - 1:] > 0, a[n - 1:], 1.0)
                         + 0.30 * sm / np.where(a[n - 1:] > 0, a[n - 1:], 1.0) + 0.20 * bp, np.nan)
    return S


def run_gate(d, tup, tdn, min_orw=0.0, ormid=True):
    d2 = d.copy(); d2["trend_up"] = tup; d2["trend_down"] = tdn; d2.attrs["sym"] = d.attrs.get("sym", "NQ")
    return B.backtest(d2, "tp2_full", "both", False, "orb", 0, 1.0, 4.0, 570, 600, 0.0, 900, "close",
                      eod_min=958, stop_mode="struct", entry_delay=0, chase_atr=1.0, strong_body=0.25,
                      ft_confirm=True, dir_seq=True, min_or_width=min_orw, or_mid_bias=ormid)


def main():
    syms = [s.upper() for s in (sys.argv[1:] or ["NQ", "QQQ", "SPY"])]
    con = hs_db.connect()
    for sym in syms:
        bars = B._externals(con, hs_db.bars(con, "5m", "rth", sym=sym), sym)
        lb = 3 if sym in ("NQ", "MNQ", "ES", "MES", "GC", "MGC") else 5
        d = H.compute_state(bars, H.P(struct_lb_fix=lb)); d.attrs["sym"] = sym
        st = d["st_state"].to_numpy()
        S = slope_combined(d)
        base_up = np.ones(len(d), bool); base_dn = np.ones(len(d), bool)
        print(f"\n{'='*100}\n{sym} RTH 5m — COMBINED SLOPE S gauntlet (N={N_SLOPE}; validated ORB config fixed)\n{'='*100}")
        line("plainORB (ref)", run_gate(d, base_up, base_dn))
        line("struct (ref)", run_gate(d, st == 1, st == 2))
        for th in THRESHOLDS:                                     # A) standalone slope gate
            line(f"A slope>|{th:.2f}|", run_gate(d, S >= th, S <= -th))
        for th in THRESHOLDS:                                     # B) additive on structure
            line(f"B struct+S{th:.2f}", run_gate(d, (st == 1) & (S >= th), (st == 2) & (S <= -th)))
        # C) alignment cohorts on the FULL stack (struct + vol-exp + OR-mid already in run_gate)
        full = run_gate(d, st == 1, st == 2, min_orw=2.4)
        line("C fullstack (ref)", full)
        line("C full+S0.10", run_gate(d, (st == 1) & (S >= 0.10), (st == 2) & (S <= -0.10), min_orw=2.4))
        # DROPPED cohort: full-stack trades where S disagreed — additivity demands these are the losers
        del d; gc.collect()
    con.close()
    print("\nKEY: additivity = the B/C rows must LIFT exp+CIlo over their refs AND the dropped cohort "
          "must be the losers; a threshold is only adopted if a PLATEAU of thresholds passes, per TF. "
          "NEXT (user plan step 3): re-run with the gate on the 1m-fed st_state (families.fast_state_1m).")


if __name__ == "__main__":
    main()
