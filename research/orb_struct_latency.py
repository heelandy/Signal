#!/usr/bin/env python3
"""HOW MANY BARS does st_state take to CONFIRM a fresh trend, on real data? (answers the user's question:
"a new trend takes ~2 swings / 30-50 min — does your data show that, and will I be IN it at the OR break?")

Two measurements on 5m RTH (gap-aware CHoCH, lb futures 3 / equity 5):
  1) CONFIRM LATENCY — every transition INTO a fresh trend (st_state 0/opposite -> 1 or 2); latency = bars
     from the launch swing (lowest low before an UP confirm / highest high before a DOWN) to the confirm bar.
     Distribution in bars AND minutes (bars x TF).
  2) AT THE OR BREAK — for the actual validated ORB entries: what fraction are ALREADY structure-aligned at
     entry (the gate fires), and for the rest, how many bars until st_state confirms (i.e., how "late" the
     confirmed direction is vs the static OR breakout the user already takes).

    python research/orb_struct_latency.py NQ QQQ SPY
"""
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "engine"))
import numpy as np, pandas as pd
import hs_db, hs_harness as H, hs_backtest as B

def q(a, p):
    return float(np.percentile(a, p)) if len(a) else float("nan")

def main():
    syms = [s.upper() for s in (sys.argv[1:] or ["NQ", "QQQ", "SPY"])]
    con = hs_db.connect()
    for sym in syms:
        lb = 3 if sym in ("NQ", "ES", "GC") else 5
        ext = B._externals(con, hs_db.bars(con, "5m", "rth", sym=sym), sym)
        d = H.compute_state(ext, H.P(struct_lb_fix=lb)); d.attrs["sym"] = sym
        st = d["st_state"].to_numpy(); lo = d["low"].to_numpy(); hi = d["high"].to_numpy()
        day = pd.to_datetime(d["ts"]).dt.tz_convert("America/New_York").dt.date.to_numpy()
        # 1) fresh-trend confirmations
        lat = []
        for i in range(2, len(st)):
            if st[i] in (1, 2) and st[i-1] != st[i] and st[i-1] != st[i]:   # entered a trend this bar
                if st[i-1] == st[i]:
                    continue
                j0 = i
                while j0 > 0 and day[j0-1] == day[i] and i - j0 < 40:       # search back within the day
                    j0 -= 1
                seg = slice(j0, i+1)
                if st[i] == 1:                                              # up: launch = the low it rose from
                    launch = j0 + int(np.argmin(lo[seg]))
                else:
                    launch = j0 + int(np.argmax(hi[seg]))
                if i - launch >= 0:
                    lat.append(i - launch)
        lat = np.array(lat)
        print(f"\n{'='*92}\n{sym} 5m (lb={lb}) — STRUCTURE CONFIRM LATENCY: bars from launch swing to fresh-trend confirm\n{'='*92}")
        if len(lat):
            print(f"  n={len(lat)} fresh trends |  bars  p25 {q(lat,25):.0f}  MEDIAN {q(lat,50):.0f}  p75 {q(lat,75):.0f}  p90 {q(lat,90):.0f}  max {lat.max()}")
            print(f"                    minutes p25 {5*q(lat,25):.0f}  MEDIAN {5*q(lat,50):.0f}  p75 {5*q(lat,75):.0f}  p90 {5*q(lat,90):.0f}  (x5m)")
            print(f"  claim check: '~2 swings / 30-50 min' -> {100*np.mean((lat*5>=30)&(lat*5<=50)):.0f}% land 30-50m, "
                  f"{100*np.mean(lat*5<30):.0f}% FASTER (<30m), {100*np.mean(lat*5>50):.0f}% slower")
        # 2) at the OR break — validated stack entries, structure aligned or lagging?
        d2 = d.copy(); d2["trend_up"] = True; d2["trend_down"] = True    # plain ORB (take EVERY break) to sample
        tr = B.backtest(d2, "tp2_full", "both", False, "orb", 0, 1.0, 4.0, 570, 600, 0.0, 900, "close",
                        eod_min=958, stop_mode="struct", entry_delay=0, chase_atr=1.0, strong_body=0.25,
                        ft_confirm=True, dir_seq=True, or_mid_bias=True, min_or_width=2.4)
        ts_bar = pd.to_datetime(d["ts"], utc=True).astype("int64").to_numpy()
        e_ts = pd.to_datetime(tr["entry_time"], utc=True).astype("int64").to_numpy()
        ei = np.searchsorted(ts_bar, e_ts)
        aligned = 0; lags = []
        for k, r in enumerate(tr.itertuples()):
            i = ei[k]; want = 1 if r.direction == "long" else 2
            if i < len(st) and st[i] == want:
                aligned += 1
            else:                                                          # how many bars forward until confirm
                j = i; steps = 0
                while j < len(st) and day[j] == day[min(i, len(day)-1)] and st[j] != want and steps < 40:
                    j += 1; steps += 1
                lags.append(steps if (j < len(st) and st[j] == want) else 40)
        lags = np.array(lags)
        print(f"  AT THE OR BREAK (n={len(tr)} plain-ORB entries): {100*aligned/len(tr):.0f}% ALREADY structure-aligned at entry "
              f"(gate fires immediately); of the rest, median {q(lags,50):.0f} bars (~{5*q(lags,50):.0f}m) to confirm.")
    con.close()
    print("\nREAD: the static OR break happens NOW; the confirmed-structure gate is what adds the latency above. "
          "High %-aligned-at-break = the break itself is usually already IN the confirmed trend.")

if __name__ == "__main__":
    main()
