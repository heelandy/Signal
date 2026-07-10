"""ASIA-FADE + STOP GRID (F97, user 2026-07-10: "we need to have a stop loss" — measured BEFORE
the lineage takes its first shadow entry). Same rule as the gauntlet pass (bottom-third RTH close
-> long 18:00 -> exit 03:00), now with a stop at s x the risk unit (the RTH range) checked
bar-by-bar through the Asia session, GAP-AWARE (a bar opening through the stop fills at the open).

The menu this prints: each stop width -> edge retained vs no-stop, WR, PF, worst trade capped at.
Adoption bar: keeps >= 80% of the no-stop expectancy AND all 7 gauntlet checks still pass.

    python research/asia_fade_stop.py [SYM ...]    (default NQ)
"""
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "engine"))
import numpy as np
import pandas as pd
import hs_db

rng = np.random.default_rng(17)
TICK, SLIP_TICKS, COMM, PT = 0.25, 2, 0.52, 2.0
STOPS = [None, 0.25, 0.5, 0.75, 1.0, 1.5]      # x the risk unit (RTH range); None = gauntlet baseline


def cost_pct(price, slip_mult=1.0):
    return (2 * TICK * SLIP_TICKS * slip_mult + 2 * COMM / PT) / price


def bars(con, sym):
    b = hs_db.bars(con, "5m", "full", sym=sym).sort_values("ts").reset_index(drop=True)
    dt = pd.to_datetime(b["ts"], utc=True).dt.tz_convert("America/New_York")
    return b.assign(dt=dt, hm=dt.dt.hour * 60 + dt.dt.minute, day=dt.dt.strftime("%Y-%m-%d"))


_setups_cache = {}


def _setups(b):
    """ONE pass over the frame -> per qualifying day: entry, risk unit, and the Asia bar arrays.
    (The first version re-masked the 500k-row frame per day PER STOP LEVEL and never finished.)"""
    key = id(b)
    if key in _setups_cache:
        return _setups_cache[key]
    by_day = {d: g for d, g in b.groupby("day", sort=True)}
    days = sorted(by_day)
    out = []
    for di in range(len(days) - 1):
        g = by_day[days[di]]
        rth = g[g["hm"].between(9 * 60 + 30, 15 * 60 + 59)]
        if len(rth) < 30:
            continue
        h, l, c = float(rth["high"].max()), float(rth["low"].min()), float(rth["close"].iloc[-1])
        rng_ = h - l
        if rng_ <= 0 or (c - l) / rng_ > 1 / 3:
            continue
        asia = pd.concat([g[g["hm"] >= 18 * 60], by_day[days[di + 1]].query("hm < 180")])
        if len(asia) < 10:
            continue
        out.append({"day": days[di], "entry": float(asia["open"].iloc[0]), "risk": rng_,
                    "op": asia["open"].to_numpy(float), "lo": asia["low"].to_numpy(float),
                    "close": float(asia["close"].iloc[-1])})
    _setups_cache[key] = out
    return out


def trades(b, stop_mult, slip_mult=1.0):
    out = []
    for s in _setups(b):
        e, rng_ = s["entry"], s["risk"]
        stop = e - stop_mult * rng_ if stop_mult else None
        x = None
        if stop is not None:
            op, lo = s["op"], s["lo"]
            for j in range(1, len(op)):
                if op[j] <= stop:                     # gap through -> the open (honest fill)
                    x = op[j]; break
                if lo[j] <= stop:
                    x = stop; break
        if x is None:
            x = s["close"]                            # 03:00 exit
        out.append((s["day"], (x - e) / e - cost_pct(e, slip_mult), (x - e) / rng_))
    return out


def report(tag, tr, base_exp=None):
    rs = np.array([t[1] for t in tr])
    if not len(rs):
        print(f"  {tag}: no trades"); return None
    lo = float(np.percentile(rng.choice(rs, (3000, len(rs)), replace=True).mean(1), 5))
    cut = int(len(rs) * 0.7); oos = rs[cut:]
    yrs = {}
    for d, r, _ in tr:
        yrs[d[:4]] = yrs.get(d[:4], 0.0) + r
    yp, yn = sum(1 for v in yrs.values() if v > 0), len(yrs)
    w, l = rs[rs > 0].sum(), -rs[rs <= 0].sum()
    pf = float(w / l) if l > 0 else float("inf")
    keep = f" keeps {100*rs.mean()/base_exp:3.0f}%" if base_exp else ""
    g7 = (len(rs) >= 100 and rs.mean() > 0 and lo > 0 and yp >= 0.7 * yn
          and len(oos) and oos.mean() > 0 and pf >= 1.2)
    print(f"  {tag:12} n={len(rs):>4} exp {1e4*rs.mean():+5.1f}bps WR {100*(rs>0).mean():3.0f}% "
          f"PF {pf:4.2f} CI_lo {1e4*lo:+5.1f} yrs+ {yp:>2}/{yn} OOS {1e4*oos.mean():+5.1f} "
          f"worst {100*rs.min():+5.2f}%{keep}{' GAUNTLET-OK' if g7 else ''}")
    return float(rs.mean())


def main():
    syms = [s.upper() for s in (sys.argv[1:] or ["NQ"])]
    con = hs_db.connect()
    for sym in syms:
        b = bars(con, sym)
        print(f"\n######## {sym} — asia-fade STOP GRID (stop = s x RTH range, gap-aware) ########")
        base = report("no stop", trades(b, None))
        for s in STOPS[1:]:
            report(f"stop {s}x", trades(b, s), base)
    con.close()
    print("\nadoption bar: keeps >=80% of the no-stop exp AND GAUNTLET-OK (all 7). The widest "
          "stop that qualifies becomes the lineage's DISASTER STOP.")


if __name__ == "__main__":
    main()
