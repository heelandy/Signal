#!/usr/bin/env python3
"""
HIGHSTRIKE Phase 3.3/3.4 — validation stats engine (the real one).

Consumes a trade list (hs_backtest.py output, or fills->trades with a net_R column) and
reports the numbers the definition of success is written in:
  * expectancy (net R) + 90% bootstrap CI  -> WIN requires the LOWER CI > 0
  * profit factor, win%, payoff, max drawdown (R) + bootstrapped maxDD
  * regime-stratified (A/B/C/D via the trade's macro regime tag)
  * per-year + the 5 success-criteria regime windows (2011 / 2015-16 / 2018-Q4 / 2020 / 2022)
  * long vs short subset (settle the short edge)
  * slippage stress (+1 / +2 ticks) using each trade's risk_pts

    python hs_validate.py data/bt_nq_15m.csv [--boot 5000]
PF target rules: 1.5 solid / 1.75 good / 2.0 strong / 4.0+ = curve-fit warning.
"""
import sys
import numpy as np, pandas as pd

PT_VALUE, TICK, CONTRACTS = 2.0, 0.25, 2


def pf(x):
    w = x[x > 0].sum(); ldn = -x[x < 0].sum()
    return (w / ldn) if ldn > 0 else float("inf")


def maxdd(r):
    eq = np.cumsum(r); return float((eq - np.maximum.accumulate(eq)).min())


def block(name, r):
    if len(r) == 0:
        print(f"  {name:22} (no trades)"); return
    print(f"  {name:22} n={len(r):>5}  exp {np.mean(r):+.3f}R  PF {pf(r):.2f}  "
          f"win {100*np.mean(r>0):4.1f}%  net {np.sum(r):+7.0f}R  maxDD {maxdd(r):7.1f}R")


def main():
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    path = args[0] if args else "data/bt_nq_15m.csv"
    B = 5000
    for i, f in enumerate(sys.argv):
        if f == "--boot" and i + 1 < len(sys.argv): B = int(sys.argv[i + 1])
    t = pd.read_csv(path)
    if "net_R" not in t.columns:
        sys.exit("trade list needs a net_R column (use hs_backtest.py output).")
    t["entry_time"] = (pd.to_datetime(t["entry_time"], utc=True, errors="coerce")
                       .dt.tz_convert("America/New_York").dt.tz_localize(None))
    t["year"] = t["entry_time"].dt.year
    r = t["net_R"].to_numpy()
    rng = np.random.default_rng(7)

    print(f"VALIDATION  {path}   ({len(t):,} trades, {t.entry_time.min().date()}..{t.entry_time.max().date()})\n")
    print("HEADLINE (net of costs):")
    print(f"  expectancy:   {r.mean():+.4f} R / trade        total {r.sum():+.0f} R")
    print(f"  profit factor:{pf(r):.3f}    win {100*np.mean(r>0):.1f}%    "
          f"payoff {t.net_R[t.net_R>0].mean():.2f} / {t.net_R[t.net_R<=0].mean():.2f}")
    print(f"  max drawdown: {maxdd(r):.1f} R")
    # bootstrap expectancy CI (the gate)
    means = rng.choice(r, size=(B, len(r)), replace=True).mean(axis=1)
    lo, hi = np.percentile(means, [5, 95])
    dd = np.array([maxdd(rng.choice(r, len(r), replace=True)) for _ in range(min(B, 1000))])
    verdict = "PASS (lower CI > 0)" if lo > 0 else "FAIL (lower CI <= 0)"
    print(f"  90% CI expectancy: [{lo:+.4f}, {hi:+.4f}] R   -> {verdict}")
    print(f"  bootstrapped maxDD 5th pct: {np.percentile(dd,5):.1f} R")

    print("\nLONG vs SHORT:")
    block("long", t.net_R[t.direction == "long"].to_numpy())
    block("short", t.net_R[t.direction == "short"].to_numpy())

    print("\nBY MACRO REGIME:")
    for g in ["A", "B", "C", "D", "—"]:
        if (t.regime == g).any(): block(f"regime {g}", t.net_R[t.regime == g].to_numpy())

    print("\nSUCCESS-CRITERIA REGIME WINDOWS:")
    wins = {"2011": ("2011-01-01", "2011-12-31"), "2015-16": ("2015-07-01", "2016-03-31"),
            "2018-Q4": ("2018-10-01", "2018-12-31"), "2020": ("2020-01-01", "2020-12-31"),
            "2022": ("2022-01-01", "2022-12-31")}
    for lbl, (a, b) in wins.items():
        m = (t.entry_time >= a) & (t.entry_time <= b)
        block(lbl, t.net_R[m].to_numpy())

    print("\nPER YEAR:")
    for y in sorted(t.year.unique()):
        block(str(y), t.net_R[t.year == y].to_numpy())

    print("\nSLIPPAGE STRESS (extra ticks/fill, via each trade's risk_pts):")
    block("baseline", r)
    for extra in (1, 2):
        add_R = (extra * TICK * PT_VALUE * 2 * CONTRACTS) / (t["risk_pts"] * PT_VALUE * CONTRACTS)
        block(f"+{extra} tick", (t["net_R"] - add_R).to_numpy())


if __name__ == "__main__":
    main()
