#!/usr/bin/env python3
"""
F55 — FULL GAUNTLET for the F52 volatility-breakout survivor (Crabel/Williams: enter on a break of
open +/- k*prior-day-range, gap-aware fill at worse of level/open, exit at the same bar's CLOSE).

Sections:
  A  param plateau   k in {0.2..0.6} x assets — is the edge a plateau or a spike?
  B  slippage stress 1x / 2x / 3x costs at k=0.3 — does it survive realistic execution? (the key caveat)
  C  direction       both / long-only / short-only — is it a real 2-sided edge or just equity drift?
  D  regime stress   pre-2018 vs 2018+ on the LONG-history assets (NQ/ES/GC) — the test that killed Connors/ML
  E  path ambiguity  % of trades on days that hit BOTH levels (close-based result is path-assumed there)
  F  diversification daily-P&L correlation vs the production ORB stack (NQ, QQQ) — does it ADD a stream?

    python research/strat_volbreak_test.py [--corr]      (--corr also runs F; default A-E)
"""
import sys, os, gc
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "engine"))
import numpy as np, pandas as pd
import hs_db, hs_harness as H, hs_backtest as B, hs_validate as V
from strat_daily import atr, cost_pct, loci, load, EQ

rng = np.random.default_rng(7)


def volbreak(d, k=0.3, slip=1.0, side="both", lo=None, hi=None):
    o, h, l, c = (d[x].to_numpy() for x in ("open", "high", "low", "close")); a = atr(d)
    dt = d["dt"]; sym = d.attrs["sym"]; n = len(c); rp = pd.Series(h - l).shift(1).to_numpy()
    yr = dt.dt.year.to_numpy(); tr = []; both_hit = 0
    for i in range(1, n):
        if np.isnan(rp[i]) or (lo and yr[i] < lo) or (hi and yr[i] > hi): continue
        u = o[i] + k * rp[i]; dn = o[i] - k * rp[i]
        hu, hd = h[i] >= u, l[i] <= dn
        if hu and hd: both_hit += 1
        if hu and side in ("both", "long"):
            e = max(u, o[i]); x = c[i]; tr.append((dt[i], 1, (x - e) / e - slip * cost_pct(sym, e), (x - e) / a[i]))
        elif hd and side in ("both", "short"):
            e = min(dn, o[i]); x = c[i]; tr.append((dt[i], -1, -(x - e) / e - slip * cost_pct(sym, e), -(x - e) / a[i]))
    return tr, both_hit


def rpt(tag, tr):
    if len(tr) < 30:
        print(f"  {tag:24} n={len(tr)} (<30)"); return None
    df = pd.DataFrame(tr, columns=["dt", "dir", "ret", "R"]); r = df["ret"].to_numpy() * 100; Rr = df["R"].to_numpy()
    df["year"] = df["dt"].dt.year
    yrs = [(y, g["ret"].mean()) for y, g in df.groupby("year") if len(g) >= 5]
    pos = sum(1 for _, e in yrs if e > 0); tot = len(yrs); neg = [int(y) for y, e in yrs if e <= 0]
    df = df.sort_values("dt"); kk = int(len(df) * 0.7); OUT = df.iloc[kk:]["ret"].mean()
    L = df[df.dir == 1]["ret"]; S = df[df.dir == -1]["ret"]
    both = not (len(L) > 5 and len(S) > 5) or (L.mean() > 0 and S.mean() > 0)
    ci = loci(Rr)
    g = "PASS" if (r.mean() > 0 and ci > 0 and tot and pos >= 0.7 * tot and OUT > 0 and both) else "fail"
    print(f"  {tag:24} n={len(r):>4} ret/t {r.mean():+.3f}% expR {Rr.mean():+.3f} PF {V.pf(r):>4.2f} "
          f"win {100*np.mean(r>0):>2.0f}% CIr {ci:+.3f} yr+{pos}/{tot} OOS {OUT*100:+.3f}% {g}{'  NEG'+str(neg) if neg else ''}")
    return df


