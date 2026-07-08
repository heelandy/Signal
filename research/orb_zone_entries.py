#!/usr/bin/env python3
"""ZONE-BASED ENTRIES (doc items 14 entry-types / 15 trend<->liquidity roles / 21 shock-candle), tested on
EVERY day of on-disk 1m data. NOT the ORB break — a NEW entry family: trade the liquidity zones conditioned on
the trend/range regime, fed through the VALIDATED exit (struct stop + 4R cap) so it's comparable + additivity-
testable against the current stack (user protocol: standalone AND additive).

  regime (per 5m bar): UP = st_state 1, DOWN = st_state 2, RANGE = else.
  zones: the day's MAJOR/STRONG zones from the FIRST 60 RTH 1m bars (09:30-10:30, causal snapshot), reused
         for the rest of the day (10:30-15:00 entries).
  21 SHOCK filter: skip any entry bar whose range > SHOCK_ATR x ATR (a shock is not a setup).
  15 TREND<->LIQUIDITY entries + 14 type tags:
     UP  regime + price PULLS BACK to a BUY-side (support) zone from above + bullish close  -> LONG  (pullback)
     DOWN regime + price rallies to a SELL-side (resistance) zone + bearish close            -> SHORT (pullback)
     RANGE + price at the UPPER (sell) zone + bearish close -> SHORT (fade);  LOWER (buy) + bullish -> LONG (fade)
  Exit = the validated struct-stop + 4R cap (via the ext hook). Standalone gauntlet + overlap vs the ORB.

    python research/orb_zone_entries.py NQ QQQ ES GC
"""
import sys, os, gc
sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "engine"))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import numpy as np, pandas as pd
import hs_db, hs_harness as H, hs_backtest as B, hs_validate as V
from orb_liquidity_zones import detect_zones

DATA = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "data")
SHOCK_ATR = 3.0                       # 21: bar range > this x ATR = shock, skip
NEAR_ATR = 0.30                       # price within this x ATR of a zone center = "at" the zone
_rng = np.random.default_rng(7)
def ci_lo(r):
    return float(np.percentile(_rng.choice(r, size=(1000, len(r)), replace=True).mean(axis=1), 5)) if len(r) >= 10 else float("nan")
def yr(tr):
    t = tr.copy(); t["y"] = pd.to_datetime(t["entry_time"], utc=True).dt.tz_convert("America/New_York").dt.year
    g = t.groupby("y")["net_R"].mean(); return int((g > 0).sum()), len(g)
def line(tag, tr):
    if tr is None or len(tr) < 20:
        print(f"  {tag:20} n={0 if tr is None else len(tr):>4}  (too few)"); return
    r = tr["net_R"].to_numpy(); L = tr.net_R[tr.direction == "long"].to_numpy(); S = tr.net_R[tr.direction == "short"].to_numpy()
    lo = ci_lo(r); p, ny = yr(tr)
    both = len(L) > 5 and L.mean() > 0 and len(S) > 5 and S.mean() > 0
    g = "PASS" if (lo > 0 and both and ny and p >= 0.7 * ny) else "----"
    print(f"  {tag:20} n={len(r):>4} exp {r.mean():+.3f} PF {V.pf(r):>4.2f} win {100*np.mean(r>0):>2.0f}% "
          f"CIlo {lo:+.3f} L{(L.mean() if len(L) else 0):+.2f} S{(S.mean() if len(S) else 0):+.2f} yr+{p}/{ny} {g}")

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
    df = df[(mm >= 570) & (mm < 960)].copy(); df["dd"] = et[(mm >= 570) & (mm < 960)].dt.date.to_numpy()
    df["mm"] = mm[(mm >= 570) & (mm < 960)].to_numpy()
    return df

