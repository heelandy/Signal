"""Market Intelligence (MIE/GMI-001) — market context (SPY/VIX), regime, and a risk-on/off read.

Gives every signal its broader-market backdrop: SPY trend, VIX level/regime, and a combined
risk-on/neutral/risk-off label the dashboard shows and the strategy layer can use as a soft filter.
"""
from __future__ import annotations

import pandas as pd

from bot.market_data.providers import get_bars
from bot.features import ema


def _series(sym, provider="yahoo"):
    """NaN-safe daily closes — a provider hiccup returns EMPTY, never raises (the raise path is
    what froze the dashboard header at 'market: unknown' for hours, D4 2026-07-09)."""
    try:
        b = get_bars(sym, "1d", period="6mo", provider=provider)
        return b["close"].astype(float) if len(b) else pd.Series(dtype=float)
    except Exception:
        return pd.Series(dtype=float)


_last_good: dict = {}    # last context that actually resolved a regime — served through hiccups


def market_context() -> dict:
    spy = _series("SPY", provider=None)     # provider CHAIN (webull covers SPY) — was yahoo-pinned,
    vix = _series("^VIX")                   # and yahoo rate-limits at the close; ^VIX is yahoo-only
    out = {"ts": pd.Timestamp.now(tz="America/New_York").isoformat()}
    if len(spy) > 50:
        e50 = ema(spy, 50)
        out["spy"] = round(float(spy.iloc[-1]), 2)
        out["spy_above_ema50"] = bool(spy.iloc[-1] > e50.iloc[-1])
        out["spy_trend"] = "up" if spy.iloc[-1] > e50.iloc[-1] else "down"
        out["spy_5d_pct"] = round(100 * (spy.iloc[-1] / spy.iloc[-6] - 1), 2) if len(spy) > 6 else None
    if len(vix):
        v = float(vix.iloc[-1])
        out["vix"] = round(v, 2)
        out["vix_regime"] = "low" if v < 15 else "high" if v > 25 else "normal"
    # combined risk read
    up = out.get("spy_above_ema50"); v = out.get("vix")
    if up is not None and v is not None:
        out["regime"] = ("risk_on" if (up and v < 20) else
                         "risk_off" if (not up and v > 22) else "neutral")
        out["note"] = f"SPY {out['spy_trend']} ({'>' if up else '<'}50EMA), VIX {v} ({out['vix_regime']}) -> {out['regime']}"
        _last_good.clear(); _last_good.update(out)
    else:
        out["regime"] = "unknown"; out["note"] = "market context unavailable"
        if _last_good:                          # serve the LAST GOOD read through a hiccup, marked stale
            return {**_last_good, "ts": out["ts"], "stale": True,
                    "note": _last_good.get("note", "") + " · provider hiccup — last good context"}
    return out


if __name__ == "__main__":
    import json
    print(json.dumps(market_context(), indent=2))
    print("market intelligence OK")
