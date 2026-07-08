#!/usr/bin/env python3
"""OPRA CHAIN EXTRACTOR — compress the 13 GB QQQ options archive into ONE small parquet the
options study reads in seconds.

The archive (OPRA.PILLAR `cbbo-1m`, QQQ.OPT parent, 2026-05-27..06-25) ships each session as a
DIRECTORY named `opra-pillar-YYYYMMDD.cbbo-1m.csv/` holding one ~647 MB inner CSV. Per shard a
single memory-capped DuckDB pass keeps only what the study needs:

  * QUOTE rows — the file interleaves rtype-193 *definition* rows (empty bid/ask) with quotes;
    the discriminator is a POPULATED top-of-book, NOT the rtype (every row here is rtype 193).
  * expiry 0..30 days out (the tradable window)
  * strike within +-6% of that session's QQQ spot (read from our own bar store)
  * the OCC symbol parsed in SQL — fixed-width 21 chars: root[6] expiry[6] C/P[1] strike[8],
    e.g. `QQQ   260717C00545000` -> 2026-07-17 CALL strike 545.0

Output: data/opra_qqq_cbbo.parquet (minute, expiry, dte, cp, strike, bid, ask, mid, sizes, spot),
~10-30 MB. The raw 13 GB stays on D:, never copied (register-path law). Every study re-run then
reads the parquet in seconds instead of a fresh 13 GB pass.

    python research/opra_extract.py                     # auto-find the OPRA dir on D:
    python research/opra_extract.py "D:/OPRA-20260627-5VQCWWD67U"

Shards run one-per-subprocess (constant memory — the proven OOM-safe pattern).
"""
from __future__ import annotations

import glob
import re
import subprocess
import sys
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
PY = sys.executable
DTE_MAX = 30
STRIKE_PCT = 0.06
SHARD_DIR = ROOT / "data" / "opra_shards"
OUT = ROOT / "data" / "opra_qqq_cbbo.parquet"
UNDERLYING = "qqq"                                  # OPRA parent is QQQ.OPT


def _utf8_stdout() -> None:
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8", errors="backslashreplace")
        except Exception:
            pass


def _find_opra_dir() -> str | None:
    for base in ("D:/", "E:/", "C:/"):
        hits = sorted(glob.glob(base + "OPRA-*"))
        for h in hits:
            if Path(h).is_dir():
                return h
    return None


def _session_spots() -> dict[str, float]:
    """Per-session QQQ spot = median RTH close, for the +-6% strike window (coarse is fine)."""
    df = pd.read_parquet(ROOT / "data" / f"{UNDERLYING}_continuous_1m.parquet",
                         columns=["ts_et", "close", "session"])
    et = pd.to_datetime(df["ts_et"]).dt.tz_convert("America/New_York")
    rth = df[df["session"] == "RTH"].assign(date=et.dt.date)
    spots = rth.groupby("date")["close"].median()
    return {str(k): float(v) for k, v in spots.items()}


def _inner_csv(shard_dir: str) -> str | None:
    """The one big CSV inside a `*.csv/` shard directory (Databento day-split)."""
    inner = sorted(glob.glob(str(Path(shard_dir) / "*.csv")))
    if inner:
        return inner[0]
    files = [f for f in glob.glob(str(Path(shard_dir) / "*")) if Path(f).is_file()]
    return sorted(files)[0] if files else None