def main():
    syms = [s.upper() for s in (sys.argv[1:] or ["NQ", "QQQ", "ES", "GC"])]
    con = hs_db.connect()
    for sym in syms:
        b1 = load_1m(sym)
        if b1 is None:
            print(f"{sym}: no 1m parquet — skipped"); continue
        lb = 3 if sym in ("NQ", "ES", "GC") else 5
        d = H.compute_state(B._externals(con, hs_db.bars(con, "5m", "rth", sym=sym), sym), H.P(struct_lb_fix=lb))
        d.attrs["sym"] = sym
        st = d["st_state"].to_numpy(); c = d["close"].to_numpy(); o = d["open"].to_numpy()
        hi = d["high"].to_numpy(); lo_ = d["low"].to_numpy(); atr = d["atr14"].to_numpy()
        et = pd.to_datetime(d["ts"]).dt.tz_convert("America/New_York")
        dd = et.dt.date.to_numpy(); mn = (et.dt.hour * 60 + et.dt.minute).to_numpy()
        # per-day zone snapshot from the first 60 RTH 1m bars (09:30-10:30)
        zmap = {}
        for day, g in b1.groupby("dd"):
            form = g[g["mm"] <= 630]
            if len(form) >= 40:
                try:
                    zmap[day] = [z for z in detect_zones(form, sym=sym) if z["label"] in ("MAJOR", "STRONG")]
                except Exception:
                    pass
        # separate pullback (trend-continuation) vs fade (range-boundary) so we can locate the failure
        pb_l = np.zeros(len(d), bool); pb_s = np.zeros(len(d), bool)   # pullback into support/resistance WITH trend
        fd_l = np.zeros(len(d), bool); fd_s = np.zeros(len(d), bool)   # fade the range boundary
        tags = {"pullback": 0, "fade": 0, "shock_skip": 0}
        for i in range(1, len(d)):
            if mn[i] < 630 or mn[i] >= 900:                       # entries only after the zone snapshot, before EOD
                continue
            zs = zmap.get(dd[i])
            if not zs or atr[i] <= 0:
                continue
            if (hi[i] - lo_[i]) > SHOCK_ATR * atr[i]:             # 21 shock filter
                tags["shock_skip"] += 1; continue
            buy = [z for z in zs if "BUY" in z["type"]]; sell = [z for z in zs if "SELL" in z["type"]]
            near_buy = any(abs(c[i] - z["center"]) <= NEAR_ATR * atr[i] for z in buy)
            near_sell = any(abs(c[i] - z["center"]) <= NEAR_ATR * atr[i] for z in sell)
            bull = c[i] > o[i] and c[i] > c[i-1]; bear = c[i] < o[i] and c[i] < c[i-1]
            reg = "UP" if st[i] == 1 else "DOWN" if st[i] == 2 else "RANGE"
            if reg == "UP" and near_buy and bull:
                pb_l[i] = True; tags["pullback"] += 1            # 14/15: pullback into support, with trend
            elif reg == "DOWN" and near_sell and bear:
                pb_s[i] = True; tags["pullback"] += 1
            elif reg == "RANGE":
                if near_sell and bear:
                    fd_s[i] = True; tags["fade"] += 1           # 14/15: fade the range top
                elif near_buy and bull:
                    fd_l[i] = True; tags["fade"] += 1
        ext_l = pb_l | fd_l; ext_s = pb_s | fd_s
        d["trend_up"] = True; d["trend_down"] = True
        bt = lambda el, es: B.backtest(d, "tp2_full", "both", False, "ext", 0, 1.0, 4.0, 570, 600, 0.0, 900, "close",
                                       eod_min=958, stop_mode="struct", ext_long=el, ext_short=es)
        trz = bt(ext_l, ext_s); trpb = bt(pb_l, pb_s); trfd = bt(fd_l, fd_s)
        # fade with a FIXED target at the opposing zone would need a zone-target exit; the trail is a known mismatch —
        # so trfd is a lower bound on fades. trpb (trend-continuation pullback) is the fair test of item 15's core.
        # the ORB baseline (the current stack entry) for the additivity contrast
        d2 = d.copy(); d2["trend_up"] = st == 1; d2["trend_down"] = st == 2   # (struct as grade — but ORB ref uses none)
        d2["trend_up"] = True; d2["trend_down"] = True
        orb = B.backtest(d2, "tp2_full", "both", False, "orb", 0, 1.0, 4.0, 570, 600, 0.0, 900, "close",
                         eod_min=958, stop_mode="struct", entry_delay=0, chase_atr=1.0, strong_body=0.25,
                         ft_confirm=True, dir_seq=True, or_mid_bias=True, min_or_width=2.4)
        # overlap: do zone entries fire on DIFFERENT days/bars than the ORB? (additive only if unique + positive)
        ok = set(zip(pd.to_datetime(orb["entry_time"]).astype("int64"), orb["direction"])) if len(orb) else set()
        uniq = trz[[ (t, dr) not in ok for t, dr in zip(pd.to_datetime(trz["entry_time"]).astype("int64"), trz["direction"]) ]] if len(trz) else trz
        print(f"\n{'='*96}\n{sym} — ZONE ENTRIES (14 type / 15 trend<->liq / 21 shock) on ALL days "
              f"({len(zmap)} days w/ zones; {tags['pullback']} pullback + {tags['fade']} fade sig, {tags['shock_skip']} shock-skipped)\n{'='*96}")
        line("ZONE entries (all)", trz)
        line("  PULLBACK (trend)", trpb)
        line("  FADE (range, trail)", trfd)
        line("  all uniq vs ORB", uniq)
        line("ORB baseline (ref)", orb)
        del d, b1; gc.collect()
    con.close()
    print("\nKEY: zone entries GRADUATE only if standalone PASS (exp+CIlo>0, both sides, >=70% yrs) AND the "
          "UNIQUE (non-ORB) cohort is also positive = a real ADDITIVE stream, not ORB in disguise. 21 shock-skip count shown.")

if __name__ == "__main__":
    main()
