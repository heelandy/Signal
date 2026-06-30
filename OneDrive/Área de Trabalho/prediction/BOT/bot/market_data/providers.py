"""Multi-provider market data — Yahoo / Webull / TradingView / Databento behind one interface.

The bot doesn't care where bars come from; it asks the router and gets a normalized frame
(ts_et, open, high, low, close, volume). Providers are tried in priority order with fallback.

  • yahoo       — yfinance, free, works now (primary free fallback).
  • databento   — premium 1m/MBO (the validated source; via databento_feed).
  • webull      — UNOFFICIAL reverse-engineered API; needs login. Adapter ready, returns [] until creds set.
  • tradingview — NO official API. Live = the webhook alerts the AUTO Pine already sends (ingested
                  elsewhere); historical = optional unofficial `tvdatafeed`. Adapter documents both.

    from bot.market_data.providers import get_bars
    df = get_bars("SPY", "5m", period="5d")                 # Yahoo
    df = get_bars("QQQ", "1m", period="1d", provider="yahoo")
"""
from __future__ import annotations

import numpy as np
import pandas as pd

ET = "America/New_York"
_YF_INTERVAL = {"1m": "1m", "2m": "2m", "5m": "5m", "15m": "15m", "30m": "30m",
                "60m": "60m", "1h": "60m", "1d": "1d"}
# futures -> Yahoo continuous-front tickers (Alpaca has no futures; Yahoo/Databento do)
_FUT_YF = {"NQ": "NQ=F", "MNQ": "NQ=F", "ES": "ES=F", "MES": "ES=F", "GC": "GC=F", "MGC": "GC=F"}
FUTURES = set(_FUT_YF)


def _normalize(df: pd.DataFrame, source: str) -> pd.DataFrame:
    if df is None or len(df) == 0:
        return pd.DataFrame(columns=["ts_et", "open", "high", "low", "close", "volume", "source"])
    if isinstance(df.index, (pd.DatetimeIndex, pd.MultiIndex)) or df.index.name:
        df = df.reset_index()                       # only promote a meaningful index (avoid a spurious 'index' col)
    df = df.rename(columns=str.lower)
    tcol = next((c for c in df.columns if c.lower() in ("datetime", "date", "ts_event", "timestamp", "ts_et")),
                df.columns[0])
    ts = pd.to_datetime(df[tcol], utc=True, errors="coerce").dt.tz_convert(ET)
    out = pd.DataFrame({"ts_et": ts, "open": df["open"].astype(float), "high": df["high"].astype(float),
                        "low": df["low"].astype(float), "close": df["close"].astype(float),
                        "volume": df.get("volume", 0).astype("int64"), "source": source})
    return out.dropna(subset=["close"]).sort_values("ts_et").reset_index(drop=True)


# ---- adapters ---------------------------------------------------------------

def yahoo_bars(symbol: str, tf: str = "5m", period: str = "5d", start=None, end=None) -> pd.DataFrame:
    import yfinance as yf
    iv = _YF_INTERVAL.get(tf, "5m")
    yf_sym = _FUT_YF.get(symbol.upper(), symbol)            # NQ -> NQ=F, GC -> GC=F, etc.
    df = yf.download(yf_sym, interval=iv, period=(None if start else period), start=start, end=end,
                     progress=False, auto_adjust=False)
    if isinstance(df.columns, pd.MultiIndex):
        df.columns = df.columns.get_level_values(0)
    return _normalize(df, "yahoo")


def alpaca_bars(symbol: str, tf: str = "5m", start=None, end=None, limit: int = 2000) -> pd.DataFrame:
    """Alpaca market data (IEX free feed; SIP needs a data subscription). Uses your ALPACA_* keys."""
    from datetime import datetime, timedelta, timezone
    from alpaca.data.historical import StockHistoricalDataClient
    from alpaca.data.requests import StockBarsRequest
    from alpaca.data.timeframe import TimeFrame, TimeFrameUnit
    from alpaca.data.enums import DataFeed
    from bot.config import settings
    key, secret = settings.require_alpaca()
    tfmap = {"1m": TimeFrame(1, TimeFrameUnit.Minute), "5m": TimeFrame(5, TimeFrameUnit.Minute),
             "15m": TimeFrame(15, TimeFrameUnit.Minute), "30m": TimeFrame(30, TimeFrameUnit.Minute),
             "1h": TimeFrame(1, TimeFrameUnit.Hour), "1d": TimeFrame(1, TimeFrameUnit.Day)}
    start = start or (datetime.now(timezone.utc) - timedelta(days=7))
    req = StockBarsRequest(symbol_or_symbols=symbol, timeframe=tfmap.get(tf, tfmap["5m"]),
                           start=start, end=end, limit=limit, feed=DataFeed.IEX)
    df = StockHistoricalDataClient(key, secret).get_stock_bars(req).df
    if df is None or len(df) == 0:
        return _normalize(None, "alpaca")
    return _normalize(df, "alpaca")                 # keep the (symbol, timestamp) MultiIndex for _normalize


