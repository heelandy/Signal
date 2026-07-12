#!/usr/bin/env python3
"""
HIGHSTRIKE F33 — is there edge in the trades the local RANGE block discards? (F31 treatment
for the LOCAL regime filter: local_regime==2 = ADX<20 chop days, blocked in every validated run.)
NQ 5m, adopted stack (struct gate + VWAP cap + struct stop + 2ATR trail), baseline context =
the ADOPTED F31f config (regime B unblocked for RTH/Asia, blocked for London).

Per session: production reference, then RANGE gate forced OPEN and trades sliced by the TRUE
local regime at entry (1=trend, 2=range, 3=volatile). The lr==2 slice gets the standard gate
(both sides>0, CI>0, >=70% yrs) + IS/OOS split + 2x slip. Plus the full "unblock RANGE" config.

    python research/orb_range_block.py
"""
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "engine"))
import numpy as np, pandas as pd
import hs_db, hs_harness as H, hs_backtest as B, hs_validate as V
from orb_optimize import state

rng = np.random.default_rng(7)
KCAP = 2.0
SESSIONS = [
    ("RTH",    570, 600, 900, False, 958, True),    # last flag: unblock B (F31f adopted)
    ("Asia",   60,  120, 540, True,  540, True),
    ("London", 540, 570, 840, True,  840, False),   # London keeps the B block
]


def run(d, ors, ore, cut, tdy, eod):
    return B.backtest(d, "trail", "both", False, "orb", 0, 1.0, 4.0, ors, ore, 0.0, cut, "stop",
                      tradeday=tdy, eod_min=eod, vwap_cap=KCAP, stop_mode="struct")


def loci(r):
    return np.percentile(rng.choice(r, (3000, len(r)), replace=True).mean(1), 5) if len(r) else 0.0


def report(tag, tr, min_n=25):
    if tr is None or len(tr) < min_n:
        print(f"    {tag:26} n={0 if tr is None else len(tr):>4}  (<{min_n} — no read)")
        return
    r = tr["net_R"].to_numpy()
    L = tr[tr.direction == "long"]["net_R"].to_numpy()
    S = tr[tr.direction == "short"]["net_R"].to_numpy()
    both = len(L) > 5 and L.mean() > 0 and len(S) > 5 and S.mean() > 0
    lo = loci(r)
    t = tr.copy()
    t["year"] = pd.to_datetime(t["entry_time"], utc=True).dt.tz_convert("America/New_York").dt.year
    yrs = [(int(y), g["net_R"].mean()) for y, g in t.groupby("year") if len(g) >= 8]
    pos = sum(1 for _, e in yrs if e > 0); tot = len(yrs)
    g = "PASS" if (both and lo > 0 and tot and pos >= 0.7 * tot) else "----"
    print(f"    {tag:26} n={len(r):>4} exp {r.mean():+.3f} PF {V.pf(r):>4.2f} win {100*np.mean(r>0):>2.0f}% "
          f"CI {lo:+.3f}  L {L.mean() if len(L) else 0:+.2f}({len(L)}) S {S.mean() if len(S) else 0:+.2f}({len(S)})  "
          f"yrs +{pos}/{tot}  {g}")


def main():
    d0 = state("NQ", "5m")
    _gate_st = d0["st_state"].to_numpy()
    d0["trend_up"] = _gate_st == 1
    d0["trend_down"] = _gate_st == 2
    true_lr = pd.Series(d0["local_regime"].to_numpy().copy(), index=pd.to_datetime(d0["ts"], utc=True))
    unb = d0["macro_allow_trades"].to_numpy() | (d0["macro_regime"] == "B").to_numpy()
    print(f"NQ 5m — {len(d0):,} bars. F33: RANGE-block slice (baseline = adopted F31f macro config).\n")
    for name, ors, ore, cut, tdy, eod, unbB in SESSIONS:
        base = d0.copy(deep=False)
        if unbB:
            base["macro_allow_trades"] = unb
        base.attrs.update(d0.attrs)
        dopen = base.copy(deep=False)
        dopen["local_regime"] = 1                     # force the local gate open (engine blocks lr==2)
        dopen.attrs.update(d0.attrs)
        print(f"\n  {name}")
        report("prod (RANGE blocked)", run(base, ors, ore, cut, tdy, eod))
        tro = run(dopen, ors, ore, cut, tdy, eod)
        lr = true_lr.reindex(pd.to_datetime(tro["entry_time"], utc=True)).to_numpy()
        for v, lbl in ((1, "lr=1 TREND slice"), (2, "lr=2 RANGE slice"), (3, "lr=3 VOLATILE slice")):
            report(lbl, tro[lr == v])
        trR = tro[lr == 2]
        if len(trR) >= 25:
            yr = pd.to_datetime(trR["entry_time"], utc=True).dt.tz_convert("America/New_York").dt.year.to_numpy()
            report("RANGE — IS 2010-21", trR[yr <= 2021])
            report("RANGE — OOS 2022+", trR[yr >= 2022], min_n=20)
        report("unblock RANGE (full)", tro)
        B.SLIP_MULT = 2.0
        tro2 = run(dopen, ors, ore, cut, tdy, eod)
        lr2 = true_lr.reindex(pd.to_datetime(tro2["entry_time"], utc=True)).to_numpy()
        report("RANGE slice @ 2x slip", tro2[lr2 == 2])
        B.SLIP_MULT = 1.0


if __name__ == "__main__":
    main()
