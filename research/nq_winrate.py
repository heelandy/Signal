"""NQ 75%-WIN-RATE SEARCH — what geometry/filters get NQ to >= 75% WR profitably?

Finding (target_geometry 2026-07-05): a 45-tick (11.25 pt) stop is INSIDE NQ's bar-to-bar noise —
every TP fraction loses (PF 0.33-0.80). This study keeps the canonical entries and searches the
two structural levers the user can actually change:

  1. STOP BUDGET  — fixed ticks {45..300} AND ATR-scaled {0.5..2.0}x ATR(14) (vol-adaptive:
     the right size in 2018 NQ ~7000 and 2026 NQ ~24000 is not the same tick count)
  2. TP FRACTION  — {0.25, 0.33, 0.40, 0.50, 0.60} x stop
  3. REGIME FILTER — all trades vs regime-A only (the canonical backtest tags each trade)

Flags: wr75 = WR >= 75% & PF >= 1.2 (the user's ask) · goal = WR >= 85% & PF >= 1.8 (ultimate).
Honest costs: 2 ticks slip + commission per round trip; stop-first on same-bar ambiguity; EOD flat.

    .venv/Scripts/python research/nq_winrate.py            # NQ (default)
    .venv/Scripts/python research/nq_winrate.py NQ ES      # any futures
Report -> BOT/data/ml/reports/nq_winrate.json
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

from bot.strategy.orb_candidates import load_state, run_backtest  # noqa: E402

REPORT = ROOT / "BOT" / "data" / "ml" / "reports" / "nq_winrate.json"
TP_FRACS = (0.25, 0.33, 0.40, 0.50, 0.60)
STOP_TICKS = (45, 60, 90, 120, 150, 180, 240, 300)
ATR_MULTS = (0.5, 0.75, 1.0, 1.5, 2.0)
# tick size, round-trip cost in points (2 ticks slip + commission)
SPEC = {"NQ": (0.25, 2 * 0.25 + 0.15), "ES": (0.25, 2 * 0.25 + 0.06)}


def _walk(entries, h, lo, c, et_date, stops, tp_frac, cost_u):
    """First-touch walk per entry with a PER-ENTRY stop size. Returns net-R array."""
    rs = []
    for (i, sign, entry), stop_u in zip(entries, stops):
        sl = entry - sign * stop_u
        tp = entry + sign * round(tp_frac * stop_u, 4)
        res = None
        for k in range(i + 1, min(i + 400, len(c))):
            if et_date[k] != et_date[i]:
                res = sign * (c[k - 1] - entry)
                break
            adverse = lo[k] if sign == 1 else h[k]
            favor = h[k] if sign == 1 else lo[k]
            if sign * (adverse - sl) <= 0:          # stop first on ambiguity (conservative)
                res = -stop_u; break
            if sign * (favor - tp) >= 0:
                res = tp_frac * stop_u; break
        if res is None:
            res = sign * (c[min(i + 399, len(c) - 1)] - entry)
        rs.append((res - cost_u) / stop_u)
    return np.asarray(rs, float)


def _cell(r):
    wins, losses = r[r > 0], r[r <= 0]
    pf = float(wins.sum() / abs(losses.sum())) if len(losses) and losses.sum() != 0 else None
    eq = np.cumsum(r)
    dd = float((eq - np.maximum.accumulate(eq)).min()) if len(r) else 0.0
    wr = float((r > 0).mean()) if len(r) else 0.0
    return {"n": int(len(r)), "win_pct": round(100 * wr, 1),
            "pf": round(pf, 2) if pf else None,
            "avg_r": round(float(r.mean()), 4) if len(r) else None,
            "max_dd_r": round(dd, 1),
            "wr75": bool(wr >= 0.75 and pf and pf >= 1.2),
            "goal": bool(wr >= 0.85 and pf and pf >= 1.8)}


def study(sym: str) -> dict:
    tick, cost_u = SPEC[sym.upper()]
    d = load_state(sym)
    tr = run_backtest(d).reset_index(drop=True)
    ts64 = pd.to_datetime(d["ts"], utc=True).to_numpy("datetime64[ns]")
    h = d["high"].to_numpy(float); lo = d["low"].to_numpy(float); c = d["close"].to_numpy(float)
    et_date = pd.to_datetime(d["ts"]).dt.tz_convert("America/New_York").dt.date.to_numpy()
    # ATR(14) on the same bars, PIT (uses bars up to and incl. the entry bar)
    prev_c = np.concatenate([[c[0]], c[:-1]])
    tr_rng = np.maximum(h - lo, np.maximum(np.abs(h - prev_c), np.abs(lo - prev_c)))
    atr = pd.Series(tr_rng).rolling(14, min_periods=5).mean().to_numpy()

    entries, regimes = [], []
    for _, t in tr.iterrows():
        ets = pd.Timestamp(t["entry_time"])
        ets = ets.tz_localize("UTC") if ets.tz is None else ets.tz_convert("UTC")
        i = int(np.searchsorted(ts64, ets.as_unit("ns").to_datetime64()))
        if i < len(ts64):
            entries.append((i, 1 if t["direction"] == "long" else -1, float(t["entry_price"])))
            regimes.append(str(t.get("regime", "?")))
    if not entries:
        return {"error": f"no trade timestamps matched ({len(tr)} trades)"}
    regimes = np.asarray(regimes)
    out = {"entries": len(entries), "tick": tick, "round_trip_cost_units": cost_u,
           "regime_counts": {k: int(v) for k, v in zip(*np.unique(regimes, return_counts=True))},
           "grid": {}}
    for reg_name, mask in (("all", np.ones(len(entries), bool)), ("regA", regimes == "A")):
        sub = [e for e, m in zip(entries, mask) if m]
        if len(sub) < 30:
            continue
        for frac in TP_FRACS:
            for st in STOP_TICKS:
                stops = [st * tick] * len(sub)
                out["grid"][f"{reg_name}|stop_{st}t|tp_{frac:.2f}x"] = (
                    {"stop": f"{st}t", **_cell(_walk(sub, h, lo, c, et_date, stops, frac, cost_u))})
            for am in ATR_MULTS:
                stops = [max(am * atr[i], 4 * tick) for i, _, _ in sub]
                cell = _cell(_walk(sub, h, lo, c, et_date, stops, frac, cost_u))
                cell["stop"] = f"{am}xATR"
                cell["median_stop_ticks"] = round(float(np.median(stops)) / tick, 0)
                out["grid"][f"{reg_name}|atr_{am}|tp_{frac:.2f}x"] = cell
    return out


def main(syms):
    out = {"generated_at": pd.Timestamp.now("UTC").isoformat(),
           "ask": "NQ >= 75% win rate with PF >= 1.2 (wr75); ultimate goal WR>=85 & PF>=1.8 (goal)",
           "symbols": {}}
    REPORT.parent.mkdir(parents=True, exist_ok=True)
    for sym in syms:
        print(f"=== NQ-WR {sym} ===", flush=True)
        try:
            out["symbols"][sym] = study(sym)
        except Exception as e:
            out["symbols"][sym] = {"error": str(e)[:200]}
            print(f"  ERROR {e}")
            continue
        hits = {k: v for k, v in out["symbols"][sym]["grid"].items() if v["wr75"]}
        best = sorted(out["symbols"][sym]["grid"].items(),
                      key=lambda kv: (kv[1]["win_pct"], kv[1]["pf"] or 0), reverse=True)[:8]
        print(f"  cells with WR>=75 & PF>=1.2: {len(hits)}")
        for k, v in (hits.items() if hits else best):
            tag = "<<< GOAL" if v["goal"] else ("<< wr75" if v["wr75"] else "")
            print(f"  {k}: WR {v['win_pct']}% PF {v['pf']} avg {v['avg_r']:+.4f}R "
                  f"n {v['n']} dd {v['max_dd_r']}R {tag}", flush=True)
        REPORT.write_text(json.dumps(out, indent=1), encoding="utf-8")
    print(f"saved -> {REPORT}")
    return out


if __name__ == "__main__":
    main([s.upper() for s in (sys.argv[1:] or ["NQ"])])