def main():
    corr = "--corr" in sys.argv
    syms = ["NQ", "ES", "QQQ", "SPY", "GC"]
    con = hs_db.connect()
    daily = {}
    for sym in syms:
        d = load(con, sym); d.attrs["sym"] = sym; daily[sym] = d

    print("==== A. PARAM PLATEAU (k sweep, both sides) ====")
    for sym in syms:
        print(f"# {sym}")
        for k in (0.2, 0.3, 0.4, 0.5, 0.6):
            rpt(f"k{k}", volbreak(daily[sym], k)[0])

    print("\n==== B. SLIPPAGE STRESS (k0.3) ====")
    for sym in syms:
        print(f"# {sym}")
        for s in (1.0, 2.0, 3.0):
            rpt(f"{int(s)}x cost", volbreak(daily[sym], 0.3, slip=s)[0])

    print("\n==== C. DIRECTION SPLIT (k0.3) ====")
    for sym in syms:
        print(f"# {sym}")
        for side in ("both", "long", "short"):
            rpt(side, volbreak(daily[sym], 0.3, side=side)[0])

    print("\n==== D. REGIME STRESS pre-2018 vs 2018+ (k0.3, long-history assets) ====")
    for sym in ("NQ", "ES", "GC"):
        print(f"# {sym}")
        rpt("2010-2017", volbreak(daily[sym], 0.3, lo=2010, hi=2017)[0])
        rpt("2018-2026", volbreak(daily[sym], 0.3, lo=2018, hi=2026)[0])

    print("\n==== E. PATH AMBIGUITY (both-levels-hit days, k0.3) ====")
    for sym in syms:
        tr, bh = volbreak(daily[sym], 0.3)
        print(f"  {sym:4} both-levels-hit {bh}/{len(tr)} = {100*bh/max(1,len(tr)):.1f}% of trades (close-based dir is path-assumed there)")

    if corr:
        print("\n==== F. DIVERSIFICATION: daily-P&L correlation vs the production ORB stack ====")
        for sym in ("NQ", "QQQ"):
            bars = B._externals(con, hs_db.bars(con, "5m", "rth", sym=sym), sym)
            dd = H.compute_state(bars, H.P()); dd.attrs["sym"] = sym; del bars; gc.collect()
            st = dd["st_state"].to_numpy()
            obl = dd["in_bull_ob"].shift(1).fillna(False).to_numpy().astype(bool)
            obs = dd["in_bear_ob"].shift(1).fillna(False).to_numpy().astype(bool)
            dd["trend_up"] = (st == 1) & obl; dd["trend_down"] = (st == 2) & obs
            et = pd.to_datetime(dd["ts"]).dt.tz_convert("America/New_York")
            sk = ((et.dt.hour * 60 + et.dt.minute).to_numpy()) < 660
            tr_s = B.backtest(dd, "tp2_full", "both", False, "orb", 0, 1.0, 4.0, 570, 600, 0.0, 900, "stop",
                              eod_min=958, vwap_cap=2.0, skip_mask=sk, stop_mode="struct")
            sR = tr_s.copy(); sR["day"] = pd.to_datetime(sR["entry_time"], utc=True).dt.tz_convert("America/New_York").dt.normalize()
            stack_daily = sR.groupby("day")["net_R"].sum()
            vb, _ = volbreak(daily[sym], 0.3)
            vdf = pd.DataFrame(vb, columns=["dt", "dir", "ret", "R"])
            vdf["day"] = vdf["dt"].dt.tz_convert("America/New_York").dt.normalize()
            vb_daily = vdf.groupby("day")["R"].sum()
            j = pd.concat([stack_daily.rename("stack"), vb_daily.rename("vbreak")], axis=1).dropna()
            c = j["stack"].corr(j["vbreak"]) if len(j) > 10 else float("nan")
            ov = len(j); sd = len(stack_daily)
            print(f"  {sym:4} overlap days {ov} (stack trades {sd}d) | daily-PnL corr {c:+.3f} "
                  f"({'DIVERSIFYING' if abs(c) < 0.3 else 'correlated'})")
            del dd; gc.collect()
    con.close()


if __name__ == "__main__":
    main()
