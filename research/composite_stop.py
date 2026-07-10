"""NQ-COMPOSITE + STOP GRID (F107, user 2026-07-10: "does the entry/stop/tp get calculated?").
The gauntleted composite is enter-10:35 -> exit-16:00 with NO intraday stop. This walks the
actual 5m path of every confluence day with a stop at s x the PRIOR-DAY RANGE (the same risk
unit family as volbreak/weekend-fade), gap-aware. Adoption bar: keeps >= 80% of the no-stop
expectancy AND all seven checks still pass — the widest qualifying stop becomes the rule.

    python research/composite_stop.py
"""
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "engine"))
import numpy as np
import pandas as pd
import hs_db

rng = np.random.default_rng(41)
TICK, SLIP_TICKS, COMM, PT = 0.25, 2, 0.52, 2.0
STOPS = [None, 0.25, 0.5, 0.75, 1.0]
MIN_VOTES = 2


def cost_pct(price, slip_mult=1.0):
    return (2 * TICK * SLIP_TICKS * slip_mult + 2 * COMM / PT) / price


def setups(con, sym="NQ"):
    b = hs_db.bars(con, "5m", "full", sym=sym).sort_values("ts").reset_index(drop=True)
    dt = pd.to_datetime(b["ts"], utc=True).dt.tz_convert("America/New_York")
    b = b.assign(hm=dt.dt.hour * 60 + dt.dt.minute, day=dt.dt.strftime("%Y-%m-%d"),
                 dow=dt.dt.dayofweek)
    by_day = {d: g for d, g in b.groupby("day", sort=True)}
    days = sorted(by_day)
    fh_hist = []
    out = []
    for i in range(1, len(days)):
        prev, g = by_day[days[i - 1]], by_day[days[i]]
        rth_prev = prev[prev["hm"].between(570, 959)]
        rth = g[g["hm"].between(570, 959)]
        fh = rth[rth["hm"] < 630]
        rest = rth[rth["hm"] >= 635]                       # walk bars from 10:35
        if len(rth_prev) < 30 or len(fh) < 4 or len(rest) < 10:
            continue
        prev_o, prev_c = float(rth_prev["open"].iloc[0]), float(rth_prev["close"].iloc[-1])
        prev_rng = float(rth_prev["high"].max()) - float(rth_prev["low"].min())
        fh_ret = float(fh["close"].iloc[-1]) / float(fh["open"].iloc[0]) - 1
        gap = float(rth["open"].iloc[0]) / prev_c - 1
        fh_hist.append(abs(fh_ret))
        if len(fh_hist) < 100 or prev_rng <= 0:
            continue
        thr = float(np.quantile(fh_hist[-252:], 2 / 3))    # causal trailing tercile
        v = 0
        if int(g["dow"].iloc[0]) == 0:
            v += 1
        if abs(fh_ret) >= thr:
            v += 1 if fh_ret > 0 else -1
        v -= 1 if (prev_c - prev_o) > 0 else -1 if (prev_c - prev_o) < 0 else 0
        if gap > 0:
            v += 1
        if abs(v) < MIN_VOTES:
            continue
        out.append({"day": days[i], "dir": 1 if v > 0 else -1, "risk": prev_rng,
                    "op": rest["open"].to_numpy(float), "hi": rest["high"].to_numpy(float),
                    "lo": rest["low"].to_numpy(float), "cl": rest["close"].to_numpy(float)})
    return out


def trades(S, stop_mult, slip=1.0):
    out = []
    for s in S:
        d = s["dir"]; e = s["op"][0]
        stop = e - d * stop_mult * s["risk"] if stop_mult else None
        x = None
        if stop is not None:
            for j in range(1, len(s["op"])):
                if (s["op"][j] - stop) * d <= 0:
                    x = s["op"][j]; break
                adverse = s["lo"][j] if d == 1 else s["hi"][j]
                if (adverse - stop) * d <= 0:
                    x = stop; break
        if x is None:
            x = s["cl"][-1]
        out.append((s["day"], d * (x - e) / e - cost_pct(e, slip)))
    return out


def gauntlet(tag, tr, tr2, base=None):
    rs = np.array([t[1] for t in tr])
    lo = float(np.percentile(rng.choice(rs, (3000, len(rs)), replace=True).mean(1), 5))
    cut = int(len(rs) * 0.7); oos = rs[cut:]
    yrs = {}
    for d, r in tr:
        yrs[d[:4]] = yrs.get(d[:4], 0.0) + r
    yp, yn = sum(1 for v in yrs.values() if v > 0), len(yrs)
    w, l = rs[rs > 0].sum(), -rs[rs <= 0].sum()
    pf = float(w / l) if l > 0 else float("inf")
    rs2 = np.array([t[1] for t in tr2])
    ok = (len(rs) >= 100 and rs.mean() > 0 and lo > 0 and yp >= 0.7 * yn
          and len(oos) and oos.mean() > 0 and len(rs2) and rs2.mean() > 0 and pf >= 1.2)
    keep = f" keeps {100*rs.mean()/base:3.0f}%" if base else ""
    print(f"  {tag:10} n={len(rs):>4} exp {1e4*rs.mean():+5.1f}bps WR {100*(rs>0).mean():3.0f}% "
          f"PF {pf:4.2f} CI_lo {1e4*lo:+5.1f} yrs+ {yp:>2}/{yn} OOS {1e4*oos.mean():+5.1f} "
          f"worst {100*rs.min():+5.2f}%{keep}  [{'ALL 7' if ok else 'fail'}]")
    return float(rs.mean())


def main():
    con = hs_db.connect()
    S = setups(con, "NQ")
    con.close()
    print(f"######## F107 — nq-composite STOP GRID ({len(S)} confluence days, stop = s x prior-day range) ########")
    base = gauntlet("no stop", trades(S, None), trades(S, None, 2.0))
    for s in STOPS[1:]:
        gauntlet(f"stop {s}x", trades(S, s), trades(S, s, 2.0), base)
    print("\nadoption: widest stop keeping >=80% AND all-7 -> becomes the composite's risk rule; "
          "the risk UNIT (prior-day range) is also the position-sizing denominator.")


if __name__ == "__main__":
    main()
