#!/usr/bin/env python3
"""
F62 — FOUR-FAMILY HEAD-TO-HEAD on NQ/QQQ/SPY (5m RTH), one honest gauntlet, under the corrected
(gap-aware) fills. Consolidates the scattered prior findings into one comparison.

Families (one clean representative each):
  1. TREND / MOMENTUM      — ORB with the HH/HL structure trend gate (st_state) + close-confirm + F61 dir-seq
  2. BREAKOUT / VOL-EXPAND  — plain ORB (no trend gate) = the F58 validated default
  3. MEAN-REVERSION / FADE  — range-day VWAP fade on chop (local_regime==2)  [reuses strat_rangefade]
  4. STRUCTURE / ORDER-FLOW — SMC: ORB fired at an order block (F41 OB confluence) + a liquidity-sweep
                              variant (execm="sweepgo": sweep the opposite edge, then break this one)
Common exit = capped-TP2 4R on the structure stop, skip-first-hour, EOD-flat. Gauntlet per family/sym:
exp net R>0, bootstrap CIlo>0, PF, both sides>0, >=70% yrs+, 70/30 OOS-out>0.

OPTIONS: any family that passes on QQQ/SPY maps to 0DTE naked/debit/credit via bot/options
(naked call/put, debit @ TP1, credit @ structure stop). NQ/MNQ = futures or NQ options.

    python research/strat_four_families.py [SYM ...]      (default NQ QQQ SPY)
"""
import sys, os, gc
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "engine"))
import numpy as np, pandas as pd
import hs_db, hs_harness as H, hs_backtest as B, hs_validate as V
from strat_rangefade import fade            # family 3 (F53)

rng = np.random.default_rng(7)
ORS, ORE, CUT, EOD = 570, 600, 900, 958
T1, T2, DELAY, SB = 1.0, 4.0, 60, 0.25


def run_engine(d, gate="none", execm="close", ob=False):
    st = d["st_state"].to_numpy()
    if gate == "trend":
        d["trend_up"] = (st == 1); d["trend_down"] = (st == 2)
    else:
        d["trend_up"] = True; d["trend_down"] = True
    cl = execm == "close"
    return B.backtest(d, "tp2_full", "both", False, "orb", 0, T1, T2, ORS, ORE, 0.0, CUT, execm,
                      eod_min=EOD, stop_mode="struct", entry_delay=DELAY,
                      strong_body=(SB if cl else 0.0), ft_confirm=cl, dir_seq=cl, ob_confluence=ob)


def _norm(obj):
    """-> (dt[ns,ET], dir(+/-1), R) from an engine trades df OR a rangefade list."""
    if isinstance(obj, pd.DataFrame):
        if not len(obj):
            return pd.DataFrame(columns=["dt", "dir", "R"])
        dt = pd.to_datetime(obj["entry_time"], utc=True).dt.tz_convert("America/New_York")
        dd = np.where(obj["direction"].to_numpy() == "long", 1, -1)
        return pd.DataFrame({"dt": dt.to_numpy(), "dir": dd, "R": obj["net_R"].to_numpy()})
    return pd.DataFrame(obj, columns=["dt", "dir", "R"])


def gauntlet(tag, obj):
    df = _norm(obj)
    if len(df) < 30:
        print(f"  {tag:22} n={len(df):>4} (<30, skip)"); return
    r = df["R"].to_numpy(); df["year"] = pd.to_datetime(df["dt"]).dt.year
    yrs = [(y, g["R"].mean()) for y, g in df.groupby("year") if len(g) >= 8]
    pos = sum(1 for _, e in yrs if e > 0); tot = len(yrs); neg = [int(y) for y, e in yrs if e <= 0]
    df = df.sort_values("dt"); k = int(len(df) * 0.7); OUT = df.iloc[k:]["R"].mean()
    L, S = df[df.dir == 1]["R"], df[df.dir == -1]["R"]
    both = len(L) > 5 and L.mean() > 0 and len(S) > 5 and S.mean() > 0
    ci = np.percentile(rng.choice(r, (2000, len(r)), replace=True).mean(1), 5)
    g = "PASS" if (r.mean() > 0 and ci > 0 and tot and pos >= 0.7 * tot and OUT > 0 and both) else "fail"
    print(f"  {tag:22} n={len(r):>4} expR {r.mean():+.3f} PF {V.pf(r):>4.2f} win {100*np.mean(r>0):>2.0f}% "
          f"CI {ci:+.3f} both={'Y' if both else 'n'} yr+{pos}/{tot} OOS {OUT:+.3f} {g}{'  NEG'+str(neg) if neg else ''}")


def main():
    syms = [s.upper() for s in (sys.argv[1:] or ["NQ", "QQQ", "SPY"])]
    con = hs_db.connect()
    for sym in syms:
        bars = B._externals(con, hs_db.bars(con, "5m", "rth", sym=sym), sym)
        d = H.compute_state(bars, H.P()); d.attrs["sym"] = sym; del bars; gc.collect()
        print(f"\n######## {sym} 5m RTH — four-family gauntlet ########")
        gauntlet("1 trend/momentum", run_engine(d, "trend", "close"))
        gauntlet("2 breakout/vol-exp", run_engine(d, "none", "close"))
        gauntlet("3 mean-rev/fade", fade(d, k=1.5, m=1.5))
        gauntlet("4 smc/order-block", run_engine(d, "trend", "close", ob=True))
        gauntlet("4b smc/liq-sweep", run_engine(d, "none", "sweepgo"))
        del d; gc.collect()
    con.close()
    print("\nPASS = exp net R>0 AND CIlo>0 AND both sides>0 AND >=70% yrs+ AND OOS-out>0.")
    print("Options: passing QQQ/SPY families -> 0DTE naked/debit/credit via bot/options.")


if __name__ == "__main__":
    main()