def extract_shard(inner: str, session_date: str, spot: float, out: str) -> int:
    """One memory-capped DuckDB pass: filter+parse the shard, write a compact parquet. TRY_CAST
    everywhere so a shard whose CSV sniffer typed a mostly-empty column as VARCHAR still parses."""
    import duckdb
    p = str(inner).replace("\\", "/")
    lo, hi = spot * (1 - STRIKE_PCT), spot * (1 + STRIKE_PCT)
    tmp = ROOT / "data" / "ml" / "duck_tmp"
    tmp.mkdir(parents=True, exist_ok=True)
    con = duckdb.connect()
    try:
        con.execute(f"SET memory_limit='1GB'; SET threads=1; SET preserve_insertion_order=false; "
                    f"SET temp_directory='{tmp.as_posix()}'")
        exp = "CAST(strptime('20' || substr(symbol, 7, 6), '%Y%m%d') AS DATE)"
        strike = "CAST(substr(symbol, 14, 8) AS INTEGER) / 1000.0"
        q = f"""
        COPY (
          WITH q AS (
            SELECT TRY_CAST(ts_recv AS TIMESTAMP)     AS minute,
                   symbol,
                   TRY_CAST(bid_px_00 AS DOUBLE)      AS bid,
                   TRY_CAST(ask_px_00 AS DOUBLE)      AS ask,
                   TRY_CAST(bid_sz_00 AS BIGINT)      AS bid_sz,
                   TRY_CAST(ask_sz_00 AS BIGINT)      AS ask_sz
            FROM read_csv_auto('{p}', sample_size=200000, ignore_errors=true)
          )
          SELECT minute,
                 {exp}                                          AS expiry,
                 datediff('day', DATE '{session_date}', {exp})  AS dte,
                 substr(symbol, 13, 1)                          AS cp,
                 {strike}                                       AS strike,
                 bid, ask, (bid + ask) / 2.0                    AS mid,
                 bid_sz, ask_sz,
                 CAST({spot} AS DOUBLE)                         AS spot,
                 DATE '{session_date}'                          AS session
          FROM q
          WHERE bid IS NOT NULL AND ask IS NOT NULL AND bid > 0 AND ask > bid
            AND length(symbol) >= 21
            AND substr(symbol, 13, 1) IN ('C', 'P')
            AND {strike} BETWEEN {lo} AND {hi}
            AND datediff('day', DATE '{session_date}', {exp}) BETWEEN 0 AND {DTE_MAX}
        ) TO '{str(out).replace(chr(92), '/')}' (FORMAT PARQUET);
        """
        con.execute(q)
        n = con.execute(f"SELECT count(*) FROM '{str(out).replace(chr(92), '/')}'").fetchone()[0]
        return int(n)
    finally:
        con.close()


def main(opra_dir: str | None = None) -> None:
    _utf8_stdout()
    opra_dir = opra_dir or _find_opra_dir()
    if not opra_dir or not Path(opra_dir).is_dir():
        print(f"OPRA dir not found ({opra_dir}); pass it explicitly."); return
    shards = sorted(d for d in glob.glob(str(Path(opra_dir) / "*.csv")) if Path(d).is_dir())
    print(f"=== OPRA EXTRACT {opra_dir} — {len(shards)} day-shards ===", flush=True)
    spots = _session_spots()
    SHARD_DIR.mkdir(parents=True, exist_ok=True)

    made, total = [], 0
    for d in shards:
        m = re.search(r"(\d{8})", Path(d).name)
        if not m:
            print(f"  ! {Path(d).name}: no date in name — skipped", flush=True); continue
        sd = f"{m.group(1)[:4]}-{m.group(1)[4:6]}-{m.group(1)[6:8]}"
        spot = spots.get(sd)
        if spot is None:
            print(f"  ! {sd}: no QQQ spot in bar store — skipped", flush=True); continue
        inner = _inner_csv(d)
        if not inner:
            print(f"  ! {sd}: no inner csv — skipped", flush=True); continue
        out = SHARD_DIR / f"opra_{sd}.parquet"
        r = subprocess.run([PY, __file__, "--shard", inner, sd, f"{spot:.4f}", str(out)],
                           capture_output=True, text=True, encoding="utf-8", errors="replace")
        n = 0
        if out.exists():
            try:
                n = len(pd.read_parquet(out, columns=["minute"]))
            except Exception:
                n = 0
        if r.returncode != 0 and n == 0:
            tail = (r.stderr or r.stdout or "").strip().splitlines()[-1:] or [""]
            print(f"  ! {sd}: extract failed rc={r.returncode} {tail[0][:120]}", flush=True); continue
        made.append(out)
        total += n
        print(f"  {sd}  spot~{spot:7.2f}  ->  {n:>7,} quote rows", flush=True)

    if not made:
        print("no shards extracted — nothing written."); return
    frames = [pd.read_parquet(f) for f in made]
    allf = pd.concat(frames, ignore_index=True).sort_values(["minute", "expiry", "strike", "cp"])
    allf.to_parquet(OUT, index=False)
    print(f"=== WROTE {OUT}  {len(allf):,} rows  {len(made)} sessions  "
          f"{allf['minute'].min()}..{allf['minute'].max()} ===", flush=True)


if __name__ == "__main__":
    if len(sys.argv) > 1 and sys.argv[1] == "--shard":
        _utf8_stdout()
        n = extract_shard(sys.argv[2], sys.argv[3], float(sys.argv[4]), sys.argv[5])
        print(f"shard {sys.argv[3]}: {n} rows")
    else:
        main(sys.argv[1] if len(sys.argv) > 1 else None)
