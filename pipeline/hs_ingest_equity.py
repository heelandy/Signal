#!/usr/bin/env python3
"""
HIGHSTRIKE — ingest a Databento US-equity OHLCV-1m CSV (XNAS.ITCH / DBEQ) into the same
continuous-1m parquet the futures pipeline uses, so hs_resample.py + hs_db + the backtest
all work unchanged. Equities have no contract roll, so adj_factor=1, is_roll=False.

    python hs_ingest_equity.py "xnas-...ohlcv-1m.csv" SPY
then:
    python hs_resample.py SPY     # -> data/bars/sym=SPY/...
"""
import sys, os
import numpy as np, pandas as pd, duckdb

ET = "America/New_York"


def ingest(csv, sym, replace: bool = False):
    con = duckdb.connect()
    cols = [r[0] for r in con.execute(f"DESCRIBE SELECT * FROM read_csv('{csv}') LIMIT 1").fetchall()]
    df = con.execute(
        f"SELECT * FROM read_csv('{csv}') WHERE open IS NOT NULL ORDER BY ts_event").df()
    con.close()
    # INSTRUMENT IDENTITY (remediation Phase 4): a full-venue file must never land under one
    # symbol. Symbol column when present; duplicate timestamps + price-continuity as fallback.
    if "symbol" in cols:
        uniq = sorted(set(df["symbol"].astype(str).str.upper()))
        if uniq != [sym.upper()]:
            raise ValueError(f"input is not single-instrument {sym}: symbols {uniq[:6]} — "
                             f"filter the file first (Phase 4 identity gate)")
    if df["ts_event"].duplicated().any():
        raise ValueError(f"{int(df['ts_event'].duplicated().sum())} duplicate timestamps — "
                         f"multiple instruments in one file? (Phase 4 identity gate)")
    jumps = df["close"].astype(float).pct_change().abs()
    if (jumps > 0.25).any():
        raise ValueError(f"price continuity broken (max bar-to-bar jump "
                         f"{100 * jumps.max():.0f}%) — mixed instruments? (Phase 4 identity gate)")
    df = df[["ts_event", "open", "high", "low", "close", "volume"]]
    et = pd.to_datetime(df["ts_event"], utc=True).dt.tz_convert(ET)
    mins = et.dt.hour * 60 + et.dt.minute
    wk = et.dt.dayofweek < 5
    out = pd.DataFrame({
        "ts_et": et,
        "open": df["open"].astype("float64"), "high": df["high"].astype("float64"),
        "low": df["low"].astype("float64"), "close": df["close"].astype("float64"),
        "volume": df["volume"].astype("int64"),
        "adj_factor": 1.0, "is_roll": False,
        "session": np.where(wk & (mins >= 570) & (mins < 960), "RTH", "ETH"),  # 09:30-16:00 ET = RTH
    })
    path = os.path.join("data", f"{sym.lower()}_continuous_1m.parquet")
    if os.path.exists(path) and not replace:
        raise SystemExit(f"{path} already exists — this ingest REPLACES the whole store; "
                         f"pass --replace to confirm (Phase 4 overwrite protection)")
    out.to_parquet(path, index=False)
    _manifest_row(csv, sym, out)
    rth = (out["session"] == "RTH").sum()
    print(f"{sym}: {len(out):,} 1m bars ({rth:,} RTH)  "
          f"{out['ts_et'].min().date()}..{out['ts_et'].max().date()}  -> {path}")


def _manifest_row(csv, sym, out):
    """Source manifest (Phase 4 lineage): file, sha256, span, symbol — every ingest is traceable."""
    import hashlib
    import json
    h = hashlib.sha256()
    with open(csv, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    mp = os.path.join("data", "mbo_bars_manifest.json")
    try:
        m = json.load(open(mp, encoding="utf-8"))
    except Exception:
        m = {}
    m[f"{sym.upper()}_equity_ingest"] = {
        "source": os.path.basename(str(csv)), "sha256": h.hexdigest(), "rows": int(len(out)),
        "span": [str(out['ts_et'].min()), str(out['ts_et'].max())],
        "created_at": pd.Timestamp.now("UTC").isoformat()}
    os.makedirs("data", exist_ok=True)
    json.dump(m, open(mp, "w", encoding="utf-8"), indent=1)


if __name__ == "__main__":
    ingest(sys.argv[1], sys.argv[2].upper(), replace="--replace" in sys.argv)
