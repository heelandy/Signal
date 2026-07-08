"""OPTIONS × STRATEGY CROSS-TEST — which strategy's signals make money as OPTIONS, and in
which structure? (user 2026-07-06: "use the other strategies for testing as well and find
which one will make it")

Each approved module's historical trades are re-priced as option plays with a DTE matched to
its holding horizon:
  orb_core   (QQQ/SPY intraday)  -> 0DTE      (already gauntleted: naked PASSES — reference row)
  volbreak   (QQQ/SPY intraday)  -> 0DTE
  eq_swing   (QQQ, ~days-weeks)  -> 21 DTE
  connors    (QQQ/SPY, ~days)    -> 14 DTE
Structures per trade: NAKED buy / DEBIT vertical / CREDIT vertical (bot/options/strategies),
Black-Scholes at entry (S=entry, T=DTE) and exit (S=exit, T=DTE−held), per-leg spread+commission,
same gauntlet gate as options_replay: avg ret-on-risk>0, CIlo>0, >=70% yrs+, OOS>0.

The interesting hypothesis this tests: structures should match trade PROFILES — low-WR/big-win
(ORB, volbreak) wants convex NAKED; high-WR/small-win mean reversion (Connors) may carry DEBIT
(capped is fine) or even CREDIT (selling the move that mean-reverts).

    .venv/Scripts/python research/options_cross.py
Report -> BOT/data/ml/reports/options_cross.json
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

from bot.options.strategies import signal_to_options  # noqa: E402
from bot.options.pricing import price as bs_price  # noqa: E402

REPORT = ROOT / "BOT" / "data" / "ml" / "reports" / "options_cross.json"
R_RATE, IV = 0.04, 0.20
LEG_COST = 2 * (0.03 + 0.0065)                     # per leg round trip, per share
MIN_T = 1.0 / (252 * 390)
STOP_ATR, TGT_ATR, HORIZON = 1.5, 3.0, 20
VB_K = 0.3
CONNORS_HOLD = 10


def _daily(sym):
    from bot.ml.swing_dataset import _daily_frame
    return _daily_frame(sym, "1d")


def _rsi2(c: pd.Series) -> pd.Series:
    d = c.diff()
    up = d.clip(lower=0).ewm(alpha=0.5, adjust=False).mean()
    dn = (-d.clip(upper=0)).ewm(alpha=0.5, adjust=False).mean()
    return 100 - 100 / (1 + up / dn.replace(0, np.nan))


def gen_swing(sym: str) -> list[dict]:
    """Pullback-reclaim trades: entry close of signal day; exit at stop/tp/horizon close."""
    b = _daily(sym)
    c = b["close"].to_numpy(float); h = b["high"].to_numpy(float); lo = b["low"].to_numpy(float)
    e20 = b["ema20"].to_numpy(float); e50 = b["ema50"].to_numpy(float)
    atr = b["atr14"].to_numpy(float)
    out, until = [], -1
    for i in range(60, len(b) - 1):
        if i <= until or not np.isfinite(atr[i]) or atr[i] <= 0:
            continue
        up = c[i] > e20[i] > e50[i]; dn = c[i] < e20[i] < e50[i]
        sign = 1 if (up and lo[i] <= e20[i] and c[i] > e20[i]) else \
            -1 if (dn and h[i] >= e20[i] and c[i] < e20[i]) else 0
        if not sign:
            continue
        entry = c[i]; sl = entry - sign * STOP_ATR * atr[i]; tp = entry + sign * TGT_ATR * atr[i]
        exitp, held = None, HORIZON
        for k in range(i + 1, min(i + 1 + HORIZON, len(b))):
            a_, f_ = (lo[k], h[k]) if sign == 1 else (h[k], lo[k])
            if sign * (a_ - sl) <= 0:
                exitp, held = sl, k - i; break
            if sign * (f_ - tp) >= 0:
                exitp, held = tp, k - i; break
        if exitp is None:
            k = min(i + HORIZON, len(b) - 1); exitp, held = c[k], k - i
        until = i + held
        out.append({"side": "long" if sign == 1 else "short", "entry": entry, "exit": exitp,
                    "stop": sl, "tp1": entry + sign * STOP_ATR * atr[i], "tp2": tp,
                    "held_days": held, "year": int(str(b['ts'].iloc[i])[:4])})
    return out


def gen_volbreak(sym: str) -> list[dict]:
    """open ± k·prev-range stop-entry, EOD flat; both-band days = conservative loss side."""
    b = _daily(sym)
    o = b["open"].to_numpy(float); h = b["high"].to_numpy(float)
    lo = b["low"].to_numpy(float); c = b["close"].to_numpy(float)
    out = []
    for i in range(1, len(b)):
        rng = h[i - 1] - lo[i - 1]
        if rng <= 0:
            continue
        k = VB_K * rng
        up, dn = o[i] + k, o[i] - k
        long_hit, short_hit = h[i] >= up, lo[i] <= dn
        if not (long_hit or short_hit):
            continue
        if long_hit and short_hit:                     # whipsaw: book the side the close punishes
            side = "long" if c[i] < o[i] else "short"
        else:
            side = "long" if long_hit else "short"
        sign = 1 if side == "long" else -1
        entry = up if side == "long" else dn
        out.append({"side": side, "entry": entry, "exit": c[i],
                    "stop": entry - sign * k, "tp1": entry + sign * k,
                    "tp2": entry + sign * 2 * k, "held_days": 0,
                    "year": int(str(b['ts'].iloc[i])[:4])})
    return out


def gen_connors(sym: str) -> list[dict]:
    """RSI2 <10 long over SMA200 (mirror short); exit RSI2 >90 (mirror) or 10 days."""
    b = _daily(sym)
    c = b["close"]; rsi = _rsi2(c); sma = c.rolling(200).mean()
    cv = c.to_numpy(float); rv = rsi.to_numpy(float); sv = sma.to_numpy(float)
    atr = b["atr14"].to_numpy(float)
    out, until = [], -1
    for i in range(200, len(b) - 1):
        if i <= until or not np.isfinite(rv[i]) or not np.isfinite(sv[i]):
            continue
        sign = 1 if (cv[i] > sv[i] and rv[i] < 10) else -1 if (cv[i] < sv[i] and rv[i] > 90) else 0
        if not sign or not np.isfinite(atr[i]) or atr[i] <= 0:
            continue
        entry = cv[i]; exitp, held = None, CONNORS_HOLD
        for k in range(i + 1, min(i + 1 + CONNORS_HOLD, len(b))):
            if (sign == 1 and rv[k] > 90) or (sign == -1 and rv[k] < 10):
                exitp, held = cv[k], k - i; break
        if exitp is None:
            k = min(i + CONNORS_HOLD, len(b) - 1); exitp, held = cv[k], k - i
        until = i + held
        risk = STOP_ATR * atr[i]
        out.append({"side": "long" if sign == 1 else "short", "entry": entry, "exit": exitp,
                    "stop": entry - sign * risk, "tp1": entry + sign * risk,
                    "tp2": entry + sign * 2 * risk, "held_days": held,
                    "year": int(str(b['ts'].iloc[i])[:4])})
    return out


def price_stream(trades: list[dict], dte_days: int) -> dict:
    """Every trade through naked/debit/credit; gauntlet per structure."""
    rows = {"naked": [], "debit": [], "credit": []}
    for t in trades:
        T0 = max(dte_days / 252.0, 30 * MIN_T)                      # 0DTE ≈ half a session
        T1 = max(T0 - t["held_days"] / 252.0, MIN_T)
        try:
            plays = signal_to_options(t["side"], t["entry"], t["stop"], t["tp1"], t["tp2"],
                                      S=t["entry"], iv=IV, T=T0, r=R_RATE, inc=1.0)
        except Exception:
            continue
        for name, play in plays.items():
            if name not in rows:
                continue
            pnl = 0.0
            for leg in play.legs:
                px_out = bs_price(t["exit"], leg.strike, T1, R_RATE, IV, leg.right)
                s = 1.0 if leg.side == "long" else -1.0
                pnl += s * (px_out - leg.price) - LEG_COST
            basis = abs(play.net)
            if name == "credit":
                basis = max(abs(play.legs[0].strike - play.legs[1].strike) - abs(play.net), 0.05)
            if basis < 0.01:
                continue
            rows[name].append({"ret": pnl / basis, "year": t["year"]})
    out = {}
    for name, rs in rows.items():
        if len(rs) < 30:
            out[name] = {"error": f"only {len(rs)}"}
            continue
        r = np.array([x["ret"] for x in rs])
        yrs = pd.Series(r).groupby([x["year"] for x in rs]).mean()
        yrs = [(y, v) for y, v in yrs.items() if sum(1 for x in rs if x["year"] == y) >= 8]
        pos = sum(1 for _, v in yrs if v > 0)
        cut = int(0.7 * len(r))
        rng = np.random.default_rng(7)
        ci = float(np.percentile(rng.choice(r, (2000, len(r)), replace=True).mean(1), 5))
        wins, losses = r[r > 0], r[r <= 0]
        gate = bool(r.mean() > 0 and ci > 0 and yrs and pos >= 0.7 * len(yrs) and r[cut:].mean() > 0)
        out[name] = {"n": int(len(r)), "avg": round(float(r.mean()), 3),
                     "win_pct": round(100 * float((r > 0).mean()), 1),
                     "pf": round(float(wins.sum() / abs(losses.sum())), 2) if len(losses) and losses.sum() else None,
                     "ci_lo": round(ci, 3), "yrs": f"{pos}/{len(yrs)}",
                     "oos": round(float(r[cut:].mean()), 3), "gate": "PASS" if gate else "fail"}
    return out


STREAMS = [("eq_swing", "QQQ", gen_swing, 21), ("volbreak", "QQQ", gen_volbreak, 0),
           ("volbreak", "SPY", gen_volbreak, 0), ("connors", "QQQ", gen_connors, 14),
           ("connors", "SPY", gen_connors, 14)]


def main():
    out = {"generated_at": pd.Timestamp.now("UTC").isoformat(), "iv": IV,
           "reference": "orb_core 0DTE naked PASSES (options_replay.json)", "streams": {}}
    REPORT.parent.mkdir(parents=True, exist_ok=True)
    for module, sym, gen, dte in STREAMS:
        key = f"{module}_{sym}@{dte}dte"
        print(f"=== {key} ===", flush=True)
        trades = gen(sym)
        res = price_stream(trades, dte)
        out["streams"][key] = {"n_trades": len(trades), **res}
        for name, v in res.items():
            print(f"  {name:7} {v if 'error' in v else ''}" if "error" in v else
                  f"  {name:7} n {v['n']} ret/risk {v['avg']:+.3f} win {v['win_pct']}% "
                  f"PF {v['pf']} CIlo {v['ci_lo']:+.3f} yr+{v['yrs']} OOS {v['oos']:+.3f} "
                  f"-> {v['gate']}", flush=True)
        REPORT.write_text(json.dumps(out, indent=1), encoding="utf-8")
    print(f"saved -> {REPORT}")


if __name__ == "__main__":
    main()
