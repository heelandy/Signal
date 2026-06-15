#!/usr/bin/env python3
"""
HIGHSTRIKE F31e — user day-throttle rule in the eval sim: max N trades/day + LOCK the day
after K losing trades. Baseline (no throttle) vs throttle(5 trades, lock @ 2 losses) on the
production and unblock-B streams, per session + ALL THREE. Adds median CALENDAR days-to-pass
(the throttle stretches trade counts across days, so trades-to-pass alone would mislead).

    python research/orb_prop_eval_throttle.py
"""
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "engine"))
import numpy as np, pandas as pd
from orb_optimize import state
from orb_prop_eval import stack

PROFILES = [(9, 6, 4), (15, 10, 6), (30, 12, 8)]


def eval_path(r, dt, target, trail, daily, max_trades, cap=10**9, lock=10**9):
    """One attempt from index 0. Throttle: per ET day, stop taking trades after `cap` taken
    or `lock` losers. Skipped trades don't exist (flat). Returns (passed, blew, taken, days)."""
    eq = peak = 0.0; cur = None; day_sum = 0.0; day_n = 0; day_loss = 0
    taken = 0; days = 0
    for k in range(len(r)):
        if dt[k] != cur:
            cur = dt[k]; day_sum = 0.0; day_n = 0; day_loss = 0; days += 1
        if day_n >= cap or day_loss >= lock:
            continue                                   # throttled: this signal is not taken
        taken += 1; day_n += 1
        if r[k] < 0:
            day_loss += 1
        eq += r[k]; day_sum += r[k]; peak = max(peak, eq)
        if day_sum <= -daily:   return (False, True, taken, days)
        if eq <= peak - trail:  return (False, True, taken, days)
        if eq >= target:        return (True, False, taken, days)
        if taken >= max_trades: break
    return (False, False, taken, days)


def simulate(name, tr, cap=10**9, lock=10**9, max_trades=200):
    t = tr.sort_values("entry_time").reset_index(drop=True)
    r = t["net_R"].to_numpy()
    dt = pd.to_datetime(t["entry_time"], utc=True).dt.tz_convert("America/New_York").dt.normalize().to_numpy()
    print(f"  {name}  (n={len(r)})")
    for target, trail, daily in PROFILES:
        P = Bl = tot = 0; tp = []; dys = []
        for s in range(0, max(len(r) - 10, 1)):
            passed, blew, taken, days = eval_path(r[s:], dt[s:], target, trail, daily, max_trades, cap, lock)
            tot += 1; P += passed; Bl += blew
            if passed:
                tp.append(taken); dys.append(days)
        med = int(np.median(tp)) if tp else 0
        medd = int(np.median(dys)) if dys else 0
        print(f"    +{target}R/-{trail}R/-{daily}R: PASS {100*P/tot:4.0f}%  BLOW-UP {100*Bl/tot:4.0f}%  "
              f"timeout {100*(tot-P-Bl)/tot:4.0f}%  median {med if med else '—'} trades / {medd if medd else '—'} days")


def main():
    d = state("NQ", "5m")
    d3 = d.copy(deep=False)
    d3["macro_allow_trades"] = d["macro_allow_trades"].to_numpy() | (d["macro_regime"] == "B").to_numpy()
    d3.attrs.update(d.attrs)
    cat = lambda *xs: pd.concat(xs).sort_values("entry_time").reset_index(drop=True)
    print("F31e — day throttle (max 5 trades/day, lock day after 2 losses) vs no throttle\n")
    for lbl, dd in (("prod", d), ("unblock-B", d3)):
        ses = {s: stack(dd, s) for s in ("rth", "asia", "london")}
        ses["ALL THREE"] = cat(*ses.values())
        for sname, tr in ses.items():
            simulate(f"{lbl} {sname} — baseline", tr)
            simulate(f"{lbl} {sname} — throttle 5/2", tr, cap=5, lock=2)
            print()


if __name__ == "__main__":
    main()
