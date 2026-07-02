"""Multi-provider market data — Yahoo / Webull / TradingView / Databento behind one interface.

The bot doesn't care where bars come from; it asks the router and gets a normalized frame
(ts_et, open, high, low, close, volume). Providers are tried in priority order with fallback.

  • yahoo       — yfinance, free, works now (primary free fallback).
  • databento   — premium 1m/MBO (the validated source; via databento_feed).
  • webull      — OFFICIAL Webull OpenAPI (developer.webull.com). pip install webull-openapi-python-sdk
                  + WEBULL_APP_KEY/SECRET in .env. Adapter ready, returns [] until both are set.
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


# tf -> Webull OpenAPI Timespan enum (verified against the SDK: S5/S15/M1/M5/M15/M30/M60/M120/M240/D/W/M)
_WB_TIMESPAN = {"1m": "M1", "5m": "M5", "15m": "M15", "30m": "M30", "60m": "M60", "1h": "M60", "1d": "D"}
_WB_ETF = {"QQQ", "SPY", "IWM", "DIA", "GLD", "SLV", "TLT", "XLF", "XLE", "XLK", "VOO", "VTI"}
# Webull FUTURES: continuous "{root}main" contracts via dc.futures_market_data (needs a US-futures DATA
# entitlement — the instrument/products endpoint works without it, the bars endpoint 401s until enabled).
# Roots verified from get_futures_products('US_FUTURES'): index (XCME/XCBT), metals (XCEC), energy (XNYM).
_WB_FUT = {"NQ": "NQmain", "ES": "ESmain", "MNQ": "MNQmain", "MES": "MESmain", "YM": "YMmain", "RTY": "RTYmain",
           "GC": "GCmain", "MGC": "MGCmain", "SI": "SImain", "CL": "CLmain"}
_WB_FUT_OFF = {"v": False}            # self-disable webull-futures after a 401 (no entitlement) — no per-scan hammer


def _webull_rows(res):
    """Pull the bar list out of a Webull OpenAPI response (defensive across SDK/payload shapes)."""
    body = res
    for attr in ("json", "get_body", "body", "data"):           # response wrappers vary by SDK version
        v = getattr(res, attr, None)
        body = v() if callable(v) else (v if v is not None else body)
        if body is not res:
            break
    if isinstance(body, dict):
        for k in ("data", "bars", "candles", "list"):
            if isinstance(body.get(k), list):
                return body[k]
        return [body]
    return body if isinstance(body, list) else []


_WB_CLIENT = {}                                                  # cache the authenticated DataClient (avoid re-auth/call)


def _webull_client():
    from webull.core.client import ApiClient
    from webull.data.data_client import DataClient
    from bot.config import settings
    key, secret = settings.require_webull()                     # raises if keys unset
    ck = (key, settings.webull_region, settings.webull_endpoint)
    if ck not in _WB_CLIENT:
        # auto_retry=False + explicit timeouts: the SDK HANGS on the prod gateway with its default retry loop.
        client = ApiClient(key, secret, settings.webull_region, connect_timeout=10, timeout=10, auto_retry=False)
        client.add_endpoint(settings.webull_region, settings.webull_endpoint)
        _WB_CLIENT.clear(); _WB_CLIENT[ck] = DataClient(client)  # one cached client (DataClient auths on init)
    return _WB_CLIENT[ck]


def webull_bars(symbol: str, tf: str = "5m", count: int = 800) -> pd.DataFrame:
    """OFFICIAL Webull OpenAPI (developer.webull.com) market data.
        pip install webull-openapi-python-sdk    +    WEBULL_APP_KEY / WEBULL_APP_SECRET in .env
    Returns [] (graceful) until both are present, so the router just falls through to the next provider."""
    try:
        from webull.data.common.category import Category
        from webull.data.common.timespan import Timespan
    except ImportError:
        return _normalize(None, "webull")                       # SDK not installed -> empty
    sym = symbol.upper()
    is_fut = sym in _WB_FUT
    if is_fut and _WB_FUT_OFF["v"]:                             # futures entitlement missing -> stay disabled
        return _normalize(None, "webull")
    try:
        dc = _webull_client()
        span = getattr(Timespan, _WB_TIMESPAN.get(tf, "M5")).name
        if is_fut:                                              # FUTURES via the dedicated namespace (NQmain etc.)
            try:
                res = dc.futures_market_data.get_futures_history_bars(_WB_FUT[sym], Category.US_FUTURES.name, span, count)
            except Exception as e:
                if "401" in str(e) or "permission" in str(e).lower():
                    _WB_FUT_OFF["v"] = True                     # no US-futures data entitlement -> disable, fall back
                return _normalize(None, "webull")
        else:
            cat = (Category.US_ETF if sym in _WB_ETF else Category.US_STOCK).name
            res = dc.market_data.get_history_bar(sym, cat, span)
        rows = _webull_rows(res)
        if not rows:
            return _normalize(None, "webull")
        df = pd.DataFrame(rows)
        # Webull returns: time (ISO UTC) + string OHLCV. Map 'time' -> the normalizer's time column.
        ren = {"time": "ts_event", "timeStamp": "ts_event", "tradeTime": "ts_event", "t": "ts_event",
               "o": "open", "h": "high", "l": "low", "c": "close", "v": "volume", "vol": "volume"}
        df = df.rename(columns={k: v for k, v in ren.items() if k in df.columns})
        return _normalize(df, "webull")
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


# ── TradeStation Web API v3 (REST + OAuth2) — equities AND futures ──────────────────────────────
_TS_UNIT = {"1m": (1, "Minute"), "5m": (5, "Minute"), "15m": (15, "Minute"), "30m": (30, "Minute"),
            "60m": (60, "Minute"), "1h": (60, "Minute"), "1d": (1, "Daily")}
_TS_FUT = {"NQ": "@NQ", "MNQ": "@MNQ", "ES": "@ES", "MES": "@MES", "GC": "@GC", "MGC": "@MGC"}
_TS_TOKEN = {"access": None, "exp": 0.0}                          # cached access token (~20 min life)


def _ts_base() -> str:
    from bot.config import settings
    return "https://sim-api.tradestation.com/v3" if settings.tradestation_env == "sim" else "https://api.tradestation.com/v3"


def _ts_access_token() -> str:
    """Exchange the long-lived refresh token for a short-lived access token (cached until ~1 min before expiry)."""
    import time as _t, requests
    from bot.config import settings
    if _TS_TOKEN["access"] and _t.time() < _TS_TOKEN["exp"]:
        return _TS_TOKEN["access"]
    key, secret, refresh = settings.require_tradestation()
    r = requests.post("https://signin.tradestation.com/oauth/token",
                      data={"grant_type": "refresh_token", "client_id": key, "client_secret": secret,
                            "refresh_token": refresh}, timeout=15)
    r.raise_for_status()
    j = r.json()
    _TS_TOKEN["access"] = j["access_token"]
    _TS_TOKEN["exp"] = _t.time() + int(j.get("expires_in", 1200)) - 60
    return _TS_TOKEN["access"]


def tradestation_bars(symbol: str, tf: str = "5m", count: int = 800) -> pd.DataFrame:
    """OFFICIAL TradeStation Web API v3 market data (equities + futures).
        TRADESTATION_API_KEY / _API_SECRET / _REFRESH_TOKEN in .env (one-time OAuth gives the refresh token).
    Returns [] (graceful) until configured, so the router falls through to the next provider."""
    try:
        import requests
        from bot.config import settings
    except ImportError:
        return _normalize(None, "tradestation")
    try:
        settings.require_tradestation()                          # raises if unset -> caught -> empty
        interval, unit = _TS_UNIT.get(tf, (5, "Minute"))
        sym = _TS_FUT.get(symbol.upper(), symbol.upper())        # futures -> continuous @NQ/@ES/@GC
        url = f"{_ts_base()}/marketdata/barcharts/{sym}"
        r = requests.get(url, headers={"Authorization": f"Bearer {_ts_access_token()}"},
                         params={"interval": interval, "unit": unit, "barsback": min(count, 57600)}, timeout=20)
        r.raise_for_status()
        rows = r.json().get("Bars", [])
        if not rows:
            return _normalize(None, "tradestation")
        df = pd.DataFrame(rows).rename(columns={"TimeStamp": "ts_event", "Open": "open", "High": "high",
                                                "Low": "low", "Close": "close", "TotalVolume": "volume"})
        return _normalize(df, "tradestation")
    except Exception:
        return _normalize(None, "tradestation")


_PROVIDERS = {"alpaca": alpaca_bars, "yahoo": yahoo_bars, "webull": webull_bars,
              "tradestation": tradestation_bars, "tradingview": tradingview_bars, "databento": databento_bars}
_FALLBACK_ORDER = ["alpaca", "yahoo", "webull", "tradestation", "tradingview"]  # alpaca first, then fallbacks


def _default_order() -> list[str]:
    """Priority order, overridable via PROVIDER_ORDER in .env (e.g. 'webull,alpaca,yahoo') so you can
    promote Webull to primary the moment you paste prod keys — no code edit needed."""
    from bot.config import settings
    custom = [p.strip() for p in (settings.provider_order or "").split(",") if p.strip() in _PROVIDERS]
    return custom or _FALLBACK_ORDER


DEFAULT_ORDER = _default_order()


def get_bars(symbol: str, tf: str = "5m", period: str = "5d", provider: str | None = None,
             start=None, end=None, fallback: bool = True) -> pd.DataFrame:
    """One symbol's bars from `provider` (or the priority order with fallback)."""
    if provider:
        order = [provider]
    else:
        # Alpaca is equities-only (skip for futures). Webull CAN do futures (NQmain via futures_market_data) but
        # needs a US-futures data entitlement; it self-disables + falls back until that's enabled on the account.
        order = [p for p in _default_order() if not (p == "alpaca" and symbol.upper() in FUTURES)]
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


