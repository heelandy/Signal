"""TURN-OF-MONTH (TOM) — buy the close 4 trading days before month-end, sell the close of the
3rd trading day of the new month. The documented calendar anomaly (Lakonishok-Smidt 1988;
Ogden 1990; McConnell-Xu 2008: the ENTIRE equity premium concentrates at the turn of the month
— pension/401k inflows, month-end rebalancing, payroll timing). Long-only (the anomaly is long),
a calendar stream fully uncorrelated with the breakout/trend/vol books.

Causality: "T-4 of the month" is known from the exchange calendar in advance — no lookahead.
Control: the SAME hold on all NON-window days must show ~nothing, or the "effect" is just drift.

Reported through strat_daily's gauntlet (exp>0 net costs, bootstrap CI(R)>0, >=70% yrs+, OOS-out>0).

    python research/turn_of_month.py [SYM ...]   (default QQQ SPY NQ ES)
"""
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "engine"))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import numpy as np
import pandas as pd
import hs_db
from strat_daily import load, cost_pct, atr, report

ENTER_BEFORE = 4       # enter at the close of the 4th-to-last trading day of the month
EXIT_AFTER = 3         # exit at the close of the 3rd trading day of the new month


def _tom_flags(dt: pd.Series) -> tuple[np.ndarray, np.ndarray]:
    """(enter[i], in_window[i]) per bar from the ACTUAL trading calendar in the data:
    enter = this bar is T-`ENTER_BEFORE` of its month; window = T-4 .. T+3 (for the control split)."""
    per = dt.dt.tz_convert("America/New_York").dt.to_period("M")
    n = len(dt)
    enter = np.zeros(n, bool)
    window = np.zeros(n, bool)
    idx = np.arange(n)
    for _, g in pd.Series(idx).groupby(per.values):
        gi = g.to_numpy()
        m = len(gi)
        if m >= ENTER_BEFORE:
            enter[gi[m - ENTER_BEFORE]] = True         # T-4 close
            window[gi[m - ENTER_BEFORE:]] = True       # T-4..month-end
        if m >= EXIT_AFTER:
            window[gi[:EXIT_AFTER]] = True             # T+1..T+3 of the new month
    return enter, window


def s_tom(d):
    """Enter MOC at T-4, exit MOC at T+3 of the next month (or last bar)."""
    c = d["close"].to_numpy()
    a, dt, sym = atr(d), d["dt"], d.attrs["sym"]
    enter, _ = _tom_flags(dt)
    per = dt.dt.tz_convert("America/New_York").dt.to_period("M").to_numpy()
    tr = []
    for i in np.flatnonzero(enter):
        j = i
        seen_new = 0
        while j + 1 < len(c):                          # walk into the new month, count T+ days
            j += 1
            if per[j] != per[i]:
                seen_new += 1
                if seen_new == EXIT_AFTER:
                    break
        e, x = c[i], c[j]
        ret = (x - e) / e - cost_pct(sym, e)
        tr.append((dt.iloc[i], 1, ret, (x - e) / a[i] if a[i] > 0 else 0.0))
    return tr


def s_control(d):
    """CONTROL — the same ~7-day hold entered at the close of every day OUTSIDE the TOM window.
    If this shows the same edge, the anomaly is just market drift and TOM adds nothing."""
    c = d["close"].to_numpy()
    a, dt, sym = atr(d), d["dt"], d.attrs["sym"]
    _, window = _tom_flags(dt)
    hold = ENTER_BEFORE + EXIT_AFTER                   # same length as the TOM hold
    tr = []
    i = 0
    while i < len(c) - hold:
        if not window[i]:
            e, x = c[i], c[i + hold]
            ret = (x - e) / e - cost_pct(sym, e)
            tr.append((dt.iloc[i], 1, ret, (x - e) / a[i] if a[i] > 0 else 0.0))
            i += hold                                  # non-overlapping holds
        else:
            i += 1
    return tr


def main():
    syms = [s.upper() for s in (sys.argv[1:] or ["QQQ", "SPY", "NQ", "ES"])]
    con = hs_db.connect()
    for sym in syms:
        d = load(con, sym); d.attrs["sym"] = sym
        print(f"\n######## {sym} 1d — turn of month (T-{ENTER_BEFORE} MOC -> T+{EXIT_AFTER} MOC) ########")
        report("TOM window", s_tom(d))
        report("control (all other days, same hold)", s_control(d))
    con.close()
    print("\nPASS = exp>0 net costs AND bootstrap CI(R)>0 AND >=70% yrs+ AND OOS-out>0 "
          "AND the control shows materially LESS (else it's just drift).")


if __name__ == "__main__":
    main()
