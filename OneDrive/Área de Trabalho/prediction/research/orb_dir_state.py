#!/usr/bin/env python3
"""DIRECTIONAL-STATE conditioners (user 'follow, be aware of where price is going'):
  sign1    directional state detection  f(ΔP)=sign(close−close[1])         (base momentum sign)
  state    price direction state machine (flip on k consecutive same-sign ΔP, else hold)
  persist  directional persistence   |Σ sign(ΔP)| / N   over N intraday bars   (0..1; dir=sign of sum)
  eff      price efficiency (Kaufman) |close−close[N]| / Σ|ΔP|  over N          (0..1; chop filter; dir=sign net)

Tested TWO ways on the validated ORB (delay0/chase1/struct-stop/cap4R/strong0.25/ft/OR-mid/dir-seq), RTH 5m:
  A) STANDALONE gate  (replace the structure gate) — does the signal know direction on its own?
  B) ADDITIVE on struct3 (structure gives direction; the signal's MAGNITUDE gates quality) — does it LIFT?
Windows are INTRADAY (reset each session, so the window never crosses the open). Additivity control: the
DROPPED cohort must be the losers, and the lift must beat just gating harder (struct5 shown at matched n).

    python research/orb_dir_state.py NQ QQQ SPY
"""
import sys, os, gc
sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "engine"))
import numpy as np, pandas as pd
import hs_db, hs_harness as H, hs_backtest as B, hs_validate as V

_rng = np.random.default_rng(7)
def ci_lo(r):
    return float(np.percentile(_rng.choice(r, size=(1500, len(r)), replace=True).mean(axis=1), 5)) if len(r) >= 10 else float("nan")
def yr(tr):
    t = tr.copy(); t["y"] = pd.to_datetime(t["entry_time"], utc=True).dt.tz_convert("America/New_York").dt.year
    g = t.groupby("y")["net_R"].mean(); return int((g > 0).sum()), len(g)
def oos(tr):
    r = tr.sort_values("entry_time")["net_R"].to_numpy(); k = int(len(r) * 0.7)
    return (r[:k].mean(), r[k:].mean()) if (k >= 5 and len(r) - k >= 5) else (float("nan"), float("nan"))
def line(tag, tr):
    r = tr["net_R"].to_numpy()
    if len(r) < 20:
        print(f"  {tag:16} n={len(r):>4}  (too few)"); return
    L = tr.net_R[tr.direction == "long"].to_numpy(); S = tr.net_R[tr.direction == "short"].to_numpy()
    lo = ci_lo(r); p, ny = yr(tr); is_, oo = oos(tr)
    both = len(L) > 5 and L.mean() > 0 and len(S) > 5 and S.mean() > 0
    g = "PASS" if (lo > 0 and both and ny and p >= 0.7 * ny and oo > 0) else "----"
    print(f"  {tag:16} n={len(r):>4} exp {r.mean():+.3f} PF {V.pf(r):>4.2f} win {100*np.mean(r>0):>2.0f}% "
          f"CIlo {lo:+.3f} L{(L.mean() if len(L) else 0):+.2f} S{(S.mean() if len(S) else 0):+.2f} "
          f"yr+{p}/{ny} OOS{is_:+.2f}/{oo:+.2f} {g}")

def run(d, tup, tdn):
    d2 = d.copy(); d2["trend_up"] = tup; d2["trend_down"] = tdn; d2.attrs["sym"] = d.attrs.get("sym", "NQ")
    return B.backtest(d2, "tp2_full", "both", False, "orb", 0, 1.0, 4.0, 570, 600, 0.0, 900, "close",
                      eod_min=958, stop_mode="struct", entry_delay=0, chase_atr=1.0, strong_body=0.25,
                      ft_confirm=True, dir_seq=True, or_mid_bias=True)

def state_machine(sgn, k=3):
    """flip to +1 after k consecutive +ΔP, −1 after k consecutive −ΔP, else HOLD the last state."""
    n = len(sgn); out = np.zeros(n); run_len = 0; run_s = 0; cur = 0
    for i in range(n):
        s = sgn[i]
        if s == run_s and s != 0: run_len += 1
        else: run_s = s; run_len = 1 if s != 0 else 0
        if run_len >= k and run_s != 0: cur = run_s
        out[i] = cur
    return out