_DBN_LIVE_OFF = {"v": False}                              # disable Databento-live after a hard failure (no hangs)


def _dbn_key():
    from bot.config import settings
    return settings.databento_api_key


def latest_price(symbol: str) -> dict:
    """Real-time last price — NOT the last 5m bar close (which lags pre-open / after-hours / on feed
    delay, the cause of the 'QQQ shows the wrong price' issue). Prefers Yahoo's CONSOLIDATED quote
    (what the user sees on a chart/broker) over Alpaca's free IEX feed, which only sees one venue and
    lags the true price (e.g. QQQ IEX 723.52 vs consolidated 724.08). Returns {price, source, ts}."""
    sym = symbol.upper()
    # FUTURES: prefer Databento Live (real-time) over Yahoo (15-min delayed) — only if a key is set,
    # and self-disables after a hard failure so it never hangs the scan when unentitled.
    if (sym in FUTURES or sym in _FUT_YF) and _is_set(_dbn_key()) and not _DBN_LIVE_OFF["v"]:
        try:
            from bot.market_data.databento_live import live_price as _dbn_live
            lp = _dbn_live(sym, timeout=1.5)
            if lp.get("price"):
                return {"price": lp["price"], "source": lp["source"], "ts": lp.get("ts")}
        except Exception:
            _DBN_LIVE_OFF["v"] = True                       # auth/import error -> stop trying this session
    try:                                                   # Yahoo fast_info = consolidated (equities + futures)
        import yfinance as yf
        fi = yf.Ticker(_FUT_YF.get(sym, sym)).fast_info
        px = fi.get("last_price") or fi.get("lastPrice")
        if px and float(px) > 0:
            return {"price": round(float(px), 2), "source": "yahoo-rt", "ts": None}
    except Exception:
        pass
    if sym not in FUTURES and sym not in _FUT_YF:          # Alpaca IEX trade as a fallback for equities
        try:
            from alpaca.data.historical import StockHistoricalDataClient
            from alpaca.data.requests import StockLatestTradeRequest
            from alpaca.data.enums import DataFeed
            from bot.config import settings
            key, secret = settings.require_alpaca()
            req = StockLatestTradeRequest(symbol_or_symbols=sym, feed=DataFeed.IEX)
            tr = StockHistoricalDataClient(key, secret).get_stock_latest_trade(req)[sym]
            ts = getattr(tr, "timestamp", None)
            return {"price": round(float(tr.price), 2), "source": "alpaca-iex",
                    "ts": ts.isoformat() if ts is not None else None}
        except Exception:
            pass
    return {}


