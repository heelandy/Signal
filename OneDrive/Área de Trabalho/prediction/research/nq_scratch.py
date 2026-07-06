"""NQ/ES HIGH-WR REFINE — break-even move + time-stop on the best cells from nq_winrate.py.

nq_winrate.py found NQ reaches 75-81% WR (regA, ATR-scaled stops, small TP) but PF <= 0.91:
at TP = 0.25-0.33x stop, the 20% full-stop losses outweigh the small wins. The two levers that
cut LOSS SIZE without capping winners:

  BE move   — once price moves be_frac x stop in favor, stop -> entry (full -1R becomes ~scratch)
  time-stop — neither TP nor SL hit after N bars -> exit at close (slow deaths exit partial,
              and partial-positive exits still count as wins -> can RAISE WR)

Grid: base cells {atr_1.5, atr_2.0, stop_60t..} x tp {0.25, 0.33} x regime {all, regA}
      x be_frac {none, 0.33, 0.5} x tmax {none, 6, 12, 24} bars.
Flags: wr75 = WR >= 75% & PF >= 1.2 · goal = WR >= 85% & PF >= 1.8.

    .venv/Scripts/python research/nq_scratch.py NQ ES
Report -> BOT/data/ml/reports/nq_scratch.json
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

REPORT = ROOT / "BOT" / "data" / "ml" / "reports" / "nq_scratch.json"
TP_FRACS = (0.25, 0.33)
BE_FRACS = (None, 0.10, 0.15)         # x stop distance — must sit BELOW the TP or it never fires
TMAXES = (None, 3, 6, 12)             # bars; None = EOD only
ABORTS = (None, 0.5)                  # close-based soft stop: bar CLOSES beyond -x*stop -> exit
STOPS = ("atr_1.5", "atr_2.0", "60t", "90t")
SPEC = {"NQ": (0.25, 2 * 0.25 + 0.15), "ES": (0.25, 2 * 0.25 + 0.06)}


def _walk(entries, h, lo, c, et_date, stops, tp_frac, cost_u, be_frac, tmax, abort):
    rs = []
    for (i, sign, entry), stop_u in zip(entries, stops):
        sl = entry - sign * stop_u
        tp = entry + sign * round(tp_frac * stop_u, 4)
        be_trig = entry + sign * be_frac * stop_u if be_frac else None
        res = None
        for k in range(i + 1, min(i + 400, len(c))):
            if et_date[k] != et_date[i]:
                res = sign * (c[k - 1] - entry); break
            adverse = lo[k] if sign == 1 else h[k]
            favor = h[k] if sign == 1 else lo[k]
            if sign * (adverse - sl) <= 0:                     # stop first on ambiguity
                res = sign * (sl - entry); break
            if sign * (favor - tp) >= 0:
                res = tp_frac * stop_u; break
            if be_trig is not None and sign * (favor - be_trig) >= 0:
                sl = entry                                      # BE move (checked NEXT bar)
                be_trig = None
            if abort is not None and sign * (c[k] - entry) <= -abort * stop_u:
                res = sign * (c[k] - entry); break              # soft close-based abort
            if tmax is not None and k - i >= tmax:
                res = sign * (c[k] - entry); break
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
        return {"error": "no trade timestamps matched"}
    regimes = np.asarray(regimes)
    out = {"entries": len(entries), "grid": {}}
    for reg_name, mask in (("all", np.ones(len(entries), bool)), ("regA", regimes == "A")):
        sub = [e for e, m in zip(entries, mask) if m]
        if len(sub) < 30:
            continue
        for stop_kind in STOPS:
            if stop_kind.endswith("t"):
                stops = [int(stop_kind[:-1]) * tick] * len(sub)
            else:
                am = float(stop_kind.split("_")[1])
                stops = [max(am * atr[i], 4 * tick) for i, _, _ in sub]
            for frac in TP_FRACS:
                for be in BE_FRACS:
                    for tm in TMAXES:
                        for ab in ABORTS:
                            key = (f"{reg_name}|{stop_kind}|tp{frac:.2f}|be{be if be else '-'}"
                                   f"|t{tm if tm else '-'}|ab{ab if ab else '-'}")
                            out["grid"][key] = _cell(
                                _walk(sub, h, lo, c, et_date, stops, frac, cost_u, be, tm, ab))
    return out


def main(syms):
    out = {"generated_at": pd.Timestamp.now("UTC").isoformat(), "symbols": {}}
    REPORT.parent.mkdir(parents=True, exist_ok=True)
    for sym in syms:
        print(f"=== SCRATCH {sym} ===", flush=True)
        out["symbols"][sym] = study(sym)
        grid = out["symbols"][sym].get("grid", {})
        hits = {k: v for k, v in grid.items() if v["wr75"]}
        show = hits or dict(sorted(grid.items(),
                                   key=lambda kv: ((kv[1]["pf"] or 0) if kv[1]["win_pct"] >= 75
                                                   else 0, kv[1]["win_pct"]), reverse=True)[:10])
        print(f"  wr75 hits: {len(hits)} / {len(grid)} cells")
        for k, v in list(show.items())[:14]:
            tag = "<<< GOAL" if v["goal"] else ("<< wr75" if v["wr75"] else "")
            print(f"  {k}: WR {v['win_pct']}% PF {v['pf']} avg {v['avg_r']:+.4f}R "
                  f"n {v['n']} dd {v['max_dd_r']}R {tag}", flush=True)
        REPORT.write_text(json.dumps(out, indent=1), encoding="utf-8")
    print(f"saved -> {REPORT}")


if __name__ == "__main__":
    main([s.upper() for s in (sys.argv[1:] or ["NQ", "ES"])])
