#!/usr/bin/env python3
"""Full multi-strategy book tests: 6 ETF sleeves + ORB (leg 7), risk-parity combination, vol-targeting +
VRP tail cap, drop-the-negatives sensitivity, and a per-year regime breakdown. Honest — flags the traps.
"""
import sys, os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "engine"))
import numpy as np, pandas as pd
from multi_strategy_book import load, stats, leg1_trend, leg2_xsmom, leg3_value, leg4_quality, leg6_vrp, leg8_defensive


def orb_leg():
    """Leg 7 = the intraday ORB book: daily R summed across NQ/ES/QQQ/SPY (5m RTH, full validated config)."""
    import hs_db, hs_harness as H, hs_backtest as B
    con = hs_db.connect(); series = {}
    for sym in ("NQ", "ES", "QQQ", "SPY"):
        d = H.compute_state(B._externals(con, hs_db.bars(con, "5m", "rth", sym=sym), sym), H.P())
        d.attrs["sym"] = sym; d["trend_up"] = True; d["trend_down"] = True
        tr = B.backtest(d, "tp2_full", "both", False, "orb", 0, 1.0, 4.0, 570, 600, 0.0, 900, "close",
                        eod_min=958, stop_mode="struct", entry_delay=60, strong_body=0.25, ft_confirm=True, dir_seq=True)
        tr["date"] = pd.to_datetime(tr.entry_time, utc=True).dt.tz_convert("America/New_York").dt.date
        series[sym] = tr.groupby("date").net_R.sum()
    con.close()
    r = pd.concat(series, axis=1).fillna(0).sum(axis=1) * 0.01     # 1% risk/R -> daily return (scale-invariant for RP)
    r.index = pd.to_datetime(r.index)
    return r


def risk_parity(L):
    vol = L.rolling(90).std()
    w = (1 / vol).div((1 / vol).sum(axis=1), axis=0).shift(1)
    return (w * L).sum(axis=1).dropna()


def vol_target(r, tgt=0.12):
    rv = (r.rolling(60).std() * np.sqrt(252)).shift(1)
    lev = (tgt / rv).clip(upper=5.0)
    return (r * lev).dropna()


def main():
    px = load(); ret = px.pct_change()
    legs = {"1 Trend": leg1_trend(px, ret), "2 XS-Mom": leg2_xsmom(px, ret), "3 Value": leg3_value(ret),
            "4 Quality": leg4_quality(ret), "6 VRP": leg6_vrp(px, ret), "8 Defensive": leg8_defensive(ret)}
    L6 = pd.DataFrame(legs).dropna(how="all")
    orb = orb_leg()
    L6.index = L6.index.normalize()
    orb.index = orb.index.normalize()
    L7 = L6.join(orb.rename("7 ORB"), how="outer")
    L7["7 ORB"] = L7["7 ORB"].fillna(0.0)                          # ORB = 0 on no-trade days
    L7 = L7.loc[L6.index.min():]

    print("=== ORB (leg 7) standalone ===")
    print(pd.DataFrame([stats(orb, "7 ORB (NQ+ES+QQQ+SPY daily)")]).to_string(index=False))
    print(f"ORB corr to SPY: {orb.reindex(ret.index.normalize()).corr(ret['SPY'].set_axis(ret.index.normalize())):+.2f}")

    print("\n=== BOOK comparisons (risk-parity) ===")
    book6 = risk_parity(L6); book7 = risk_parity(L7)
    L7_noneg = L7.drop(columns=["3 Value", "4 Quality", "8 Defensive"])   # keep 1,2,6,7 (the positive-Sharpe ones)
    book_pos = risk_parity(L7_noneg)
    rows = [stats(book6, "6 ETF sleeves"), stats(book7, "7 sleeves (+ORB)"),
            stats(book_pos, "4 positive only (1,2,6,7)")]
    print(pd.DataFrame(rows).to_string(index=False))
    for nm, b in (("7-sleeve", book7),):
        print(f"  {nm} corr to SPY: {b.corr(ret['SPY'].set_axis(ret.index.normalize()).reindex(b.index)):+.2f}")

    print("\n=== VOL-TARGETED (12%) + VRP TAIL CAP ===")
    L7c = L7.copy(); L7c["6 VRP"] = L7c["6 VRP"].clip(lower=-0.05)  # hard -5%/day floor on the short-vol leg
    book7c = risk_parity(L7c)
    lev7 = vol_target(book7, 0.12); lev7c = vol_target(book7c, 0.12)
    print(pd.DataFrame([stats(lev7, "7-sleeve levered 12% (no cap)"),
                        stats(lev7c, "7-sleeve levered 12% + VRP -5% cap")]).to_string(index=False))

    print("\n=== PER-YEAR Sharpe (7-sleeve book vs SPY) ===")
    yr = pd.DataFrame({"book": book7, "spy": ret["SPY"].set_axis(ret.index.normalize()).reindex(book7.index)}).dropna()
    yr["y"] = yr.index.year
    out = yr.groupby("y").apply(lambda g: pd.Series({
        "book_Sharpe": round(g.book.mean() / g.book.std() * np.sqrt(252), 2) if g.book.std() else 0,
        "spy_Sharpe": round(g.spy.mean() / g.spy.std() * np.sqrt(252), 2) if g.spy.std() else 0}))
    print(out.to_string())


if __name__ == "__main__":
    main()
