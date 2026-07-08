"""OPTIONS PAYOFF REPLAY — the options module's gauntlet (the plan's missing step: "payoff-
simulated replay on the underlying champion's signals").

Every canonical QQQ/SPY trade (run_backtest, rule 07.4) is translated to the three defined plays
(bot/options/strategies.signal_to_options: naked buy / debit vertical / credit vertical, 0DTE)
and P&L'd honestly:
  entry : legs priced Black-Scholes at the underlying entry (T = minutes to 16:00 ET)
  exit  : legs re-priced at the underlying exit price and exit time (T floored at 1 minute)
  costs : per leg per side — half-spread $0.03/share + $0.65/contract commission
  metric: return on cost basis (debit plays) / on max loss (credit) — comparable across plays
Gate per structure: avg return > 0 net costs AND bootstrap CIlo > 0 AND >= 70% years+ AND
70/30 OOS > 0. IV is model-approximated (no chain history) — run at 0.20 with 0.15/0.30
sensitivity; the paper phase measures real fills before any sizing.

    .venv/Scripts/python research/options_replay.py QQQ SPY
Report -> BOT/data/ml/reports/options_replay.json
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

REPORT = ROOT / "BOT" / "data" / "ml" / "reports" / "options_replay.json"
R_RATE = 0.04
HALF_SPREAD = 0.03           # $/share per leg per side (0DTE ATM QQQ/SPY typical)
COMMISSION = 0.0065          # $/share per leg per side ($0.65/contract)
LEG_COST = 2 * (HALF_SPREAD + COMMISSION)          # per leg ROUND TRIP, per share
MIN_YEAR_T = 1.0 / (252 * 390)                     # 1 trading minute in years


def _t_years(ts) -> float:
    """0DTE: minutes from ts to 16:00 ET as a year fraction (floored at one minute)."""
    t = pd.Timestamp(ts)
    t = t.tz_convert("America/New_York") if t.tz is not None else t.tz_localize("America/New_York")
    mins = (16 * 60) - (t.hour * 60 + t.minute)
    return max(mins, 1) * MIN_YEAR_T


def replay(sym: str, iv: float = 0.20) -> dict:
    from bot.strategy.orb_candidates import load_state, run_backtest
    tr = run_backtest(load_state(sym)).reset_index(drop=True)
    rows = {"naked": [], "debit": [], "credit": []}
    meta = []
    for _, t in tr.iterrows():
        entry, exitp, risk = float(t["entry_price"]), float(t["exit_price"]), float(t["risk_pts"])
        if risk <= 0:
            continue
        side = str(t["direction"])
        sgn = 1 if side == "long" else -1
        stop = entry - sgn * risk
        tp1, tp2 = entry + sgn * 1.5 * risk, entry + sgn * 4.0 * risk
        T0, T1 = _t_years(t["entry_time"]), max(_t_years(t["exit_time"]), MIN_YEAR_T)
        try:
            plays = signal_to_options(side, entry, stop, tp1, tp2, S=entry, iv=iv, T=T0,
                                      r=R_RATE, inc=1.0)
        except Exception:
            continue
        yr = pd.Timestamp(t["entry_time"]).year
        for name, play in plays.items():
            if name not in rows:
                continue
            pnl = 0.0
            for leg in play.legs:
                px_out = bs_price(exitp, leg.strike, T1, R_RATE, iv, leg.right)
                s = 1.0 if leg.side == "long" else -1.0
                pnl += s * (px_out - leg.price) - LEG_COST
            basis = abs(play.net) if abs(play.net) > 0.01 else None      # debit paid / credit rcvd
            if name == "credit":
                width = abs(play.legs[0].strike - play.legs[1].strike)
                basis = max(width - abs(play.net), 0.05)                 # max loss per share
            if basis is None:
                continue
            rows[name].append({"ret": pnl / basis, "year": yr})
        meta.append(yr)
    out = {"n_trades": int(len(meta)), "iv": iv, "plays": {}}
    for name, rs in rows.items():
        if len(rs) < 30:
            out["plays"][name] = {"error": f"only {len(rs)} priced"}
            continue
        r = np.array([x["ret"] for x in rs])
        yrs = pd.Series(r).groupby([x["year"] for x in rs]).mean()
        yrs = [(y, v) for y, v in yrs.items() if sum(1 for x in rs if x["year"] == y) >= 8]
        pos = sum(1 for _, v in yrs if v > 0)
        cut = int(0.7 * len(r))
        rng = np.random.default_rng(7)
        ci = float(np.percentile(rng.choice(r, (2000, len(r)), replace=True).mean(1), 5))
        wins, losses = r[r > 0], r[r <= 0]
        gate = bool(r.mean() > 0 and ci > 0 and yrs and pos >= 0.7 * len(yrs)
                    and r[cut:].mean() > 0)
        out["plays"][name] = {
            "n": int(len(r)), "avg_ret_on_risk": round(float(r.mean()), 3),
            "win_pct": round(100 * float((r > 0).mean()), 1),
            "pf": round(float(wins.sum() / abs(losses.sum())), 2) if len(losses) and losses.sum() else None,
            "ci_lo": round(ci, 3), "years_pos": f"{pos}/{len(yrs)}",
            "oos30": round(float(r[cut:].mean()), 3), "gate": "PASS" if gate else "fail"}
    return out


def main(syms):
    out = {"generated_at": pd.Timestamp.now("UTC").isoformat(),
           "costs": f"per leg round trip ${LEG_COST:.3f}/share (spread {HALF_SPREAD} x2 + comm)",
           "symbols": {}}
    REPORT.parent.mkdir(parents=True, exist_ok=True)
    for sym in syms:
        print(f"=== OPTIONS REPLAY {sym} ===", flush=True)
        res = {"iv_0.20": replay(sym, 0.20)}
        for iv in (0.15, 0.30):                       # IV sensitivity (no chain history)
            sens = replay(sym, iv)
            res[f"iv_{iv:.2f}"] = {k: {"avg": v.get("avg_ret_on_risk"), "gate": v.get("gate")}
                                   for k, v in sens["plays"].items()}
        out["symbols"][sym] = res
        for name, v in res["iv_0.20"]["plays"].items():
            if "error" in v:
                print(f"  {name:7} {v['error']}")
            else:
                print(f"  {name:7} n {v['n']} ret/risk {v['avg_ret_on_risk']:+.3f} "
                      f"win {v['win_pct']}% PF {v['pf']} CIlo {v['ci_lo']:+.3f} "
                      f"yr+{v['years_pos']} OOS {v['oos30']:+.3f} -> {v['gate']}", flush=True)
        print(f"  sensitivity: iv .15 {res['iv_0.15']} | iv .30 {res['iv_0.30']}")
        REPORT.write_text(json.dumps(out, indent=1), encoding="utf-8")
    print(f"saved -> {REPORT}")


if __name__ == "__main__":
    main([s.upper() for s in (sys.argv[1:] or ["QQQ", "SPY"])])
