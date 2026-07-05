"""L2/L3 market-depth data — registered IN PLACE from any disk, synthesized into causal features.

The raw book data NEVER gets copied onto the machine: you register a PATH (external drive is
fine); DuckDB reads the file where it lives (csv / csv.zst / parquet — Databento MDP-3 exports
and generic depth dumps) and aggregates it into small per-minute FEATURE parquets in the
FeatureStore. Only the synthesized features persist (a few MB); the raw stays on your disk.
The Training Lab's drop zone streams a dragged file through the same synthesis without saving
the raw either.

Formats auto-detected from the header:
    mbp     L2 book snapshots  (bid_px_00/ask_px_00/bid_sz_00/... — Databento MBP-1/MBP-10)
    mbo     L3 order-by-order  (action/side/price/size/order_id — Databento MBO)
    trades  tick trades        (price/size/side aggressor)
    ohlcv   plain bars         (open/high/low/close — registered but not book-synthesized)

Synthesized per-minute features (l2_* — joined onto candidates at their signal minute):
    l2_spread_bps    average top-of-book spread in bps
    l2_depth_imb     (bid size − ask size) / total at the top level  ∈ [−1, 1]
    l2_flow_imb      signed aggressor/trade flow imbalance           ∈ [−1, 1]
    l2_quote_rate    book updates per minute (log10)
    l2_absorption    volume traded while price went nowhere (z-ish proxy)
    l2_book_pressure multi-level depth imbalance when 10 levels exist

    python -m bot.ml.l2_features register "E:\\data\\nq_mbp10.csv.zst" NQ
    python -m bot.ml.l2_features sync <source_id>
"""
from __future__ import annotations

import json
import uuid
from pathlib import Path

import numpy as np
import pandas as pd

from bot.config import BOT_ROOT
from bot.ml.registry import FeatureStore

SOURCES = BOT_ROOT / "data" / "l2_sources.json"
L2_COLUMNS = ["l2_spread_bps", "l2_depth_imb", "l2_flow_imb", "l2_quote_rate",
              "l2_absorption", "l2_book_pressure"]


def _load() -> list[dict]:
    if SOURCES.exists():
        try:
            return json.loads(SOURCES.read_text(encoding="utf-8"))
        except Exception:
            return []
    return []


def _save(rows: list[dict]) -> None:
    SOURCES.parent.mkdir(parents=True, exist_ok=True)
    SOURCES.write_text(json.dumps(rows, indent=1), encoding="utf-8")


def _duck_path(path: str) -> str:
    return str(path).replace("\\", "/")


def _columns(path: str) -> list[str]:
    import duckdb
    con = duckdb.connect()
    try:
        cols = [r[0] for r in con.execute(
            f"DESCRIBE SELECT * FROM '{_duck_path(path)}' LIMIT 0").fetchall()]
    finally:
        con.close()
    return [c.lower() for c in cols]


def detect_format(path: str) -> tuple[str, list[str]]:
    cols = _columns(path)
    if any(c.startswith("bid_px_0") for c in cols) and any(c.startswith("ask_px_0") for c in cols):
        return "mbp", cols
    if "order_id" in cols and "action" in cols:
        return "mbo", cols
    if "price" in cols and "size" in cols:
        return "trades", cols
    if {"open", "high", "low", "close"} <= set(cols):
        return "ohlcv", cols
    return "unknown", cols


def _ts_expr(cols: list[str]) -> str | None:
    """Minute-bucket expression for the file's timestamp column (Databento ns ints or ISO)."""
    for c in ("ts_event", "ts_recv", "ts", "timestamp", "time"):
        if c in cols:
            return (f"date_trunc('minute', to_timestamp({c} / 1000000000.0))"
                    if c.startswith("ts_") else f"date_trunc('minute', CAST({c} AS TIMESTAMP))")
    return None


DATA_EXTS = (".csv", ".csv.zst", ".csv.gz", ".parquet", ".zip")


def _zip_inner(path: str) -> str | None:
    """First data member inside a zip (auto-unzip support — streamed, never extracted to disk)."""
    import zipfile
    try:
        with zipfile.ZipFile(path) as z:
            for n in z.namelist():
                if n.lower().endswith((".csv", ".parquet")):
                    return n
    except Exception:
        return None
    return None


