#!/usr/bin/env python3
"""FILL-MODE head-to-head — the thing that actually moves the needle.
Same validated stack (struct3 + OR-mid + dir-seq + vol-exp 2.4, delay0/chase1/struct-stop/cap4R). Swap ONLY how
the breakout FILLS:
  close   candle CLOSES beyond the level (strong body 0.25 + next-bar follow-through) — fill at that close (honest)
  stop    resting STOP at the level, fills intrabar on the touch (F58) — earlier, but a wick that closes back in counts
  retest  break THEN pull back to the OR edge, fill on the retest (the 'enter near the level' philosophy)
Sessions: RTH + Asia + London (the Asia artifact: close-confirm looked bad there). Report exp gauntlet + n + latency.

    python research/orb_fillmode.py            (RTH NQ QQQ SPY ES)
    python research/orb_fillmode.py --sess asia NQ
"""
import sys, os, gc
sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "engine"))
import numpy as np, pandas as pd
import hs_db, hs_harness as H, hs_backtest as B, hs_validate as V

_rng = np.random.default_rng(7)
def ci_lo(r):
    return float(np.percentile(_rng.choice(r, size=(1500, len(r)), replace=True).mean(axis=1), 5)) if len(r) >= 10 else float("nan")
def yr(tr):
    t = tr.copy(); t["y"] = pd.to_datetime(t["entry_time"], utc=True).dt.tz_convert("America/New_York").dt.year
    g = t.groupby("y")["net_R"].mean(); return int((g > 0).sum()), len(g)
def oos(tr):
    r = tr.sort_values("entry_time")["net_R"].to_numpy(); k = int(len(r) * 0.7)
    return (r[:k].mean(), r[k:].mean()) if (k >= 5 and len(r) - k >= 5) else (float("nan"), float("nan"))
def line(tag, tr):
    if tr is None or len(tr) < 20 or "net_R" not in tr.columns:
        print(f"  {tag:9} n={0 if tr is None or 'net_R' not in getattr(tr,'columns',[]) else len(tr):>4}  (too few)"); return
    r = tr["net_R"].to_numpy(); L = tr.net_R[tr.direction == "long"].to_numpy(); S = tr.net_R[tr.direction == "short"].to_numpy()
    lo = ci_lo(r); p, ny = yr(tr); is_, oo = oos(tr)
    both = len(L) > 5 and L.mean() > 0 and len(S) > 5 and S.mean() > 0
    g = "PASS" if (lo > 0 and both and ny and p >= 0.7 * ny and oo > 0) else "----"
    print(f"  {tag:9} n={len(r):>4} exp {r.mean():+.3f} PF {V.pf(r):>4.2f} win {100*np.mean(r>0):>2.0f}% "
          f"CIlo {lo:+.3f} L{(L.mean() if len(L) else 0):+.2f} S{(S.mean() if len(S) else 0):+.2f} yr+{p}/{ny} OOS{is_:+.2f}/{oo:+.2f} {g}")

SESS = {"rth": ("rth", False, 570, 600, 900, 958), "asia": ("full", True, 60, 120, 540, 540),
        "london": ("full", True, 540, 570, 840, 840)}

def run(d, cfg, execm, strong, ft):
    _, td, or_s, or_e, tod_end, eod = cfg
    d2 = d.copy(); st3 = d2["_st3"].to_numpy(); d2["trend_up"] = st3 == 1; d2["trend_down"] = st3 == 2
    d2.attrs["sym"] = d.attrs.get("sym", "NQ")
    return B.backtest(d2, "tp2_full", "both", False, "orb", 0, 1.0, 4.0, or_s, or_e, 0.0, tod_end, execm,
                      tradeday=td, eod_min=eod, stop_mode="struct", entry_delay=0, chase_atr=1.0,
                      strong_body=strong, ft_confirm=ft, dir_seq=True, or_mid_bias=True, min_or_width=2.4)

def main():
    args = [a for a in sys.argv[1:]]; sess = "rth"
    if "--sess" in args:
        i = args.index("--sess"); sess = args[i + 1]; del args[i:i + 2]
    syms = [s.upper() for s in (args or ["NQ", "QQQ", "SPY", "ES"])]
    cfg = SESS[sess]; con = hs_db.connect()
    for sym in syms:
        ext = B._externals(con, hs_db.bars(con, "5m", cfg[0], sym=sym), sym)
        d = H.compute_state(ext, H.P()); d.attrs["sym"] = sym
        d["_st3"] = H.compute_state(ext, H.P(struct_lb_fix=3))["st_state"].to_numpy()
        print(f"\n{'='*96}\n{sym} {sess.upper()} — FILL MODE (same stack; swap only how the breakout fills)\n{'='*96}")
        line("close", run(d, cfg, "close", 0.25, True))
        line("stop", run(d, cfg, "stop", 0.0, False))
        line("retest", run(d, cfg, "retest", 0.0, False))
        del d, ext; gc.collect()
    con.close()
    print("\nKEY: 'close' = honest close-confirm (STACK default). 'stop' = resting-stop touch (earlier, less honest). "
          "'retest' = enter on the pullback. Winner by exp+CIlo+gauntlet, per session.")

if __name__ == "__main__":
    main()
