#!/usr/bin/env python3
"""
F60 — CONSOLIDATED GAUNTLET under the FINAL (corrected) entry semantics.

All the entry fixes from F56-F59c are now in the engine; this re-runs the whole validation ONCE under the
single production entry so we have a clean, consistent set of numbers (not the piecemeal per-fix runs):

  FINAL ENTRY = clean-TREND gate (structure st_state) + close-confirm (execm="close") + STRONG full-body
                breakout candle (strong_body 0.25, right colour) + NEXT-candle CONTINUATION (ft_confirm) +
                honest gap-aware fill at the confirming close + struct stop + skip-first-hour (delay 60) +
                cap4 exit (full→4R) ; VWAP-cap OFF, OB OFF, macro+local-regime ON. RTH 5m.

Sections:
  1. ENTRY-FIX LADDER — touch(old) → close-confirm → +strong → +follow-through(FINAL), shows the cumulative
     effect of the fixes on NQ/QQQ/SPY.
  2. FINAL-CONFIG FULL GAUNTLET — per asset: n, exp(net), PF, win%, bootstrap 90% CI (the WIN gate),
     long/short split, per-year (pos/total, worst yr), 70/30 OOS, 2x/4x slip stress (futures).

    python research/orb_final_gauntlet.py [SYM ...]      (default NQ QQQ SPY ES GC)
"""
import sys, os, gc
sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "engine"))
import numpy as np, pandas as pd
import hs_db, hs_harness as H, hs_backtest as B, hs_validate as V

ORS, ORE, CUT, EOD, T1, T2, DELAY, SB = 570, 600, 900, 958, 1.0, 4.0, 60, 0.25
_rng = np.random.default_rng(7)


def ci_lo(r, n=2000):
    return float(np.percentile(_rng.choice(r, size=(n, len(r)), replace=True).mean(axis=1), 5)) if len(r) >= 10 else float("nan")


def run(d, execm="close", strong=SB, ft=True, gate="struct"):
    st = d["st_state"].to_numpy()
    if gate == "off":
        d["trend_up"] = True; d["trend_down"] = True
    else:
        d["trend_up"] = (st == 1); d["trend_down"] = (st == 2)
    return B.backtest(d, "tp2_full", "both", False, "orb", 0, T1, T2, ORS, ORE, 0.0, CUT, execm,
                      eod_min=EOD, vwap_cap=0.0, stop_mode="struct", entry_delay=DELAY, ob_confluence=False,
                      strong_body=strong, ft_confirm=ft)


def yr(tr):
    t = tr.copy()
    t["y"] = pd.to_datetime(t["entry_time"], utc=True).dt.tz_convert("America/New_York").dt.year
    g = t.groupby("y")["net_R"].mean()
    return int((g > 0).sum()), len(g), (g.min() if len(g) else float("nan"))


def oos(tr):
    r = tr.sort_values("entry_time")["net_R"].to_numpy(); k = int(len(r) * 0.7)
    return (r[:k].mean(), r[k:].mean()) if (k >= 5 and len(r) - k >= 5) else (float("nan"), float("nan"))


def line(sym, tr):
    r = tr["net_R"].to_numpy()
    if not len(r):
        print(f"  {sym:>4}  (no trades)"); return
    lr = tr.net_R[tr.direction == "long"].to_numpy(); sr = tr.net_R[tr.direction == "short"].to_numpy()
    p, ny, w = yr(tr); is_, oo = oos(tr); lo = ci_lo(r)
    gate = "PASS" if lo > 0 else "fail"
    print(f"  {sym:>4} {len(r):>5} {r.mean():>+7.3f} {V.pf(r):>5.2f} {100*np.mean(r>0):>4.0f}  "
          f"{lo:>+7.3f} {gate:>4}  {(lr.mean() if len(lr) else float('nan')):>+6.3f}/{(sr.mean() if len(sr) else float('nan')):>+6.3f}  "
          f"{p:>2}/{ny:<2} {w:>+6.3f}  {is_:>+6.3f}/{oo:>+6.3f}")


def hdr(t): print(f"\n{'='*100}\n{t}\n{'='*100}")


def load(con, sym):
    bars = B._externals(con, hs_db.bars(con, "5m", "rth", sym=sym), sym)
    d = H.compute_state(bars, H.P()); d.attrs["sym"] = sym
    del bars; gc.collect()
    return d


def main():
    syms = [s.upper() for s in (sys.argv[1:] or ["NQ", "QQQ", "SPY", "ES", "GC"])]
    only = len(syms) == 1                       # one-asset-per-process mode (memory-lean; run from a bash loop)
    con = hs_db.connect()
    if not only:
        print("NOTE: run one symbol per process on this box (low RAM):  for s in NQ QQQ SPY ES GC; do python research/orb_final_gauntlet.py $s; done")
    print(f"\n{'sym':>4} {'n':>5} {'expR':>7} {'PF':>5} {'win':>4}  {'CIlo':>7} {'gate':>4}  "
          f"{'long/short':>13}  {'yr+':>5} {'wYr':>6}  {'IS/OOS':>14}")
    for sym in syms:
        try:
            d = load(con, sym)
        except Exception as e:
            print(f"  {sym:>4}  (load failed: {str(e)[:50]})"); continue
        # ladder (cumulative effect of the entry fixes) for the equity/index majors
        if sym in ("NQ", "QQQ", "SPY"):
            print(f"  --- {sym} ENTRY-FIX LADDER (structure gate, cap4, struct stop, skip-1st-hr) ---")
            for lbl, ex, sb, ft in [("touch (old/F58 stop)", "stop", 0.0, False),
                                    ("close-confirm (F59)", "close", 0.0, False),
                                    ("+strong0.25 (F59b)", "close", SB, False),
                                    ("+follow-thru FINAL", "close", SB, True)]:
                r = run(d, ex, sb, ft)["net_R"].to_numpy()
                print(f"      {lbl:>22} n={len(r):>4} exp {r.mean():>+7.3f} PF {V.pf(r):>4.2f} win {100*np.mean(r>0):>3.0f}% CIlo {ci_lo(r):>+7.3f}")
        # FINAL-config gauntlet line + slip stress
        line(sym, run(d))
        if sym in ("NQ", "ES", "MNQ", "GC", "MGC"):
            orig = B.SLIP_TICKS; parts = []
            for mult in (1, 2, 3):
                B.SLIP_TICKS = orig * mult
                r = run(d)["net_R"].to_numpy()
                parts.append(f"{mult}x={r.mean():+.3f}(PF{V.pf(r):.2f})")
            B.SLIP_TICKS = orig
            print(f"      slip stress (futures): " + "  ".join(parts))
        del d; gc.collect()
    con.close()
    if only:
        print("\nKEY: CIlo=bootstrap 5th-pct exp (WIN gate >0). long/short=per-side exp. yr+=positive yrs/total.")
        print("wYr=worst-year exp. IS/OOS=70/30 split. FINAL=clean-trend+strong close-confirm+follow-through, cap4.")


if __name__ == "__main__":
    main()
