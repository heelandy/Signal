#!/usr/bin/env python3
"""
HIGHSTRIKE Phase 0.4 — Storage layer (multi-symbol).

One DuckDB query interface over the partitioned Parquet, so every downstream
stage (validation, signal gen, ML) reads bars the same way.

    data/hs.duckdb
      view <sym>_1m -> data/<sym>_continuous_1m.parquet   (continuous front-month 1m; nq_1m, es_1m, ...)
      view bars     -> data/bars/** (hive: sym, tf, session, year)

CLI:
    python hs_db.py                      # (re)build views + sanity report
    python hs_db.py "SELECT ... "        # run an ad-hoc query
Python:
    from hs_db import connect, bars
    con = connect()
    df  = bars(con, "5m", "rth", sym="ES", year=2022)
"""
import os, sys, glob
import duckdb

DB    = os.path.join("data", "hs.duckdb")
BARS  = os.path.join("data", "bars", "**", "*.parquet").replace("\\", "/")


def connect(db=":memory:"):
    # in-memory by default: the views are rebuilt from parquet on every connect (the on-disk DB stores
    # only view defs), so reads are identical AND lock-free — many processes can read concurrently.
    con = duckdb.connect(db)
    # one continuous-1m view per symbol found on disk
    for path in sorted(glob.glob(os.path.join("data", "*_continuous_1m.parquet"))):
        sym = os.path.basename(path).split("_")[0]          # nq, es, ...
        con.execute(f"CREATE OR REPLACE VIEW {sym}_1m AS "
                    f"SELECT * FROM read_parquet('{path.replace(chr(92), '/')}');")
    con.execute(f"CREATE OR REPLACE VIEW bars AS "
                f"SELECT * FROM read_parquet('{BARS}', hive_partitioning=true);")
    vix = os.path.join("data", "vix_daily.parquet")
    if os.path.exists(vix):                                  # front-month VX (macro vol)
        con.execute(f"CREATE OR REPLACE VIEW vix_daily AS "
                    f"SELECT * FROM read_parquet('{vix.replace(chr(92), '/')}');")
    return con


def bars(con, tf, session, sym="NQ", year=None):
    q = "SELECT * FROM bars WHERE sym=? AND tf=? AND session=?"
    args = [sym.upper(), tf, session]
    if year is not None:
        q += " AND year=?"; args.append(year)
    return con.execute(q + " ORDER BY ts", args).df()


def _report(con):
    syms = [r[0] for r in con.execute(
        "SELECT table_name FROM information_schema.tables "
        "WHERE table_name LIKE '%_1m' ORDER BY table_name").fetchall()]
    print("CONTINUOUS-1m VIEWS:", ", ".join(syms))
    for v in syms:
        # timestamp column differs by feed: futures store ts_utc, equities (QQQ/SPY) ts_et —
        # detect per view instead of assuming (data-QA fix 2026-07-04)
        cols = [r[0] for r in con.execute(f"DESCRIBE {v}").fetchall()]
        tcol = next((c for c in ("ts_utc", "ts_et", "ts") if c in cols), None)
        if tcol is None:
            print(f"  {v}: no timestamp column found (cols: {cols[:8]})")
            continue
        r = con.execute(f"SELECT count(*) n, min({tcol}) lo, max({tcol}) hi FROM {v}").df()
        print(f"  {v} [{tcol}]:", r.to_string(index=False, header=False))
    print("\nbars per sym/tf/session:")
    print(con.execute("""
        SELECT sym, tf, session, count(*) bars, min(year) y0, max(year) y1
        FROM bars GROUP BY sym, tf, session
        ORDER BY sym, session, CASE tf WHEN '5m' THEN 1 WHEN '15m' THEN 2 WHEN '30m' THEN 3
                                       WHEN '1h' THEN 4 WHEN '4h' THEN 5 ELSE 6 END
    """).df().to_string(index=False))
    print("\nexample — last daily-RTH bar per symbol:")
    print(con.execute("""
        SELECT sym, ts, open, high, low, close, volume
        FROM bars WHERE tf='1d' AND session='rth'
        QUALIFY row_number() OVER (PARTITION BY sym ORDER BY ts DESC) = 1
        ORDER BY sym
    """).df().to_string(index=False))


def main():
    con = connect()
    if len(sys.argv) > 1:
        print(con.execute(sys.argv[1]).df().to_string(index=False))
    else:
        _report(con)
    con.close()


if __name__ == "__main__":
    main()