def _detect_any(path: str) -> tuple[str, list[str]]:
    """Format detection incl. zips (peek the inner member via a streamed sample — no extraction)."""
    if str(path).lower().endswith(".zip"):
        inner = _zip_inner(path)
        if inner is None:
            return "unknown", []
        import zipfile
        with zipfile.ZipFile(path) as z, z.open(inner) as f:
            head = pd.read_csv(f, nrows=50) if inner.lower().endswith(".csv") else pd.read_parquet(f)
        cols = [c.lower() for c in head.columns]
        if any(c.startswith("bid_px_0") for c in cols):
            return "mbp", cols
        if "order_id" in cols and "action" in cols:
            return "mbo", cols
        if "price" in cols and "size" in cols:
            return "trades", cols
        if {"open", "high", "low", "close"} <= set(cols):
            return "ohlcv", cols
        return "unknown", cols
    return detect_format(path)


def register(path: str, symbol: str) -> dict:
    """Register an on-disk L2/L3 file OR a whole FOLDER (auto-scans for data files, including
    zips — nothing is copied or extracted to disk). Run sync per source to synthesize."""
    p = Path(path)
    if not p.exists():
        return {"error": f"path not found: {path}"}
    if p.is_dir():                                   # AUTO-SCAN a folder (user 2026-07-05)
        found = []
        for f in sorted(p.rglob("*")):
            name = f.name.lower()
            if f.is_file() and any(name.endswith(e) for e in DATA_EXTS):
                r = register(str(f), symbol)
                if "error" not in r:
                    found.append({k: r[k] for k in ("id", "path", "kind", "size_mb")})
            if len(found) >= 50:
                break
        return {"folder": str(p), "registered": len(found), "sources": found} if found else \
            {"error": f"no data files ({'/'.join(DATA_EXTS)}) found under {p}"}
    kind, cols = _detect_any(str(p))
    rows = _load()
    src = {"id": uuid.uuid4().hex[:8], "path": str(p), "symbol": symbol.upper(), "kind": kind,
           "size_mb": round(p.stat().st_size / 1e6, 1), "added_at": pd.Timestamp.now("UTC").isoformat(),
           "status": "registered" if kind != "unknown" else "unknown_format",
           "zipped": str(p).lower().endswith(".zip"), "columns": cols[:24]}
    rows.append(src)
    _save(rows)
    from bot.audit import log as _audit
    _audit("l2_source_registered", **{k: src[k] for k in ("id", "path", "symbol", "kind", "size_mb")})
    return src


def sources() -> list[dict]:
    return _load()


