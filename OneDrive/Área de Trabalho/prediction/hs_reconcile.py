#!/usr/bin/env python3
"""
HIGHSTRIKE Phase 1.1 — Python ↔ Pine reconcile diff.

Input: a TradingView "Export chart data" CSV from V44 with the hs_recon_export.pine plots.
Re-runs the Python harness on the SAME OHLCV (+ the x_* macro/HTF/VWAP inputs the Pine used),
then diffs harness-derived state vs the Pine's x_* state, per column, and logs mismatches.

    python hs_reconcile.py <tv_export.csv> [--adaptive] [--warmup 200]

Bars are identical (same export) so every mismatch is a pure logic divergence to resolve (1.2).
"""
import sys
import numpy as np, pandas as pd
import hs_harness as H

# harness external-input name  <-  TV export column
EXT = {"spy_close": "x_spy_close", "spy_e20": "x_spy_e20", "spy_e50": "x_spy_e50",
       "spy_adx": "x_spy_adx", "vix_sma5": "x_vix_sma5", "vix_prev5": "x_vix_prev5",
       "vwap_sess": "x_vwap_sess", "vwap_wk": "x_vwap_wk"}
EXT_BOOL = {"htf_bull": "x_htf_bull", "htf_bear": "x_htf_bear",
            "sig_htf_bull": "x_sig_htf_bull", "sig_htf_bear": "x_sig_htf_bear"}

# harness state column  ->  (Pine export column, kind)
CMP = [("st_state", "x_st_state", "int"), ("is_hh", "x_is_hh", "bool"),
       ("is_hl", "x_is_hl", "bool"), ("is_lh", "x_is_lh", "bool"), ("is_ll", "x_is_ll", "bool"),
       ("bos_bull", "x_bos_bull", "bool"), ("bos_bear", "x_bos_bear", "bool"),
       ("choch_bull", "x_choch_bull", "bool"), ("choch_bear", "x_choch_bear", "bool"),
       ("struct_long_ok", "x_struct_long", "bool"), ("struct_short_ok", "x_struct_short", "bool"),
       ("macro_regime", "x_regime", "regime"), ("dir_bias", "x_dir_bias", "int"),
       ("master_bias", "x_master_bias", "mbias"),
       ("trigger_long", "x_trig_long", "bool"), ("trigger_short", "x_trig_short", "bool")]

REG = {"—": 0, "A": 1, "B": 2, "C": 3, "D": 4}
MB  = {"LONG": 1, "SHORT": -1, "NONE": 0}


def _harness_int(series, kind):
    if kind == "bool":   return series.astype(bool).astype(int).to_numpy()
    if kind == "regime": return series.map(REG).fillna(0).astype(int).to_numpy()
    if kind == "mbias":  return series.map(MB).fillna(0).astype(int).to_numpy()
    return series.astype(int).to_numpy()


def main():
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    flags = [a for a in sys.argv[1:] if a.startswith("--")]
    if not args:
        print("usage: python hs_reconcile.py <tv_export.csv> [--adaptive] [--warmup N]"); return
    path = args[0]
    warmup = 200
    for i, f in enumerate(sys.argv):
        if f == "--warmup" and i + 1 < len(sys.argv): warmup = int(sys.argv[i + 1])

    raw = pd.read_csv(path)
    raw.columns = [str(c).strip() for c in raw.columns]
    low = {c.lower(): c for c in raw.columns}
    tcol = next((low[k] for k in ("time", "date", "datetime", "timestamp") if k in low), raw.columns[0])
    df = pd.DataFrame({"ts": pd.to_datetime(raw[tcol], utc=True, errors="coerce")})
    for k in ("open", "high", "low", "close", "volume"):
        if k in low: df[k] = pd.to_numeric(raw[low[k]], errors="coerce")
    if "volume" not in df: df["volume"] = 0.0
    for hn, xn in EXT.items():
        if xn in raw.columns: df[hn] = pd.to_numeric(raw[xn], errors="coerce")
    for hn, xn in EXT_BOOL.items():
        if xn in raw.columns: df[hn] = pd.to_numeric(raw[xn], errors="coerce").fillna(0) > 0.5
    df = df.dropna(subset=["open", "high", "low", "close"]).reset_index(drop=True)

    p = H.P(struct_adaptive=("--adaptive" in flags))
    out = H.compute_state(df, p)

    print(f"RECONCILE  {path}")
    print(f"  bars {len(out):,}   warmup-excluded first {warmup}   adaptive_lb={p.struct_adaptive}\n")
    print(f"  {'column':16} {'match%':>8} {'mismatch':>9}   first mismatch bars")
    total_mm = 0; rows = []
    m = np.arange(len(out)) >= warmup
    for hcol, xcol, kind in CMP:
        if xcol not in raw.columns:
            print(f"  {hcol:16} {'(no x col)':>8}"); continue
        hv = _harness_int(out[hcol], kind)
        pv = pd.to_numeric(raw[xcol], errors="coerce").round().astype("Int64").to_numpy()
        pv = pv[:len(hv)]
        valid = m & ~pd.isna(pv)
        mism = valid & (hv != pv)
        nm = int(mism.sum()); total_mm += nm
        rate = 100.0 * (1 - nm / max(int(valid.sum()), 1))
        idx = list(np.where(mism)[0][:5])
        print(f"  {hcol:16} {rate:8.2f} {nm:9,}   {idx}")
        for i in np.where(mism)[0]:
            rows.append({"bar": i, "ts": out['ts'].iloc[i], "column": hcol,
                         "harness": hv[i], "pine": pv[i]})
    print(f"\n  TOTAL mismatches: {total_mm:,}")
    if rows:
        pd.DataFrame(rows).to_csv("data/reconcile_mismatches.csv", index=False)
        print("  wrote data/reconcile_mismatches.csv (resolve these for 1.2)")
    else:
        print("  ✅ exact match across all compared state columns")


if __name__ == "__main__":
    main()
