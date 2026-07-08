#!/usr/bin/env python3
"""
F63 — BOOK-LEVEL order-flow PREDICTIVE test (QQQ XNAS MBO). The question F62 left open: is L3 order
flow ADDITIVE (predicts direction at a tradeable horizon) or just a filter on the breakout?

Method: per minute over the available MBO days, signed aggressive-trade flow (cum-delta, side 'B'=buy)
+ its rolling z-score; forward returns at 1/5/15/30 min (within-day). Report the Information
Coefficient (corr) at each horizon, and a continuation toy (trade the strong-imbalance direction,
hold H min) — exp/win over the window. Earlier contemporaneous QI–microprice corr was +0.96 and the
1s-ahead IC was NEGATIVE (reversion); this asks whether a LONGER horizon is predictable.

CAVEAT: only ~22 QQQ MBO days exist — this is EXPLORATORY (small sample), not a gauntlet graduate.

    python research/strat_orderflow_book.py [N_DAYS]      (default 10)
"""
import sys, os, time
sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "BOT"))
import numpy as np, pandas as pd
from bot.market_data import databento_local as L

HOR = [1, 5, 15, 30]


def day_minute(date, symbol="QQQ"):
    tr = L.load_mbo_day(date, symbol, actions=("T",), hhmm=("09:30", "16:00"))
    if tr.empty:
        return pd.DataFrame()
    tr = tr.set_index("ts_et")
    buy = tr["size"].where(tr["side"] == "B", 0)
    sell = tr["size"].where(tr["side"] == "A", 0)
    m = pd.DataFrame({"delta": (buy - sell).resample("1min").sum(),
                      "price": tr["price"].astype(float).resample("1min").last(),
                      "vol": tr["size"].resample("1min").sum()}).dropna(subset=["price"])
    base = m["delta"].rolling(30, min_periods=10)
    m["zcd"] = (m["delta"] - base.mean()) / (base.std() + 1e-9)
    m["cum"] = m["delta"].cumsum()
    for h in HOR:
        m[f"fwd{h}"] = m["price"].shift(-h) / m["price"] - 1.0     # within-day forward return
        m.iloc[-h:, m.columns.get_loc(f"fwd{h}")] = np.nan          # don't cross the day boundary
    return m


def main():
    ndays = int(sys.argv[1]) if len(sys.argv) > 1 else 10
    days = L.list_days("xnas")[:ndays]
    print(f"book-level order-flow test — {len(days)} QQQ MBO days ({days[0]}..{days[-1]})")
    frames = []
    for d in days:
        t = time.time(); m = day_minute(d)
        if len(m):
            frames.append(m); print(f"  {d}: {len(m)} min ({time.time()-t:.0f}s)")
    M = pd.concat(frames, ignore_index=True)
    print(f"\ntotal minutes: {len(M)}")

    print("\n=== Information Coefficient (corr of order-flow vs FORWARD return) ===")
    print(f"  {'feature':>8} " + " ".join(f"{'fwd'+str(h):>9}" for h in HOR))
    for feat in ("delta", "zcd"):
        ics = [M[[feat, f"fwd{h}"]].dropna().corr().iloc[0, 1] for h in HOR]
        print(f"  {feat:>8} " + " ".join(f"{ic:>+9.3f}" for ic in ics))

    print("\n=== Continuation toy: trade the strong-imbalance direction, hold H min ===")
    print(f"  {'rule':>16} {'n':>6} {'expRet':>9} {'win%':>5} {'avg|move|':>9}")
    for k in (1.0, 1.5, 2.0):
        for h in (5, 15):
            s = M[(M["zcd"].abs() >= k)].dropna(subset=[f"fwd{h}"])
            if len(s) < 30:
                continue
            ret = np.sign(s["zcd"]) * s[f"fwd{h}"]                  # return in the imbalance direction
            print(f"  |zcd|>={k} h{h:>2}m {len(s):>6} {ret.mean()*100:>+8.4f}% {100*(ret>0).mean():>4.0f}% "
                  f"{s[f'fwd{h}'].abs().mean()*100:>8.4f}%")
    print("\nREAD: IC>0 & rising with horizon + continuation expRet>cost => order flow is PREDICTIVE")
    print("(additive). IC~0/negative => contemporaneous/reversion only (a filter at best). Small n!")


if __name__ == "__main__":
    main()
