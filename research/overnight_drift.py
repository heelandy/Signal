"""OVERNIGHT DRIFT — buy MOC, sell next MOO (the close->open gap). The documented 'night effect'
(Cliff-Cooper-Gulen; Lou-Polk-Skouras "A Tug of War", JFE 2019): index returns accrue OVERNIGHT
while the RTH session is ~flat. Long-only (the anomaly is long). NOT in the ORB stack — a
diversifying stream that harvests exactly the window the intraday-flat book skips.

Reported through strat_daily's gauntlet (exp>0 net costs, bootstrap CI(R)>0, >=70% yrs+, OOS-out>0).
For contrast we also print the intraday (O->C) leg the anomaly says is weak.

    python research/overnight_drift.py [SYM ...]   (default QQQ SPY NQ ES)
"""
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "engine"))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import numpy as np
import hs_db
from strat_daily import load, cost_pct, atr, report


def s_overnight(d):
    o, c = d["open"].to_numpy(), d["close"].to_numpy()
    a, dt, sym = atr(d), d["dt"], d.attrs["sym"]
    tr = []
    for i in range(len(c) - 1):
        e, x = c[i], o[i + 1]                          # MOC in, next MOO out
        ret = (x - e) / e - cost_pct(sym, e)
        tr.append((dt.iloc[i], 1, ret, (x - e) / a[i] if a[i] > 0 else 0.0))
    return tr


def s_intraday(d):
    o, c = d["open"].to_numpy(), d["close"].to_numpy()
    a, dt, sym = atr(d), d["dt"], d.attrs["sym"]
    return [(dt.iloc[i], 1, (c[i] - o[i]) / o[i] - cost_pct(sym, o[i]),
             (c[i] - o[i]) / a[i] if a[i] > 0 else 0.0) for i in range(len(c))]


def main():
    syms = [s.upper() for s in (sys.argv[1:] or ["QQQ", "SPY", "NQ", "ES"])]
    con = hs_db.connect()
    for sym in syms:
        d = load(con, sym); d.attrs["sym"] = sym
        print(f"\n######## {sym} 1d — overnight drift ########")
        report("overnight (C->O)", s_overnight(d))
        report("intraday  (O->C)", s_intraday(d))
    con.close()
    print("\nPASS = exp>0 net costs AND bootstrap CI(R)>0 AND >=70% yrs+ AND OOS-out>0.")


if __name__ == "__main__":
    main()
