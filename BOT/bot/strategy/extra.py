"""Extra strategies (TSL-001 library) — VWAP mean-reversion, trend-pullback, ETF momentum, stock
factor rank. Each emits canonical TradeCandidates / target weights so they slot into the same risk →
execution → journal pipeline.

⚠️ VALIDATION STATUS: only the ORB stack (`orb_candidates.py`) has cleared the research gauntlet.
These are RESEARCH-GRADE — `strategy_version` is suffixed `-UNVALIDATED`; they must pass the same
gauntlet (OOS PF, no single-symbol/month, 2× costs) before being enabled for paper/live. Built here
so the library is complete and testable; the regime selector + risk gate keep them gated off by default.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from bot.contracts import TradeCandidate, Session
from bot.strategy.orb_candidates import load_state, _in_repo_root  # reuse engine state builder

ET = "America/New_York"


def _ts_iso(v):
    t = pd.Timestamp(v)
    return (t.tz_localize("UTC") if t.tz is None else t.tz_convert("UTC")).isoformat()


def vwap_revert_candidates(d, sym: str = "QQQ", z_in: float = 2.0) -> list[TradeCandidate]:
    """Range-regime VWAP mean-reversion: price stretched z_in·ATR beyond session VWAP, reversal
    candle -> fade back toward VWAP. One per side per day. (Evidence Strategy B)."""
    et = pd.to_datetime(d["ts"]).dt.tz_convert(ET)
    day = et.dt.date.to_numpy(); mins = (et.dt.hour * 60 + et.dt.minute).to_numpy()
    c, o, h, l = (d[k].to_numpy(float) for k in ("close", "open", "high", "low"))
    vw, atr = d["vwap_sess"].to_numpy(float), d["atr14"].to_numpy(float)
    out, cur, done_l, done_s = [], None, False, False
    for i in range(len(d)):
        if day[i] != cur:
            cur, done_l, done_s = day[i], False, False
        if mins[i] < 600 or mins[i] > 870 or np.isnan(vw[i]) or np.isnan(atr[i]) or atr[i] <= 0:
            continue
        z = (c[i] - vw[i]) / atr[i]
        if not done_l and z <= -z_in and c[i] > o[i]:            # stretched below VWAP + bullish reversal
            entry, stop, tgt = c[i], l[i] - 0.5 * atr[i], vw[i]
            if tgt - entry > (entry - stop) * 1.0:               # need >=1R room to VWAP
                out.append(_mk(sym, "long", entry, stop, tgt, _ts_iso(d["ts"].iloc[i]), "vwap_revert")); done_l = True
        if not done_s and z >= z_in and c[i] < o[i]:
            entry, stop, tgt = c[i], h[i] + 0.5 * atr[i], vw[i]
            if entry - tgt > (stop - entry) * 1.0:
                out.append(_mk(sym, "short", entry, stop, tgt, _ts_iso(d["ts"].iloc[i]), "vwap_revert")); done_s = True
    return out


def trend_pullback_candidates(d, sym: str = "QQQ") -> list[TradeCandidate]:
    """Trend-continuation pullback (Evidence Strategy A2): uptrend (close>EMA50, EMA20>EMA50), price
    dips to EMA20 then closes back above the prior bar high -> long. Mirror short. Once/side/day."""
    et = pd.to_datetime(d["ts"]).dt.tz_convert(ET)
    day = et.dt.date.to_numpy(); mins = (et.dt.hour * 60 + et.dt.minute).to_numpy()
    c, h, l = (d[k].to_numpy(float) for k in ("close", "high", "low"))
    e20, e50, atr = d["ema20"].to_numpy(float), d["ema50"].to_numpy(float), d["atr14"].to_numpy(float)
    out, cur, done_l, done_s = [], None, False, False
    for i in range(2, len(d)):
        if day[i] != cur:
            cur, done_l, done_s = day[i], False, False
        if mins[i] < 600 or mins[i] > 870 or np.isnan(e50[i]) or np.isnan(atr[i]) or atr[i] <= 0:
            continue
        up = c[i] > e50[i] and e20[i] > e50[i]
        dn = c[i] < e50[i] and e20[i] < e50[i]
        if not done_l and up and l[i-1] <= e20[i-1] and c[i] > h[i-1]:        # pulled to EMA20, resumed
            entry, stop = c[i], min(l[i-1], l[i]) - 0.25 * atr[i]
            out.append(_mk(sym, "long", entry, stop, entry + 2 * (entry - stop), _ts_iso(d["ts"].iloc[i]), "trend_pullback")); done_l = True
        if not done_s and dn and h[i-1] >= e20[i-1] and c[i] < l[i-1]:
            entry, stop = c[i], max(h[i-1], h[i]) + 0.25 * atr[i]
            out.append(_mk(sym, "short", entry, stop, entry - 2 * (stop - entry), _ts_iso(d["ts"].iloc[i]), "trend_pullback")); done_s = True
    return out


def _mk(sym, side, entry, stop, tp2, ts, setup):
    return TradeCandidate(symbol=sym, side=side, timeframe="5m", setup=setup,
                          entry=round(entry, 2), stop=round(stop, 2), tp2=round(tp2, 2),
                          strategy_version=f"{setup}-0.1-UNVALIDATED", session=Session.RTH, generated_at=ts)


def etf_momentum_weights(returns: dict[str, dict[str, float]], top_n: int = 5,
                         vols: dict[str, float] | None = None) -> dict[str, float]:
    """Long-term ETF trend/momentum (Evidence §6): score = 0.2·r3 + 0.3·r6 + 0.5·r12_1, keep only
    positive-trend names, take top_n, inverse-vol weight. `returns[sym]={'r3','r6','r12_1'}`."""
    from bot.portfolio import inverse_vol_weights
    score = {s: 0.2 * r.get("r3", 0) + 0.3 * r.get("r6", 0) + 0.5 * r.get("r12_1", 0)
             for s, r in returns.items() if r.get("r12_1", 0) > 0 and r.get("r6", 0) > 0}
    top = sorted(score, key=score.get, reverse=True)[:top_n]
    if not top:
        return {}
    v = {s: (vols or {}).get(s, 0.15) for s in top}
    return inverse_vol_weights(v)


def stock_factor_rank(stocks: dict[str, dict[str, float]]) -> list[tuple[str, float]]:
    """Individual-stock multi-factor rank (Evidence §7): momentum 30% + quality 20% + growth 15% +
    fcf 15% + balance 10% + liquidity 10%. Inputs are pre-normalised 0–1 factor scores. STUB: needs a
    fundamentals feed before live."""
    w = {"momentum": 0.30, "quality": 0.20, "growth": 0.15, "fcf": 0.15, "balance": 0.10, "liquidity": 0.10}
    ranked = [(s, round(sum(w[k] * f.get(k, 0.0) for k in w), 4)) for s, f in stocks.items()]
    return sorted(ranked, key=lambda x: x[1], reverse=True)


if __name__ == "__main__":
    d = load_state("QQQ")
    vr = vwap_revert_candidates(d, "QQQ")
    tp = trend_pullback_candidates(d, "QQQ")
    print(f"vwap_revert candidates: {len(vr)} (e.g. {vr[0].to_json()[:120] if vr else 'none'}...)")
    print(f"trend_pullback candidates: {len(tp)}")
    assert all(c.rr > 0 and c.risk > 0 for c in vr + tp), "all candidates must have valid geometry"
    w = etf_momentum_weights({"SPY": {"r3": .05, "r6": .1, "r12_1": .2}, "TLT": {"r3": -.02, "r6": -.01, "r12_1": -.05},
                              "GLD": {"r3": .03, "r6": .06, "r12_1": .12}}, top_n=3)
    print("ETF momentum weights (TLT filtered, neg trend):", w)
    rk = stock_factor_rank({"NVDA": {"momentum": .9, "quality": .8}, "F": {"momentum": .2, "quality": .4}})
    print("stock factor rank:", rk)
    print("extra strategies OK (all UNVALIDATED — gated off for live)")
