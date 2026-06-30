"""Databento API puller — paste your key in BOT/config/.env, then this just works.

This is the ONLY file that talks to the Databento cloud. It pulls OHLCV-1m bars for the
symbols the strategy trades and writes them into the SAME continuous-1m parquet shape the
existing pipeline/engine already use (ts_et, open, high, low, close, volume, adj_factor,
is_roll, session), so hs_resample.py / hs_db / the backtest keep working unchanged.

    # one-time: pip install databento   (the local D: loader does NOT need this)
    # then put DATABENTO_API_KEY in BOT/config/.env
    python -m bot.market_data.databento_feed QQQ 2026-05-01 2026-06-27
    python -m bot.market_data.databento_feed NQ  2026-05-01 2026-06-27 --futures

Datasets used:
    equities/ETFs  -> XNAS.ITCH    (ohlcv-1m, stype_in=raw_symbol)
    futures        -> GLBX.MDP3    (ohlcv-1m, stype_in=continuous, e.g. NQ.c.0)
Live streaming is stubbed (`stream_live`) for the paper/live phase.
"""
from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pandas as pd

from bot.config import settings, BOT_ROOT

ET = "America/New_York"
DATA_DIR = BOT_ROOT.parent / "data"   # repo-root data/ (where the other parquets live)

# symbol -> (dataset, stype_in, databento symbol)
_EQUITY = {
    "QQQ": ("XNAS.ITCH", "raw_symbol", "QQQ"),
    "SPY": ("XNAS.ITCH", "raw_symbol", "SPY"),
}
_FUTURES = {
    "NQ": ("GLBX.MDP3", "continuous", "NQ.c.0"),
    "ES": ("GLBX.MDP3", "continuous", "ES.c.0"),
    "GC": ("GLBX.MDP3", "continuous", "GC.c.0"),
}


def _client():
    try:
        import databento as db
    except ImportError as e:
        raise RuntimeError(
            "The `databento` package is not installed. Run:  pip install databento\n"
            "(Only needed for pulling NEW data from the API — reading the local D: "
            "batch files does not need it.)"
        ) from e
    return db.Historical(settings.require_databento())


def historical_ohlcv_1m(symbol: str, start: str, end: str, futures: bool = False) -> pd.DataFrame:
    """Pull 1-minute OHLCV bars for one symbol between [start, end) (YYYY-MM-DD)."""
    table = _FUTURES if futures else _EQUITY
    sym = symbol.upper()
    if sym not in table:
        raise KeyError(f"{sym} not mapped. Add it to _{'FUTURES' if futures else 'EQUITY'} in databento_feed.py")
    dataset, stype_in, dbsym = table[sym]
    client = _client()
    data = client.timeseries.get_range(
        dataset=dataset, schema="ohlcv-1m", symbols=[dbsym],
        stype_in=stype_in, start=start, end=end,
    )
    df = data.to_df()  # databento returns a tz-aware UTC index + open/high/low/close/volume
    return _normalize(df, sym, futures)


def _normalize(df: pd.DataFrame, sym: str, futures: bool) -> pd.DataFrame:
    """Map a Databento OHLCV-1m frame to the repo's continuous-1m parquet schema."""
    if df.empty:
        return df
    df = df.reset_index()
    tcol = "ts_event" if "ts_event" in df.columns else df.columns[0]
    et = pd.to_datetime(df[tcol], utc=True).dt.tz_convert(ET)
    mins = et.dt.hour * 60 + et.dt.minute
    wk = et.dt.dayofweek < 5
    out = pd.DataFrame({
        "ts_et": et,
        "open": df["open"].astype("float64"), "high": df["high"].astype("float64"),
        "low": df["low"].astype("float64"), "close": df["close"].astype("float64"),
        "volume": df["volume"].astype("int64"),
        "adj_factor": 1.0, "is_roll": False,
        "session": np.where(wk & (mins >= 570) & (mins < 960), "RTH", "ETH"),
    })
    return out.sort_values("ts_et").reset_index(drop=True)


def write_continuous_parquet(symbol: str, start: str, end: str, futures: bool = False) -> Path:
    """Pull and persist to data/<sym>_continuous_1m.parquet (merging with any existing)."""
    out = _normalize_path(symbol)
    new = historical_ohlcv_1m(symbol, start, end, futures)
    if out.exists():
        old = pd.read_parquet(out)
        new = (pd.concat([old, new])
               .drop_duplicates(subset="ts_et", keep="last")
               .sort_values("ts_et").reset_index(drop=True))
    new.to_parquet(out, index=False)
    print(f"{symbol}: {len(new):,} 1m bars  {new['ts_et'].min()}..{new['ts_et'].max()}  -> {out}")
    return out


def _normalize_path(symbol: str) -> Path:
    return DATA_DIR / f"{symbol.lower()}_continuous_1m.parquet"


def stream_live(symbols: list[str], on_bar) -> None:
    """Live 1m bars via Databento Live (paper/live phase). Stub until that phase.

    on_bar(symbol, bar_dict) is called per closed minute bar."""
    raise NotImplementedError(
        "Live streaming is wired in the paper-trading phase (see BUILD_PLAN.md Phase 6). "
        "Historical pulls + the local D: replay data cover replay/backtest today."
    )


def main(argv: list[str]) -> None:
    if len(argv) < 3:
        print(__doc__)
        return
    symbol, start, end = argv[0], argv[1], argv[2]
    futures = "--futures" in argv
    write_continuous_parquet(symbol, start, end, futures)


if __name__ == "__main__":
    main(sys.argv[1:])
