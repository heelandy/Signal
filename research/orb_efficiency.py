#!/usr/bin/env python3
"""PRICE EFFICIENCY (Kaufman ER) as an additive CHOP filter — graduation gauntlet.
ER = |close−close[N]| / Σ|ΔP| over N intraday bars (0=pure chop, 1=straight line). High ER = clean move (follow);
low ER = chop (stand aside). We add it ON TOP OF THE FULL CURRENT STACK (struct3 + OR-mid + dir-seq + VOL-EXPANSION
min_or_width=2.4) — the missing control from orb_dir_state (which omitted vol-exp). Graduation needs:
  * exp AND CIlo lift over the full-stack base, across a θ×N grid (robust, not a fitted peak),
  * the DROPPED (choppy) cohort = the losers,
  * beat 'just gate harder' (struct5 + vol-exp at matched n).

    python research/orb_efficiency.py NQ QQQ SPY
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
        print(f"  {tag:18} n={len(r):>4}  (too few)"); return
    L = tr.net_R[tr.direction == "long"].to_numpy(); S = tr.net_R[tr.direction == "short"].to_numpy()
    lo = ci_lo(r); p, ny = yr(tr); is_, oo = oos(tr)
    both = len(L) > 5 and L.mean() > 0 and len(S) > 5 and S.mean() > 0
    g = "PASS" if (lo > 0 and both and ny and p >= 0.7 * ny and oo > 0) else "----"
    print(f"  {tag:18} n={len(r):>4} exp {r.mean():+.3f} PF {V.pf(r):>4.2f} win {100*np.mean(r>0):>2.0f}% "
          f"CIlo {lo:+.3f} L{(L.mean() if len(L) else 0):+.2f} S{(S.mean() if len(S) else 0):+.2f} "
          f"yr+{p}/{ny} OOS{is_:+.2f}/{oo:+.2f} {g}")

def run(d, tup, tdn, volexp=2.4):
    d2 = d.copy(); d2["trend_up"] = tup; d2["trend_down"] = tdn; d2.attrs["sym"] = d.attrs.get("sym", "NQ")
    return B.backtest(d2, "tp2_full", "both", False, "orb", 0, 1.0, 4.0, 570, 600, 0.0, 900, "close",
                      eod_min=958, stop_mode="struct", entry_delay=0, chase_atr=1.0, strong_body=0.25,
                      ft_confirm=True, dir_seq=True, or_mid_bias=True, min_or_width=volexp)

def er(d, N):
    et = pd.to_datetime(d["ts"]).dt.tz_convert("America/New_York"); day = et.dt.date.to_numpy()
    df = pd.DataFrame({"day": day, "c": d["close"].to_numpy()})
    df["dP"] = df.groupby("day")["c"].diff()
    absmove = df.groupby("day")["dP"].transform(lambda s: s.abs().rolling(N, min_periods=N).sum()).to_numpy()
    cN = df.groupby("day")["c"].transform(lambda s: s.shift(N)).to_numpy()
    with np.errstate(invalid="ignore", divide="ignore"):
        return np.where(absmove > 0, np.abs(df["c"].to_numpy() - cN) / absmove, np.nan)

def dropped(base, sub):
    ks = set(zip(pd.to_datetime(sub["entry_time"]).astype("int64"), sub["direction"]))
    return base[[(ts, dr) not in ks for ts, dr in zip(pd.to_datetime(base["entry_time"]).astype("int64"), base["direction"])]]

def main():
    syms = [s.upper() for s in (sys.argv[1:] or ["NQ", "QQQ", "SPY"])]
    con = hs_db.connect()
    for sym in syms:
        ext = B._externals(con, hs_db.bars(con, "5m", "rth", sym=sym), sym)
        d = H.compute_state(ext, H.P()); d.attrs["sym"] = sym
        st5 = d["st_state"].to_numpy()
        st3 = H.compute_state(ext, H.P(struct_lb_fix=3))["st_state"].to_numpy()
        print(f"\n{'='*100}\n{sym} RTH — EFFICIENCY (chop filter) additive to FULL STACK (struct3 + vol-exp 2.4)\n{'='*100}")
        base = run(d, st3 == 1, st3 == 2); line("STACK base", base)
        line("gate-harder str5", run(d, st5 == 1, st5 == 2))
        for N in (6, 10):
            e = er(d, N)
            print(f"  -- ER window N={N} --")
            for th in (0.3, 0.4, 0.5, 0.6):
                sub = run(d, (st3 == 1) & (e >= th), (st3 == 2) & (e >= th))
                line(f"str3 & ER{N}>={th}", sub)
            # additivity: are the trades dropped by the best threshold the losers?
            dd = dropped(base, run(d, (st3 == 1) & (e >= 0.5), (st3 == 2) & (e >= 0.5)))
            line(f"  DROPPED(ER{N}<.5)", dd)
        del d, ext; gc.collect()
    con.close()
    print("\nKEY: graduates if str3&ER lifts exp+CIlo over STACK base ACROSS the threshold grid (robust), the DROPPED "
          "choppy cohort is the losers, and it beats gate-harder(str5) at matched n. This is the chop/awareness lever.")

if __name__ == "__main__":
    main()
