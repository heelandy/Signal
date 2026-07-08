#!/usr/bin/env python3
"""STRUCTURE LATENCY: 1-minute vs chart-TF (5m) — the user's exact complaint: "when OR + VWAP + SLOPE were
aligned, STRUCT was still lagging to say where price is going." Quantify it on real data:

  1) OSV-AGREE GAP: at every bar where OR-mid bias + VWAP-side + SLOPE-sign all AGREE (nonzero), is STRUCT
     already aligned? Measured for 5m struct and 1m struct. When it lags, how many MINUTES until it aligns?
     -> shows how much of the lag the 1m feed removes.
  2) FRESH-TREND SPEED: for each fresh 5m-struct trend, how many minutes EARLIER did the 1m struct confirm the
     same direction? -> the raw speedup the 1m implementation buys.

1m from data/<sym>_continuous_1m.parquet (RTH); 5m from the DB. Structure = gap-aware CHoCH, lb futures 3/equity 5.

    python research/orb_struct_speed.py NQ QQQ
"""
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "engine"))
import numpy as np, pandas as pd
import hs_db, hs_harness as H, hs_backtest as B
DATA = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "data")

def load_1m(sym):
    p = os.path.join(DATA, f"{sym.lower()}_continuous_1m.parquet")
    if not os.path.exists(p):
        return None
    df = pd.read_parquet(p)
    tcol = "ts_et" if "ts_et" in df.columns else ("ts" if "ts" in df.columns else df.columns[0])
    df = df.rename(columns={tcol: "ts"}); df["ts"] = pd.to_datetime(df["ts"], utc=True)
    et = df["ts"].dt.tz_convert("America/New_York"); mm = et.dt.hour * 60 + et.dt.minute
    if "volume" not in df:
        df["volume"] = 0.0
    return df[(mm >= 570) & (mm < 960)][["ts", "open", "high", "low", "close", "volume"]].sort_values("ts").reset_index(drop=True)

def q(a, p):
    return float(np.percentile(a, p)) if len(a) else float("nan")

def main():
    syms = [s.upper() for s in (sys.argv[1:] or ["NQ", "QQQ"])]
    con = hs_db.connect()
    for sym in syms:
        lb = 3 if sym in ("NQ", "ES", "GC") else 5
        d = H.compute_state(B._externals(con, hs_db.bars(con, "5m", "rth", sym=sym), sym), H.P(struct_lb_fix=lb))
        d.attrs["sym"] = sym
        st5 = d["st_state"].to_numpy()
        c = d["close"].to_numpy(); vs = d["vwap_sess"].to_numpy()
        day = pd.to_datetime(d["ts"]).dt.tz_convert("America/New_York").dt.date.to_numpy()
        et = pd.to_datetime(d["ts"]).dt.tz_convert("America/New_York"); hm = (et.dt.hour*60+et.dt.minute).to_numpy()
        # DIR-fast components on 5m
        lr = pd.Series(c).rolling(12).apply(lambda x: np.polyfit(np.arange(12), x, 1)[0], raw=True).to_numpy()
        dir_slp = np.sign(lr)
        dir_vw = np.sign(c - vs)
        # OR-mid bias per day (frozen at 10:00)
        dir_or = np.zeros(len(d))
        df_or = pd.DataFrame({"day": day, "hm": hm, "h": d["high"].to_numpy(), "l": d["low"].to_numpy(), "c": c})
        w = df_or[(df_or.hm >= 570) & (df_or.hm < 600)]
        bias = {}
        for dd, g in w.groupby("day"):
            mid = (g["h"].max() + g["l"].min())/2.0; bias[dd] = 1.0 if g.sort_values("hm")["c"].iloc[-1] > mid else -1.0
        for i in range(len(d)):
            dir_or[i] = bias.get(day[i], 0.0) if hm[i] >= 600 else 0.0
        # 1m struct aligned onto the 5m frame
        b1 = load_1m(sym)
        st1 = np.full(len(d), np.nan)
        if b1 is not None:
            d1 = H.compute_state(b1, H.P(struct_lb_fix=lb))
            t1 = pd.to_datetime(d1["ts"], utc=True).astype("datetime64[ns, UTC]")
            t5 = (pd.to_datetime(d["ts"], utc=True)+pd.Timedelta(minutes=4)).astype("datetime64[ns, UTC]")
            m = pd.merge_asof(pd.DataFrame({"ts": t5.to_numpy()}).sort_values("ts"),
                              pd.DataFrame({"ts": t1.to_numpy(), "st": d1["st_state"].to_numpy(float)}).sort_values("ts"),
                              on="ts", direction="backward")
            st1 = m["st"].to_numpy(float)
        ds5 = np.where(st5 == 1, 1, np.where(st5 == 2, -1, 0))
        ds1 = np.where(st1 == 1, 1, np.where(st1 == 2, -1, 0))
        # 1) OSV-agree bars
        osv = np.where((dir_or != 0) & (dir_or == dir_vw) & (dir_vw == dir_slp), dir_or, 0)
        idx = np.nonzero(osv != 0)[0]
        a5 = np.mean(ds5[idx] == osv[idx]) if len(idx) else float("nan")
        a1 = np.mean(ds1[idx] == osv[idx]) if len(idx) else float("nan")
        # lag: at the FIRST bar of each OSV-agree run, bars until struct aligns (same day)
        lag5, lag1 = [], []
        prev = -9
        for k in idx:
            if k == prev + 1:
                prev = k; continue                              # only the run's first bar
            prev = k
            for arr, out in ((ds5, lag5), (ds1, lag1)):
                j = k; steps = 0
                while j < len(d) and day[j] == day[k] and arr[j] != osv[k] and steps < 40:
                    j += 1; steps += 1
                out.append(steps if (j < len(d) and arr[j] == osv[k]) else 40)
        lag5, lag1 = np.array(lag5), np.array(lag1)
        print(f"\n{'='*94}\n{sym} — STRUCT LATENCY when OR+VWAP+SLOPE agree (n={len(idx)} agree-bars, {len(lag5)} runs)\n{'='*94}")
        print(f"  STRUCT already aligned at OSV-agree:   5m {100*a5:.0f}%   |   1m {100*a1:.0f}%   (higher = less lag)")
        print(f"  when lagging, minutes until STRUCT aligns:  5m median {5*q(lag5,50):.0f}m (p75 {5*q(lag5,75):.0f})  "
              f"|  1m median {q(lag1,50):.0f}m (p75 {q(lag1,75):.0f})")
        # 2) fresh 5m trend -> how many minutes earlier did 1m confirm same dir
        early = []
        for i in range(1, len(d)):
            if ds5[i] != 0 and ds5[i] != ds5[i-1] and day[i] == day[i-1]:
                j = i
                while j > 0 and day[j-1] == day[i] and ds1[j] == ds5[i] and i - j < 40:
                    j -= 1
                if ds1[j] != ds5[i]:
                    j += 1
                if ds1[j] == ds5[i]:
                    early.append(i - j)
        early = np.array(early)
        if len(early):
            print(f"  1m confirms the same fresh trend a MEDIAN {5*q(early,50):.0f}m EARLIER than 5m "
                  f"(p25 {5*q(early,25):.0f} / p75 {5*q(early,75):.0f}); {100*np.mean(early>0):.0f}% of trends 1m leads")
    con.close()
    print("\nREAD: higher %-aligned + lower lag on the 1m column = the 1m implementation closes the STRUCT-lag "
          "the user sees. This is the DIRECTION-READ speed, separate from the entry backtest.")

if __name__ == "__main__":
    main()
