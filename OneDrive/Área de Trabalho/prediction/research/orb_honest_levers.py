#!/usr/bin/env python3
"""
F58 (part 2) — honest re-check of the levers HELD CONSTANT in orb_honest_revalidation.py.

That test proved the GATE (F20/F41) and the VWAP-CAP (F16) don't earn their keep with honest fills. But it
held three other production levers fixed — and each was originally tuned against the SAME inflated fills:
  - skip-first-hour TIME GATE (F38, entry_delay=60)
  - struct vs OR STOP (F25b, stop_mode)
  - capped-TP2 EXIT (F34b)
This re-checks each as a one-lever sweep on the honest PLAIN ORB core (no gate, no cap), NQ/QQQ/SPY (ES is dead).
Baseline = delay 60, stop struct, exit cap4. Reports exp(net), PF, n, bootstrap 90% CIlo (the WIN gate).

    python research/orb_honest_levers.py [SYM ...]      (default NQ QQQ SPY)
"""
import sys, os, gc
sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "engine"))
import numpy as np, pandas as pd
import hs_db, hs_harness as H, hs_backtest as B, hs_validate as V

ORS, ORE, CUT, EOD, T1 = 570, 600, 900, 958, 1.0
_rng = np.random.default_rng(7)


def cilo(r, n=4000):
    if len(r) < 10:
        return float("nan")
    return float(np.percentile(_rng.choice(r, size=(n, len(r)), replace=True).mean(axis=1), 5))


def run(d, delay=60, stop="struct", exit_mode="tp2_full", t2=4.0):
    """PLAIN ORB (no direction gate, no cap), production economics. Only the swept lever changes."""
    d["trend_up"] = True; d["trend_down"] = True
    return B.backtest(d, exit_mode, "both", False, "orb", 0, T1, t2, ORS, ORE, 0.0, CUT, "stop",
                      eod_min=EOD, vwap_cap=0.0, stop_mode=stop, entry_delay=delay, ob_confluence=False)


def line(lbl, r):
    if not len(r):
        print(f"    {lbl:>16}  (no trades)"); return
    print(f"    {lbl:>16}  n={len(r):>5}  exp {r.mean():>+7.3f}R  PF {V.pf(r):>4.2f}  "
          f"win {100*np.mean(r>0):>4.0f}%  CIlo {cilo(r):>+7.3f}")


def hdr(t):
    print(f"\n{'='*84}\n{t}\n{'='*84}")


def main():
    syms = [s.upper() for s in (sys.argv[1:] or ["NQ", "QQQ", "SPY"])]
    con = hs_db.connect()
    for sym in syms:
        bars = B._externals(con, hs_db.bars(con, "5m", "rth", sym=sym), sym)
        d = H.compute_state(bars, H.P()); d.attrs["sym"] = sym
        del bars; gc.collect()

        hdr(f"{sym} 5m RTH — honest PLAIN-ORB lever re-check (baseline: delay60 / struct / cap4)")

        print("  A) TIME GATE (skip first hour after OR) — stop struct, exit cap4:")
        for dly in (0, 30, 60, 90):
            line(f"delay={dly}m", run(d, delay=dly)["net_R"].to_numpy())

        print("  B) STOP anchor — delay 60, exit cap4:")
        for stop in ("or", "struct"):
            line(f"stop={stop}", run(d, stop=stop)["net_R"].to_numpy())

        print("  C) EXIT mode — delay 60, stop struct:")
        line("cap4 (tp2_full)", run(d, exit_mode="tp2_full", t2=4.0)["net_R"].to_numpy())
        line("scale_be 4R", run(d, exit_mode="scale_be", t2=4.0)["net_R"].to_numpy())
        line("tp2_full 2R", run(d, exit_mode="tp2_full", t2=2.0)["net_R"].to_numpy())
        line("trail", run(d, exit_mode="trail")["net_R"].to_numpy())

        del d; gc.collect()
    con.close()
    print("\nCIlo = bootstrap 5th-pct expectancy (WIN gate = CIlo>0). One-lever sweeps; others at baseline.")


if __name__ == "__main__":
    main()