def synthesize(source_id: str, tf_minutes: int = 1) -> dict:
    """DuckDB aggregation DIRECTLY against the registered path -> per-minute l2_* features
    saved to the FeatureStore as `l2feat_{symbol}` (only the features persist)."""
    rows = _load()
    src = next((r for r in rows if r["id"] == source_id), None)
    if src is None:
        return {"error": f"unknown source {source_id}"}
    # AUTO-UNZIP path: stream the inner member in CHUNKS through the in-memory synthesizer —
    # the archive is read where it lives; nothing is ever extracted to disk.
    if str(src["path"]).lower().endswith(".zip"):
        import zipfile
        inner = _zip_inner(src["path"])
        if inner is None:
            return {"error": "zip has no csv/parquet member"}
        agg = []
        with zipfile.ZipFile(src["path"]) as z, z.open(inner) as f:
            if inner.lower().endswith(".parquet"):
                res = synthesize_frame(pd.read_parquet(f), src["symbol"])
            else:
                for chunk in pd.read_csv(f, chunksize=2_000_000):
                    r = synthesize_frame(chunk, src["symbol"], save=False)
                    if "frame" in r:
                        agg.append(r["frame"])
                if not agg:
                    return {"error": "zip synthesis produced no rows"}
                allf = (pd.concat(agg, ignore_index=True)
                        .groupby("minute", as_index=False).mean(numeric_only=True))
                FeatureStore().save(f"l2feat_{src['symbol']}", "v1", allf)
                res = {"symbol": src["symbol"], "feature_rows": int(len(allf)),
                       "span": [str(allf['minute'].iloc[0])[:16], str(allf['minute'].iloc[-1])[:16]]}
        if "error" not in res:
            for r in rows:
                if r["id"] == source_id:
                    r["status"] = "synthesized"
                    r["feature_rows"] = res["feature_rows"]
            _save(rows)
            from bot.audit import log as _audit
            _audit("l2_synthesized", id=source_id, symbol=src["symbol"],
                   rows=res["feature_rows"], via="zip_stream")
        return res
    import duckdb
    path = _duck_path(src["path"])
    cols = _columns(src["path"])
    ts = _ts_expr(cols)
    if ts is None:
        return {"error": f"no timestamp column found in {cols[:10]}"}
    kind = src["kind"]
    con = duckdb.connect()
    try:
        if kind == "mbp":
            lvl10 = "bid_sz_09" in cols and "ask_sz_09" in cols
            deep_b = " + ".join(f"bid_sz_0{i}" for i in range(10)) if lvl10 else "bid_sz_00"
            deep_a = " + ".join(f"ask_sz_0{i}" for i in range(10)) if lvl10 else "ask_sz_00"
            q = f"""
            SELECT {ts} AS minute,
                   avg((ask_px_00 - bid_px_00) / nullif((ask_px_00 + bid_px_00) / 2.0, 0)) * 10000 AS l2_spread_bps,
                   avg((bid_sz_00 - ask_sz_00) / nullif(bid_sz_00 + ask_sz_00, 0))          AS l2_depth_imb,
                   log10(count(*) + 1)                                                       AS l2_quote_rate,
                   avg(({deep_b}) - ({deep_a})) / nullif(avg(({deep_b}) + ({deep_a})), 0)    AS l2_book_pressure
            FROM '{path}' WHERE bid_px_00 > 0 AND ask_px_00 > 0
            GROUP BY 1 ORDER BY 1"""
        elif kind in ("mbo", "trades"):
            side_col = "side" if "side" in cols else None
            trade_filter = "WHERE action = 'T'" if (kind == "mbo" and "action" in cols) else ""
            signed = (f"sum(CASE WHEN {side_col} IN ('B','b') THEN size ELSE -size END)"
                      if side_col else "0")
            q = f"""
            SELECT {ts} AS minute,
                   {signed} / nullif(sum(size), 0)                       AS l2_flow_imb,
                   log10(count(*) + 1)                                    AS l2_quote_rate,
                   sum(size) / nullif(abs(max(price) - min(price)) * 10000 / nullif(avg(price), 0) + 1, 0)
                                                                          AS l2_absorption
            FROM '{path}' {trade_filter}
            GROUP BY 1 ORDER BY 1"""
        else:
            return {"error": f"kind '{kind}' has no book synthesis (ohlcv/unknown)"}
        df = con.execute(q).df()
    finally:
        con.close()
    if not len(df):
        return {"error": "synthesis produced no rows"}
    df["minute"] = pd.to_datetime(df["minute"], utc=True)
    for c in L2_COLUMNS:
        if c not in df.columns:
            df[c] = np.nan
    df = df[["minute", *L2_COLUMNS]]
    ver = "v1"
    FeatureStore().save(f"l2feat_{src['symbol']}", ver, df)
    for r in rows:
        if r["id"] == source_id:
            r["status"] = "synthesized"
            r["feature_rows"] = int(len(df))
            r["synthesized_at"] = pd.Timestamp.now("UTC").isoformat()
    _save(rows)
    from bot.audit import log as _audit
    _audit("l2_synthesized", id=source_id, symbol=src["symbol"], rows=int(len(df)))
    return {"id": source_id, "symbol": src["symbol"], "kind": kind, "feature_rows": int(len(df)),
            "span": [str(df['minute'].iloc[0])[:16], str(df['minute'].iloc[-1])[:16]]}


