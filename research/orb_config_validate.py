#!/usr/bin/env python3
"""
F34 (option A) — VALIDATE the actual production config (struct gate + struct STOP + TRAIL) that the
live STACK Pine trades, since F33-CONFIG showed its PF-17/+3.6R headline is R-inflated and the combo
was never walk-forwarded together. Question: in DOLLARS (fixed-$ risk per trade, per instrument) and
per-year, is struct+trail actually better than the validated struct+scale_be / or+scale_be, or just
optically hot? Also exposes the STOP-OUT RATE (the user's screenshot: signals firing into instant
stops) so we can see if the tight struct stop whipsaws.

Cross-instrument NQ/QQQ/SPY/ES/GC 5m, RTH. Per-year +/tot + 70/30 OOS. Fixed-$ sizing: contracts =
risk_$ / (stop_pts × point_value), so 1 trade ≈ the same $ risk on every instrument.

    python research/orb_config_validate.py
"""
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "engine"))
import numpy as np, pandas as pd
import hs_db, hs_harness as H, hs_backtest as B, hs_validate as V

rng = np.random.default_rng(7)
RISK_D = 250.0                                    # fixed $ risk per trade (the funded sizing target)
# per-ticker point value ($ per 1.0 index point, 1 contract). Micros for futures, per-share for ETFs.
PTVAL = {"NQ": 2.0, "ES": 5.0, "GC": 10.0, "QQQ": 1.0, "SPY": 1.0}
CONFIGS = [                                        # label, exit mode, stop mode
    ("struct+trail (PROD)", "trail",    "struct"),
    ("struct+scale (F25b)", "scale_be", "struct"),
    ("or+scale (eval-canon)", "scale_be", "or"),
    ("struct+trail capped", "tp2_full", "struct"),  # struct stop but a 2R/-1R cap (tames the R blow-up)
]


def loci(r):
    return np.percentile(rng.choice(r, (3000, len(r)), replace=True).mean(1), 5) if len(r) else 0.0


def run(d, exit_mode, stop_mode):
    st = d["st_state"].to_numpy(); d["trend_up"] = st == 1; d["trend_down"] = st == 2
    return B.backtest(d, exit_mode, "both", False, "orb", 0, 1.0, 4.0, 570, 600, 0.0, 900, "stop",
                      eod_min=958, vwap_cap=2.0, stop_mode=stop_mode)


def report(sym, tag, tr):
    if tr is None or len(tr) < 30:
        print(f"    {tag:22} n={0 if tr is None else len(tr):>4}  (<30)"); return
    r = tr["net_R"].to_numpy()
    # dollar P&L with fixed-$ sizing: each trade risks ~RISK_D, so $ = net_R * RISK_D (R is $-normalized)
    dollars = r * RISK_D
    stop_rate = 100 * np.mean(r <= -0.5)          # "stopped for a loss" share (the whipsaw tell)
    be_rate   = 100 * np.mean((r > -0.5) & (r <= 0.1))
    # per-year + OOS
    t = tr.copy(); t["year"] = pd.to_datetime(t["entry_time"], utc=True).dt.tz_convert("America/New_York").dt.year
    yrs = [(int(y), g["net_R"].mean()) for y, g in t.groupby("year") if len(g) >= 8]
    pos = sum(1 for _, e in yrs if e > 0); tot = len(yrs)
    t = t.sort_values("entry_time").reset_index(drop=True); k = int(len(t) * 0.7)
    IN = t.iloc[:k]["net_R"].to_numpy(); OUT = t.iloc[k:]["net_R"].to_numpy()
    g = "PASS" if (loci(r) > 0 and tot and pos >= 0.7 * tot) else "----"
    print(f"    {tag:22} n={len(r):>4} exp {r.mean():+.3f}R  PF {V.pf(r):>5.2f}  win {100*np.mean(r>0):>2.0f}%  "
          f"STOP {stop_rate:>2.0f}% BE {be_rate:>2.0f}%  $/{int(RISK_D)}: avg {dollars.mean():>+5.0f} "
          f"med {np.median(dollars):>+5.0f}  yrs +{pos}/{tot}  OOS {IN.mean():+.2f}->{OUT.mean():+.2f}  {g}")


def main():
    con = hs_db.connect()
    print(f"F34 — production-config validation, RTH 5m, fixed ${int(RISK_D)} risk/trade.")
    print(f"STOP% = trades exiting at a loss <=-0.5R (the screenshot whipsaw). PF/exp in R; $ via per-ticker point value.\n")
    for sym in ("NQ", "QQQ", "SPY", "ES", "GC"):
        bars = B._externals(con, hs_db.bars(con, "5m", "full", sym=sym), sym)
        d = H.compute_state(bars, H.P()); d.attrs["sym"] = sym
        print(f"  == {sym}  (pt=${PTVAL.get(sym, 2.0):.0f}) ==")
        for label, exit_mode, stop_mode in CONFIGS:
            report(sym, label, run(d, exit_mode, stop_mode))
        print()
    con.close()


if __name__ == "__main__":
    main()
