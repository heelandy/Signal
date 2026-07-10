"""NQ PATTERN CENSUS (F99, user 2026-07-10: "what patterns are noticeable across all the years
of NQ"). A disciplined atlas — the standard pattern families, each cell gated exactly like the
relay study (n>=150, bootstrap CI excludes 0, OOS same sign) so noise doesn't masquerade as
pattern. Families:
  1 day-of-week RTH returns          4 first hour -> rest of day
  2 day-of-week overnight returns    5 hour-of-day drift map
  3 opening gap fade/follow          6 prior-day direction -> today (momentum/reversal)
  7 volatility clustering (prior range tercile -> today's range — sizing, not direction)

    python research/nq_census.py [SYM ...]     (default NQ)
"""
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "engine"))
import numpy as np
import pandas as pd
import hs_db

rng = np.random.default_rng(23)
DOW = ["Mon", "Tue", "Wed", "Thu", "Fri"]


def cell(tag, x, pct=True):
    x = np.asarray(x, float)
    x = x[np.isfinite(x)]
    if len(x) < 150:
        return
    m = rng.choice(x, (2000, len(x)), replace=True).mean(1)
    lo, hi = float(np.percentile(m, 5)), float(np.percentile(m, 95))
    cut = int(len(x) * 0.7); oos = x[cut:]
    sig = lo > 0 or hi < 0
    oos_ok = len(oos) and np.sign(oos.mean()) == np.sign(x.mean())
    if not (sig and oos_ok):
        return
    u = 1e4 if pct else 1.0
    print(f"  {tag:46} n={len(x):>4} mean {u*x.mean():+7.1f}{'bps' if pct else '':<3} "
          f"WR {100*(x>0).mean():3.0f}% CI[{u*lo:+.1f},{u*hi:+.1f}] OOS {u*oos.mean():+7.1f}")


def main():
    syms = [s.upper() for s in (sys.argv[1:] or ["NQ"])]
    con = hs_db.connect()
    for sym in syms:
        b = hs_db.bars(con, "5m", "full", sym=sym).sort_values("ts").reset_index(drop=True)
        dt = pd.to_datetime(b["ts"], utc=True).dt.tz_convert("America/New_York")
        b = b.assign(dt=dt, hm=dt.dt.hour * 60 + dt.dt.minute, day=dt.dt.strftime("%Y-%m-%d"),
                     dow=dt.dt.dayofweek)
        days = []
        for d, g in b.groupby("day", sort=True):
            rth = g[g["hm"].between(570, 959)]
            if len(rth) < 30:
                continue
            fh = rth[rth["hm"] < 630]                                    # 09:30-10:30
            rest = rth[rth["hm"] >= 630]
            days.append({"day": d, "dow": int(g["dow"].iloc[0]),
                         "o": float(rth["open"].iloc[0]), "c": float(rth["close"].iloc[-1]),
                         "h": float(rth["high"].max()), "l": float(rth["low"].min()),
                         "fh_ret": (float(fh["close"].iloc[-1]) - float(fh["open"].iloc[0])) / float(fh["open"].iloc[0]) if len(fh) > 3 else np.nan,
                         "rest_ret": (float(rest["close"].iloc[-1]) - float(rest["open"].iloc[0])) / float(rest["open"].iloc[0]) if len(rest) > 3 else np.nan})
        D = pd.DataFrame(days)
        D["ret"] = (D["c"] - D["o"]) / D["o"]
        D["rng"] = (D["h"] - D["l"]) / D["o"]
        D["prev_c"] = D["c"].shift(1); D["prev_ret"] = D["ret"].shift(1)
        D["prev_rng"] = D["rng"].shift(1)
        D["gap"] = (D["o"] - D["prev_c"]) / D["prev_c"]
        D["on_ret"] = D["gap"]                                           # overnight = close->open
        print(f"\n######## {sym} census — {len(D)} RTH days ({D['day'].iloc[0][:4]}–{D['day'].iloc[-1][:4]}) "
              f"— ONLY cells passing CI+OOS print ########")
        print("\n[1] day-of-week RTH (open->close):")
        for w in range(5):
            cell(f"{DOW[w]} RTH", D[D.dow == w]["ret"].dropna())
        print("[2] day-of-week overnight (prior close->open):")
        for w in range(5):
            cell(f"into {DOW[w]} overnight", D[D.dow == w]["on_ret"].dropna())
        print("[3] opening gap -> RTH day (follow>0 / fade<0):")
        g = D.dropna(subset=["gap", "ret"])
        big = g["gap"].abs().quantile(2 / 3)
        cell("gap UP   -> day ret", g[g.gap > 0]["ret"])
        cell("gap DOWN -> day ret", g[g.gap < 0]["ret"])
        cell("BIG gap  -> follow (ret x sign(gap))", (g[g.gap.abs() >= big]["ret"] * np.sign(g[g.gap.abs() >= big]["gap"])))
        print("[4] first hour -> rest of day (follow dir):")
        f = D.dropna(subset=["fh_ret", "rest_ret"])
        cell("rest-of-day x sign(first hour)", f["rest_ret"] * np.sign(f["fh_ret"]))
        fh_big = f["fh_ret"].abs().quantile(2 / 3)
        cell("after BIG first hour -> follow", (f[f.fh_ret.abs() >= fh_big]["rest_ret"] * np.sign(f[f.fh_ret.abs() >= fh_big]["fh_ret"])))
        print("[5] hour-of-day drift (per-bar mean, RTH+overnight):")
        b5 = b.assign(r=b["close"].pct_change())
        for h0 in range(0, 24):
            seg = b5[(b5["hm"] >= h0 * 60) & (b5["hm"] < h0 * 60 + 60)]["r"].dropna()
            cell(f"{h0:02d}:00-{h0:02d}:59 per-5m-bar", seg)
        print("[6] prior-day direction -> today (follow dir):")
        p = D.dropna(subset=["prev_ret", "ret"])
        cell("today x sign(yesterday)", p["ret"] * np.sign(p["prev_ret"]))
        print("[7] volatility clustering (range, not direction):")
        v = D.dropna(subset=["prev_rng", "rng"])
        hi_t = v["prev_rng"].quantile(2 / 3); lo_t = v["prev_rng"].quantile(1 / 3)
        cell("range after HIGH-range day (vs median dev)", v[v.prev_rng >= hi_t]["rng"] - v["rng"].median(), pct=True)
        cell("range after LOW-range day (vs median dev)", v[v.prev_rng <= lo_t]["rng"] - v["rng"].median(), pct=True)
    con.close()
    print("\nCells that DON'T print failed the noise gates. Directional pass-cells are gauntlet "
          "candidates; [7] informs SIZING (vol clustering), not direction.")


if __name__ == "__main__":
    main()