def synthesize_frame(df: pd.DataFrame, symbol: str, save: bool = True) -> dict:
    """Same synthesis for an UPLOADED (dragged) frame or a zip CHUNK — processed in memory, raw
    never written. Accepts mbp/trades-shaped frames with a ts column. save=False returns the
    per-minute frame (chunked zip synthesis re-aggregates and saves once)."""
    cols = [c.lower() for c in df.columns]
    df.columns = cols
    tcol = next((c for c in ("ts_event", "ts_recv", "ts", "timestamp", "time") if c in cols), None)
    if tcol is None:
        return {"error": f"no timestamp column in {cols[:10]}"}
    t = df[tcol]
    if np.issubdtype(t.dtype, np.number):
        # integer epoch — unit varies by vendor (Databento ns, others µs/ms/s): detect by
        # magnitude and view as datetime64 (unambiguous across pandas versions)
        v = t.astype("int64").to_numpy()
        mag = float(np.nanmedian(np.abs(v[v != 0]))) if (v != 0).any() else 0.0
        unit = "ns" if mag > 1e17 else "us" if mag > 1e14 else "ms" if mag > 1e11 else "s"
        minute = pd.Series(v.view(f"datetime64[{unit}]") if unit == "ns" else
                           v.astype(f"datetime64[{unit}]"),
                           index=t.index).dt.tz_localize("UTC").dt.floor("min")
    else:
        minute = pd.to_datetime(t, utc=True).dt.floor("min")
    out = pd.DataFrame({"minute": minute})
    if "bid_px_00" in cols and "ask_px_00" in cols:
        mid = (df["ask_px_00"] + df["bid_px_00"]) / 2.0
        out["l2_spread_bps"] = (df["ask_px_00"] - df["bid_px_00"]) / mid.replace(0, np.nan) * 10000
        tot = (df["bid_sz_00"] + df["ask_sz_00"]).replace(0, np.nan)
        out["l2_depth_imb"] = (df["bid_sz_00"] - df["ask_sz_00"]) / tot
        g = out.groupby("minute").agg(l2_spread_bps=("l2_spread_bps", "mean"),
                                      l2_depth_imb=("l2_depth_imb", "mean"))
        g["l2_quote_rate"] = np.log10(out.groupby("minute").size() + 1)
    elif "price" in cols and "size" in cols:
        sgn = df["side"].astype(str).str.upper().map({"B": 1.0}).fillna(-1.0) if "side" in cols else 0.0
        out["signed"] = df["size"] * sgn
        out["size"] = df["size"]
        g = out.groupby("minute").agg(signed=("signed", "sum"), size=("size", "sum"))
        g["l2_flow_imb"] = g["signed"] / g["size"].replace(0, np.nan)
        g["l2_quote_rate"] = np.log10(out.groupby("minute").size() + 1)
        g = g.drop(columns=["signed", "size"])
    else:
        return {"error": f"unrecognized upload shape: {cols[:10]}"}
    g = g.reset_index()
    for c in L2_COLUMNS:
        if c not in g.columns:
            g[c] = np.nan
    g = g[["minute", *L2_COLUMNS]]
    if not save:
        return {"symbol": symbol.upper(), "feature_rows": int(len(g)), "frame": g}
    FeatureStore().save(f"l2feat_{symbol.upper()}", "v1", g)
    return {"symbol": symbol.upper(), "feature_rows": int(len(g)),
            "span": [str(g['minute'].iloc[0])[:16], str(g['minute'].iloc[-1])[:16]]}


def attach_l2(df: pd.DataFrame, symbol: str) -> pd.DataFrame:
    """Left-join the symbol's synthesized l2_* features onto candidate rows by signal minute.
    No store -> the l2_* columns stay NaN (median-imputed at train time)."""
    try:
        feat = FeatureStore().load(f"l2feat_{symbol.upper()}", "v1")
    except FileNotFoundError:
        for c in L2_COLUMNS:
            df[c] = np.nan
        return df
    feat = feat.copy()
    feat["minute"] = pd.to_datetime(feat["minute"], utc=True)
    key = pd.to_datetime(df["ts"], utc=True).dt.floor("min")
    merged = df.copy()
    merged["__minute"] = key
    merged = merged.merge(feat, left_on="__minute", right_on="minute", how="left")
    return merged.drop(columns=["__minute", "minute"], errors="ignore")


if __name__ == "__main__":
    import sys
    if len(sys.argv) >= 2 and sys.argv[1] == "register":
        print(json.dumps(register(sys.argv[2], sys.argv[3] if len(sys.argv) > 3 else "NQ"), indent=1))
    elif len(sys.argv) >= 2 and sys.argv[1] == "sync":
        print(json.dumps(synthesize(sys.argv[2]), indent=1))
    else:
        print(json.dumps(sources(), indent=1))
