#!/usr/bin/env python3
"""SIZING LADDER policy backtest (the 'act on direction sooner, never bet full on the unconfirmed read' idea).
Not a new signal — a POLICY over the two cohorts we already have:
  starter  = break + OR-mid + dir-seq (no structure gate)  -> the 'none' cohort (independently PASS)
  confirm  = starter AND st_state(lb3) agrees              -> the 'struct3' cohort (fires 30-60m later, at a
                                                              worse price, but higher expectancy)
Policies (risk-based sizing; 1.0 = the full per-trade risk budget; matches GRADE_MULT B=0.4 / A=1.0):
  BINARY   (current) : trade ONLY confirmed, size 1.0            -> waits, skips the unconfirmed cohort
  ALL-FULL           : trade every starter, size 1.0            -> earliest, but full budget on the unconfirmed read
  LADDER   w0/w1     : starter w0 on EVERY break + add w1 on the confirmed subset (total 1.0 when confirmed)
Reentry OFF (one setup / day / side) so starter<->confirm match 1:1 by (day, side). v1 does NOT model the
'exit starter on opposite structure' cut (conservative — the starter just rides to its normal exit); noted.
Metrics: total PnL in R, risk DEPLOYED (sum of sizes), return-on-risk (PnL/deployed), and max drawdown of the
chronological cumulative-R curve. The question: does LADDER book MORE total R than BINARY at acceptable DD?

    python research/orb_sizing_ladder.py NQ QQQ SPY ES
"""
import sys, os, gc
sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "engine"))
import numpy as np, pandas as pd
import hs_db, hs_harness as H, hs_backtest as B, hs_validate as V
ET = "America/New_York"

def run(d, tup, tdn):
    d2 = d.copy(); d2["trend_up"] = tup; d2["trend_down"] = tdn; d2.attrs["sym"] = d.attrs.get("sym", "NQ")
    return B.backtest(d2, "tp2_full", "both", False, "orb", 0, 1.0, 4.0, 570, 600, 0.0, 900, "close",
                      eod_min=958, stop_mode="struct", entry_delay=0, chase_atr=1.0, strong_body=0.25,
                      ft_confirm=True, dir_seq=True, or_mid_bias=True)

def maxdd(cum):
    if len(cum) == 0:
        return 0.0
    peak = np.maximum.accumulate(cum)
    return float((cum - peak).min())

def policy_stats(events):
    """events = list of (ts_ns, size, R). Returns dict of totals + chronological maxDD."""
    if not events:
        return dict(pnl=0.0, deployed=0.0, ror=float("nan"), dd=0.0, n=0)
    ev = sorted(events)
    size = np.array([e[1] for e in ev]); R = np.array([e[2] for e in ev])
    pnlv = size * R
    cum = np.cumsum(pnlv)
    dep = size.sum()
    return dict(pnl=float(pnlv.sum()), deployed=float(dep), ror=float(pnlv.sum() / dep) if dep else float("nan"),
                dd=maxdd(cum), n=len(ev))

def line(tag, s):
    print(f"  {tag:16} PnL {s['pnl']:+8.1f}R  deployed {s['deployed']:6.1f}  RoR/unit {s['ror']:+.3f}  "
          f"maxDD {s['dd']:+7.1f}R  PnL/|DD| {(s['pnl']/abs(s['dd']) if s['dd'] else float('nan')):+5.2f}  n={s['n']}")

def main():
    syms = [s.upper() for s in (sys.argv[1:] or ["NQ", "QQQ", "SPY", "ES"])]
    con = hs_db.connect()
    for sym in syms:
        ext = B._externals(con, hs_db.bars(con, "5m", "rth", sym=sym), sym)
        d = H.compute_state(ext, H.P()); d.attrs["sym"] = sym
        st3 = H.compute_state(ext, H.P(struct_lb_fix=3))["st_state"].to_numpy()
        T = np.ones(len(d), bool)
        none_tr = run(d, T, T)                                  # starter cohort
        s3_tr = run(d, st3 == 1, st3 == 2)                      # confirmed cohort (fires later)
        for tr in (none_tr, s3_tr):
            tr["day"] = pd.to_datetime(tr["entry_time"], utc=True).dt.tz_convert(ET).dt.date
            tr["tns"] = pd.to_datetime(tr["entry_time"], utc=True).astype("int64")
        s3map = {(r.day, r.direction): (r.net_R, r.tns) for r in s3_tr.itertuples()}
        # build events per policy
        ev_binary = [(r.tns, 1.0, r.net_R) for r in s3_tr.itertuples()]
        ev_allfull = [(r.tns, 1.0, r.net_R) for r in none_tr.itertuples()]
        n_conf = n_unconf = 0; conf_starterR = []; unconf_R = []; conf_addR = []
        def ladder(w0, w1):
            ev = []
            for r in none_tr.itertuples():
                ev.append((r.tns, w0, r.net_R))                 # starter on every break
                if (r.day, r.direction) in s3map:
                    addR, addtns = s3map[(r.day, r.direction)]
                    ev.append((addtns, w1, addR))               # add when structure confirms
            return ev
        for r in none_tr.itertuples():
            if (r.day, r.direction) in s3map:
                n_conf += 1; conf_starterR.append(r.net_R); conf_addR.append(s3map[(r.day, r.direction)][0])
            else:
                n_unconf += 1; unconf_R.append(r.net_R)
        print(f"\n{'='*104}\n{sym} RTH — SIZING LADDER policy (starter=break+ORmid+seq, add=struct-confirm lb3)\n{'='*104}")
        print(f"  cohort: {n_conf} CONFIRMED (starter avg {np.mean(conf_starterR):+.3f}R, add avg {np.mean(conf_addR):+.3f}R) | "
              f"{n_unconf} UNCONFIRMED-only (avg {np.mean(unconf_R) if unconf_R else 0:+.3f}R  <- binary SKIPS these, ladder takes @ w0)")
        line("BINARY (wait)", policy_stats(ev_binary))
        line("ALL-FULL", policy_stats(ev_allfull))
        line("LADDER 0.4/0.6", policy_stats(ladder(0.4, 0.6)))
        line("LADDER 0.5/0.5", policy_stats(ladder(0.5, 0.5)))
        del d, ext; gc.collect()
    con.close()
    print("\nKEY: LADDER wins if it books MORE total PnL(R) than BINARY at a comparable or better PnL/|DD|. "
          "RoR/unit = blended expectancy per unit RISK deployed (BINARY = the pure struct3 expectancy).")

if __name__ == "__main__":
    main()
