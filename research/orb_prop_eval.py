#!/usr/bin/env python3
"""
HIGHSTRIKE F26 — prop-eval / path simulation of the stack (the practical go-live check).
Walk the stack's CHRONOLOGICAL trade path against a funded-account ruleset, expressed in R (sizing-
agnostic; 1R = your fixed per-trade $ risk): a profit TARGET, a TRAILING max drawdown, and a DAILY-loss
limit. Rolling-start Monte-Carlo over the real sequence → pass-rate, blow-up-rate, median trades-to-pass.
Streams: NQ 5m RTH / Asia / London stacks, each pair, and ALL THREE on one account (F29 added London).

    python research/orb_prop_eval.py
"""
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "engine"))
import numpy as np, pandas as pd
import hs_db, hs_harness as H, hs_backtest as B
from orb_optimize import state


def _gate(d):
    st = d["st_state"].to_numpy(); d["trend_up"] = st == 1; d["trend_down"] = st == 2


def stack(d, session="rth"):
    _gate(d)
    if session == "asia":    # Tokyo-open OR 19:00-20:00 ET, flat 03:00 (trade-day mins, 18:00 ET = 0)
        return B.backtest(d, "scale_be", "both", False, "orb", 0, 1.0, 4.0, 60, 120, 0.0, 540, "stop",
                          tradeday=True, eod_min=540, vwap_cap=2.0)
    if session == "london":  # London-open OR 03:00-03:30 ET, flat 08:00 (F29 validated window)
        return B.backtest(d, "scale_be", "both", False, "orb", 0, 1.0, 4.0, 540, 570, 0.0, 840, "stop",
                          tradeday=True, eod_min=840, vwap_cap=2.0)
    return B.backtest(d, "scale_be", "both", False, "orb", 0, 1.0, 4.0, 570, 600, 0.0, 900, "stop",
                      eod_min=958, vwap_cap=2.0)


def eval_path(r, dt, target, trail, daily, max_trades):
    """One eval attempt from the start of arrays r (net_R) / dt (ET date). Returns (passed, blew, n)."""
    eq = peak = 0.0; cur = None; day_sum = 0.0
    for k in range(min(len(r), max_trades)):
        if dt[k] != cur:
            cur = dt[k]; day_sum = 0.0
        eq += r[k]; day_sum += r[k]; peak = max(peak, eq)
        if day_sum <= -daily:   return (False, True, k + 1)     # daily-loss breach
        if eq <= peak - trail:  return (False, True, k + 1)     # trailing-DD breach
        if eq >= target:        return (True, False, k + 1)     # target hit → pass
    return (False, False, min(len(r), max_trades))              # ran out of window (no breach, no pass)


def simulate(name, tr, profiles, max_trades=200):
    t = tr.sort_values("entry_time").reset_index(drop=True)
    r = t["net_R"].to_numpy()
    dt = pd.to_datetime(t["entry_time"], utc=True).dt.tz_convert("America/New_York").dt.normalize().to_numpy()
    print(f"  {name}  (n={len(r)} trades, span {t.entry_time.min():%Y-%m} … {t.entry_time.max():%Y-%m})")
    for target, trail, daily in profiles:
        starts = range(0, max(len(r) - 10, 1))
        P = Bl = tot = 0; tp = []
        for s in starts:
            passed, blew, n = eval_path(r[s:], dt[s:], target, trail, daily, max_trades)
            tot += 1; P += passed; Bl += blew
            if passed: tp.append(n)
        med = int(np.median(tp)) if tp else None
        print(f"    target +{target}R / trail -{trail}R / daily -{daily}R / {max_trades}-trade window: "
              f"PASS {100*P/tot:4.0f}%  BLOW-UP {100*Bl/tot:4.0f}%  timeout {100*(tot-P-Bl)/tot:4.0f}%  "
              f"median trades-to-pass {med if med else '—'}")


def main():
    d = state("NQ", "5m")
    rth = stack(d, "rth")
    asia = stack(d, "asia")
    lond = stack(d, "london")
    cat = lambda *xs: pd.concat(xs).sort_values("entry_time").reset_index(drop=True)
    # eval profiles in R: (target, trailing-DD, daily-loss). 1R ≈ your per-trade $ risk.
    profiles = [(9, 6, 4), (15, 10, 6), (30, 12, 8)]
    print("F26 prop-eval sim — NQ 5m stack, rolling-start over the real sequence (fixed-R sizing)\n")
    simulate("RTH stream", rth, profiles)
    print()
    simulate("Asia stream", asia, profiles)
    print()
    simulate("London stream", lond, profiles)
    print()
    simulate("RTH + Asia", cat(rth, asia), profiles)
    print()
    simulate("RTH + London", cat(rth, lond), profiles)
    print()
    simulate("Asia + London", cat(asia, lond), profiles)
    print()
    simulate("ALL THREE sessions", cat(rth, asia, lond), profiles)
    print("\n  note: profiles are in R. Map to your account by 1R = the $ you risk per trade")
    print("  (e.g. MNQ risking $150/trade -> target +15R ~ $2,250, trail -10R ~ $1,500, daily -6R ~ $900).")


if __name__ == "__main__":
    main()
