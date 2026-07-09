"""TIME-SERIES MOMENTUM (Moskowitz-Ooi-Pedersen, JFE 2012) — the managed-futures trend premium.
Sign of the trailing 12-month return (skipping the most recent month) sets the position for the
next month; both sides; non-overlapping monthly trades. On the futures (NQ/ES/GC) + equities.

Distinct from the intraday breakout stack — a slow, cross-regime trend stream. Reported through
strat_daily's gauntlet.

    python research/tsmom.py [SYM ...]   (default NQ ES GC QQQ SPY)
"""
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "engine"))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import numpy as np
import hs_db
from strat_daily import load, cost_pct, atr, report


def s_tsmom(d, lookback=252, skip=21, hold=21):
    c = d["close"].to_numpy(); a = atr(d); dt = d["dt"]; sym = d.attrs["sym"]; n = len(c)
    tr = []; i = lookback
    while i + hold < n:
        past = c[i - skip] / c[i - lookback] - 1.0        # 12mo ending ~1mo ago (causal)
        if not np.isfinite(past) or past == 0:
            i += hold; continue
        dr = 1 if past > 0 else -1
        fwd = c[i + hold] / c[i] - 1.0
        ret = dr * fwd - cost_pct(sym, c[i])
        R = dr * (c[i + hold] - c[i]) / a[i] if a[i] > 0 else 0.0
        tr.append((dt.iloc[i], dr, ret, R))
        i += hold
    return tr


def main():
    syms = [s.upper() for s in (sys.argv[1:] or ["NQ", "ES", "GC", "QQQ", "SPY"])]
    con = hs_db.connect()
    for sym in syms:
        d = load(con, sym); d.attrs["sym"] = sym
        print(f"\n######## {sym} 1d — time-series momentum (12-1mo) ########")
        for lb in (252, 126):                              # 12mo and 6mo trend
            report(f"tsmom {lb//21}mo", s_tsmom(d, lookback=lb))
    con.close()
    print("\nPASS = exp>0 net costs AND bootstrap CI(R)>0 AND >=70% yrs+ AND OOS-out>0 AND both sides>0.")


if __name__ == "__main__":
    main()
