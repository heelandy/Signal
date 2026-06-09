#!/usr/bin/env python3
"""
HIGHSTRIKE — ingest a Databento US-equity OHLCV-1m CSV (XNAS.ITCH / DBEQ) into the same
continuous-1m parquet the futures pipeline uses, so hs_resample.py + hs_db + the backtest
all work unchanged. Equities have no contract roll, so adj_factor=1, is_roll=False.

    python hs_ingest_equity.py "xnas-...ohlcv-1m.csv" SPY
then:
    python hs_resample.py SPY     # -> data/bars/sym=SPY/...
"""
import sys, os
import numpy as np, pandas as pd, duckdb

ET = "America/New_York"


def ingest(csv, sym):
    con = duckdb.connect()
    df = con.execute(
        f"SELECT ts_event, open, high, low, close, volume FROM read_csv('{csv}') "
        f"WHERE open IS NOT NULL ORDER BY ts_event").df()
    con.close()
    et = pd.to_datetime(df["ts_event"], utc=True).dt.tz_convert(ET)
    mins = et.dt.hour * 60 + et.dt.minute
    wk = et.dt.dayofweek < 5
    out = pd.DataFrame({
        "ts_et": et,
        "open": df["open"].astype("float64"), "high": df["high"].astype("float64"),
        "low": df["low"].astype("float64"), "close": df["close"].astype("float64"),
        "volume": df["volume"].astype("int64"),
        "adj_factor": 1.0, "is_roll": False,
        "session": np.where(wk & (mins >= 570) & (mins < 960), "RTH", "ETH"),  # 09:30-16:00 ET = RTH
    })
    path = os.path.join("data", f"{sym.lower()}_continuous_1m.parquet")
    out.to_parquet(path, index=False)
    rth = (out["session"] == "RTH").sum()
    print(f"{sym}: {len(out):,} 1m bars ({rth:,} RTH)  "
          f"{out['ts_et'].min().date()}..{out['ts_et'].max().date()}  -> {path}")


if __name__ == "__main__":
    ingest(sys.argv[1], sys.argv[2].upper())
