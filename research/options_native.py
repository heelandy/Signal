"""OPTIONS-ONLY strategy search (user 2026-07-06: "through all the research look for a strategy
for options only") — edges that exist purely in OPTION space, no underlying signal at all.

The archive has never tested one (everything prior translates underlying signals). With the data
on hand (SPY/QQQ daily + the vix_daily table) the canonical options-native candidates are:

  short_straddle   VARIANCE RISK PREMIUM: implied vol (VIX) persistently exceeds realized —
                   sell the ATM daily straddle at the open, expire at the close.
  long_straddle    the mirror (long gamma): pays only if realized > implied.
  short_vix_rich   VRP harvested ONLY when premium is rich (VIX > 1.1 x its SMA5).
  long_vix_calm    long gamma ONLY when premium is compressed (VIX < 0.9 x SMA5).

Pricing: ATM straddle at the OPEN, K = open, T = 1 trading day, sigma = VIX/100 (SPY; QQQ uses
VIX x 1.25 — a stated proxy, NASDAQ vol runs richer); payoff at expiry = |close - K|; costs
2 legs x (spread + commission). Basis for return = the premium (margin proxy for shorts —
CAVEAT: short-straddle true risk is unbounded, the gauntlet's yearly/CI checks carry the tail).
CAVEAT: VIX is 30-day SPX implied — a PROXY for daily ATM IV; a pass here is a research
candidate, not an adoption (needs real chain data to confirm).

Gate per variant: avg ret > 0 net costs AND bootstrap CIlo > 0 AND >= 70% yrs+ AND 70/30 OOS > 0.

    .venv/Scripts/python research/options_native.py
Report -> BOT/data/ml/reports/options_native.json
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

from bot.options.pricing import price as bs_price  # noqa: E402

REPORT = ROOT / "BOT" / "data" / "ml" / "reports" / "options_native.json"
R_RATE = 0.04
LEG_COST = 2 * (0.03 + 0.0065)          # per leg round trip per share
T_DAY = 1.0 / 252.0
IV_MULT = {"SPY": 1.00, "QQQ": 1.25}    # QQQ proxy: NASDAQ implied runs ~25% richer than VIX


def _frames(sym: str):
    import hs_db
    con = hs_db.connect()
    b = hs_db.bars(con, "1d", "rth", sym=sym)
    vix = con.execute("SELECT * FROM vix_daily ORDER BY 1").df()
    con.close()
    tcol = next(c for c in ("ts_et", "ts_utc", "ts", "date") if c in vix.columns)
    vix["_d"] = pd.to_datetime(vix[tcol]).dt.date
    vcol = next(c for c in ("close", "vix", "value") if c in vix.columns)
    b["_d"] = pd.to_datetime(b["ts"]).dt.date
    m = b.merge(vix[["_d", vcol]].rename(columns={vcol: "vix"}), on="_d", how="left")
    m["vix_prev"] = m["vix"].shift(1)                 # PIT: yesterday's close VIX prices today
    m["vix_sma5"] = m["vix"].shift(1).rolling(5).mean()
    return m.dropna(subset=["vix_prev"]).reset_index(drop=True)


def straddle_rets(m: pd.DataFrame, sym: str, side: str, gate: str | None) -> list[dict]:
    o = m["open"].to_numpy(float); c = m["close"].to_numpy(float)
    vix = m["vix_prev"].to_numpy(float) / 100.0 * IV_MULT[sym]
    sma = m["vix_sma5"].to_numpy(float) / 100.0 * IV_MULT[sym]
    yrs = pd.to_datetime(m["ts"]).dt.year.to_numpy()
    out = []
    for i in range(len(m)):
        if not (np.isfinite(vix[i]) and vix[i] > 0.01 and np.isfinite(o[i])):
            continue
        if gate == "rich" and not (np.isfinite(sma[i]) and vix[i] > 1.1 * sma[i]):
            continue
        if gate == "calm" and not (np.isfinite(sma[i]) and vix[i] < 0.9 * sma[i]):
            continue
        prem = (bs_price(o[i], o[i], T_DAY, R_RATE, vix[i], "C")
                + bs_price(o[i], o[i], T_DAY, R_RATE, vix[i], "P"))
        if prem <= 0.02:
            continue
        payoff = abs(c[i] - o[i])
        pnl = (prem - payoff if side == "short" else payoff - prem) - 2 * LEG_COST
        out.append({"ret": pnl / prem, "year": int(yrs[i])})
    return out


def gauntlet(rs: list[dict]) -> dict:
    if len(rs) < 60:
        return {"error": f"only {len(rs)} days"}
    r = np.array([x["ret"] for x in rs])
    yg = pd.Series(r).groupby([x["year"] for x in rs]).mean()
    yg = [(y, v) for y, v in yg.items() if sum(1 for x in rs if x["year"] == y) >= 8]
    pos = sum(1 for _, v in yg if v > 0)
    cut = int(0.7 * len(r))
    rng = np.random.default_rng(7)
    ci = float(np.percentile(rng.choice(r, (2000, len(r)), replace=True).mean(1), 5))
    wins, losses = r[r > 0], r[r <= 0]
    ok = bool(r.mean() > 0 and ci > 0 and yg and pos >= 0.7 * len(yg) and r[cut:].mean() > 0)
    return {"n": int(len(r)), "avg_ret_on_prem": round(float(r.mean()), 3),
            "win_pct": round(100 * float((r > 0).mean()), 1),
            "pf": round(float(wins.sum() / abs(losses.sum())), 2) if len(losses) and losses.sum() else None,
            "ci_lo": round(ci, 3), "yrs": f"{pos}/{len(yg)}",
            "worst_day": round(float(r.min()), 2),
            "oos": round(float(r[cut:].mean()), 3), "gate": "PASS" if ok else "fail"}


VARIANTS = [("short_straddle", "short", None), ("long_straddle", "long", None),
            ("short_vix_rich", "short", "rich"), ("long_vix_calm", "long", "calm")]


def main():
    out = {"generated_at": pd.Timestamp.now("UTC").isoformat(),
           "caveat": "VIX = 30d SPX implied, used as a daily-ATM-IV PROXY (QQQ x1.25); a pass "
                     "is a research candidate only — confirm on real chain data before any ladder",
           "symbols": {}}
    REPORT.parent.mkdir(parents=True, exist_ok=True)
    for sym in ("SPY", "QQQ"):
        print(f"=== OPTIONS-NATIVE {sym} ===", flush=True)
        m = _frames(sym)
        out["symbols"][sym] = {}
        for name, side, gate in VARIANTS:
            res = gauntlet(straddle_rets(m, sym, side, gate))
            out["symbols"][sym][name] = res
            print(f"  {name:16} {res if 'error' in res else ''}" if "error" in res else
                  f"  {name:16} n {res['n']:>5} ret/prem {res['avg_ret_on_prem']:+.3f} "
                  f"win {res['win_pct']}% PF {res['pf']} CIlo {res['ci_lo']:+.3f} "
                  f"yr+{res['yrs']} worst {res['worst_day']} OOS {res['oos']:+.3f} "
                  f"-> {res['gate']}", flush=True)
        REPORT.write_text(json.dumps(out, indent=1), encoding="utf-8")
    print(f"saved -> {REPORT}")


if __name__ == "__main__":
    main()
