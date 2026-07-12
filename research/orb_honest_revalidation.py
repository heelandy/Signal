#!/usr/bin/env python3
"""
F58 — HONEST RE-VALIDATION of the gated stack after the F56 fill fix.

F56 found the gated-stack's documented +1-2R edge was largely a STALE-FILL ARTIFACT: execm="stop" fired
the entry only when the LAGGING trend gate (st_state HH/HL + OB) confirmed (~1.8 ATR past the break level),
but the backtest recorded the fill AT the stale break level. The engine now fills gap-aware (worse of
{level, bar open}). This script answers the questions that opens, head-to-head, net of costs, honest fills:

  A. Does the STRUCTURE gate (F20) or STRUCTURE+OB (F41/F45) beat a PLAIN ORB once fills are honest?
  B. Re-tune the VWAP-cap (F16) for honest fills (it was set against inflated entries).
  C. Per-year positivity + 70/30 OOS for the leading configs.
  D. 2x slippage stress (futures NQ/ES).

Common config = exactly what the production STACK trades: execm="stop", struct stop (F25b), skip first
hour (F38, entry_delay=60), capped-TP2 exit (full -> 4R cap on struct stop, the current shipped default).
Only the GATE and the CAP vary. RTH 5m bars (3.5x lighter, same edge).

    python research/orb_honest_revalidation.py [SYM ...]      (default NQ QQQ SPY ES)
"""
import sys, os, gc
sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "engine"))
import numpy as np, pandas as pd
import hs_db, hs_harness as H, hs_backtest as B, hs_validate as V

ORS, ORE, CUT, EOD = 570, 600, 900, 958
T1, T2 = 1.0, 4.0           # capped-TP2: full position to a 4R cap on the struct stop (shipped STACK default)
DELAY = 60                  # F38: skip the first hour after OR close (enter >= 11:00)
CONFIGS = ["pure", "struct", "stackOB"]
CAPS = [99.0, 2.0, 1.7, 1.5, 1.3]    # 99 = no cap


def set_gate(d, cfg):
    """Bake the gate into trend_up/down; OB handled via the engine's prior-bar ob_confluence path."""
    st = d["st_state"].to_numpy()
    if cfg == "pure":
        d["trend_up"] = True;        d["trend_down"] = True;        ob = False
    else:                                   # struct + (optionally) OB
        d["trend_up"] = (st == 1);   d["trend_down"] = (st == 2);   ob = (cfg == "stackOB")
    return ob


def run(d, cfg, vcap=99.0):
    ob = set_gate(d, cfg)
    return B.backtest(d, "tp2_full", "both", False, "orb", 0, T1, T2, ORS, ORE, 0.0, CUT, "stop",
                      eod_min=EOD, vwap_cap=(0.0 if vcap >= 99 else vcap), stop_mode="struct",
                      entry_delay=DELAY, ob_confluence=ob)


def yr_stats(tr):
    """(#years, #years>0, worst-year exp) on net_R."""
    t = tr.copy()
    t["y"] = pd.to_datetime(t["entry_time"], utc=True).dt.tz_convert("America/New_York").dt.year
    g = t.groupby("y")["net_R"].mean()
    return len(g), int((g > 0).sum()), (g.min() if len(g) else float("nan"))


def oos(tr):
    """70/30 chronological split -> (in-sample exp, out-sample exp, n_out)."""
    t = tr.sort_values("entry_time"); r = t["net_R"].to_numpy()
    k = int(len(r) * 0.7)
    if k < 5 or len(r) - k < 5:
        return float("nan"), float("nan"), len(r) - k
    return r[:k].mean(), r[k:].mean(), len(r) - k


def hdr(title):
    print(f"\n{'='*92}\n{title}\n{'='*92}")


