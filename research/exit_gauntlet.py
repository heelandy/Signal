"""EXIT GAUNTLET (F93, user 2026-07-10: "run the full gauntlet, if pass wire the per-asset exit").
Candidate: FUTURES scale 50% at TP1=1.5R + stop-to-BE (F27 rerun's winner) vs the current booking
convention full-to-TP2 4R. Seven checks, candidate vs default, per futures symbol:
  1 min_trades>=100 · 2 full-sample exp > default · 3 OOS(30%) exp > 0 AND >= default ·
  4 survives 2x slippage (exp > 0) · 5 years positive >= 70% or >= default ·
  6 both sides positive · 7 max drawdown not worse than 1.25x default.
Equities are NOT candidates (BE protection measured to COST ~0.13R/trade there — full-to-TP2 kept).

    python research/exit_gauntlet.py [SYM ...]      (default NQ ES)
"""
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "engine"))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import numpy as np, pandas as pd
import hs_backtest as B
from orb_optimize import state

CAND = ("scale_be", 1.5, 4.0, 0.5)     # mode, tp1_r, tp2_r, scale_frac
DFLT = ("tp2_full", 1.5, 4.0, 0.5)     # the tracker's booking convention (full ride to 4R)


def setgate(d):
    st = d["st_state"].to_numpy(); d["trend_up"] = st == 1; d["trend_down"] = st == 2


def run(d, cfg):
    mode, tp1, tp2, sf = cfg
    return B.backtest(d, mode, "both", False, "orb", 0, tp1, tp2, 570, 600, 0.0, 900, "stop",
                      eod_min=958, vwap_cap=2.0, scale_frac=sf)


def profile(tr):
    """Engine trades = a DataFrame with net_R / direction / entry_time."""
    if tr is None or not len(tr):
        return None
    rs = tr["net_R"].to_numpy(float)
    cut = int(len(rs) * 0.7)
    oos = rs[cut:]
    cum = np.cumsum(rs)
    dd = float((cum - np.maximum.accumulate(cum)).min())
    ys = tr.groupby(pd.to_datetime(tr["entry_time"]).dt.year)["net_R"].sum()
    L = tr[tr["direction"] == "long"]["net_R"]
    S = tr[tr["direction"] == "short"]["net_R"]
    return {"n": len(rs), "exp": float(rs.mean()), "oos": float(oos.mean()) if len(oos) else float("nan"),
            "dd": dd, "yrs_pos": int((ys > 0).sum()), "yrs": len(ys),
            "sides_pos": bool(len(L) >= 10 and L.mean() > 0 and len(S) >= 10 and S.mean() > 0),
            "win": float((rs > 0).mean() * 100)}


def gauntlet(sym):
    d = state(sym, "5m"); setgate(d)
    pc = profile(run(d, CAND)); pd_ = profile(run(d, DFLT))
    # 2x slippage stress on the candidate
    base_slip = B.SLIP_TICKS
    B.SLIP_TICKS = base_slip * 2
    ps = profile(run(d, CAND))
    B.SLIP_TICKS = base_slip
    if pc is None or pd_ is None:
        print(f"{sym}: not enough data"); return False
    checks = {
        "min_trades": pc["n"] >= 100,
        "exp_beats_default": pc["exp"] > pd_["exp"],
        "oos_positive_and_ge_default": pc["oos"] > 0 and pc["oos"] >= pd_["oos"] - 1e-9,
        "slip_2x_survives": ps is not None and ps["exp"] > 0,
        "years_consistent": pc["yrs_pos"] >= max(int(0.7 * pc["yrs"]), pd_["yrs_pos"] - 1),
        "both_sides_positive": pc["sides_pos"],
        "dd_not_worse": pc["dd"] >= pd_["dd"] * 1.25,       # dd is negative: >= means shallower/comparable
    }
    verdict = all(checks.values())
    print(f"\n### {sym} — candidate scale_be@1.5R/50%+BE vs default full-to-TP2 4R")
    print(f"  candidate: n={pc['n']} exp {pc['exp']:+.3f} win {pc['win']:.0f}% OOS {pc['oos']:+.3f} "
          f"DD {pc['dd']:+.0f} yrs+ {pc['yrs_pos']}/{pc['yrs']}")
    print(f"  default:   n={pd_['n']} exp {pd_['exp']:+.3f} win {pd_['win']:.0f}% OOS {pd_['oos']:+.3f} "
          f"DD {pd_['dd']:+.0f} yrs+ {pd_['yrs_pos']}/{pd_['yrs']}")
    print(f"  cand @2x slip: exp {ps['exp']:+.3f}" if ps else "  cand @2x slip: n/a")
    for k, v in checks.items():
        print(f"  {'PASS' if v else 'FAIL'}  {k}")
    print(f"  VERDICT: {'ADOPT_CANDIDATE' if verdict else 'KEEP_DEFAULT'}")
    return verdict


def main():
    syms = [s.upper() for s in (sys.argv[1:] or ["NQ", "ES"])]
    results = {s: gauntlet(s) for s in syms}
    print("\n==== EXIT GAUNTLET SUMMARY ====")
    for s, ok in results.items():
        print(f"  {s}: {'ADOPT_CANDIDATE' if ok else 'KEEP_DEFAULT'}")


if __name__ == "__main__":
    main()
