"""CENSUS CANDIDATES — full gauntlet (F101, from the F99 atlas): the two directional pass-cells
as actual trading rules, seven checks each, NQ:

  monday-drift:      LONG at Monday's RTH open -> exit Monday's RTH close (census +8.1bps OOS +18)
  first-hour-follow: at 10:30, enter the FIRST HOUR's direction (big first-hours only, top tercile
                     |move|) -> exit 16:00 (census +5.1bps OOS +9.7)

    python research/census_gauntlet.py
"""
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "engine"))
import numpy as np
import pandas as pd
import hs_db

rng = np.random.default_rng(29)
TICK, SLIP_TICKS, COMM, PT = 0.25, 2, 0.52, 2.0


EQ = {"QQQ", "SPY"}
_COST_SYM = {"sym": "NQ"}                # set per-run; equities pay ticks, not futures slippage


def cost_pct(price, slip_mult=1.0):
    # COST-MODEL FIX (2026-07-10): the futures model (~30-40bps on a $500 ETF!) was applied to
    # QQQ/SPY and poisoned every equity verdict; equities pay ~1 tick/side (strat_daily model).
    if _COST_SYM["sym"] in EQ:
        return (2 * 0.01 * slip_mult) / price
    return (2 * TICK * SLIP_TICKS * slip_mult + 2 * COMM / PT) / price


def day_frames(con, sym="NQ"):
    b = hs_db.bars(con, "5m", "full", sym=sym).sort_values("ts").reset_index(drop=True)
    dt = pd.to_datetime(b["ts"], utc=True).dt.tz_convert("America/New_York")
    b = b.assign(hm=dt.dt.hour * 60 + dt.dt.minute, day=dt.dt.strftime("%Y-%m-%d"),
                 dow=dt.dt.dayofweek)
    out = []
    for d, g in b.groupby("day", sort=True):
        rth = g[g["hm"].between(570, 959)]
        if len(rth) < 30:
            continue
        fh = rth[rth["hm"] < 630]; rest = rth[rth["hm"] >= 630]
        out.append({"day": d, "dow": int(g["dow"].iloc[0]),
                    "o": float(rth["open"].iloc[0]), "c": float(rth["close"].iloc[-1]),
                    "fh_o": float(fh["open"].iloc[0]) if len(fh) > 3 else np.nan,
                    "fh_c": float(fh["close"].iloc[-1]) if len(fh) > 3 else np.nan,
                    "rest_o": float(rest["open"].iloc[0]) if len(rest) > 3 else np.nan,
                    "rest_c": float(rest["close"].iloc[-1]) if len(rest) > 3 else np.nan})
    return pd.DataFrame(out)


def monday_drift(D, slip=1.0):
    g = D[D.dow == 0]
    return [(r.day, (r.c - r.o) / r.o - cost_pct(r.o, slip)) for r in g.itertuples()]


def first_hour_follow(D, slip=1.0):
    g = D.dropna(subset=["fh_o", "fh_c", "rest_o", "rest_c"]).copy()
    g["fh_ret"] = (g.fh_c - g.fh_o) / g.fh_o
    big = g["fh_ret"].abs().quantile(2 / 3)
    g = g[g.fh_ret.abs() >= big]
    return [(r.day, np.sign(r.fh_ret) * (r.rest_c - r.rest_o) / r.rest_o - cost_pct(r.rest_o, slip))
            for r in g.itertuples()]


def gauntlet(tag, tr, tr2):
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
    ok = {"1 n>=100": len(rs) >= 100, "2 exp>0": rs.mean() > 0, "3 CI>0": lo > 0,
          "4 yrs>=70%": yp >= 0.7 * yn, "5 OOS>0": len(oos) and oos.mean() > 0,
          "6 2xslip>0": len(rs2) and rs2.mean() > 0, "7 PF>=1.2": pf >= 1.2}
    print(f"\n### {tag}")
    print(f"  n={len(rs)} exp {1e4*rs.mean():+.1f}bps WR {100*(rs>0).mean():.0f}% PF {pf:.2f} "
          f"CI_lo {1e4*lo:+.1f} yrs+ {yp}/{yn} OOS {1e4*oos.mean():+.1f} 2xslip {1e4*rs2.mean():+.1f}")
    for k, v in ok.items():
        print(f"  {'PASS' if v else 'FAIL'}  {k}")
    print(f"  VERDICT: {'ADOPT_CANDIDATE' if all(ok.values()) else 'REJECT'}")


def main():
    syms = [s.upper() for s in (sys.argv[1:] or ["NQ"])]
    con = hs_db.connect()
    for sym in syms:
        _COST_SYM["sym"] = sym
        D = day_frames(con, sym)
        # WINDOW-MATCHED per-security candidates (user 2026-07-10: "own patterns for their own
        # composite") — each cell judged in the WINDOW its census pass was measured on.
        print(f"\n######## F101 — census candidates, FULL GAUNTLET ({sym}) ########")
        gauntlet(f"{sym} monday-drift (Mon RTH open->close, long)", monday_drift(D), monday_drift(D, 2.0))
        gauntlet(f"{sym} first-hour-follow (big FH dir @10:30 -> 16:00)", first_hour_follow(D), first_hour_follow(D, 2.0))
    con.close()


if __name__ == "__main__":
    main()
