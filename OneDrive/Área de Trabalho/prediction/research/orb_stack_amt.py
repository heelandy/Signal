#!/usr/bin/env python3
"""
RESEARCH (F42 candidate) — AUCTION MARKET THEORY family (agenda item 2). Nothing AMT is in the harness, so
build a proper VOLUME PROFILE of the PRIOR RTH day (volume distributed uniformly across each 5m bar's range,
50 bins): POC (max-volume price), and the 70% VALUE AREA (VAH/VAL). Causal — today's breakout uses YESTERDAY's
completed profile. Test the canonical AMT thesis as a stack confluence filter:
  outside_va : take the breakout ONLY if its entry (OR level) is ACCEPTED OUTSIDE prior value
               (long: OR-high > prior VAH ; short: OR-low < prior VAL) — "out-of-balance = trend day"
  above_poc  : looser — long: OR-high > prior POC ; short: OR-low < prior POC
Full gauntlet incl. the additivity/frontier-lift control + on top of the F38 time gate + the F41 OB gate
(is AMT orthogonal to what already graduated, or a shadow of it?).

    python research/orb_stack_amt.py             (gate test)
    python research/orb_stack_amt.py --additive  (frontier-lift vs vwap-cap + on top of F38 + on top of F41)
"""
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "engine"))
import numpy as np, pandas as pd
import hs_db, hs_harness as H, hs_backtest as B, hs_validate as V
from orb_kernel_filter import loci, slip2x, ORS, ORE, CUT, T1, T2, EOD, KCAP

VARIANTS = ("outside_va", "above_poc")


def _day_va(sub, nb=50):
    """{date: (poc, vah, val)} from a one-day RTH slice; volume spread across each bar's [low,high]."""
    out = {}
    for dt, g in sub.groupby("date"):
        lo, hi = g["low"].min(), g["high"].max()
        if not (hi > lo):
            continue
        edges = np.linspace(lo, hi, nb + 1); cw = edges[1] - edges[0]; hist = np.zeros(nb)
        for L, Hh, vol in zip(g["low"].to_numpy(), g["high"].to_numpy(), g["volume"].to_numpy()):
            li = min(max(int((L - lo) / cw), 0), nb - 1); hi_i = min(max(int((Hh - lo) / cw), 0), nb - 1)
            hist[li:hi_i + 1] += vol / (hi_i - li + 1)
        poc_i = int(hist.argmax()); tot = hist.sum(); tgt = 0.7 * tot
        a = b = poc_i; acc = hist[poc_i]
        while acc < tgt and (a > 0 or b < nb - 1):
            left = hist[a - 1] if a > 0 else -1.0
            right = hist[b + 1] if b < nb - 1 else -1.0
            if right >= left: b += 1; acc += hist[b]
            else: a -= 1; acc += hist[a]
        out[dt] = ((edges[poc_i] + edges[poc_i + 1]) / 2.0, edges[b + 1], edges[a])
    return out


def levels(d):
    et = pd.to_datetime(d["ts"]).dt.tz_convert("America/New_York")
    date = et.dt.normalize().dt.tz_localize(None); mins = et.dt.hour * 60 + et.dt.minute
    base = pd.DataFrame({"date": date.to_numpy(), "low": d["low"].to_numpy(), "high": d["high"].to_numpy(),
                         "volume": d["volume"].to_numpy(), "mins": mins.to_numpy()})
    org = base[(base.mins >= ORS) & (base.mins < ORE)].groupby("date").agg(orh=("high", "max"), orl=("low", "min"))
    va = _day_va(base[(base.mins >= ORS) & (base.mins < 960)])
    vdf = pd.DataFrame([(k, *v) for k, v in va.items()], columns=["date", "poc", "vah", "val"]).set_index("date").sort_index()
    vdf[["p_poc", "p_vah", "p_val"]] = vdf[["poc", "vah", "val"]].shift(1)        # prior-day profile (causal)
    g = org.join(vdf[["p_poc", "p_vah", "p_val"]])
    return g, date


def feats(d):
    g, date = levels(d)
    ds = pd.Series(date.to_numpy())
    col = lambda nm: ds.map(g[nm]).to_numpy()
    orh, orl, ppoc, pvah, pval = col("orh"), col("orl"), col("p_poc"), col("p_vah"), col("p_val")
    et = pd.to_datetime(d["ts"]).dt.tz_convert("America/New_York")
    masks = {"outside_va": (orh > pvah, orl < pval), "above_poc": (orh > ppoc, orl < ppoc)}
    return masks, (et.dt.hour * 60 + et.dt.minute).to_numpy()


