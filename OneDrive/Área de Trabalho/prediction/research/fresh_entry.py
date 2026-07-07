"""FRESH ENTRY FROM FIRST PRINCIPLES (user 2026-07-06: "create an entry from scratch based on
your knowledge but nothing from what we share here").

A-PRIORI SPEC — written before touching any data, parameters straight from the literature
(Raschke/Connors "Street Smarts" HOLY GRAIL, intraday adaptation), no repo research consulted,
NO parameter iteration after seeing results (single-shot evaluation, mirror symmetric):

  TREND     ADX(14) >= 30 (Wilder smoothing) with +DI > -DI (long) / -DI > +DI (short),
            and EMA20 rising (long) / falling (short).
  SETUP     price PULLS BACK to the 20-EMA: bar LOW tags/undercuts EMA20 (long side) while the
            trend condition holds — the pullback bar arms a pending entry.
  TRIGGER   the first later bar whose HIGH takes out the pullback bar's high (long; mirror for
            short). Fill at that bar's CLOSE (the engine's ext hook fills at close — slightly
            conservative vs the literature's buy-stop).
  CANCEL    pending dies when the trend condition lapses, after 10 bars without a trigger, or at
            the session boundary (no overnight pendings). One entry per pullback tag.
  SESSION   09:30-16:00 ET only (all instruments — a-priori simplicity).
  EXIT      the platform's standard trade geometry (struct stop, TP2-full at the house T1/T2) and
            standard costs — this is an ENTRY test; the exit/costs stay the house harness.

    .venv/Scripts/python research/fresh_entry.py QQQ SPY NQ ES
Report -> BOT/data/ml/reports/fresh_entry.json — honest single-shot verdict per symbol.
"""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "BOT"))
sys.path.insert(0, str(ROOT / "engine"))
os.chdir(ROOT)

from bot.strategy.orb_candidates import load_state, T1, T2, EOD, CUT  # noqa: E402  (harness only)

REPORT = ROOT / "BOT" / "data" / "ml" / "reports" / "fresh_entry.json"

ADX_LEN, ADX_MIN, EMA_LEN, PENDING_MAX = 14, 30.0, 20, 10   # literature defaults — frozen


def wilder_adx(h: np.ndarray, l: np.ndarray, c: np.ndarray, n: int = ADX_LEN):
    """Classic Wilder ADX/+DI/-DI (ewm alpha=1/n), self-contained (no repo indicators)."""
    hd, ld = np.diff(h, prepend=h[0]), -np.diff(l, prepend=l[0])
    pdm = np.where((hd > ld) & (hd > 0), hd, 0.0)
    mdm = np.where((ld > hd) & (ld > 0), ld, 0.0)
    cp = np.roll(c, 1); cp[0] = c[0]
    tr = np.maximum(h - l, np.maximum(np.abs(h - cp), np.abs(l - cp)))
    a = 1.0 / n
    atr = pd.Series(tr).ewm(alpha=a, adjust=False).mean().to_numpy()
    with np.errstate(invalid="ignore", divide="ignore"):
        pdi = 100 * pd.Series(pdm).ewm(alpha=a, adjust=False).mean().to_numpy() / atr
        mdi = 100 * pd.Series(mdm).ewm(alpha=a, adjust=False).mean().to_numpy() / atr
        dx = 100 * np.abs(pdi - mdi) / np.where((pdi + mdi) == 0, np.nan, pdi + mdi)
    adx = pd.Series(dx).fillna(0).ewm(alpha=a, adjust=False).mean().to_numpy()
    return adx, pdi, mdi