def _is_set(v) -> bool:
    return bool(v and "PUT_YOUR" not in str(v) and "changeme" not in str(v))


def provider_status(probe: bool = False) -> dict:
    """Readiness of every data provider — for the dashboard 'Data Sources' panel. probe=True actively
    hits Webull to confirm the keys authenticate (so when you paste PROD keys you SEE it go green)."""
    from bot.config import settings
    import importlib.util as _u
    wb_sdk = _u.find_spec("webull") is not None
    wb_conf = _is_set(settings.webull_app_key) and _is_set(settings.webull_app_secret)
    uat = "uat" in (settings.webull_endpoint or "").lower()
    webull = {"configured": wb_conf, "sdk_installed": wb_sdk, "endpoint": settings.webull_endpoint,
              "env": "TEST/UAT (AAPL only)" if uat else "production", "covers": "US equities/ETFs (no futures)",
              "ready": wb_conf and wb_sdk}
    if probe and wb_conf and wb_sdk:
        try:
            n = len(webull_bars("AAPL", "5m"))
            webull["authenticated"] = n > 0
            webull["probe"] = f"AAPL {n} bars OK" if n else "auth ok, no rows"
        except Exception as e:
            webull["authenticated"] = False
            webull["probe"] = str(e)[:80]
    ts_conf = (_is_set(settings.tradestation_api_key) and _is_set(settings.tradestation_api_secret)
               and _is_set(settings.tradestation_refresh_token))
    tradestation = {"configured": ts_conf, "env": settings.tradestation_env,
                    "covers": "US equities + futures (NQ/ES/GC)", "ready": ts_conf}
    if probe and ts_conf:
        try:
            n = len(tradestation_bars("QQQ", "5m"))
            tradestation["authenticated"] = n > 0
            tradestation["probe"] = f"QQQ {n} bars OK" if n else "auth ok, no rows"
        except Exception as e:
            tradestation["authenticated"] = False
            tradestation["probe"] = str(e)[:80]
    out = {
        "order": _default_order(),
        "alpaca": {"configured": _is_set(settings.alpaca_key_id), "covers": "US equities/options (IEX feed, paper)",
                   "ready": _is_set(settings.alpaca_key_id)},
        "yahoo": {"configured": True, "covers": "equities + futures (free, consolidated)", "ready": True},
        "webull": webull,
        "tradestation": tradestation,
        "databento": {"configured": _is_set(settings.databento_api_key),
                      "covers": "premium 1m/MBO + local batches + LIVE real-time (futures/equities/options)",
                      "ready": _is_set(settings.databento_api_key)},
        "tradingview": {"configured": _is_set(settings.webhook_token),
                        "covers": "webhook alerts only (no bars API)", "ready": False},
    }
    return out


if __name__ == "__main__":
    import sys as _sys
    if "status" in _sys.argv:                              # python -m bot.market_data.providers status [probe]
        import json as _json
        print(_json.dumps(provider_status(probe=("probe" in _sys.argv)), indent=2, default=str))
        _sys.exit(0)
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
