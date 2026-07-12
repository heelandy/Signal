#!/usr/bin/env python3
"""
F33b — RANGE-block decision on the EVAL-CANONICAL config (struct gate + OR stop + scale_be +
VWAP cap), i.e. exactly what orb_prop_eval.stack() validated and what F31d/e/f passed on.
This avoids the R-inflation of the struct-stop+trail combo (F33-debug: that config prints
PF 17 / +3.6R because a sub-ATR struct-stop denominator × an uncapped trail explodes the
R-multiple — a measurement artifact, not a tradeable edge; see notes).

Per session (adopted F31f macro frame): prod (RANGE blocked) vs the lr=2 RANGE slice (gate forced
open, sliced by TRUE local_regime at entry) with IS/OOS + 2x slip + per-year. Then the eval-path
pass/blow-up for prod vs unblock-RANGE on the combined account.

    python research/orb_range_eval.py
"""
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "engine"))
import numpy as np, pandas as pd
import hs_db, hs_harness as H, hs_backtest as B, hs_validate as V
from orb_optimize import state
from orb_prop_eval import eval_path

rng = np.random.default_rng(7)
KCAP = 2.0
# session, OR start, OR end, cut, tradeday, eod, unblock-B (F31f: RTH/Asia yes, London no)
SESSIONS = [
    ("RTH",    570, 600, 900, False, 958, True),
    ("Asia",   60,  120, 540, True,  540, True),
    ("London", 540, 570, 840, True,  840, False),
]


def run(d, ors, ore, cut, tdy, eod):
    # EVAL-CANONICAL: scale_be exit + OR stop (matches orb_prop_eval.stack())
    return B.backtest(d, "scale_be", "both", False, "orb", 0, 1.0, 4.0, ors, ore, 0.0, cut, "stop",
                      tradeday=tdy, eod_min=eod, vwap_cap=KCAP)


def loci(r):
    return np.percentile(rng.choice(r, (3000, len(r)), replace=True).mean(1), 5) if len(r) else 0.0


def grade(tr, min_n=25):
    if tr is None or len(tr) < min_n:
        return None
    r = tr["net_R"].to_numpy()
    L = tr[tr.direction == "long"]["net_R"].to_numpy(); S = tr[tr.direction == "short"]["net_R"].to_numpy()
    both = len(L) > 5 and L.mean() > 0 and len(S) > 5 and S.mean() > 0
    lo = loci(r)
    t = tr.copy(); t["year"] = pd.to_datetime(t["entry_time"], utc=True).dt.tz_convert("America/New_York").dt.year
    yrs = [(int(y), g["net_R"].mean()) for y, g in t.groupby("year") if len(g) >= 8]
    pos = sum(1 for _, e in yrs if e > 0); tot = len(yrs)
    g = "PASS" if (both and lo > 0 and tot and pos >= 0.7 * tot) else "----"
    return dict(n=len(r), exp=r.mean(), pf=V.pf(r), win=100*np.mean(r > 0), ci=lo,
                Le=L.mean() if len(L) else 0, Ln=len(L), Se=S.mean() if len(S) else 0, Sn=len(S),
                pos=pos, tot=tot, g=g)


def show(tag, tr, min_n=25):
    m = grade(tr, min_n)
    if m is None:
        print(f"    {tag:24} n={0 if tr is None else len(tr):>4}  (<{min_n})"); return
    print(f"    {tag:24} n={m['n']:>4} exp {m['exp']:+.3f} PF {m['pf']:>4.2f} win {m['win']:>2.0f}% "
          f"CI {m['ci']:+.3f}  L {m['Le']:+.2f}({m['Ln']}) S {m['Se']:+.2f}({m['Sn']})  yrs +{m['pos']}/{m['tot']}  {m['g']}")


def main():
    d0 = state("NQ", "5m")
    st = d0["st_state"].to_numpy(); d0["trend_up"] = st == 1; d0["trend_down"] = st == 2
    true_lr = pd.Series(d0["local_regime"].to_numpy().copy(), index=pd.to_datetime(d0["ts"], utc=True))
    unb = d0["macro_allow_trades"].to_numpy() | (d0["macro_regime"] == "B").to_numpy()
    print(f"NQ 5m — F33b RANGE decision on the EVAL-CANONICAL config (scale_be + OR stop + struct gate + cap).\n")
    blocked_streams, unblock_streams = {}, {}
    for name, ors, ore, cut, tdy, eod, unbB in SESSIONS:
        base = d0.copy(deep=False)
        if unbB:
            base["macro_allow_trades"] = unb
        base.attrs.update(d0.attrs)
        dopen = base.copy(deep=False); dopen["local_regime"] = 1; dopen.attrs.update(d0.attrs)
        print(f"\n  {name}")
        tr_blocked = run(base, ors, ore, cut, tdy, eod)
        tro = run(dopen, ors, ore, cut, tdy, eod)
        lr = true_lr.reindex(pd.to_datetime(tro["entry_time"], utc=True)).to_numpy()
        trR = tro[lr == 2]
        show("prod (RANGE blocked)", tr_blocked)
        show("lr=2 RANGE slice", trR)
        if len(trR) >= 25:
            yr = pd.to_datetime(trR["entry_time"], utc=True).dt.tz_convert("America/New_York").dt.year.to_numpy()
            show("RANGE IS 2010-21", trR[yr <= 2021])
            show("RANGE OOS 2022+", trR[yr >= 2022], min_n=15)
        B.SLIP_MULT = 2.0
        tro2 = run(dopen, ors, ore, cut, tdy, eod)
        lr2 = true_lr.reindex(pd.to_datetime(tro2["entry_time"], utc=True)).to_numpy()
        show("RANGE @ 2x slip", tro2[lr2 == 2])
        B.SLIP_MULT = 1.0
        blocked_streams[name] = tr_blocked
        unblock_streams[name] = tro

    # eval-path pass/blow-up, combined account
    cat = lambda streams: pd.concat(streams.values()).sort_values("entry_time").reset_index(drop=True)
    print("\n  EVAL PATH (combined account, rolling start, F26 profiles):")
    for lbl, streams in (("prod (RANGE blocked)", blocked_streams), ("unblock RANGE", unblock_streams)):
        tr = cat(streams)
        r = tr["net_R"].to_numpy()
        dt = pd.to_datetime(tr["entry_time"], utc=True).dt.tz_convert("America/New_York").dt.normalize().to_numpy()
        print(f"    {lbl}  (n={len(r)})")
        for target, trail, daily in [(9, 6, 4), (15, 10, 6), (30, 12, 8)]:
            P = Bl = tot = 0
            for s in range(0, max(len(r) - 10, 1)):
                passed, blew, _ = eval_path(r[s:], dt[s:], target, trail, daily, 200)
                tot += 1; P += passed; Bl += blew
            print(f"      +{target}/-{trail}/-{daily}R: PASS {100*P/tot:4.0f}%  BLOW-UP {100*Bl/tot:4.0f}%")


if __name__ == "__main__":
    main()
