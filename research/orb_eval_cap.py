#!/usr/bin/env python3
"""
F34c — eval-path pass/blow-up on the GRADUATED cap-4R config (struct stop + 4R target, full position)
vs the current trail and the old eval-sim baseline (scale_be). Adopted-F31f macro frame, combined
NQ account, F26 profiles. Confirms the funded-eval numbers hold on the config we'd make default.

    python research/orb_eval_cap.py
"""
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "engine"))
import numpy as np, pandas as pd
import hs_db, hs_harness as H, hs_backtest as B
from orb_optimize import state
from orb_prop_eval import eval_path

# session, OR start/end, cut, tradeday, eod, unblock-B (F31f)
SESSIONS = [("RTH", 570, 600, 900, False, 958, True),
            ("Asia", 60, 120, 540, True, 540, True),
            ("London", 540, 570, 840, True, 840, False)]
PROFILES = [(9, 6, 4), (15, 10, 6), (30, 12, 8)]


def run(d, ors, ore, cut, tdy, eod, mode, cap=4.0):
    st = d["st_state"].to_numpy(); d["trend_up"] = st == 1; d["trend_down"] = st == 2
    return B.backtest(d, mode, "both", False, "orb", 0, 1.0, cap, ors, ore, 0.0, cut, "stop",
                      tradeday=tdy, eod_min=eod, vwap_cap=2.0, stop_mode="struct")


def sim(name, tr):
    t = tr.sort_values("entry_time").reset_index(drop=True)
    r = t["net_R"].to_numpy()
    dt = pd.to_datetime(t["entry_time"], utc=True).dt.tz_convert("America/New_York").dt.normalize().to_numpy()
    print(f"  {name}  (n={len(r)}, med ${np.median(r)*250:+.0f}/trade @ $250R)")
    for target, trail, daily in PROFILES:
        P = Bl = tot = 0
        for s in range(0, max(len(r) - 10, 1)):
            passed, blew, _ = eval_path(r[s:], dt[s:], target, trail, daily, 200)
            tot += 1; P += passed; Bl += blew
        print(f"    +{target}/-{trail}/-{daily}R: PASS {100*P/tot:4.0f}%  BLOW-UP {100*Bl/tot:4.0f}%")


def main():
    d0 = state("NQ", "5m")
    unb = d0["macro_allow_trades"].to_numpy() | (d0["macro_regime"] == "B").to_numpy()
    cat = lambda xs: pd.concat(xs).sort_values("entry_time").reset_index(drop=True)
    print("F34c — eval path on cap-4R vs trail vs scale_be (combined NQ, adopted F31f frame)\n")
    for label, mode, cap in (("cap-4R (candidate)", "tp2_full", 4.0),
                             ("trail (current prod)", "trail", 4.0),
                             ("scale_be (old eval baseline)", "scale_be", 4.0)):
        streams = []
        for name, ors, ore, cut, tdy, eod, unbB in SESSIONS:
            d = d0.copy(deep=False)
            if unbB:
                d["macro_allow_trades"] = unb
            d.attrs.update(d0.attrs)
            streams.append(run(d, ors, ore, cut, tdy, eod, mode, cap))
        sim(label, cat(streams))
        print()


if __name__ == "__main__":
    main()