def signals(d: pd.DataFrame):
    """The a-priori state machine -> ext_long/ext_short boolean arrays (strictly causal)."""
    h, l, c = d["high"].to_numpy(float), d["low"].to_numpy(float), d["close"].to_numpy(float)
    ema = d["ema20"].to_numpy(float)
    adx, pdi, mdi = wilder_adx(h, l, c)
    et = pd.to_datetime(d["ts"]).dt.tz_convert("America/New_York")
    mins = (et.dt.hour * 60 + et.dt.minute).to_numpy()
    day = et.dt.date.to_numpy()
    rth = (et.dt.dayofweek.to_numpy() < 5) & (mins >= 570) & (mins < 960)
    ema_up = np.diff(ema, prepend=ema[0]) > 0
    trend_l = (adx >= ADX_MIN) & (pdi > mdi) & ema_up & rth
    trend_s = (adx >= ADX_MIN) & (mdi > pdi) & ~ema_up & rth
    n = len(d)
    ext_l = np.zeros(n, bool); ext_s = np.zeros(n, bool)
    pend_hi = pend_lo = np.nan
    age_l = age_s = 0
    cur = None
    for i in range(1, n):
        if day[i] != cur:
            cur = day[i]; pend_hi = pend_lo = np.nan          # no overnight pendings
        # long: cancel / trigger / arm
        if pend_hi == pend_hi:
            age_l += 1
            if not trend_l[i] or age_l > PENDING_MAX:
                pend_hi = np.nan
            elif h[i] > pend_hi:
                ext_l[i] = True; pend_hi = np.nan
        if pend_hi != pend_hi and trend_l[i] and l[i] <= ema[i] and c[i - 1] > ema[i - 1]:
            pend_hi = h[i]; age_l = 0                          # pullback tag arms the entry
        # short mirror
        if pend_lo == pend_lo:
            age_s += 1
            if not trend_s[i] or age_s > PENDING_MAX:
                pend_lo = np.nan
            elif l[i] < pend_lo:
                ext_s[i] = True; pend_lo = np.nan
        if pend_lo != pend_lo and trend_s[i] and h[i] >= ema[i] and c[i - 1] < ema[i - 1]:
            pend_lo = l[i]; age_s = 0
    return ext_l, ext_s


def metrics(tr):
    if not len(tr):
        return {"n": 0}
    r = tr["net_R"].to_numpy(float)
    wins, losses = r[r > 0], r[r <= 0]
    eq = np.cumsum(r); cut = int(0.7 * len(r))
    return {"n": int(len(r)), "win_pct": round(100 * float((r > 0).mean()), 1),
            "avg_r": round(float(r.mean()), 3), "total_r": round(float(r.sum()), 1),
            "pf": round(float(wins.sum() / abs(losses.sum())), 2) if len(losses) and losses.sum() else None,
            "max_dd_r": round(float((eq - np.maximum.accumulate(eq)).min()), 1),
            "oos30": round(float(r[cut:].mean()), 3) if len(r) - cut > 5 else None}


def main(syms):
    import hs_backtest as B
    out = {"generated_at": pd.Timestamp.now("UTC").isoformat(),
           "spec": "Holy-Grail ADX(14)>=30 EMA20-pullback continuation, literature defaults, "
                   "single-shot (no tuning), house exit/costs", "symbols": {}}
    REPORT.parent.mkdir(parents=True, exist_ok=True)
    for sym in syms:
        d = load_state(sym)
        el, es_ = signals(d)
        tr = B.backtest(d, "tp2_full", "both", False, "ext", 0, T1, T2, eod_min=EOD,
                        tod_end=CUT, stop_mode="struct", ext_long=el, ext_short=es_)
        m = metrics(tr)
        out["symbols"][sym] = {"signals_long": int(el.sum()), "signals_short": int(es_.sum()),
                               "metrics": m}
        print(f"{sym:4} sig L/S {el.sum():>4}/{es_.sum():<4} n {m.get('n'):4} "
              f"avg {m.get('avg_r')} PF {m.get('pf')} total {m.get('total_r')} "
              f"dd {m.get('max_dd_r')} oos {m.get('oos30')}", flush=True)
    REPORT.write_text(json.dumps(out, indent=1), encoding="utf-8")
    print(f"saved -> {REPORT}")


if __name__ == "__main__":
    main([s.upper() for s in (sys.argv[1:] or ["QQQ", "SPY", "NQ", "ES"])])
