#!/usr/bin/env python3
"""LIQUIDITY ZONES step 2 — ADDITIVE on the CURRENT validated entry (user protocol: same entry process,
zones as confluence, NOT their own edge). For every trade of the exact stack config (struct gate + OR-mid +
dir-seq + vol-exp + close-confirm), compute the CAUSAL zone map at entry time (zones from the day's 1m bars
UP TO the entry minute) and tag:
    ahead_atr  = distance (in ATR) to the nearest MAJOR/STRONG zone AHEAD in the trade direction
                 ("clean air" = no zone within k ATR — the F-crossorb Globex-H/L analogy)
    from_zone  = entry within 0.5 ATR of a MAJOR/STRONG zone BEHIND (breaking out FROM support/resistance)
Tests: full stack ± clean-air gate (k = 1/2/3 ATR) and ± from-zone, with the DROPPED-cohort control.
Zones step 1 (beats random) passed; this decides whether they touch the entry logic. NQ/QQQ*/SPY* — only
futures have the continuous 1m parquet; equities skipped automatically if no 1m source.

    python research/orb_zones_additive.py NQ ES
"""
import sys, os, gc
sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "engine"))
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__))))
import numpy as np, pandas as pd
import hs_db, hs_harness as H, hs_backtest as B, hs_validate as V
from orb_liquidity_zones import detect_zones

_rng = np.random.default_rng(7)
def ci_lo(r):
    return float(np.percentile(_rng.choice(r, size=(1200, len(r)), replace=True).mean(axis=1), 5)) if len(r) >= 10 else float("nan")
def yr(tr):
    t = tr.copy(); t["y"] = pd.to_datetime(t["entry_time"], utc=True).dt.tz_convert("America/New_York").dt.year
    g = t.groupby("y")["net_R"].mean(); return int((g > 0).sum()), len(g)
def oos(tr):
    r = tr.sort_values("entry_time")["net_R"].to_numpy(); k = int(len(r) * 0.7)
    return (r[:k].mean(), r[k:].mean()) if (k >= 5 and len(r) - k >= 5) else (float("nan"), float("nan"))
def line(tag, tr):
    if tr is None or len(tr) < 20:
        print(f"  {tag:22} n={0 if tr is None else len(tr):>4}  (too few)"); return
    r = tr["net_R"].to_numpy(); L = tr.net_R[tr.direction == "long"].to_numpy(); S = tr.net_R[tr.direction == "short"].to_numpy()
    lo = ci_lo(r); p, ny = yr(tr); is_, oo = oos(tr)
    both = len(L) > 5 and L.mean() > 0 and len(S) > 5 and S.mean() > 0
    g = "PASS" if (lo > 0 and both and ny and p >= 0.7 * ny and oo > 0) else "----"
    print(f"  {tag:22} n={len(r):>4} exp {r.mean():+.3f} PF {V.pf(r):>4.2f} CIlo {lo:+.3f} "
          f"L{(L.mean() if len(L) else 0):+.2f} S{(S.mean() if len(S) else 0):+.2f} yr+{p}/{ny} OOS{is_:+.2f}/{oo:+.2f} {g}")

DATA = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "data")

def load_1m(sym):
    p = os.path.join(DATA, f"{sym.lower()}_continuous_1m.parquet")
    if not os.path.exists(p):
        return None
    df = pd.read_parquet(p)
    tcol = "ts_et" if "ts_et" in df.columns else ("ts" if "ts" in df.columns else df.columns[0])
    df = df.rename(columns={tcol: "ts"})
    df["ts"] = pd.to_datetime(df["ts"], utc=True)
    et = df["ts"].dt.tz_convert("America/New_York")
    df["_d"] = et.dt.date; df["_m"] = et.dt.hour * 60 + et.dt.minute
    return df[(df["_m"] >= 570) & (df["_m"] < 960)].sort_values("ts").reset_index(drop=True)