def main():
    syms = [s.upper() for s in (sys.argv[1:] or ["NQ", "QQQ", "SPY", "ES"])]
    con = hs_db.connect()
    # ---- A + cap frontier per symbol ----
    leading = {}                                   # sym -> dict of cached trade lists for C/D
    for sym in syms:
        bars = B._externals(con, hs_db.bars(con, "5m", "rth", sym=sym), sym)
        d = H.compute_state(bars, H.P()); d.attrs["sym"] = sym
        del bars; gc.collect()

        hdr(f"{sym} 5m RTH — A) GATE head-to-head (honest gap-aware fill, cap4 exit, struct stop, no VWAP-cap)")
        print(f"  {'config':>8} {'n':>5} {'exp R':>8} {'PF':>5} {'win%':>5} {'net R':>7}  "
              f"{'longExp':>8} {'shrtExp':>8}  {'yrs+':>6} {'OOSout':>7}")
        cache = {}
        for cfg in CONFIGS:
            tr = run(d, cfg); r = tr["net_R"].to_numpy()
            cache[cfg] = tr
            if not len(r):
                print(f"  {cfg:>8}  (no trades)"); continue
            lr = tr.net_R[tr.direction == "long"].to_numpy()
            sr = tr.net_R[tr.direction == "short"].to_numpy()
            ny, npos, _ = yr_stats(tr); _, oo, _ = oos(tr)
            print(f"  {cfg:>8} {len(r):>5} {r.mean():>+8.3f} {V.pf(r):>5.2f} {100*np.mean(r>0):>5.0f} "
                  f"{r.sum():>+7.0f}  {(lr.mean() if len(lr) else float('nan')):>+8.3f} "
                  f"{(sr.mean() if len(sr) else float('nan')):>+8.3f}  {npos}/{ny:<4} {oo:>+7.3f}")

        hdr(f"{sym} 5m RTH — B) VWAP-cap frontier (re-tune for honest fills): pure vs stackOB")
        print(f"  {'cap k':>6} {'pure n':>7} {'pure exp':>9} {'pf':>5}   {'stkOB n':>7} {'stkOB exp':>10} {'pf':>5}")
        for k in CAPS:
            rp = run(d, "pure", k);    rpr = rp["net_R"].to_numpy()
            rs = run(d, "stackOB", k); rsr = rs["net_R"].to_numpy()
            klbl = "none" if k >= 99 else f"{k:.1f}"
            pe = f"{rpr.mean():+.3f}" if len(rpr) else "  -  "
            se = f"{rsr.mean():+.3f}" if len(rsr) else "  -  "
            pp = f"{V.pf(rpr):.2f}" if len(rpr) else " - "
            sp = f"{V.pf(rsr):.2f}" if len(rsr) else " - "
            print(f"  {klbl:>6} {len(rpr):>7} {pe:>9} {pp:>5}   {len(rsr):>7} {se:>10} {sp:>5}")
            del rp, rs; gc.collect()

        leading[sym] = cache
        del d; gc.collect()

    # ---- C) per-year detail + OOS for pure vs stackOB (no cap), all symbols ----
    hdr("C) PER-YEAR + OOS — pure vs stackOB (no cap, cap4 exit)")
    print(f"  {'sym':>4} {'config':>8}  {'yrs+/yrs':>9}  {'worstYr':>8}  {'IS exp':>7}  {'OOS exp':>8}  {'OOS n':>6}")
    for sym in syms:
        for cfg in ("pure", "stackOB"):
            tr = leading[sym][cfg]
            if not len(tr):
                continue
            ny, npos, worst = yr_stats(tr); is_, oo, no = oos(tr)
            print(f"  {sym:>4} {cfg:>8}  {npos:>4}/{ny:<4}  {worst:>+8.3f}  {is_:>+7.3f}  {oo:>+8.3f}  {no:>6}")

    # ---- D) 2x slippage stress (futures) ----
    hdr("D) 2x SLIPPAGE STRESS (futures NQ/ES; slip 2 -> 4 ticks/fill)")
    fut = [s for s in syms if s in ("NQ", "ES", "MNQ", "GC")]
    if fut:
        orig = B.SLIP_MULT
        for slip in (orig, orig * 2):
            B.SLIP_MULT = slip
            print(f"  -- slip = {slip} ticks/fill --")
            for sym in fut:
                bars = B._externals(con, hs_db.bars(con, "5m", "rth", sym=sym), sym)
                d = H.compute_state(bars, H.P()); d.attrs["sym"] = sym
                del bars; gc.collect()
                for cfg in ("pure", "stackOB"):
                    r = run(d, cfg)["net_R"].to_numpy()
                    e = f"{r.mean():+.3f}" if len(r) else "  -  "
                    print(f"     {sym:>4} {cfg:>8}  n={len(r):>4}  exp {e}  PF {V.pf(r):.2f}")
                del d; gc.collect()
        B.SLIP_MULT = orig
    else:
        print("  (no futures in symbol list)")

    con.close()
    print("\nVERDICT KEY: if stackOB exp ~= pure exp, the structure/OB gate adds nothing once fills are honest")
    print("(F56). A config is tradeable only if exp>0 net, yrs+ majority, OOS exp>0, and survives 2x slip.")


if __name__ == "__main__":
    main()
