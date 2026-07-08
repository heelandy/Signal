"""Databento LIVE (real-time streaming) — https://databento.com/docs/api-reference-live

The historical side (databento_feed.py) pulls bars; THIS is the real-time gateway. Its highest-value
use here is a real-time price snapshot for FUTURES (NQ/ES/GC), where the router otherwise falls back
to 15-min-delayed Yahoo. Needs a Databento key WITH a live entitlement for the dataset (GLBX.MDP3 for
CME futures, XNAS.ITCH for Nasdaq equities). Everything is graceful: no key / no entitlement / market
closed -> returns {} and the caller falls back.

    from bot.market_data.databento_live import live_price
    live_price("NQ")     # {'price': 20137.25, 'source': 'databento-live', 'ts': ...}
"""
from __future__ import annotations

import threading

from bot.market_data.databento_feed import _EQUITY, _FUTURES

_PRICE_SCALE = 1e-9                       # Databento fixed-point integer price -> real price


def _resolve(symbol: str):
    """symbol -> (dataset, stype_in, databento symbol). Futures = continuous front (NQ.c.0)."""
    s = symbol.upper()
    if s in _FUTURES:
        return _FUTURES[s]
    if s in _EQUITY:
        return _EQUITY[s]
    return ("XNAS.ITCH", "raw_symbol", s)            # default: treat as a Nasdaq-listed equity


def live_price(symbol: str, timeout: float = 2.0) -> dict:
    """Real-time last trade via the Databento Live gateway. Returns {price, source, ts} or {} (graceful).
    Subscribes to the trades schema, grabs the first record within `timeout`, then closes the stream."""
    try:
        import databento as db
        from bot.config import settings
    except ImportError:
        return {}
    try:
        dataset, stype, dbsym = _resolve(symbol)
        key = settings.require_databento()           # raises if unset -> caught -> {}
        got: dict = {}
        ev = threading.Event()

        def _cb(rec):
            px = getattr(rec, "price", None)
            if px is not None and not ev.is_set():   # data record (TradeMsg) — system msgs have no .price
                got["price"] = round(float(px) * _PRICE_SCALE, 4)
                got["ts"] = getattr(rec, "ts_event", None)
                ev.set()

        client = db.Live(key=key)
        client.add_callback(_cb)
        client.subscribe(dataset=dataset, schema="trades", stype_in=stype, symbols=[dbsym])
        client.start()
        ev.wait(timeout)
        try:
            client.stop()
        except Exception:
            pass
        if "price" in got:
            ts = got.get("ts")
            return {"price": got["price"], "source": "databento-live",
                    "ts": str(ts) if ts is not None else None, "dataset": dataset, "symbol": dbsym}
        return {}                                    # timed out (market quiet/closed) — caller falls back
    except Exception:
        return {}


if __name__ == "__main__":
    import sys
    for s in (sys.argv[1:] or ["NQ", "QQQ"]):
        print(f"{s}: {live_price(s)}")
