#!/usr/bin/env python3
"""
HIGHSTRIKE research — POST-HOC screen of candidate entry-quality filters. RESEARCH ONLY: this never
touches the production engine defaults or any Pine file. It runs the validated baseline, then asks of
the trades the system actually took: "is the SUBSET that passes a candidate filter higher quality?"
A post-hoc screen removes failing trades without substituting later ones, so it is a SCREEN (does this
lever separate good from bad?) — not the final number. A filter only graduates to a signal-level
implementation + full re-validation if it clearly lifts PF/CI on QQQ AND NQ while keeping enough trades.

    python research/orb_levers.py [SYM=QQQ] [TF=15m]
"""
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "engine"))
import numpy as np, pandas as pd
import hs_backtest as B
from orb_optimize import state, metrics


def show(lbl, tr):
    m = metrics(tr)
    if m is None:
        print(f"  {lbl:20} (<30 trades)")
        return
    keep = "" if "all" in lbl else f"  ({100*m['n']/show.base_n:.0f}% kept)"
    print(f"  {lbl:20} n={m['n']:4} exp={m['exp']:+.3f} PF={m['pf']:.2f} win={m['win']:4.1f}% "
          f"maxDD={m['maxdd']:6.1f} CI={m['loCI']:+.3f}{keep}")


def run(sym, tf):
    d = state(sym, tf)
    tr = B.backtest(d, "scale_be", "both", False, "orb", 0, None, 4.0, 570, 600, 0.25, 900, "stop")
    feat = d[["ts", "open", "close", "high", "low", "vwap_sess"]].copy()
    feat["ts"] = pd.to_datetime(feat["ts"], utc=True)
    t = tr.copy()
    t["entry_time"] = pd.to_datetime(t["entry_time"], utc=True)
    t = t.merge(feat, left_on="entry_time", right_on="ts", how="left", suffixes=("", "_bar"))
    show.base_n = len(tr)
    print(f"\n{sym} {tf} — baseline + post-hoc filter screens:")
    show("baseline (all)", tr)
    # 1 · VWAP-side — long above session VWAP / short below
    vside = ((t.direction == "long") & (t.entry_price >= t.vwap_sess)) | \
            ((t.direction == "short") & (t.entry_price <= t.vwap_sess))
    show("VWAP-side", t[vside])
    show("VWAP-WRONG-side", t[~vside])
    # 2 · entry-bar strength — bar closes in the top/bottom half toward the trade
    rng = (t.high - t.low).replace(0, np.nan)
    body_l = (t.close - t.low) / rng
    body_s = (t.high - t.close) / rng
    strong = ((t.direction == "long") & (body_l >= 0.5)) | ((t.direction == "short") & (body_s >= 0.5))
    show("strong-body break", t[strong])
    show("weak-body break", t[~strong])


def main():
    sym = sys.argv[1] if len(sys.argv) > 1 else None
    tf = sys.argv[2] if len(sys.argv) > 2 else "15m"
    for s in ([sym] if sym else ["QQQ", "NQ"]):
        run(s, tf)


if __name__ == "__main__":
    main()
