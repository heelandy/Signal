#!/usr/bin/env python3
"""Multi-strategy 'style-premia' book (AQR/Man AHL style) — legs 1,2,3,4,6,8 built retail-realistically
from ETF history. Each leg = a daily return series; report Sharpe/vol/DD + correlation matrix, then a
risk-parity (inverse-vol) combination. Canonical params (12m TSMOM, 6m XS-mom, standard factor ETFs) — no
tuning, to avoid overfit. Long/short factor spreads for value/quality/defensive (the retail access route).
"""
import sys
import numpy as np, pandas as pd
import yfinance as yf

TK = ["SPY", "TLT", "GLD", "DBC", "UUP", "IEF",
      "XLK", "XLF", "XLE", "XLV", "XLY", "XLP", "XLI", "XLU", "XLB",
      "IWD", "IWF", "QUAL", "SPLV", "SPHB", "^VIX"]


def load():
    px = yf.download(TK, start="2014-01-01", auto_adjust=True, progress=False)["Close"]
    if isinstance(px.columns, pd.MultiIndex):
        px.columns = px.columns.get_level_values(0)
    return px.dropna(how="all")


def stats(r, name):
    r = r.dropna()
    if len(r) < 100:
        return {"leg": name, "n": len(r), "ann%": np.nan, "vol%": np.nan, "Sharpe": np.nan, "maxDD%": np.nan}
    ann = r.mean() * 252; vol = r.std() * np.sqrt(252); sh = ann / vol if vol else 0
    cum = (1 + r).cumprod(); dd = (cum / cum.cummax() - 1).min()
    return {"leg": name, "n": len(r), "ann%": round(100 * ann, 1), "vol%": round(100 * vol, 1),
            "Sharpe": round(sh, 2), "maxDD%": round(100 * dd, 1)}


def leg1_trend(px, ret):
    a = ["SPY", "TLT", "GLD", "DBC", "UUP"]                 # 5 asset classes
    sig = np.sign(px[a].pct_change(252)).shift(1)           # 12m TSMOM, causal
    volt = (ret[a].rolling(60).std() * np.sqrt(252)).shift(1)
    w = sig * (0.10 / volt).clip(upper=3.0)                 # vol-target 10%/asset, cap leverage 3x
    return (w * ret[a]).mean(axis=1)


def leg2_xsmom(px, ret):
    s = ["XLK", "XLF", "XLE", "XLV", "XLY", "XLP", "XLI", "XLU", "XLB"]
    mom = px[s].pct_change(126)                             # 6m
    rank = mom.rank(axis=1, ascending=False)
    long = (rank <= 3).astype(float)                       # hold top 3 sectors
    w = long.div(long.sum(axis=1), axis=0).shift(1)
    return (w * ret[s]).sum(axis=1)


def leg3_value(ret):
    return ret["IWD"] - ret["IWF"]                          # value minus growth (long/short factor)


def leg4_quality(ret):
    return ret["QUAL"] - ret["SPY"]                        # quality factor excess


def leg6_vrp(px, ret):
    impl = ((px["^VIX"] / 100) ** 2 / 252).shift(1)         # implied daily variance (causal)
    real = ret["SPY"] ** 2                                  # realized daily variance
    r = (impl - real)                                       # short-variance daily P&L (the VRP)
    return r * 20.0                                         # lever to a tradeable ~equity-like vol


def leg8_defensive(ret):
    return ret["SPLV"] - ret["SPHB"]                        # low-beta minus high-beta (BAB)


def main():
    px = load(); ret = px.pct_change()
    print(f"loaded {px.shape[1]} ETFs, {px.index.min().date()}->{px.index.max().date()} ({len(px)} days)")
    legs = {
        "1 Trend (TSMOM)":   leg1_trend(px, ret),
        "2 XS-Momentum":     leg2_xsmom(px, ret),
        "3 Value (IWD-IWF)": leg3_value(ret),
        "4 Quality (QUAL-SPY)": leg4_quality(ret),
        "6 VRP (short-var)": leg6_vrp(px, ret),
        "8 Defensive (BAB)": leg8_defensive(ret),
    }
    L = pd.DataFrame(legs).dropna(how="all")
    print("\n=== PER-LEG (daily-return sleeves, canonical params) ===")
    rows = [stats(L[c], c) for c in L.columns]
    rows.append(stats(ret["SPY"], "  SPY (benchmark)"))
    print(pd.DataFrame(rows).to_string(index=False))
    print("\n=== CORRELATION MATRIX (daily) ===")
    print(L.corr().round(2).to_string())
    # risk-parity (inverse-vol) combined book, rebalanced on a rolling vol
    vol = L.rolling(90).std()
    w = (1 / vol).div((1 / vol).sum(axis=1), axis=0).shift(1)
    book = (w * L).sum(axis=1).dropna()
    print("\n=== COMBINED BOOK (risk-parity across the 6 sleeves) ===")
    print(pd.DataFrame([stats(book, "MULTI-STRATEGY BOOK"), stats(ret["SPY"].loc[book.index], "SPY same window")]).to_string(index=False))
    corr_spy = book.corr(ret["SPY"].reindex(book.index))
    print(f"\nbook correlation to SPY: {corr_spy:+.2f}   (low = genuine diversification)")


if __name__ == "__main__":
    main()
