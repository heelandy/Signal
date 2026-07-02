#!/usr/bin/env python3
"""FAST DIRECTION research — "how fast can the system know which way price is going?"

The ORB breakout TRIGGER (break of OR high/low) and the exit are held fixed at the validated config
(delay-0, chase-1.0, struct stop, cap-4R, strong-body 0.25, follow-through, OR-mid bias, dir-sequence).
We swap ONLY the directional GATE (the trend_up/trend_down that must be True to fire) across candidates and
measure THREE things per candidate:
  * EXPECTANCY gauntlet (exp / PF / CIlo / yr+ / OOS / both sides)  -> does the gate keep the edge?
  * TRADES n                                                        -> does the gate starve signals?
  * LATENCY  = median minutes from OR-close to the actual entry     -> HOW FAST does it commit? (the user's ask)

Candidates (all causal / usable at the entry bar):
  none        all-True                       (plain ORB; OR-mid + dir-seq carry direction) = the proposed default
  struct5     st_state(lb=5)==1 / ==2         the OLD strict swing gate (slow: pivots confirm 5 bars late)
  struct3     st_state(lb=3)                  FASTER swing structure
  struct2     st_state(lb=2)                  fastest swing structure
  struct3rlx  st3 != 2 / != 1                 block only the CONFIRMED-opposite trend (middle ground)
  vwap        close>vwap_sess / <             0-lag: side of the session VWAP
  ema9slope   ema9 rising / falling           fast EMA slope
  mom2        close>close[2] / <              2-bar momentum
  vwap+mom    vwap AND mom2                    fast confluence
  bos3        choch/st3 break of last swing   fast break-of-structure

    python research/orb_fast_direction.py NQ QQQ SPY ES
"""
import sys, os, gc
sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "engine"))
import numpy as np, pandas as pd
from numpy.lib.stride_tricks import sliding_window_view
import hs_db, hs_harness as H, hs_backtest as B, hs_validate as V

def reg_slope(c, N):
    """rolling linear-regression slope over the last N closes (the user's 'price array -> direction' read), causal."""
    out = np.full(len(c), np.nan)
    if len(c) >= N:
        win = sliding_window_view(c, N)
        x = np.arange(N) - (N - 1) / 2.0
        out[N - 1:] = (win - win.mean(axis=1, keepdims=True)) @ x / (x ** 2).sum()
    return out

_rng = np.random.default_rng(7)
def ci_lo(r, n=1500):
    return float(np.percentile(_rng.choice(r, size=(n, len(r)), replace=True).mean(axis=1), 5)) if len(r) >= 10 else float("nan")
def yr(tr):
    t = tr.copy(); t["y"] = pd.to_datetime(t["entry_time"], utc=True).dt.tz_convert("America/New_York").dt.year
    g = t.groupby("y")["net_R"].mean(); return int((g > 0).sum()), len(g)
def oos(tr):
    r = tr.sort_values("entry_time")["net_R"].to_numpy(); k = int(len(r) * 0.7)
    return (r[:k].mean(), r[k:].mean()) if (k >= 5 and len(r) - k >= 5) else (float("nan"), float("nan"))
def latency(tr, or_e, tradeday=False):
    et = pd.to_datetime(tr["entry_time"], utc=True).dt.tz_convert("America/New_York")
    mins = (((et.dt.hour - 18) % 24) * 60 + et.dt.minute).to_numpy() if tradeday else (et.dt.hour * 60 + et.dt.minute).to_numpy()
    return float(np.median(mins - or_e))
def line(tag, tr, or_e, tradeday=False):
    r = tr["net_R"].to_numpy()
    if len(r) < 20:
        print(f"  {tag:11} n={len(r):>4}  (too few)"); return
    L = tr.net_R[tr.direction == "long"].to_numpy(); S = tr.net_R[tr.direction == "short"].to_numpy()
    lo = ci_lo(r); p, ny = yr(tr); is_, oo = oos(tr); lat = latency(tr, or_e, tradeday)
    both = len(L) > 5 and L.mean() > 0 and len(S) > 5 and S.mean() > 0
    g = "PASS" if (lo > 0 and both and ny and p >= 0.7 * ny and oo > 0) else "----"
    print(f"  {tag:11} n={len(r):>4} exp {r.mean():+.3f} PF {V.pf(r):>4.2f} win {100*np.mean(r>0):>2.0f}% "
          f"CIlo {lo:+.3f} L{(L.mean() if len(L) else 0):+.2f} S{(S.mean() if len(S) else 0):+.2f} "
          f"yr+{p}/{ny} OOS{is_:+.2f}/{oo:+.2f} lat{lat:+.0f}m {g}")


