#!/usr/bin/env python3
"""SCALPING entry research (user 2026-07-03): fast-timeframe (1/2/3/4-min) OR-break, gated by a LOOKBACK
PRICE-ARRAY direction read (store recent closes; is price higher/lower than N bars ago = moving up/down),
entered AT the break or the NEXT candle, exited SCALP-tight (small R cap + time-stop). Data = the on-disk
*_continuous_1m.parquet (RTH). Does the array add edge, and is any timeframe worth scalping net of costs?

  direction array : trend_up = close > close[-N]  (N = lookback bars); trend_down mirror. N sweep {3,5,10}.
  entry           : 'break'      = resting stop at the OR level (intrabar touch)   -> catch AT the breakout
                    'next'       = close-confirm + next-candle continuation        -> catch the NEXT candle
  scalp exit       : cap TP at R (1.0/1.5), stop = OR edge, TIME-STOP after H bars, EOD-flat. Real costs on.
Baseline (no array gate) vs array-gated, per TF, so the array's contribution is isolated.

    python research/orb_scalp.py NQ QQQ
"""
import sys, os, gc
sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "engine"))
import numpy as np, pandas as pd
import hs_harness as H, hs_backtest as B, hs_validate as V

DATA = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "data")
_rng = np.random.default_rng(7)
def ci_lo(r):
    return float(np.percentile(_rng.choice(r, size=(1000, len(r)), replace=True).mean(axis=1), 5)) if len(r) >= 10 else float("nan")
def line(tag, tr):
    if tr is None or len(tr) < 25:
        print(f"    {tag:26} n={0 if tr is None else len(tr):>5}  (too few)"); return
    r = tr["net_R"].to_numpy(); L = tr.net_R[tr.direction == "long"].to_numpy(); S = tr.net_R[tr.direction == "short"].to_numpy()
    lo = ci_lo(r); mfe = tr["mfe_R"].mean() if "mfe_R" in tr else float("nan"); hold = tr["hold_bars"].median() if "hold_bars" in tr else float("nan")
    both = len(L) > 5 and L.mean() > 0 and len(S) > 5 and S.mean() > 0
    g = "PASS" if (lo > 0 and both) else "----"
    print(f"    {tag:26} n={len(r):>5} exp {r.mean():+.3f} PF {V.pf(r):>4.2f} win {100*np.mean(r>0):>2.0f}% "
          f"CIlo {lo:+.3f} medHold {hold:>3.0f}b medMFE {mfe:+.2f} {g}")

def load_tf(sym, tf):
    p = os.path.join(DATA, f"{sym.lower()}_continuous_1m.parquet")
    if not os.path.exists(p):
        return None
    df = pd.read_parquet(p)
    tcol = "ts_et" if "ts_et" in df.columns else ("ts" if "ts" in df.columns else df.columns[0])
    df = df.rename(columns={tcol: "ts"}); df["ts"] = pd.to_datetime(df["ts"], utc=True)
    et = df["ts"].dt.tz_convert("America/New_York"); mm = et.dt.hour * 60 + et.dt.minute
    df = df[(mm >= 570) & (mm < 960)].copy()
    if "volume" not in df:
        df["volume"] = 0.0
    if tf > 1:
        df["_day"] = et[(mm >= 570) & (mm < 960)].dt.date.to_numpy()
        out = []
        for _, g in df.groupby("_day"):
            rs = g.set_index("ts").resample(f"{tf}min", label="left", closed="left").agg(
                {"open": "first", "high": "max", "low": "min", "close": "last", "volume": "sum"}).dropna()
            out.append(rs.reset_index())
        df = pd.concat(out, ignore_index=True)
    return df[["ts", "open", "high", "low", "close", "volume"]].sort_values("ts").reset_index(drop=True)

def scalp(d, tup, tdn, execm, ft, tp, hbars):
    d2 = d.copy(); d2["trend_up"] = tup; d2["trend_down"] = tdn
    return B.backtest(d2, "tp2_full", "both", False, "orb", 0, 1.0, tp, 570, 600, 0.0, 900, execm,
                      eod_min=955, stop_mode="or", entry_delay=0, chase_atr=1.0,
                      strong_body=(0.25 if execm == "close" else 0.0), ft_confirm=ft, dir_seq=False,
                      time_stop=hbars)

def main():
    syms = [s.upper() for s in (sys.argv[1:] or ["NQ", "QQQ"])]
    for sym in syms:
        for tf in (1, 2, 3, 4):
            df = load_tf(sym, tf)
            if df is None or len(df) < 500:
                print(f"{sym} {tf}m: no/insufficient 1m parquet"); continue
            d = H.compute_state(df, H.P(struct_lb_fix=3 if sym in ("NQ", "ES", "GC") else 5)); d.attrs["sym"] = sym
            c = d["close"].to_numpy(); T = np.ones(len(d), bool)
            hbars = max(10, int(30 / tf))                       # ~30-min scalp time-stop, in bars of this TF
            print(f"\n{'='*98}\n{sym} {tf}m — SCALP OR-break (scalp exit: cap TP · OR stop · time-stop {hbars}b · costs on)\n{'='*98}")
            print(f"  [entry AT break, cap {1.5}R]")
            line("no-array (baseline)", scalp(d, T, T, "stop", False, 1.5, hbars))
            for N in (3, 5, 10):
                up = c > np.concatenate([[np.nan]*N, c[:-N]]); dn = c < np.concatenate([[np.nan]*N, c[:-N]])
                line(f"array N={N} (close>c[-N])", scalp(d, up, dn, "stop", False, 1.5, hbars))
            print(f"  [entry NEXT candle (close+continuation), cap {1.5}R]")
            line("no-array next-candle", scalp(d, T, T, "close", True, 1.5, hbars))
            up5 = c > np.concatenate([[np.nan]*5, c[:-5]]); dn5 = c < np.concatenate([[np.nan]*5, c[:-5]])
            line("array N=5 next-candle", scalp(d, up5, dn5, "close", True, 1.5, hbars))
            print(f"  [entry AT break, TIGHT cap {1.0}R]")
            line("array N=5 · 1.0R", scalp(d, up5, dn5, "stop", False, 1.0, hbars))
            del d, df; gc.collect()
    print("\nREAD: scalping lives/dies on COSTS vs a tight cap. array ADDS only if array-gated beats no-array at "
          "the same TF/exit. Compare TFs: which (if any) clears CIlo>0 + both sides>0 net of costs.")

if __name__ == "__main__":
    main()
