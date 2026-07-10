"""RESOLUTION PARITY — 5m vs 1m (F100, user 2026-07-10: "run the strategies using tick to see if
we have any change"). True ticks have no 17y history, but the 1m parquets do — 5x finer than the
5m walk. This re-resolves the wired intraday-path strategies at both granularities:

  volbreak (NQ):      open +/- 0.3x prior-day range, EOD flat. At DAILY resolution ~30% of days
                      touch BOTH bands and the winner is path-ASSUMED; 5m/1m resolve it honestly.
  weekend-fade (NQ):  Sun 18:00 long, stop 0.5x Fri range, Mon 03:00 exit — stop-touch timing.

If 1m materially changes exp/WR vs 5m, finer feeds change the book; if not, 5m walks are safe.

    python research/resolution_parity.py
"""
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "engine"))
import numpy as np
import pandas as pd

TICK, SLIP_TICKS, COMM, PT = 0.25, 2, 0.52, 2.0
VB_K = 0.3


def cost_pct(price):
    return (2 * TICK * SLIP_TICKS + 2 * COMM / PT) / price


def load_1m(sym):
    b = pd.read_parquet(f"data/{sym.lower()}_continuous_1m.parquet")
    b = b.dropna(subset=["ts_et"]).sort_values("ts_et").reset_index(drop=True)
    et = pd.to_datetime(b["ts_et"])
    return b.assign(_hm=et.dt.hour * 60 + et.dt.minute, _day=et.dt.strftime("%Y-%m-%d"),
                    _dow=et.dt.dayofweek)


def to_5m(b):
    et = pd.to_datetime(b["ts_et"])
    g = b.groupby([b["_day"], et.dt.floor("5min")])
    o = g["open"].first(); h = g["high"].max(); l = g["low"].min(); c = g["close"].last()
    out = pd.DataFrame({"open": o, "high": h, "low": l, "close": c}).reset_index()
    ts = pd.to_datetime(out["ts_et"]) if "ts_et" in out else pd.to_datetime(out.iloc[:, 1])
    return out.assign(_hm=ts.dt.hour * 60 + ts.dt.minute, _day=out["_day"],
                      _dow=ts.dt.dayofweek)


def volbreak_walk(day_bars, prev_range):
    """First-touch through the session's bars: which band breaks first, then EOD close."""
    o = float(day_bars["open"].iloc[0])
    up, dn = o + VB_K * prev_range, o - VB_K * prev_range
    hi = day_bars["high"].to_numpy(float); lo = day_bars["low"].to_numpy(float)
    cl = day_bars["close"].to_numpy(float)
    for j in range(len(day_bars)):
        u, d = hi[j] >= up, lo[j] <= dn
        if u and d:
            return None                                   # ambiguous INSIDE one bar even here
        if u:
            return (cl[-1] - up) / (VB_K * prev_range)    # long from the band, EOD exit (R)
        if d:
            return (dn - cl[-1]) / (VB_K * prev_range)
    return 0.0                                            # no trigger


def run_volbreak(b, label):
    days = {d: g for d, g in b.groupby("_day", sort=True)}
    keys = sorted(days)
    rs, amb = [], 0
    for i in range(1, len(keys)):
        prev = days[keys[i - 1]]; cur = days[keys[i]]
        rth_prev = prev[prev["_hm"].between(570, 959)]
        rth_cur = cur[cur["_hm"].between(570, 959)]
        if len(rth_prev) < 30 or len(rth_cur) < 30:
            continue
        rng = float(rth_prev["high"].max()) - float(rth_prev["low"].min())
        if rng <= 0:
            continue
        r = volbreak_walk(rth_cur, rng)
        if r is None:
            amb += 1
            continue
        if r != 0.0:
            e = float(rth_cur["open"].iloc[0])
            rs.append(r - cost_pct(e) * e / (VB_K * rng))
    rs = np.array(rs)
    w, l = rs[rs > 0].sum(), -rs[rs <= 0].sum()
    print(f"  volbreak @{label:3}: n={len(rs):>4} exp {rs.mean():+.4f}R WR {100*(rs>0).mean():3.0f}% "
          f"PF {w/l if l>0 else 99:4.2f} | ambiguous(one-bar both-touch): {amb}")
    return rs


def run_weekend(b, label):
    days = {d: g for d, g in b.groupby("_day", sort=True)}
    keys = sorted(days)
    rs = []
    for i, d in enumerate(keys[:-1]):
        g = days[d]
        if int(g["_dow"].iloc[0]) != 4:
            continue
        rth = g[g["_hm"].between(570, 959)]
        if len(rth) < 30:
            continue
        h, l_, c = float(rth["high"].max()), float(rth["low"].min()), float(rth["close"].iloc[-1])
        rng = h - l_
        if rng <= 0 or (c - l_) / rng > 1 / 3:
            continue
        nxt = days[keys[i + 1]]                            # Sunday (next trading day after Friday)
        asia = pd.concat([nxt[nxt["_hm"] >= 18 * 60],
                          days[keys[i + 2]][days[keys[i + 2]]["_hm"] < 180] if i + 2 < len(keys) else nxt.iloc[0:0]])
        if len(asia) < 10:
            continue
        e = float(asia["open"].iloc[0]); stop = e - 0.5 * rng
        x = None
        op = asia["open"].to_numpy(float); lo = asia["low"].to_numpy(float)
        for j in range(1, len(asia)):
            if op[j] <= stop:
                x = op[j]; break
            if lo[j] <= stop:
                x = stop; break
        if x is None:
            x = float(asia["close"].iloc[-1])
        rs.append((x - e) / e - cost_pct(e))
    rs = np.array(rs)
    if not len(rs):
        print(f"  weekend  @{label:3}: no trades"); return rs
    w, l = rs[rs > 0].sum(), -rs[rs <= 0].sum()
    print(f"  weekend  @{label:3}: n={len(rs):>4} exp {1e4*rs.mean():+6.1f}bps WR {100*(rs>0).mean():3.0f}% "
          f"PF {w/l if l>0 else 99:4.2f}")
    return rs


def main():
    print("######## RESOLUTION PARITY — does finer data change the wired strategies? ########")
    b1 = load_1m("nq")
    b5 = to_5m(b1)
    print("\nNQ volbreak (band first-touch + EOD):")
    run_volbreak(b5, "5m"); run_volbreak(b1, "1m")
    print("\nNQ weekend-fade (0.5x stop):")
    run_weekend(b5, "5m"); run_weekend(b1, "1m")
    print("\nread: if 1m ~= 5m the coarse walk is honest; a big gap = finer feeds change the book. "
          "'ambiguous' counts shrink with granularity — what remains is what only true ticks resolve.")


if __name__ == "__main__":
    main()