def dropped(base, sub):
    k = lambda t: set(zip(pd.to_datetime(t["entry_time"]).astype("int64"), t["direction"]))
    ks = k(sub)
    return base[[(ts, dr) not in ks for ts, dr in zip(pd.to_datetime(base["entry_time"]).astype("int64"), base["direction"])]]

def main():
    syms = [s.upper() for s in (sys.argv[1:] or ["NQ", "QQQ", "SPY"])]
    N = 6
    con = hs_db.connect()
    for sym in syms:
        ext = B._externals(con, hs_db.bars(con, "5m", "rth", sym=sym), sym)
        d = H.compute_state(ext, H.P()); d.attrs["sym"] = sym
        st5 = d["st_state"].to_numpy()
        st3 = H.compute_state(ext, H.P(struct_lb_fix=3))["st_state"].to_numpy()
        et = pd.to_datetime(d["ts"]).dt.tz_convert("America/New_York")
        day = et.dt.date.to_numpy()
        c = d["close"].to_numpy()
        df = pd.DataFrame({"day": day, "c": c})
        df["dP"] = df.groupby("day")["c"].diff()
        df["sgn"] = np.sign(df["dP"]).fillna(0)
        g = df.groupby("day")
        persist_sum = g["sgn"].transform(lambda s: s.rolling(N, min_periods=N).sum())
        absmove = g["dP"].transform(lambda s: s.abs().rolling(N, min_periods=N).sum())
        cN = g["c"].transform(lambda s: s.shift(N))
        netmove = c - cN.to_numpy()
        persist = (np.abs(persist_sum) / N).to_numpy(); pdir = np.sign(persist_sum).to_numpy()
        with np.errstate(invalid="ignore", divide="ignore"):
            eff = np.where(absmove.to_numpy() > 0, np.abs(netmove) / absmove.to_numpy(), np.nan)
        edir = np.sign(netmove)
        sgn1 = df["sgn"].to_numpy()
        sm = state_machine(sgn1, 3)
        T = np.ones(len(d), bool)

        print(f"\n{'='*100}\n{sym} RTH — DIRECTIONAL-STATE signals (window N={N} intraday)\n{'='*100}")
        print("  -- baselines --")
        base_none = run(d, T, T);            line("none(ORmid+seq)", base_none)
        base3 = run(d, st3 == 1, st3 == 2);  line("struct3 (base)", base3)
        line("struct5 (tighter)", run(d, st5 == 1, st5 == 2))
        print("  -- A) STANDALONE gate (signal replaces the structure) --")
        line("sign1", run(d, sgn1 > 0, sgn1 < 0))
        line("state-machine", run(d, sm > 0, sm < 0))
        line("persist>=.5", run(d, (pdir > 0) & (persist >= 0.5), (pdir < 0) & (persist >= 0.5)))
        line("persist>=.67", run(d, (pdir > 0) & (persist >= 0.67), (pdir < 0) & (persist >= 0.67)))
        line("eff>=.3", run(d, (edir > 0) & (eff >= 0.3), (edir < 0) & (eff >= 0.3)))
        line("eff>=.5", run(d, (edir > 0) & (eff >= 0.5), (edir < 0) & (eff >= 0.5)))
        print("  -- B) ADDITIVE on struct3 (structure=direction; signal magnitude=quality gate) --")
        for th in (0.3, 0.5):
            sub = run(d, (st3 == 1) & (eff >= th), (st3 == 2) & (eff >= th)); line(f"str3 & eff>={th}", sub)
            line(f"  DROPPED(eff{th})", dropped(base3, sub))
        for th in (0.5, 0.67):
            sub = run(d, (st3 == 1) & (persist >= th), (st3 == 2) & (persist >= th)); line(f"str3 & persist>={th}", sub)
            line(f"  DROPPED(prs{th})", dropped(base3, sub))
        del d, ext; gc.collect()
    con.close()
    print("\nKEY: ADDITIVE graduates only if it beats struct3 on exp AND CIlo, the DROPPED cohort is the losers, "
          "and the lift beats just gating harder (struct5 at matched n). Chop/efficiency = a QUALITY conditioner.")

if __name__ == "__main__":
    main()
