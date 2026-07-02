#!/usr/bin/env python3
"""CROSS-ASSET LEAD-LAG (the one untested item): does leader return at bar t predict/lead follower return at t+1?
'Follow price' — if ES leads NQ (or SPY leads QQQ), a leader move gives an early read on the follower. Test the
information coefficient (Spearman) of leader_ret[t] vs follower_ret[t+k] on aligned 5m RTH bars. Contemporaneous
(k=0) is the sanity check (should be high, same-instant); a TRADEABLE lead needs k>=1 IC materially > 0.

    python research/orb_lead_lag.py
"""
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "engine"))
import numpy as np, pandas as pd
import hs_db

def rets(con, sym):
    b = hs_db.bars(con, "5m", "rth", sym=sym).sort_values("ts")
    r = np.log(b["close"].to_numpy())
    r = pd.Series(np.concatenate([[np.nan], np.diff(r)]), index=pd.to_datetime(b["ts"].to_numpy()))
    return r[~r.index.duplicated()]

def ic(a, b, k):
    df = pd.concat([a.rename("lead"), b.shift(-k).rename("fol")], axis=1).dropna()
    if len(df) < 200:
        return float("nan"), 0
    return float(df["lead"].corr(df["fol"], method="spearman")), len(df)

def main():
    con = hs_db.connect()
    R = {s: rets(con, s) for s in ["NQ", "ES", "SPY", "QQQ"]}
    con.close()
    pairs = [("ES", "NQ"), ("NQ", "ES"), ("SPY", "QQQ"), ("QQQ", "SPY"), ("SPY", "NQ"), ("ES", "QQQ")]
    print(f"\n{'='*72}\nCROSS-ASSET LEAD-LAG (5m RTH) — Spearman IC of leader[t] vs follower[t+k]\n{'='*72}")
    print(f"  {'lead→follow':14} {'k=0 (same-bar)':>16} {'k=1 (5m ahead)':>16} {'k=2 (10m)':>12}")
    for a, b in pairs:
        i0, n = ic(R[a], R[b], 0); i1, _ = ic(R[a], R[b], 1); i2, _ = ic(R[a], R[b], 2)
        flag = "  <- lead?" if (not np.isnan(i1) and abs(i1) >= 0.05) else ""
        print(f"  {a+'→'+b:14} {i0:>16.3f} {i1:>16.3f} {i2:>12.3f}  n={n}{flag}")
    print("\n  k=0 high = they move TOGETHER (same 5m bar). A tradeable LEAD needs |k>=1 IC| >> 0.")
    print("  |IC|<0.05 at k>=1 = no exploitable 5m lead-lag (the lead is intrabar / already absorbed by bar close).")

if __name__ == "__main__":
    main()
