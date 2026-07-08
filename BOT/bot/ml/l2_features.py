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
import re
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


def _ts_expr(cols: list[str], con=None, path: str | None = None) -> str | None:
    """Minute-bucket expression for the file's timestamp column. PROBES the actual DuckDB type
    when a connection is given — DuckDB's CSV sniffer parses Databento's ISO ts_event straight to
    TIMESTAMPTZ, and dividing a timestamp by 1e9 was the Binder Error that failed all 51 MBO
    syncs (user 2026-07-05). Integer epochs get magnitude-based unit detection (ns/µs/ms/s)."""
    for c in ("ts_event", "ts_recv", "ts", "timestamp", "time"):
        if c not in cols:
            continue
        if con is not None and path is not None:
            try:
                t, v = con.execute(f"SELECT typeof({c}), {c} FROM '{path}' LIMIT 1").fetchone()
                tu = str(t).upper()
                if "TIMESTAMP" in tu or "DATE" in tu:
                    return f"date_trunc('minute', {c})"
                if "VARCHAR" in tu:
                    return f"date_trunc('minute', CAST({c} AS TIMESTAMP))"
                x = abs(float(v))
                div = 1e9 if x > 1e17 else 1e6 if x > 1e14 else 1e3 if x > 1e11 else 1.0
                return f"date_trunc('minute', to_timestamp({c} / {div}))"
            except Exception:
                pass
        return (f"date_trunc('minute', to_timestamp({c} / 1000000000.0))"
                if c.startswith("ts_") else f"date_trunc('minute', CAST({c} AS TIMESTAMP))")
    return None


DATA_EXTS = (".csv", ".csv.zst", ".csv.gz", ".parquet", ".zip")

# Folder scans registered at most 50 sources — which silently truncated a 2-year daily-trades
# intake to its first 50 sessions (found 2026-07-08). Raised well past a two-symbol × 2-year drop
# (~1000 files); the fingerprint dedup below keeps re-scans idempotent so the cap is a safety
# ceiling, not a limit anyone hits.
_FOLDER_SCAN_CAP = 5000

# Windows/OneDrive copy artifacts: `spy (1).csv`, `spy - Copy.csv`, `spy - Copy (2).csv`. Stripped
# so a copied file fingerprints identically to its original.
_COPY_SUFFIX_RE = re.compile(r"(\s*\(\d+\)|\s*-\s*copy(\s*\(\d+\))?)+$", re.IGNORECASE)


def _norm_basename(path: str) -> str:
    """Basename with the data extension AND Windows copy-suffixes removed: `spy (1).csv.zst` and
    `spy - Copy.csv.zst` both normalize to `spy`. Half of the content fingerprint."""
    name = Path(path).name.lower()
    for ext in sorted(DATA_EXTS, key=len, reverse=True):   # strip `.csv.zst` before `.csv`
        if name.endswith(ext):
            name = name[: -len(ext)]
            break
    return _COPY_SUFFIX_RE.sub("", name).strip()


def _fingerprint(path: str) -> list | None:
    """Content identity WITHOUT hashing gigabytes: [normalized basename, exact size in bytes].
    Databento basenames are unique per (venue, date, schema) and size pins the payload, so the
    same data entering via a second path (D: copy, ` (1)` twin, re-extracted zip) collides here
    and is recorded as a duplicate instead of being synthesized twice. None if it can't be stat'd
    (a moved legacy path) — such a row simply won't dedup, which is safe."""
    try:
        return [_norm_basename(path), int(Path(path).stat().st_size)]
    except OSError:
        return None


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


def detect_symbols(path: str, sample_rows: int = 200_000) -> list[str]:
    """AUTO-LABEL probe (user 2026-07-06: "synthesis filters and assigns the label instead of
    user selection"): distinct values of the file's `symbol` column over a bounded head sample
    (LIMIT stops the scan early — cheap even on a 67M-row day). [] = no symbol column/unreadable."""
    try:
        import duckdb
        con = duckdb.connect()
        try:
            con.execute("SET memory_limit='512MB'; SET threads=1")
            p = _duck_path(path)
            cols = _columns(path)
            if "symbol" not in cols:
                return []
            q = (f"SELECT DISTINCT symbol FROM (SELECT symbol FROM '{p}' LIMIT {sample_rows}) "
                 f"WHERE symbol IS NOT NULL")
            return sorted(str(s[0]).upper() for s in con.execute(q).fetchall())
        finally:
            con.close()
    except Exception:
        return []


