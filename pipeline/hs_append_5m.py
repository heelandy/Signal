#!/usr/bin/env python3
"""HIGHSTRIKE — append NEW bars to a symbol's continuous-1m parquet from a 5-MINUTE OHLCV csv
(the 'python nq Catalyst' export bridged NQ's gap: store ended 2026-06-05, csv runs to today).

Each 5m bar lands as ONE row at its bar-start timestamp — the resampler then aggregates 5m
(identity), 15m/1h/D (exact OHLCV algebra), so every served timeframe is correct; only the raw
1m granularity itself is coarser over the appended span (nothing in the engine reads stored 1m).
Official bars always win on overlap (strict append-after-last). Provenance in
data/mbo_bars_manifest.json (same removal contract as the MBO scaffolding).

    python pipeline/hs_append_5m.py NQ "path/to/NQ_5min_data.csv" [utc]
then python pipeline/hs_resample.py NQ
"""
import json
import os
import sys

import numpy as np
import pandas as pd

ET = "America/New_York"
MANIFEST = os.path.join("data", "mbo_bars_manifest.json")


def main(sym: str, csv: str, tz: str = "UTC") -> None:
    df = pd.read_csv(csv)
    tcol = "date" if "date" in df.columns else df.columns[0]
    ts = pd.to_datetime(df[tcol])
    ts = ts.dt.tz_localize(tz) if ts.dt.tz is None else ts
    et = ts.dt.tz_convert(ET)
    mins = et.dt.hour * 60 + et.dt.minute
    wk = et.dt.dayofweek < 5
    new = pd.DataFrame({
        "ts_et": et,
        "open": df["open"].astype("float64"), "high": df["high"].astype("float64"),
        "low": df["low"].astype("float64"), "close": df["close"].astype("float64"),
        "volume": df["volume"].fillna(0).astype("int64"),
        "adj_factor": 1.0, "is_roll": False,
        "session": np.where(wk & (mins >= 570) & (mins < 960), "RTH", "ETH"),
    }).sort_values("ts_et")
    new = new[new["high"] >= new["low"]]                     # basic sanity
    path = os.path.join("data", f"{sym.lower()}_continuous_1m.parquet")
    old = pd.read_parquet(path)
    last = old["ts_et"].max()
    add = new[new["ts_et"] > last]
    dropped = len(new) - len(add)
    if not len(add):
        # Phase 4 fail-closed: a fully-overlapping file appends NOTHING — that must be a loud
        # non-zero exit, not a silent no-op (replacing an existing span is a deliberate rebuild)
        raise SystemExit(f"{sym}: ALL {len(new):,} rows overlap the existing store (<= {last}) — "
                         f"nothing appended. Rebuilding an existing span is a manual, explicit "
                         f"operation; this script only appends after the last official bar.")
    if dropped:
        print(f"{sym}: {dropped:,} overlapping rows (<= {last}) dropped — official bars win")
    out = pd.concat([old, add], ignore_index=True).sort_values("ts_et")
    out.to_parquet(path, index=False)
    try:
        m = json.load(open(MANIFEST, encoding="utf-8"))
    except Exception:
        m = {}
    import hashlib
    _h = hashlib.sha256()
    with open(csv, "rb") as _f:
        for _chunk in iter(lambda: _f.read(1 << 20), b""):
            _h.update(_chunk)
    m[sym.upper() + "_5m_append"] = {
        "official_cutoff": str(last), "appended": int(len(add)),
        "appended_range": [str(add["ts_et"].min()), str(add["ts_et"].max())],
        "source": csv, "sha256": _h.hexdigest(),          # Phase 4 source manifest
        "granularity": "5m-as-1m rows (resampled tfs exact)",
        "created_at": pd.Timestamp.now("UTC").isoformat()}
    os.makedirs("data", exist_ok=True)
    json.dump(m, open(MANIFEST, "w", encoding="utf-8"), indent=1)
    print(f"{sym}: appended {len(add):,} bars after {last} -> now "
          f"{out['ts_et'].min().date()}..{out['ts_et'].max().date()} ({len(out):,} rows)")


if __name__ == "__main__":
    main(sys.argv[1].upper(), sys.argv[2], sys.argv[3] if len(sys.argv) > 3 else "UTC")