def run(d, v=None, M=None, vcap=KCAP, extra=None):
    st = d["st_state"].to_numpy(); tu = st == 1; td = st == 2
    if v is not None:
        kl, ks = M[0][v]; tu = tu & kl; td = td & ks
    sk = None
    if extra == "skip11":
        sk = M[1] < 660
    elif extra == "ob":
        ob_l = d["in_bull_ob"].shift(1).fillna(False).to_numpy().astype(bool)
        ob_s = d["in_bear_ob"].shift(1).fillna(False).to_numpy().astype(bool)
        tu = tu & ob_l; td = td & ob_s
    d["trend_up"] = tu; d["trend_down"] = td
    return B.backtest(d, "scale_be", "both", False, "orb", 0, T1, T2, ORS, ORE, 0.0, CUT, "stop",
                      eod_min=EOD, vwap_cap=vcap, skip_mask=sk)


def line(tag, tr, eq=False):
    r = tr["net_R"].to_numpy()
    if len(r) < 30:
        print(f"  {tag:13} n={len(r)} (<30)"); return
    L = tr[tr.direction == "long"]["net_R"].to_numpy(); S = tr[tr.direction == "short"]["net_R"].to_numpy()
    both = len(L) > 5 and L.mean() > 0 and len(S) > 5 and S.mean() > 0
    lo = loci(r)
    t = tr.copy(); t["year"] = pd.to_datetime(t["entry_time"], utc=True).dt.tz_convert("America/New_York").dt.year
    yrs = [(int(y), g["net_R"].mean()) for y, g in t.groupby("year") if len(g) >= 10]
    pos = sum(1 for _, e in yrs if e > 0); tot = len(yrs); neg = [y for y, e in yrs if e <= 0]
    t = t.sort_values("entry_time").reset_index(drop=True); k = int(len(t) * 0.7)
    IN = t.iloc[:k]["net_R"].to_numpy(); OUT = t.iloc[k:]["net_R"].to_numpy()
    g = "PASS" if (both and lo > 0 and tot and pos >= 0.7 * tot and OUT.mean() > 0) else "fail"
    sl = "" if eq else f" 2x {slip2x(tr, eq).mean():+.3f}"
    print(f"  {tag:13} n={len(r):>4} exp {r.mean():+.3f} PF {V.pf(r):>5.2f} win {100*np.mean(r>0):>2.0f}% "
          f"DD {V.maxdd(r):>+5.0f} CI {lo:+.3f} {g} | yr +{pos}/{tot}{' NEG=' + str(neg) if neg else ''} "
          f"| OOS {IN.mean():+.3f}->{OUT.mean():+.3f}{sl}")


def sweep(con):
    for sym in ["NQ", "QQQ", "SPY"]:
        eq = sym in ("QQQ", "SPY")
        bars = B._externals(con, hs_db.bars(con, "5m", "full", sym=sym), sym)
        d = H.compute_state(bars, H.P()); d.attrs["sym"] = sym
        M = feats(d)
        print(f"\n#### {sym} 5m — Auction Market Theory: prior-day value-area confluence ####")
        line("STACK", run(d), eq)
        for v in VARIANTS:
            line("+" + v, run(d, v, M), eq)


def additive(con):
    ks = [2.0, 1.8, 1.6, 1.4, 1.2, 1.0]
    for sym in ("NQ", "QQQ"):
        bars = B._externals(con, hs_db.bars(con, "5m", "full", sym=sym), sym)
        d = H.compute_state(bars, H.P()); d.attrs["sym"] = sym
        M = feats(d)
        vo = [(len(t := run(d, vcap=k)), t["net_R"].mean()) for k in ks]
        vs = sorted(vo); ns = np.array([x[0] for x in vs]); es = np.array([x[1] for x in vs])
        for v in VARIANTS:
            print(f"\n==== {sym}: +{v} ADDITIVITY vs vwap-cap frontier ====")
            for k in ks:
                r = run(d, v, M, vcap=k)["net_R"].to_numpy()
                if len(r) < 25:
                    print(f"  {v} + vwap k={k}  n={len(r):>4} (<25)"); continue
                e_vo = float(np.interp(len(r), ns, es))
                print(f"  {v} + vwap k={k}  n={len(r):>4} exp {r.mean():+.3f} | vwap-only@n {e_vo:+.3f} | delta {r.mean() - e_vo:+.3f}")
            for tag, ex in [("skip<11:00", "skip11"), ("+ob(F41)", "ob")]:
                base = run(d, extra=ex)["net_R"]; comb = run(d, v, M, extra=ex)["net_R"]
                print(f"  -- on top of {tag} -- base n={len(base)} exp {base.mean():+.3f} || +{v} n={len(comb)} exp {comb.mean():+.3f}")


def main():
    con = hs_db.connect()
    additive(con) if "--additive" in sys.argv[1:] else sweep(con)
    con.close()


if __name__ == "__main__":
    main()