def register(path: str, symbol: str | None = None) -> dict:
    """Register an on-disk L2/L3 file OR a whole FOLDER (auto-scans for data files, including
    zips — nothing is copied or extracted to disk). Run sync per source to synthesize.
    LABELING (2026-07-06): the file's own `symbol` column decides the label — one source row per
    symbol FOUND (multi-symbol venue files split; the synthesis filter isolates each). The
    `symbol` argument is only a FALLBACK for files without a symbol column (label_source shows
    which path was taken). This kills the mislabel class (QQQ ITCH data registered as NQ)."""
    p = Path(path)
    if not p.exists():
        return {"error": f"path not found: {path}"}
    if p.is_dir():                                   # AUTO-SCAN a folder (user 2026-07-05)
        found = []                                   # rglob descends into Databento dir-shaped
        for f in sorted(p.rglob("*")):               # `*.csv/` shards and registers the inner file
            name = f.name.lower()
            if f.is_file() and any(name.endswith(e) for e in DATA_EXTS):
                r = register(str(f), symbol)
                for s in (r.get("sources") or ([r] if "error" not in r else [])):
                    found.append({k: s.get(k) for k in ("id", "path", "symbol", "kind",
                                                        "size_mb", "status")})
            if len(found) >= _FOLDER_SCAN_CAP:
                break
        dups = sum(1 for s in found if s.get("status") == "duplicate")
        return {"folder": str(p), "registered": len(found), "duplicates": dups,
                "sources": found} if found else \
            {"error": f"no data files ({'/'.join(DATA_EXTS)}) found under {p}"}
    kind, cols = _detect_any(str(p))
    detected = detect_symbols(str(p)) if kind in ("mbo", "mbp", "trades") else []
    if detected:
        labels, label_source = detected, "auto"
        if symbol and symbol.upper() not in detected:
            label_source = f"auto (user pick {symbol.upper()} not in file — ignored)"
    elif symbol:
        labels, label_source = [symbol.upper()], "user"
    else:
        return {"error": "no symbol column in file and no fallback symbol given"}
    rows = _load()
    fp = _fingerprint(str(p))
    for r in rows:                                   # lazy backfill: rows registered before
        if not r.get("fingerprint") and r.get("path"):   # fingerprints existed get one now, so
            rfp = _fingerprint(r["path"])            # they can anchor a duplicate match
            if rfp:
                r["fingerprint"] = rfp
    size_bytes = int(p.stat().st_size)
    made = []
    from bot.audit import log as _audit
    for sym in labels:
        exact = next((r for r in rows if r.get("path") == str(p)
                      and str(r.get("symbol", "")).upper() == sym), None)
        if exact is not None:                        # same file+symbol is a no-op — repeated
            made.append(exact)                       # folder scans duplicated 12 files into 21
            continue                                 # registry rows (found 2026-07-06)
        twin = next((r for r in rows                 # SAME CONTENT via a DIFFERENT path — the D:
                     if fp and r.get("fingerprint") == fp   # copy, a ` (1)` twin, a re-extracted
                     and str(r.get("symbol", "")).upper() == sym   # zip: recorded but not re-synth'd
                     and r.get("status") != "duplicate"), None)
        src = {"id": uuid.uuid4().hex[:8], "path": str(p), "symbol": sym, "kind": kind,
               "size_mb": round(size_bytes / 1e6, 1), "size_bytes": size_bytes, "fingerprint": fp,
               "added_at": pd.Timestamp.now("UTC").isoformat(),
               "label_source": label_source,
               "zipped": str(p).lower().endswith(".zip"), "columns": cols[:24]}
        if twin is not None:                         # visible in the registry, never synthesized
            src["status"] = "duplicate"
            src["duplicate_of"] = twin["id"]
            _audit("l2_source_duplicate", id=src["id"], path=str(p), symbol=sym,
                   duplicate_of=twin["id"])
        else:
            src["status"] = "registered" if kind != "unknown" else "unknown_format"
            _audit("l2_source_registered", **{k: src[k] for k in ("id", "path", "symbol", "kind",
                                                                  "size_mb", "label_source")})
        rows.append(src)
        made.append(src)
    _save(rows)
    return made[0] if len(made) == 1 else {"path": str(p), "registered": len(made),
                                           "sources": made}


def sources() -> list[dict]:
    return _load()


