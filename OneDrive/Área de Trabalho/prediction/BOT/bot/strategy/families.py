"""The 4 standing strategy families the system always scans (F62).

Until more research expands the set, these are it — each tagged with its validated status so the
system (and the user, at their discretion) knows how much to trust a signal:

  1. breakout / vol-expansion  — VALIDATED on NQ + QQQ + SPY (the core edge)
  2. trend / momentum          — validated EQUITY-ONLY (QQQ/SPY); a selectivity filter, ~0 additive net
  3. structure / order-flow    — validated EQUITY-ONLY (QQQ/SPY) SMC order-block; also a filter
  4. mean-reversion / fade     — NEGATIVE expectancy (F18/F53/F62) — scanned for context, DO NOT trade

`scan(bars_df)` runs all four on a router-provided bar frame and returns any signal active on the
latest bar (with entry/stop/tp), tagged by family. The live loop attaches options + risk to each.
"""
from __future__ import annotations

import os
import sys
from dataclasses import dataclass

import numpy as np
import pandas as pd

from bot.config import BOT_ROOT
sys.path.insert(0, str(BOT_ROOT.parent / "engine"))

from bot.contracts import Session

ORS, ORE, CUT, DELAY, SB = 570, 600, 900, 60, 0.25
T1_RR, T2_RR = 1.0, 4.0


@dataclass
class Family:
    key: str
    name: str
    status: str                 # "validated" | "equity_only" | "negative"
    gate: str                   # "none" | "trend"
    execm: str                  # "close" | "stop" | "fade" | "sweepgo"
    ob: bool = False
    tradeable: bool = True


FAMILIES = [
    Family("breakout", "breakout / vol-expansion", "validated", "none", "close"),
    Family("trend", "trend / momentum", "equity_only", "trend", "close"),
    Family("smc", "structure / order-flow (SMC OB)", "equity_only", "trend", "close", ob=True),
    Family("meanrev", "mean-reversion / range-fade", "negative", "none", "fade", tradeable=False),
]


def prepare(bars: pd.DataFrame) -> pd.DataFrame:
    """Router bar frame (ts_et, ohlcv) -> engine harness-state frame."""
    import hs_harness as H
    df = bars.rename(columns={"ts_et": "ts"}).copy()
    df["ts"] = pd.to_datetime(df["ts"], utc=True)
    for col in ("open", "high", "low", "close"):
        df[col] = df[col].astype(float)
    df["volume"] = df.get("volume", 0).astype("float64")
    d = H.compute_state(df, H.P())
    # live scan has no macro externals — make the gates permissive (breakout core doesn't need them)
    for c, v in {"macro_allow_trades": True, "macro_long_ok": True, "macro_short_ok": True,
                 "local_regime": 0}.items():
        if c not in d.columns:
            d[c] = v
    return d


def _levels(d, i, sign):
    """Struct-anchored stop + capped-TP2 at bar i (mirrors the engine)."""
    import hs_backtest as B
    entry = float(d["close"].iloc[i]); atr = float(d["atr14"].iloc[i])
    spl = d["spl"].iloc[i] if "spl" in d else np.nan
    sph = d["sph"].iloc[i] if "sph" in d else np.nan
    anc = (spl if sign == 1 else sph)
    if anc != anc:  # nan -> OR edge fallback handled in engine; use a 1.5ATR stop here
        anc = entry - sign * 1.5 * atr
    raw = anc - sign * atr * B.SL_BUF_ATR
    stop = (min(max(raw, entry - atr * B.SL_MAX_ATR), entry - atr * 0.75) if sign == 1
            else max(min(raw, entry + atr * B.SL_MAX_ATR), entry + atr * 0.75))
    risk = abs(entry - stop)
    return round(entry, 2), round(stop, 2), round(entry + sign * risk * T1_RR, 2), round(entry + sign * risk * T2_RR, 2)


def scan(bars: pd.DataFrame, symbol: str, bars_back: int = 2) -> list[dict]:
    """Run all 4 families with the symbol's PER-ASSET config; signals active in the last `bars_back` bars."""
    import hs_backtest as B
    from bot.contracts import TradeCandidate
    from bot.strategy.asset_config import asset_config
    a = asset_config(symbol)                       # per-asset: entry_delay, OR window, status
    d = prepare(bars)
    n = len(d)
    st = d["st_state"].to_numpy() if "st_state" in d else np.zeros(n)
    out = []
    sess_enum = {"rth": Session.RTH, "asia": Session.ASIA, "london": Session.LONDON}
    for fam in FAMILIES:
        d["trend_up"] = (st == 1) if fam.gate == "trend" else True
        d["trend_down"] = (st == 2) if fam.gate == "trend" else True
        obl = d["in_bull_ob"].shift(1).fillna(False).to_numpy().astype(bool) if (fam.ob and "in_bull_ob" in d) else None
        obs = d["in_bear_ob"].shift(1).fillna(False).to_numpy().astype(bool) if (fam.ob and "in_bear_ob" in d) else None
        cl = fam.execm == "close"
        for sname, or_s, or_e, cut, tradeday in a.sessions:        # futures = 3 sessions, equity = 1
            lsig, ssig, *_ = B._orb_signals(d, or_s, or_e, 0.0, cut, fam.execm, tradeday, False,
                                            ob_l=obl, ob_s=obs, entry_delay=a.entry_delay,
                                            strong_body=(SB if cl else 0.0), ft_confirm=cl, dir_seq=cl)
            for i in range(max(0, n - bars_back), n):
                sign = 1 if lsig[i] else (-1 if ssig[i] else 0)
                if sign == 0:
                    continue
                e, s, t1, t2 = _levels(d, i, sign)
                ts = pd.Timestamp(d["ts"].iloc[i]); gen = ts.tz_convert("UTC").isoformat()
                try:
                    c = TradeCandidate(symbol=symbol, side=("long" if sign == 1 else "short"), timeframe="5m",
                                       setup=fam.key, entry=e, stop=s, tp1=t1, tp2=t2,
                                       strategy_version=f"{fam.key}-f62", session=sess_enum.get(sname, Session.RTH),
                                       generated_at=gen)
                    out.append({"family": fam.key, "status": fam.status, "tradeable": fam.tradeable,
                                "asset_status": a.status, "asset_note": a.note, "session": sname,
                                "bars_ago": n - 1 - i, "candidate": c})
                except ValueError:
                    pass
    return out


if __name__ == "__main__":   # scan live router data for the 4 families
    sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
    from bot.market_data.providers import get_bars
    for sym in ("SPY", "QQQ"):
        bars = get_bars(sym, "5m", period="5d")
        sigs = scan(bars, sym, bars_back=80)        # scan recent bars to show it finds setups
        print(f"{sym} ({bars.attrs.get('provider')}, {len(bars)} bars): {len(sigs)} family signals in last 80 bars")
        for s in sigs[-4:]:
            c = s["candidate"]
            print(f"   [{s['family']:8} {s['status']:11}] {c.side.value} {c.entry}/{c.stop}/{c.tp2} "
                  f"R:R {c.rr:.1f} {c.generated_at[:16]} {'' if s['tradeable'] else '(info only)'}")
    print("\n4-family registry OK — breakout=core, trend/smc=equity filters, meanrev=info-only")
