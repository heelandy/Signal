"""VOLBREAK RE-VALIDATION at 1m (F105 — the F100 red flag: a volbreak-STYLE walk flipped sign
5m->1m; this tests the EXACT duelist spec before futures_volbreak advances past paper).

Duelist spec (strat_daily F52 / duel.py): stop-entry at OPEN ± 0.3 x PRIOR-DAY FULL-SESSION range,
first band touched wins, exit at the SESSION close, whipsaw day (both bands hit) = -1R, gap-aware
(open through a band = fill at the open). Same walk at 5m and at 1m; the seven checks at both.
If the verdict flips at 1m, the lineage is resolution-fragile and must not advance.

    python research/volbreak_revalidation.py
"""
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "engine"))
import numpy as np
import pandas as pd

rng = np.random.default_rng(37)
TICK, SLIP_TICKS, COMM, PT = 0.25, 2, 0.52, 2.0
K = 0.3


def cost_r(price, risk):
    return ((2 * TICK * SLIP_TICKS + 2 * COMM / PT)) / risk if risk > 0 else 0.0


def load(sym="nq"):
    b = pd.read_parquet(f"data/{sym}_continuous_1m.parquet").dropna(subset=["ts_et"])
    b = b.sort_values("ts_et").reset_index(drop=True)
    et = pd.to_datetime(b["ts_et"])
    return b.assign(_hm=et.dt.hour * 60 + et.dt.minute,
                    _day=et.dt.strftime("%Y-%m-%d"), _ts=et)


def to_5m(b):
    g = b.groupby([b["_day"], b["_ts"].dt.floor("5min")])
    out = pd.DataFrame({"open": g["open"].first(), "high": g["high"].max(),
                        "low": g["low"].min(), "close": g["close"].last()}).reset_index()
    ts = out["_ts"] if "_ts" in out else out.iloc[:, 1]
    ts = pd.to_datetime(ts)
    return out.assign(_hm=ts.dt.hour * 60 + ts.dt.minute, _day=out["_day"], _ts=ts)


def walk_day(g, up, dn, risk):
    """First-touch band entry -> EOD close; whipsaw = -1R; open-gap fills at the open."""
    o = g["open"].to_numpy(float); h = g["high"].to_numpy(float)
    lo = g["low"].to_numpy(float); c = g["close"].to_numpy(float)
    if o[0] >= up:                                    # gapped straight through a band at the open
        return (c[-1] - o[0]) / risk
    if o[0] <= dn:
        return (o[0] - c[-1]) / risk
    for j in range(len(g)):
        u, d = h[j] >= up, lo[j] <= dn
        if u and d:
            return -1.0                               # both inside one bar = whipsaw, worst case
        if u:                                         # long from the band; whipsaw check onward
            if (lo[j + 1:] <= dn).any():
                return -1.0
            return (c[-1] - up) / risk
        if d:
            if (h[j + 1:] >= up).any():
                return -1.0
            return (dn - c[-1]) / risk
    return None                                       # no trigger = no trade


def run(b, label):
    days = {d: g for d, g in b.groupby("_day", sort=True)}
    keys = sorted(days)
    tr = []
    for i in range(1, len(keys)):
        prev, cur = days[keys[i - 1]], days[keys[i]]
        if len(prev) < 50 or len(cur) < 50:
            continue
        rng_ = float(prev["high"].max()) - float(prev["low"].min())   # FULL-session prior range
        if rng_ <= 0:
            continue
        o = float(cur["open"].iloc[0])
        risk = K * rng_
        r = walk_day(cur, o + risk, o - risk, risk)
        if r is None:
            continue
        e_px = o
        tr.append((keys[i], r - cost_r(e_px, risk)))
    rs = np.array([t[1] for t in tr])
    lo_ci = float(np.percentile(rng.choice(rs, (3000, len(rs)), replace=True).mean(1), 5))
    cut = int(len(rs) * 0.7); oos = rs[cut:]
    yrs = {}
    for d, r in tr:
        yrs[d[:4]] = yrs.get(d[:4], 0.0) + r
    yp, yn = sum(1 for v in yrs.values() if v > 0), len(yrs)
    w, l = rs[rs > 0].sum(), -rs[rs <= 0].sum()
    pf = float(w / l) if l > 0 else float("inf")
    ok = {"n>=100": len(rs) >= 100, "exp>0": rs.mean() > 0, "CI>0": lo_ci > 0,
          "yrs>=70%": yp >= 0.7 * yn, "OOS>0": len(oos) and oos.mean() > 0, "PF>=1.2": pf >= 1.2}
    print(f"  @{label}: n={len(rs)} exp {rs.mean():+.4f}R WR {100*(rs>0).mean():.0f}% PF {pf:.2f} "
          f"CI_lo {lo_ci:+.4f} yrs+ {yp}/{yn} OOS {oos.mean():+.4f} "
          f"[{'ALL PASS' if all(ok.values()) else 'fail: ' + ','.join(k for k, v in ok.items() if not v)}]")


def main():
    print("######## F105 — futures_volbreak EXACT-SPEC re-validation, 5m vs 1m ########")
    b1 = load("nq")
    b5 = to_5m(b1)
    run(b5, "5m")
    run(b1, "1m")
    print("\nif the 1m verdict is materially worse, the lineage is resolution-fragile: "
          "it must NOT advance past paper until re-specified (e.g., confirmed-close entry).")


if __name__ == "__main__":
    main()