# session config: (bars_session, tradeday, or_s, or_e, tod_end, eod_min)  — trade-day mins for tradeday sessions
SESS = {
    "rth":    ("rth",  False, 570, 600, 900, 958),   # OR 09:30-10:00 ET, trade to 15:00
    "asia":   ("full", True,   60, 120, 540, 540),   # Tokyo OR 19:00-20:00 ET, flat 03:00 (F22)
    "london": ("full", True,  540, 570, 840, 840),   # London OR 03:00-03:30 ET, flat 08:00 (F29)
}

def run_gate(d, tup, tdn, cfg):
    _, tradeday, or_s, or_e, tod_end, eod = cfg
    d2 = d.copy()
    d2["trend_up"] = tup
    d2["trend_down"] = tdn
    d2.attrs["sym"] = d.attrs.get("sym", "NQ")
    return B.backtest(d2, "tp2_full", "both", False, "orb", 0, 1.0, 4.0, or_s, or_e, 0.0, tod_end, "close",
                      tradeday=tradeday, eod_min=eod, stop_mode="struct", entry_delay=0, chase_atr=1.0,
                      strong_body=0.25, ft_confirm=True, dir_seq=True, or_mid_bias=True)


def main():
    args = [a for a in sys.argv[1:]]
    sess = "rth"
    if "--sess" in args:
        i = args.index("--sess"); sess = args[i + 1]; del args[i:i + 2]
    syms = [s.upper() for s in (args or ["NQ", "QQQ", "SPY", "ES"])]
    cfg = SESS[sess]; bars_sess, tradeday, or_s, or_e, tod_end, eod = cfg
    con = hs_db.connect()
    for sym in syms:
        ext = B._externals(con, hs_db.bars(con, "5m", bars_sess, sym=sym), sym)
        d = H.compute_state(ext, H.P()); d.attrs["sym"] = sym           # lb=5 base (all fields)
        st5 = d["st_state"].to_numpy()
        st3 = H.compute_state(ext, H.P(struct_lb_fix=3))["st_state"].to_numpy()
        st2 = H.compute_state(ext, H.P(struct_lb_fix=2))["st_state"].to_numpy()
        c = d["close"].to_numpy(); vs = d["vwap_sess"].to_numpy(); e9 = d["ema9"].to_numpy()
        c2 = np.concatenate([[np.nan, np.nan], c[:-2]])
        e9p = np.concatenate([[np.nan], e9[:-1]])
        rs6 = reg_slope(c, 6); rs12 = reg_slope(c, 12)         # user's price-array regression-slope reads (30/60 min)
        T = np.ones(len(d), bool)
        gates = {
            "none":       (T, T),
            "struct5":    (st5 == 1, st5 == 2),
            "struct3":    (st3 == 1, st3 == 2),
            "struct2":    (st2 == 1, st2 == 2),
            "struct3rlx": (st3 != 2, st3 != 1),
            "vwap":       (c > vs, c < vs),
            "ema9slope":  (e9 > e9p, e9 < e9p),
            "mom2":       (c > c2, c < c2),
            "regslope6":  (rs6 > 0, rs6 < 0),
            "regslope12": (rs12 > 0, rs12 < 0),
            "rs12+str3":  ((rs12 > 0) & (st3 == 1), (rs12 < 0) & (st3 == 2)),
        }
        print(f"\n{'='*104}\n{sym} {sess.upper()} — FAST-DIRECTION gate sweep (ORB trigger + OR-mid + dir-seq fixed; swap only the trend gate)\n{'='*104}")
        base = None
        for name, (tu, td) in gates.items():
            tr = run_gate(d, tu, td, cfg)
            if name == "none":
                base = tr.copy()
            line(name, tr, or_e, tradeday)
        # ADDITIVITY: what does the OLD slow struct5 gate DROP vs the proposed 'none' default, and were those winners?
        if base is not None and len(base):
            tr5 = run_gate(d, st5 == 1, st5 == 2, cfg)
            key = lambda t: set(zip(pd.to_datetime(t["entry_time"]).astype("int64"), t["direction"]))
            k5 = key(tr5)
            dropped = base[[ (ts, dr) not in k5 for ts, dr in zip(pd.to_datetime(base["entry_time"]).astype("int64"), base["direction"]) ]]
            print(f"  --- struct5 (old slow gate) DROPS {len(dropped)}/{len(base)} of the plain-ORB trades; were they winners? ---")
            line("DROPPED", dropped, or_e, tradeday)
        del d, ext; gc.collect()
    con.close()
    print("\nKEY: 'none' = OR-mid + dir-seq only (fires earliest). A structure gate is only worth keeping if it "
          "RAISES exp/CIlo without pushing latency later or dropping WINNERS. lat = median minutes after OR close.")


if __name__ == "__main__":
    main()
