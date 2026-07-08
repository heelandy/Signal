#!/usr/bin/env python3
"""The two pending STRUC A/Bs on the validated stack (struct-gate ORB, delay0/chase1/struct-stop/cap4R/
strong-body/ft/OR-mid/dir-seq, RTH 5m):
  A) gap-aware CHoCH — engine `choch_gap_aware=True` (new default, fixes the 41-bar stale flip) vs False
     (the rule the backtests were validated under). Same lb (futures 3 / equity 5).
  B) 1m-FED trend gate — st_state computed on 1m bars (lb=3/5 in 1m context), causally aligned onto the
     5m frame (last 1m bar inside each 5m bar = the Pine `fast_dir` twin), vs the chart-TF (5m) gate.
     1m bars come from data/<sym>_continuous_1m.parquet (RTH filter applied).

    python research/orb_struc_ab.py NQ QQQ SPY
"""
import sys, os, gc
sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "engine"))
import numpy as np, pandas as pd
import hs_db, hs_harness as H, hs_backtest as B, hs_validate as V

DATA = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "data")
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
    if tr is None or len(tr) < 20 or "net_R" not in tr.columns:
        print(f"  {tag:26} n={0 if tr is None or 'net_R' not in getattr(tr,'columns',[]) else len(tr):>4}  (too few)"); return
    r = tr["net_R"].to_numpy(); L = tr.net_R[tr.direction == "long"].to_numpy(); S = tr.net_R[tr.direction == "short"].to_numpy()
    lo = ci_lo(r); p, ny = yr(tr); is_, oo = oos(tr)
    both = len(L) > 5 and L.mean() > 0 and len(S) > 5 and S.mean() > 0
    g = "PASS" if (lo > 0 and both and ny and p >= 0.7 * ny and oo > 0) else "----"
    print(f"  {tag:26} n={len(r):>4} exp {r.mean():+.3f} PF {V.pf(r):>4.2f} CIlo {lo:+.3f} "
          f"L{(L.mean() if len(L) else 0):+.2f} S{(S.mean() if len(S) else 0):+.2f} yr+{p}/{ny} OOS{is_:+.2f}/{oo:+.2f} {g}")

def run(d, tup, tdn):
    d2 = d.copy(); d2["trend_up"] = tup; d2["trend_down"] = tdn; d2.attrs["sym"] = d.attrs.get("sym", "NQ")
    return B.backtest(d2, "tp2_full", "both", False, "orb", 0, 1.0, 4.0, 570, 600, 0.0, 900, "close",
                      eod_min=958, stop_mode="struct", entry_delay=0, chase_atr=1.0, strong_body=0.25,
                      ft_confirm=True, dir_seq=True, or_mid_bias=True, min_or_width=2.4)

def load_1m(sym):
    p = os.path.join(DATA, f"{sym.lower()}_continuous_1m.parquet")
    if not os.path.exists(p):
        return None
    df = pd.read_parquet(p)
    tcol = "ts" if "ts" in df.columns else ("ts_et" if "ts_et" in df.columns else df.columns[0])
    df = df.rename(columns={tcol: "ts"})
    df["ts"] = pd.to_datetime(df["ts"], utc=True)
    et = df["ts"].dt.tz_convert("America/New_York")
    hm = et.dt.hour * 60 + et.dt.minute
    return df[(hm >= 570) & (hm < 960)].reset_index(drop=True).sort_values("ts")   # RTH only

def st_1m_on_5m(d5, b1, sym, lb):
    d1 = H.compute_state(b1, H.P(struct_lb_fix=lb))
    t1 = pd.to_datetime(d1["ts"], utc=True).astype("datetime64[ns, UTC]")   # parquet=us, DB=ns -> normalize
    t5 = (pd.to_datetime(d5["ts"], utc=True) + pd.Timedelta(minutes=4)).astype("datetime64[ns, UTC]")
    m = pd.merge_asof(pd.DataFrame({"ts": t5.to_numpy()}).sort_values("ts"),
                      pd.DataFrame({"ts": t1.to_numpy(), "st": d1["st_state"].to_numpy(float)}).sort_values("ts"),
                      on="ts", direction="backward")
    return m["st"].to_numpy(float)

def main():
    syms = [s.upper() for s in (sys.argv[1:] or ["NQ", "QQQ", "SPY"])]
    con = hs_db.connect()
    for sym in syms:
        lb = 3 if sym in ("NQ", "ES", "GC", "MNQ", "MES") else 5
        ext = B._externals(con, hs_db.bars(con, "5m", "rth", sym=sym), sym)
        d = H.compute_state(ext, H.P(struct_lb_fix=lb)); d.attrs["sym"] = sym      # gap-aware default ON
        st_new = d["st_state"].to_numpy()
        st_old = H.compute_state(ext, H.P(struct_lb_fix=lb, choch_gap_aware=False))["st_state"].to_numpy()
        flips = int((st_new != st_old).sum())
        print(f"\n{'='*100}\n{sym} RTH lb={lb} — STRUC A/Bs (state differs on {flips}/{len(d)} bars = {100*flips/len(d):.1f}%)\n{'='*100}")
        print("  -- A) gap-aware CHoCH (new default) vs old crossing-bar rule --")
        line("gate st(gap-aware NEW)", run(d, st_new == 1, st_new == 2))
        line("gate st(old rule)", run(d, st_old == 1, st_old == 2))
        b1 = load_1m(sym)
        if b1 is None:
            print(f"  -- B) 1m-fed gate: no data/{sym.lower()}_continuous_1m.parquet — skipped --")
        else:
            st1 = st_1m_on_5m(d, b1, sym, lb)
            cov = float(np.mean(~np.isnan(st1)))
            eff = np.where(np.isnan(st1), st_new, st1)                    # fall back to chart-TF pre-coverage
            print(f"  -- B) 1m-FED trend gate vs chart-TF gate (1m coverage {100*cov:.0f}% of 5m bars) --")
            line("gate st(1m-fed)", run(d, eff == 1, eff == 2))
            line("gate st(chart-5m)", run(d, st_new == 1, st_new == 2))
            del b1
        del d, ext; gc.collect()
    con.close()
    print("\nKEY: A) if NEW ~= old (exp/CIlo), the gap-aware fix is FREE (adopt: faster flips, same edge); if it "
          "drops, the old numbers don't transfer. B) 1m-fed must match or beat the chart gate to keep fast_dir ON.")

if __name__ == "__main__":
    main()
