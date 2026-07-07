#!/usr/bin/env python3
"""HIGHSTRIKE — build OHLCV-1m bars from Databento MBO TRADE PRINTS (action='T') and APPEND the
NEW minutes to data/<sym>_continuous_1m.parquet. Existing official OHLCV bars always win on
overlap (strict append-after-last-bar). This extends the bar store from the SAME depth archive
the L2 features come from — no new download needed (user 2026-07-07: complete the champion
unlocks with the data we have).

    python pipeline/hs_mbo_bars.py QQQ "D:/XNAS-20260627-9JFGFERR4Y/xnas-itch-*.mbo.csv.zst"
then:
    python pipeline/hs_resample.py QQQ

TEMPORARY-SCAFFOLDING CONTRACT (user 2026-07-07: "use the l2/l3 data we had for training and
confirmation; after, we can remove that information and wait for the real data"): every append
is recorded in data/mbo_bars_manifest.json (symbol, official cutoff, appended range). When the
real OHLCV download arrives:

    python pipeline/hs_mbo_bars.py QQQ --remove      # truncates back to the official cutoff
    python pipeline/hs_resample.py QQQ               # rebuilds the bar store clean
"""
import glob
import json
import os
import sys

import duckdb
import numpy as np
import pandas as pd

ET = "America/New_York"
MANIFEST = os.path.join("data", "mbo_bars_manifest.json")


def _manifest_load() -> dict:
    try:
        with open(MANIFEST, encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {}


def _manifest_save(d: dict) -> None:
    os.makedirs("data", exist_ok=True)
    with open(MANIFEST, "w", encoding="utf-8") as f:
        json.dump(d, f, indent=1)


def remove(sym: str) -> None:
    """Surgically remove the MBO-derived bars (restore the official store) per the manifest."""
    m = _manifest_load().get(sym.upper())
    path = os.path.join("data", f"{sym.lower()}_continuous_1m.parquet")
    if not m or not os.path.exists(path):
        print(f"{sym}: nothing to remove (no manifest entry / no store)")
        return
    df = pd.read_parquet(path)
    cutoff = pd.Timestamp(m["official_cutoff"])
    keep = df[df["ts_et"] <= cutoff]
    keep.to_parquet(path, index=False)
    d = _manifest_load()
    d.pop(sym.upper(), None)
    _manifest_save(d)
    print(f"{sym}: removed {len(df) - len(keep):,} MBO-derived bars — store restored to "
          f"{cutoff} ({len(keep):,} bars). Now run: python pipeline/hs_resample.py {sym}")


def bars_from_mbo(path: str, sym: str) -> pd.DataFrame:
    # timestamp probing via the battle-tested l2_features helper (review fix 2026-07-07: the
    # inline INT-vs-TIMESTAMPTZ branch missed ISO-string ts_event — the exact case that Binder-
    # Errored all 51 MBO syncs before _ts_expr existed)
    import sys as _s
    _s.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "BOT"))
    from bot.ml.l2_features import _ts_expr, _columns
    con = duckdb.connect()
    try:
        con.execute("SET memory_limit='1GB'; SET threads=1; SET preserve_insertion_order=false")
        ts = _ts_expr(_columns(path), con, path)
        if ts is None:
            raise ValueError(f"no timestamp column found in {path}")
        q = f"""
        SELECT date_trunc('minute', {ts}) AS minute,
               first(price ORDER BY ts_event)  AS open,
               max(price)                      AS high,
               min(price)                      AS low,
               last(price ORDER BY ts_event)   AS close,
               sum(size)::BIGINT               AS volume
        FROM read_csv_auto('{path}')
        WHERE action = 'T' AND price > 0 AND upper(symbol) = '{sym.upper()}'
        GROUP BY 1 ORDER BY 1"""
        return con.execute(q).df()
    finally:
        con.close()


def main(sym: str, pattern: str) -> None:
    files = sorted(glob.glob(pattern))
    if not files:
        print(f"no files match {pattern}")
        sys.exit(1)
    frames = []
    for f in files:
        df = bars_from_mbo(f, sym)
        print(f"  {os.path.basename(f)}: {len(df)} 1m bars", flush=True)
        if len(df):
            frames.append(df)
    new = pd.concat(frames, ignore_index=True).sort_values("minute")
    et = pd.to_datetime(new["minute"], utc=True).dt.tz_convert(ET)
    mins = et.dt.hour * 60 + et.dt.minute
    wk = et.dt.dayofweek < 5
    new = pd.DataFrame({
        "ts_et": et,
        "open": new["open"].astype("float64"), "high": new["high"].astype("float64"),
        "low": new["low"].astype("float64"), "close": new["close"].astype("float64"),
        "volume": new["volume"].astype("int64"),
        "adj_factor": 1.0, "is_roll": False,
        "session": np.where(wk & (mins >= 570) & (mins < 960), "RTH", "ETH"),
    })
    path = os.path.join("data", f"{sym.lower()}_continuous_1m.parquet")
    if os.path.exists(path):
        old = pd.read_parquet(path)
        last = old["ts_et"].max()
        add = new[new["ts_et"] > last]                    # official bars win on overlap
        out = pd.concat([old, add], ignore_index=True).sort_values("ts_et")
        print(f"{sym}: store ended {last} — appending {len(add):,} MBO-derived bars "
              f"(of {len(new):,} built)", flush=True)
    else:
        out, add, last = new, new, None
        print(f"{sym}: no existing store — writing all {len(new):,} bars", flush=True)
    out.to_parquet(path, index=False)
    d = _manifest_load()                                  # removal contract: record the seam
    d[sym.upper()] = {"official_cutoff": str(last), "appended": int(len(add)),
                      "appended_range": [str(add['ts_et'].min()), str(add['ts_et'].max())] if len(add) else None,
                      "source": pattern, "created_at": pd.Timestamp.now("UTC").isoformat(),
                      "note": "TEMPORARY scaffolding — remove when the real OHLCV download lands"}
    _manifest_save(d)
    print(f"{sym}: {len(out):,} 1m bars total  {out['ts_et'].min().date()}"
          f"..{out['ts_et'].max().date()}  -> {path}", flush=True)


if __name__ == "__main__":
    if "--remove" in sys.argv:
        remove(sys.argv[1] if len(sys.argv) > 1 and not sys.argv[1].startswith("-") else "QQQ")
    else:
        main(sys.argv[1].upper() if len(sys.argv) > 1 else "QQQ",
             sys.argv[2] if len(sys.argv) > 2 else r"D:/XNAS-20260627-9JFGFERR4Y/xnas-itch-*.mbo.csv.zst")
