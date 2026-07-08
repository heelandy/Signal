#!/usr/bin/env python3
"""
VERIFY the HIGHSTRIKE_ORB_MTF_ENTRIES.pine dashboard against the backtest engine.

The Pine dashboard surfaces three entries; this re-runs the engine in EXACTLY the
configs it plots and checks each clears the edge gate (both sides >0 AND lower 90% CI >0):
  5m  STOP   -> execm=stop,   buffer 0.00 ATR   (production entry; F9/F10)
  15m RETEST -> execm=retest, buffer 0.25 ATR   (F8: retest beats stop on 15m)
  15m STOP   -> execm=stop,   buffer 0.25 ATR   (the F8 comparison baseline)
Plus the F16 VWAP-extension cap (k=2.0) on the live entries, since the dashboard
literally grades each entry NEAR/EXT by VWAP extension.

Pine-mirrored params: OR 0930-1000, cutoff 15:00 (tod_end=900), TP1=1R/TP2=4R,
scale_be, EOD-flat 15:58. Validate on NQ + QQQ (NDX proxies).

    python research/verify_mtf_entries.py
"""
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "engine"))
import numpy as np
import hs_db, hs_harness as H, hs_backtest as B, hs_validate as V

rng = np.random.default_rng(7)

# Pine-mirrored production params
ORS, ORE, CUT, T1, T2, EOD = 570, 600, 900, 1.0, 4.0, 958


def metrics(tr):
    r = tr["net_R"].to_numpy()
    lo = np.percentile(rng.choice(r, (3000, len(r)), replace=True).mean(1), 5) if len(r) else 0.0
    L = tr[tr.direction == "long"]["net_R"].to_numpy()
    S = tr[tr.direction == "short"]["net_R"].to_numpy()
    return dict(n=len(tr), exp=r.mean() if len(r) else 0, pf=V.pf(r),
                win=100 * np.mean(r > 0) if len(r) else 0, maxdd=V.maxdd(r) if len(r) else 0,
                loCI=lo, Lexp=L.mean() if len(L) else 0, Sexp=S.mean() if len(S) else 0,
                Ln=len(L), Sn=len(S),
                both=(len(L) > 5 and L.mean() > 0 and len(S) > 5 and S.mean() > 0))


def run(d, brk, execm, vwap_cap=0.0):
    # backtest(d, mode, side, strict, entry_type, mtf_min, tp1, tp2, or_s, or_e, brk, tod_end, execm, ... vwap_cap)
    tr = B.backtest(d, "scale_be", "both", False, "orb", 0, T1, T2, ORS, ORE, brk, CUT, execm,
                    eod_min=EOD, vwap_cap=vwap_cap)
    return metrics(tr)


def line(tag, m):
    gate = "PASS" if (m["both"] and m["loCI"] > 0) else "FAIL"
    print(f"{tag:22} {m['n']:>5} {m['exp']:>+7.3f} {m['pf']:>5.2f} {m['win']:>5.1f} "
          f"{m['maxdd']:>7.1f} {m['loCI']:>+7.3f} {m['Lexp']:>+6.2f}({m['Ln']:>4}) "
          f"{m['Sexp']:>+6.2f}({m['Sn']:>4})  {gate}")


def main():
    syms = [s.upper() for s in (sys.argv[1:] or ["NQ", "QQQ"])]
    con = hs_db.connect()
    hdr = (f"{'entry':22} {'n':>5} {'exp':>7} {'PF':>5} {'win%':>5} {'maxDD':>7} {'loCI':>7} "
           f"{'long(n)':>12} {'short(n)':>12}  gate")
    for sym in syms:
        states = {}
        for tf in ("5m", "15m"):
            bars = B._externals(con, hs_db.bars(con, tf, "full", sym=sym), sym)
            d = H.compute_state(bars, H.P()); d.attrs["sym"] = sym
            states[tf] = d
            print(f"[{sym} {tf}] state computed over {len(bars):,} bars")
        d5, d15 = states["5m"], states["15m"]
        print(f"\n===== {sym}  (Pine: OR 0930-1000, cutoff 15:00, 1R/4R scale_be, EOD-flat) =====")
        print(hdr); print("-" * len(hdr))
        line("5m  STOP  (prod)",        run(d5,  0.00, "stop"))
        line("5m  STOP  +F16cap(k2)",   run(d5,  0.00, "stop",   vwap_cap=2.0))
        line("15m STOP  (F8 base)",     run(d15, 0.25, "stop"))
        line("15m RETEST(dash)",        run(d15, 0.25, "retest"))
        line("15m RETEST+F16cap(k2)",   run(d15, 0.25, "retest", vwap_cap=2.0))
        print()
    con.close()


if __name__ == "__main__":
    main()
