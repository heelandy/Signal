#!/usr/bin/env python3
"""SIZING LADDER v2 — adds the user's missing piece: EXIT THE STARTER when structure confirms OPPOSITE.
v1 (F66): starter 0.4x on break+ORmid+seq, add 0.6x on struct3 confirm — WON on equities, neutral/lost on
futures because the unconfirmed-only cohort is flat/negative there. v2 hypothesis: cutting the starter the
bar st3 confirms AGAINST it (long cut when st==2 confirms, mirror short) dumps the bad unconfirmed trades
early and may rescue futures. Cut fill = that 5m bar's close (confirmed-bar, causal). Add tranche unchanged.

    python research/orb_ladder_v2.py NQ QQQ SPY ES
"""
import sys, os, gc
sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "engine"))
import numpy as np, pandas as pd
import hs_db, hs_harness as H, hs_backtest as B
ET = "America/New_York"

def run(d, tup, tdn):
    d2 = d.copy(); d2["trend_up"] = tup; d2["trend_down"] = tdn; d2.attrs["sym"] = d.attrs.get("sym", "NQ")
    return B.backtest(d2, "tp2_full", "both", False, "orb", 0, 1.0, 4.0, 570, 600, 0.0, 900, "close",
                      eod_min=958, stop_mode="struct", entry_delay=0, chase_atr=1.0, strong_body=0.25,
                      ft_confirm=True, dir_seq=True, or_mid_bias=True)

def maxdd(cum):
    if len(cum) == 0:
        return 0.0
    return float((cum - np.maximum.accumulate(cum)).min())

def stats(events):
    if not events:
        return dict(pnl=0.0, dep=0.0, ror=float("nan"), dd=0.0, n=0)
    ev = sorted(events); size = np.array([e[1] for e in ev]); R = np.array([e[2] for e in ev])
    pnl = size * R; cum = np.cumsum(pnl)
    return dict(pnl=float(pnl.sum()), dep=float(size.sum()), ror=float(pnl.sum() / size.sum()),
                dd=maxdd(cum), n=len(ev))

def line(tag, s):
    print(f"  {tag:18} PnL {s['pnl']:+8.1f}R  deployed {s['dep']:6.1f}  RoR {s['ror']:+.3f}  "
          f"maxDD {s['dd']:+7.1f}R  PnL/|DD| {(s['pnl']/abs(s['dd']) if s['dd'] else float('nan')):+5.2f}  n={s['n']}")

def main():
    syms = [s.upper() for s in (sys.argv[1:] or ["NQ", "QQQ", "SPY", "ES"])]
    con = hs_db.connect()
    for sym in syms:
        lb = 3 if sym in ("NQ", "ES", "GC") else 5
        ext = B._externals(con, hs_db.bars(con, "5m", "rth", sym=sym), sym)
        d = H.compute_state(ext, H.P(struct_lb_fix=lb)); d.attrs["sym"] = sym
        st3 = d["st_state"].to_numpy()
        bar_ts = pd.to_datetime(d["ts"], utc=True).astype("datetime64[ns, UTC]").to_numpy()
        c_arr = d["close"].to_numpy()
        T = np.ones(len(d), bool)
        none_tr = run(d, T, T)                                  # starter cohort
        s3_tr = run(d, st3 == 1, st3 == 2)                      # confirmed cohort
        for tr in (none_tr, s3_tr):
            tr["day"] = pd.to_datetime(tr["entry_time"], utc=True).dt.tz_convert(ET).dt.date
            tr["tns"] = pd.to_datetime(tr["entry_time"], utc=True).astype("datetime64[ns, UTC]").astype("int64")
        s3map = {(r.day, r.direction): (r.net_R, r.tns) for r in s3_tr.itertuples()}
        # v2 starter: cut at the close of the FIRST bar where st3 confirms OPPOSITE inside the trade window
        cutR = np.full(len(none_tr), np.nan)
        e_ts = pd.to_datetime(none_tr["entry_time"], utc=True).astype("datetime64[ns, UTC]").to_numpy()
        x_ts = pd.to_datetime(none_tr["exit_time"], utc=True).astype("datetime64[ns, UTC]").to_numpy()
        i0 = np.searchsorted(bar_ts, e_ts, side="right")        # first bar AFTER entry (management i+1)
        i1 = np.searchsorted(bar_ts, x_ts, side="right")
        dirs = none_tr["direction"].to_numpy(); eps = none_tr["entry_price"].to_numpy(); rks = none_tr["risk_pts"].to_numpy()
        for k in range(len(none_tr)):
            opp = 2 if dirs[k] == "long" else 1
            seg = st3[i0[k]:i1[k]]
            hit = np.nonzero(seg == opp)[0]
            if len(hit) and rks[k] > 0:
                px = c_arr[i0[k] + hit[0]]
                cutR[k] = (px - eps[k]) / rks[k] if dirs[k] == "long" else (eps[k] - px) / rks[k]
        v2R = np.where(np.isnan(cutR), none_tr["net_R"].to_numpy(), cutR)
        n_cut = int(np.sum(~np.isnan(cutR)))
        def ladder(w0, w1, starterR):
            ev = []
            for j, r in enumerate(none_tr.itertuples()):
                ev.append((r.tns, w0, float(starterR[j])))
                if (r.day, r.direction) in s3map:
                    addR, addt = s3map[(r.day, r.direction)]
                    ev.append((addt, w1, addR))
            return ev
        print(f"\n{'='*100}\n{sym} RTH lb={lb} — LADDER v2 (cut starter on OPPOSITE structure confirm; {n_cut}/{len(none_tr)} starters cut)\n{'='*100}")
        line("BINARY (wait)", stats([(r.tns, 1.0, r.net_R) for r in s3_tr.itertuples()]))
        line("LADDER v1 0.4/0.6", stats(ladder(0.4, 0.6, none_tr["net_R"].to_numpy())))
        line("LADDER v2 0.4/0.6", stats(ladder(0.4, 0.6, v2R)))
        line("LADDER v2 0.5/0.5", stats(ladder(0.5, 0.5, v2R)))
        cutm = ~np.isnan(cutR)
        if n_cut:
            rode = none_tr["net_R"].to_numpy()[cutm]
            print(f"  cut effect: {n_cut} starters cut early; avg R cut {np.nanmean(cutR[cutm]):+.3f} vs ridden {rode.mean():+.3f} (delta {np.nanmean(cutR[cutm] - rode):+.3f}/trade)")
        del d, ext; gc.collect()
    con.close()
    print("\nKEY: v2 rescues futures only if LADDER v2 beats BINARY on PnL at >= comparable PnL/|DD| on NQ/ES. "
          "Equities: v2 must not give back the v1 win.")

if __name__ == "__main__":
    main()