def stack_trades(sym):
    con = hs_db.connect()
    ext = B._externals(con, hs_db.bars(con, "5m", "rth", sym=sym), sym)
    con.close()
    d = H.compute_state(ext, H.P(struct_lb_fix=3 if sym in ("NQ", "ES", "GC") else 5)); d.attrs["sym"] = sym
    st = d["st_state"].to_numpy(); d["trend_up"] = st == 1; d["trend_down"] = st == 2
    tr = B.backtest(d, "tp2_full", "both", False, "orb", 0, 1.0, 4.0, 570, 600, 0.0, 900, "close",
                    eod_min=958, stop_mode="struct", entry_delay=0, chase_atr=1.0, strong_body=0.25,
                    ft_confirm=True, dir_seq=True, or_mid_bias=True, min_or_width=2.4)
    et = pd.to_datetime(tr["entry_time"], utc=True).dt.tz_convert("America/New_York")
    tr["ddate"] = et.dt.date; tr["dmin"] = (et.dt.hour * 60 + et.dt.minute).to_numpy()   # no _-prefix (itertuples mangles)
    return tr

def wf3(tag, tr):
    """3-fold time split of the cohort (walk-forward view beyond the 70/30 OOS)."""
    if tr is None or len(tr) < 30:
        return
    t = tr.sort_values("entry_time"); r = t["net_R"].to_numpy(); k = len(r) // 3
    print(f"  {tag:22} WF thirds: {r[:k].mean():+.3f} / {r[k:2*k].mean():+.3f} / {r[2*k:].mean():+.3f}")


def main():
    args = [a for a in sys.argv[1:]]
    if "--slip2" in args:
        args.remove("--slip2")
        B.SLIP_TICKS *= 2                                        # futures slip stress (2x ticks per side)
        print(f"[slip stress: SLIP_TICKS doubled -> {B.SLIP_TICKS}]")
    syms = [s.upper() for s in (args or ["NQ", "ES"])]
    for sym in syms:
        b1 = load_1m(sym)
        if b1 is None:
            print(f"{sym}: no continuous 1m parquet — skipped"); continue
        tr = stack_trades(sym)
        days = dict(tuple(b1.groupby("_d")))
        ahead = np.full(len(tr), np.nan); behind = np.full(len(tr), np.nan)
        for k, row in enumerate(tr.itertuples()):
            g = days.get(row.ddate)
            if g is None or len(g) < 40:
                continue
            form = g[g["_m"] <= row.dmin]                                 # CAUSAL: bars up to the entry minute
            if len(form) < 40:
                continue
            try:
                zs = [z for z in detect_zones(form, sym=sym) if z["label"] in ("MAJOR", "STRONG")]
            except Exception:
                continue
            atr = float(np.mean(g["high"].to_numpy()[:30] - g["low"].to_numpy()[:30])) or 1.0
            e = row.entry_price; sgn = 1 if row.direction == "long" else -1
            da = [sgn * (z["center"] - e) / atr for z in zs if sgn * (z["center"] - e) > 0]
            db = [abs(z["center"] - e) / atr for z in zs if sgn * (z["center"] - e) <= 0]
            ahead[k] = min(da) if da else np.inf
            behind[k] = min(db) if db else np.inf
        tr = tr.assign(ahead=ahead, behind=behind)
        got = tr[np.isfinite(tr["ahead"]) | np.isfinite(tr["behind"]) | tr["ahead"].isna()]
        base = tr[~tr["ahead"].isna() | ~tr["behind"].isna()]
        base = tr.dropna(subset=["ahead"])                                # trades with a computed zone map
        print(f"\n{'='*100}\n{sym} — ZONES ADDITIVE on the CURRENT stack entry ({len(base)}/{len(tr)} trades mapped)\n{'='*100}")
        line("STACK base (mapped)", base)
        for k in (1.0, 2.0, 3.0):
            kept = base[base["ahead"] >= k]
            drop = base[base["ahead"] < k]
            line(f"clean-air >= {k:.0f} ATR", kept)
            line(f"  DROPPED (zone ahead)", drop)
            if k == 3.0:
                wf3("base", base); wf3(f"clean-air >= {k:.0f}", kept)
        fz = base[base["behind"] <= 0.5]
        line("from-zone (<=0.5 back)", fz)
        line("  not-from-zone", base[base["behind"] > 0.5])
        del b1, days; gc.collect()
    print("\nKEY: additive only if a clean-air k LIFTS exp+CIlo over base AND the dropped (zone-ahead) cohort is "
          "the LOSERS, consistently across NQ+ES. from-zone = does breaking FROM a level help?")

if __name__ == "__main__":
    main()
