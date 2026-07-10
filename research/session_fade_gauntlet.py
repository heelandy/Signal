"""FULL GAUNTLET for the F95 relay candidates (user 2026-07-10: "let's do the full gauntlet").
Real trade simulation on 24h 5m bars, futures costs, seven checks each:

  CANDIDATE 1 — asia-fade:     RTH closes in the BOTTOM THIRD of its range -> LONG at the 18:00
                               reopen, exit at the 03:00 Asia close. (The relay's strongest cell.)
  CANDIDATE 2 — overnight-NQ:  DOWN RTH session -> LONG at the 18:00 reopen, exit at the NEXT
                               RTH open (09:30). The equities overnight duelist's rule on futures.

Seven checks (a strategy must pass ALL):
  1 min_trades >= 100          4 years positive >= 70%
  2 exp > 0 net of costs       5 OOS (last 30%) exp > 0
  3 bootstrap CI(exp) > 0      6 survives 2x slippage (exp > 0)
                               7 PF >= 1.2
    python research/session_fade_gauntlet.py [SYM ...]    (default NQ)
"""
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "engine"))
import numpy as np
import pandas as pd
import hs_db

rng = np.random.default_rng(13)
TICK, SLIP_TICKS, COMM, PT = 0.25, 2, 0.52, 2.0          # MNQ-style cost model (same as strat_daily)


def cost_pct(price, slip_mult=1.0):
    return (2 * TICK * SLIP_TICKS * slip_mult + 2 * COMM / PT) / price


def sessions(con, sym):
    b = hs_db.bars(con, "5m", "full", sym=sym).sort_values("ts").reset_index(drop=True)
    dt = pd.to_datetime(b["ts"], utc=True).dt.tz_convert("America/New_York")
    hm = dt.dt.hour * 60 + dt.dt.minute
    shifted = (hm - 18 * 60) % (24 * 60)
    seg = np.where(shifted < 9 * 60, "ASIA",
                   np.where(hm.between(3 * 60, 9 * 60 + 29), "LONDON",
                            np.where(hm.between(9 * 60 + 30, 15 * 60 + 59), "RTH", "off")))
    b = b.assign(seg=seg, dt=dt)
    b = b[b["seg"] != "off"].reset_index(drop=True)
    inst = (b["seg"] != b["seg"].shift()).cumsum()
    rows = []
    for _, g in b.groupby(inst):
        h, l = float(g["high"].max()), float(g["low"].min())
        c = float(g["close"].iloc[-1])
        rows.append({"seg": g["seg"].iloc[0], "start": g["dt"].iloc[0], "end": g["dt"].iloc[-1],
                     "o": float(g["open"].iloc[0]), "c": c, "h": h, "l": l,
                     "close_loc": (c - l) / (h - l) if h > l else 0.5,
                     "ret": (c - float(g["open"].iloc[0])) / float(g["open"].iloc[0])})
    return pd.DataFrame(rows).reset_index(drop=True)


def trades(S, which, slip_mult=1.0):
    """Pair each RTH with the following ASIA (and next RTH for the overnight hold)."""
    out = []
    for i in range(len(S)):
        if S.loc[i, "seg"] != "RTH":
            continue
        # find the next ASIA and the next RTH after it
        j = i + 1
        while j < len(S) and S.loc[j, "seg"] != "ASIA":
            j += 1
        if j >= len(S):
            break
        if which == "asia_fade":
            if S.loc[i, "close_loc"] > 1 / 3:                 # only bottom-third RTH closes
                continue
            e, x = S.loc[j, "o"], S.loc[j, "c"]               # 18:00 -> 03:00
        else:                                                 # overnight_nq: down RTH -> next RTH open
            if S.loc[i, "ret"] >= 0:
                continue
            k = j + 1
            while k < len(S) and S.loc[k, "seg"] != "RTH":
                k += 1
            if k >= len(S):
                break
            e, x = S.loc[j, "o"], S.loc[k, "o"]               # 18:00 -> next 09:30 open
        out.append((str(S.loc[j, "start"])[:10], (x - e) / e - cost_pct(e, slip_mult)))
    return out


def gauntlet(tag, tr, tr_2x):
    rs = np.array([t[1] for t in tr])
    if not len(rs):
        print(f"### {tag}: no trades"); return False
    lo = float(np.percentile(rng.choice(rs, (3000, len(rs)), replace=True).mean(1), 5))
    cut = int(len(rs) * 0.7); oos = rs[cut:]
    yrs = {}
    for d, r in tr:
        yrs[d[:4]] = yrs.get(d[:4], 0.0) + r
    yp, yn = sum(1 for v in yrs.values() if v > 0), len(yrs)
    w, l = rs[rs > 0].sum(), -rs[rs <= 0].sum()
    pf = float(w / l) if l > 0 else float("inf")
    rs2 = np.array([t[1] for t in tr_2x])
    checks = {"1 min_trades>=100": len(rs) >= 100,
              "2 exp>0 net": rs.mean() > 0,
              "3 CI(exp)>0": lo > 0,
              "4 years>=70%": yp >= 0.7 * yn,
              "5 OOS>0": len(oos) > 0 and oos.mean() > 0,
              "6 2x-slip survives": len(rs2) > 0 and rs2.mean() > 0,
              "7 PF>=1.2": pf >= 1.2}
    print(f"\n### {tag}")
    print(f"  n={len(rs)} exp {1e4*rs.mean():+.1f}bps WR {100*(rs>0).mean():.0f}% PF {pf:.2f} "
          f"CI_lo {1e4*lo:+.1f}bps yrs+ {yp}/{yn} OOS {1e4*oos.mean():+.1f}bps 2xslip {1e4*rs2.mean():+.1f}bps")
    for k, v in checks.items():
        print(f"  {'PASS' if v else 'FAIL'}  {k}")
    ok = all(checks.values())
    print(f"  VERDICT: {'ADOPT_CANDIDATE' if ok else 'REJECT'}")
    return ok


def main():
    syms = [s.upper() for s in (sys.argv[1:] or ["NQ"])]
    con = hs_db.connect()
    for sym in syms:
        S = sessions(con, sym)
        print(f"\n######## {sym} — F95 relay candidates, FULL GAUNTLET ########")
        gauntlet(f"{sym} asia-fade (weak RTH close -> long 18:00-03:00)",
                 trades(S, "asia_fade"), trades(S, "asia_fade", 2.0))
        gauntlet(f"{sym} overnight-NQ (down RTH -> long 18:00 -> next 09:30)",
                 trades(S, "overnight"), trades(S, "overnight", 2.0))
    con.close()


if __name__ == "__main__":
    main()
