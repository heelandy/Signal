#!/usr/bin/env python3
"""
F61 — DIRECTION-SEQUENCE entry gate (example.txt / Evidence early-entry rule), honest validation.

User rule (example.txt): a long should only fire while price is *beginning to push up* — current
candle bullish AND close > prev close AND prev close > the close before (101->102->103); short mirror.
"No middle-of-trend signal, no chase, no opposite-direction signal." This is the `dir_seq` gate just
added to engine/hs_backtest.py. Question: does requiring the 2-bar rising-close sequence on TOP of the
shipped close-confirm stack KEEP the edge (propagate) or COST it (it's only a discretionary visual)?

Base = the shipped production STACK default (F59c): execm="close" full-body strong (0.25) + next-bar
follow-through, struct stop (F25b), skip first hour (F38), capped-TP2 4R exit (F34b), plain-ORB gate
(F58). Only dir_seq varies. RTH 5m.

    python research/orb_dir_seq.py [SYM ...]      (default NQ QQQ SPY)
"""
import sys, os, gc
sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "engine"))
import numpy as np, pandas as pd
import hs_db, hs_harness as H, hs_backtest as B, hs_validate as V

ORS, ORE, CUT, EOD = 570, 600, 900, 958
T1, T2, DELAY, SB = 1.0, 4.0, 60, 0.25


def run(d, dir_seq):
    d["trend_up"] = True; d["trend_down"] = True          # F58 plain-ORB gate (shipped default)
    return B.backtest(d, "tp2_full", "both", False, "orb", 0, T1, T2, ORS, ORE, 0.0, CUT, "close",
                      eod_min=EOD, stop_mode="struct", entry_delay=DELAY,
                      strong_body=SB, ft_confirm=True, dir_seq=dir_seq)


def boot_cilo(r, n=2000, seed=0):
    if len(r) < 10:
        return float("nan")
    rng = np.random.default_rng(seed)
    means = r[rng.integers(0, len(r), size=(n, len(r)))].mean(axis=1)
    return np.percentile(means, 5)


def yr_pos(tr):
    t = tr.copy()
    t["y"] = pd.to_datetime(t["entry_time"], utc=True).dt.tz_convert("America/New_York").dt.year
    g = t.groupby("y")["net_R"].mean()
    return int((g > 0).sum()), len(g), (g.min() if len(g) else float("nan"))


def oos(tr):
    t = tr.sort_values("entry_time"); r = t["net_R"].to_numpy(); k = int(len(r) * 0.7)
    if k < 5 or len(r) - k < 5:
        return float("nan"), len(r) - k
    return r[k:].mean(), len(r) - k


def main():
    syms = [s.upper() for s in (sys.argv[1:] or ["NQ", "QQQ", "SPY"])]
    con = hs_db.connect()
    print(f"{'sym':>4} {'gate':>9} {'n':>5} {'expR':>8} {'CIlo':>7} {'PF':>5} {'win%':>5} "
          f"{'totR':>7} {'longExp':>8} {'shrtExp':>8} {'yrs+':>7} {'OOSout':>7}")
    print("-" * 96)
    for sym in syms:
        bars = B._externals(con, hs_db.bars(con, "5m", "rth", sym=sym), sym)
        d = H.compute_state(bars, H.P()); d.attrs["sym"] = sym
        del bars; gc.collect()
        for label, ds in [("base", False), ("+dir_seq", True)]:
            tr = run(d, ds); r = tr["net_R"].to_numpy()
            if not len(r):
                print(f"{sym:>4} {label:>9}  (no trades)"); continue
            lr = tr.net_R[tr.direction == "long"].to_numpy()
            sr = tr.net_R[tr.direction == "short"].to_numpy()
            npos, ny, _ = yr_pos(tr); oo, no = oos(tr)
            print(f"{sym:>4} {label:>9} {len(r):>5} {r.mean():>+8.3f} {boot_cilo(r):>+7.3f} "
                  f"{V.pf(r):>5.2f} {100*np.mean(r>0):>5.0f} {r.sum():>+7.0f} "
                  f"{(lr.mean() if len(lr) else float('nan')):>+8.3f} "
                  f"{(sr.mean() if len(sr) else float('nan')):>+8.3f} {npos:>3}/{ny:<3} {oo:>+7.3f}")
        del d; gc.collect()
    con.close()
    print("\nPROPAGATE if +dir_seq keeps exp>0, CIlo>0, PF>~1.2, yrs+ majority, OOS>0 and ~holds vs base.")
    print("REJECT (visual-only) if it cuts trades and degrades exp/CIlo (like F57 chase / F58 gate).")


if __name__ == "__main__":
    main()