def databento_bars(symbol: str, tf: str = "1m", start=None, end=None) -> pd.DataFrame:
    from bot.market_data.databento_feed import historical_ohlcv_1m
    fut = symbol.upper() in ("NQ", "ES", "GC", "MNQ", "MES")
    df = historical_ohlcv_1m(symbol, start, end, futures=fut)        # already normalized shape
    df = df.rename(columns={"ts_et": "ts_et"})
    df["source"] = "databento"
    return df


def webull_bars(symbol: str, tf: str = "5m", count: int = 800) -> pd.DataFrame:
    """UNOFFICIAL Webull API. Needs `pip install webull` + a logged-in session. Returns [] until set."""
    try:
        from webull import webull              # noqa
    except ImportError:
        return _normalize(None, "webull")       # not installed -> empty (fallback handles it)
    try:
        wb = webull()
        bars = wb.get_bars(stock=symbol, interval=tf.replace("m", ""), count=count)
        return _normalize(bars, "webull")
    except Exception:
        return _normalize(None, "webull")


def tradingview_bars(symbol: str, tf: str = "5m", n: int = 800) -> pd.DataFrame:
    """TradingView has NO official data API. Historical via unofficial `tvdatafeed`; LIVE is the
    webhook-alert path the AUTO Pine already emits. Returns [] unless tvdatafeed is installed."""
    try:
        from tvDatafeed import TvDatafeed, Interval     # noqa
    except ImportError:
        return _normalize(None, "tradingview")
    try:
        tv = TvDatafeed()
        iv = {"1m": Interval.in_1_minute, "5m": Interval.in_5_minute, "15m": Interval.in_15_minute,
              "1h": Interval.in_1_hour, "1d": Interval.in_daily}.get(tf, Interval.in_5_minute)
        df = tv.get_hist(symbol=symbol, exchange="NASDAQ", interval=iv, n_bars=n)
        return _normalize(df, "tradingview")
    except Exception:
        return _normalize(None, "tradingview")


_PROVIDERS = {"alpaca": alpaca_bars, "yahoo": yahoo_bars, "webull": webull_bars,
              "tradingview": tradingview_bars, "databento": databento_bars}
DEFAULT_ORDER = ["alpaca", "yahoo", "webull", "tradingview"]   # alpaca first (your keys), yahoo fallback


def get_bars(symbol: str, tf: str = "5m", period: str = "5d", provider: str | None = None,
             start=None, end=None, fallback: bool = True) -> pd.DataFrame:
    """One symbol's bars from `provider` (or the priority order with fallback)."""
    if provider:
        order = [provider]
    else:
        order = [p for p in DEFAULT_ORDER if not (p == "alpaca" and symbol.upper() in FUTURES)]  # Alpaca has no futures
    last = pd.DataFrame()
    for name in order:
        fn = _PROVIDERS[name]
        try:
            df = fn(symbol, tf=tf, period=period) if name == "yahoo" else fn(symbol, tf=tf)
        except Exception:
            df = pd.DataFrame()                           # provider failed -> fall through to the next
        if len(df):
            df.attrs["provider"] = name
            return df
        last = df
        if not fallback:
            break
    return last


if __name__ == "__main__":
    for prov in ("alpaca", "yahoo"):
        for sym in ("SPY", "QQQ"):
            try:
                df = get_bars(sym, "5m", period="5d", provider=prov, fallback=False)
                print(f"{prov:6} {sym}: {len(df)} bars | last {df['close'].iloc[-1]:.2f} @ {df['ts_et'].iloc[-1]}"
                      if len(df) else f"{prov:6} {sym}: no data")
            except Exception as e:
                print(f"{prov:6} {sym}: {type(e).__name__}: {str(e)[:70]}")
    # router with fallback (alpaca -> yahoo -> ...)
    r = get_bars("SPY", "5m", period="5d")
    print(f"router SPY -> {r.attrs.get('provider')} ({len(r)} bars)")
    print("multi-provider data OK (alpaca + yahoo live; webull/tradingview adapters need creds/pkg)")