def synthesize(source_id: str, tf_minutes: int = 1) -> dict:
    """DuckDB aggregation DIRECTLY against the registered path -> per-minute l2_* features
    saved to the FeatureStore as `l2feat_{symbol}` (only the features persist)."""
    rows = _load()
    src = next((r for r in rows if r["id"] == source_id), None)
    if src is None:
        return {"error": f"unknown source {source_id}"}
    if src.get("status") == "duplicate":             # content already synthesized via its twin
        return {"skipped": "duplicate", "duplicate_of": src.get("duplicate_of"),
                "symbol": src.get("symbol")}
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
                _save_merged(src['symbol'], allf)
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
    kind = src["kind"]
    con = duckdb.connect()
    try:    # bounded memory (ops 2026-07-06): a 67M-row day OOM'd next to training — spill instead.
        # 1GB/1 thread: this box also runs the always-on server; preserve_insertion_order=false
        # lets the GROUP BY stream without buffering the scan order.
        tmp = BOT_ROOT / "data" / "ml" / "duck_tmp"
        tmp.mkdir(parents=True, exist_ok=True)
        con.execute(f"SET memory_limit='1GB'; SET threads=1; SET preserve_insertion_order=false; "
                    f"SET temp_directory='{tmp.as_posix()}'")
    except Exception:
        pass
    ts = _ts_expr(cols, con, path)      # type-probed (TIMESTAMPTZ vs int epoch vs ISO string)
    if ts is None:
        con.close()
        return {"error": f"no timestamp column found in {cols[:10]}"}
    try:
        # INSTRUMENT FILTER (2026-07-06 misconfig sweep): full-venue files carry many tickers —
        # aggregate ONLY the registered symbol's rows (an unfiltered venue file made "QQQ"
        # features out of the whole tape). A mislabeled source now errors instead of mixing.
        symf = f"symbol = '{str(src['symbol']).upper()}'" if "symbol" in cols else None
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
            FROM '{path}' WHERE bid_px_00 > 0 AND ask_px_00 > 0{' AND ' + symf if symf else ''}
            GROUP BY 1 ORDER BY 1"""
        elif kind in ("mbo", "trades"):
            side_col = "side" if "side" in cols else None
            conds = [c for c in (("action = 'T'" if (kind == "mbo" and "action" in cols) else None),
                                 symf) if c]
            trade_filter = ("WHERE " + " AND ".join(conds)) if conds else ""
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
    store_rows = _save_merged(src['symbol'], df)
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
    # INSTRUMENT FILTER (2026-07-06 misconfig sweep): full-venue files carry many tickers — keep
    # only the registered symbol's rows. Zero rows after the filter SURFACES a mislabeled source
    # (e.g. QQQ ITCH data registered as NQ) instead of silently attaching wrong-instrument flow.
    if "symbol" in cols:
        df = df[df["symbol"].astype(str).str.upper() == symbol.upper()]
        if not len(df):
            return {"error": f"no rows for symbol {symbol.upper()} — source mislabeled?"}
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
    _save_merged(symbol.upper(), g)
    return {"symbol": symbol.upper(), "feature_rows": int(len(g)),
            "span": [str(g['minute'].iloc[0])[:16], str(g['minute'].iloc[-1])[:16]]}


def _save_merged(symbol: str, df: pd.DataFrame) -> int:
    """APPEND-MERGE a synthesis result into the symbol's store. Each source file covers ONE day —
    a plain save clobbered the previous days, so 51 synced files left a 1-day store (bug found
    2026-07-06 on the first full sync). Dedup by minute keeps the newest synthesis."""
    fs = FeatureStore()
    df = df.copy()
    df["minute"] = pd.to_datetime(df["minute"], utc=True)
    try:
        old = fs.load(f"l2feat_{symbol}", "v1")
        old["minute"] = pd.to_datetime(old["minute"], utc=True)
        df = pd.concat([old, df], ignore_index=True)
    except FileNotFoundError:
        pass
    df = df.drop_duplicates("minute", keep="last").sort_values("minute").reset_index(drop=True)
    fs.save(f"l2feat_{symbol}", "v1", df)
    return int(len(df))


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
    # the PIT snapshot already carries NaN l2_* placeholder columns — drop them BEFORE the merge
    # or pandas suffixes both sides to l2_*_x/_y and the schema reader sees 100% NaN (bug found
    # 2026-07-06 on the first real post-sync rebuild)
    merged = df.drop(columns=[c for c in L2_COLUMNS if c in df.columns]).copy()
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
