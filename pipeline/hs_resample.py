#!/usr/bin/env python3
"""
HIGHSTRIKE Phase 0.3 — Resample once.

Reads data/nq_continuous_1m.parquet and produces 5m/15m/30m/1h/4h/D bars for
both FULL session and RTH, persisted as ONE hive-partitioned Parquet dataset:

    data/bars/tf=<tf>/session=<full|rth>/year=<YYYY>/part-*.parquet

Anchoring (matches a CME-trade-day TradingView chart):
  * full session   -> intraday bins tiled from 18:00 ET (session open);
                      daily bar = CME trade-day (18:00 ET prev -> 17:00 ET).
  * RTH            -> intraday bins tiled from 09:30 ET (cash open);
                      daily bar = one 09:30-16:00 ET candle per date.
All anchors are constants below — change once if Phase-1 reconcile demands.

OHLCV aggregation: open=first, high=max, low=min, close=last, volume=sum.
Carries adj_factor=last (adjusted price = raw*adj_factor) and is_roll=any.

Usage: python hs_resample.py
"""
import os, sys, glob, shutil
import pandas as pd, numpy as np

ET        = "America/New_York"
SYM       = (sys.argv[1] if len(sys.argv) > 1 else "nq").upper()   # symbol namespace
SRC       = os.path.join("data", f"{SYM.lower()}_continuous_1m.parquet")
OUTROOT   = os.path.join("data", "bars")
TFS       = {"5m": "5min", "15m": "15min", "30m": "30min",
             "1h": "60min", "4h": "240min"}      # intraday; daily handled separately
FULL_ORIGIN = pd.Timestamp("2010-01-01 18:00", tz=ET)   # CME session open
RTH_ORIGIN  = pd.Timestamp("2010-01-01 09:30", tz=ET)   # cash open

AGG = {"open": "first", "high": "max", "low": "min", "close": "last",
       "volume": "sum", "adj_factor": "last", "is_roll": "any"}


def _finish(df, tf, session):
    """Drop empty resample bins, tag tf/session/year, normalise ts dtype."""
    df = df.dropna(subset=["open"]).reset_index().rename(columns={"ts_et": "ts"})
    df["volume"]  = df["volume"].astype("int64")
    df["is_roll"] = df["is_roll"].fillna(False).astype(bool)
    df["year"]    = df["ts"].dt.year.astype("int32")          # ET year (bins are ET-anchored)
    df["ts"]      = df["ts"].dt.tz_convert("UTC").dt.as_unit("ns")  # uniform instant for concat
    df["tf"], df["session"] = tf, session
    return df


def resample_intraday(src, freq, origin, tf, session):
    g = src.set_index("ts_et").resample(freq, origin=origin, label="left", closed="left")
    return _finish(g.agg(AGG), tf, session)


def resample_daily(src, session):
    if session == "rth":
        key = src["ts_et"].dt.date                       # cash calendar date
    else:
        key = (src["ts_et"] + pd.Timedelta(hours=6)).dt.date   # CME trade-day (18:00 ET)
    out = src.groupby(key).agg(AGG)
    out.index = pd.to_datetime(list(out.index)).tz_localize(ET)
    out.index.name = "ts_et"
    return _finish(out, "1d", session)


def main():
    print(f"reading {SRC} ...")
    df = pd.read_parquet(SRC, columns=["ts_et", "open", "high", "low", "close",
                                       "volume", "adj_factor", "is_roll", "session"])
    df["ts_et"] = pd.to_datetime(df["ts_et"])
    full = df.drop(columns="session")
    rth  = df[df["session"] == "RTH"].drop(columns="session")
    print(f"  full {len(full):,} bars · rth {len(rth):,} bars")

    sym_dir = os.path.join(OUTROOT, f"sym={SYM}")
    if os.path.isdir(sym_dir):
        # ROBUST RMTREE (bug hunt 2026-07-12): historical partition dirs can carry the Windows
        # READ-ONLY attribute (git/backup artifact) -> plain rmtree fails WinError 5 (Access
        # denied) on rmdir. Clear the bit and retry per-path. NQ resampled only because its dirs
        # had already been rewritten; QQQ/SPY/ES/GC (untouched since the historical build) were
        # deterministically blocked. This bit the live-persister's hive refresh.
        import stat as _stat

        def _onerr(func, path, _exc):
            os.chmod(path, _stat.S_IWRITE)
            func(path)
        try:
            shutil.rmtree(sym_dir, onexc=_onerr)          # py3.12+
        except TypeError:
            shutil.rmtree(sym_dir, onerror=_onerr)        # py<3.12

    frames = []
    for tf, freq in TFS.items():
        f_full = resample_intraday(full, freq, FULL_ORIGIN, tf, "full")
        f_rth  = resample_intraday(rth,  freq, RTH_ORIGIN,  tf, "rth")
        frames += [f_full, f_rth]
        print(f"  {tf:>4}  full {len(f_full):>9,}   rth {len(f_rth):>9,}")
    d_full = resample_daily(full, "full")
    d_rth  = resample_daily(rth,  "rth")
    frames += [d_full, d_rth]
    print(f"  {'1d':>4}  full {len(d_full):>9,}   rth {len(d_rth):>9,}")

    bars = pd.concat(frames, ignore_index=True)
    bars["sym"] = SYM
    bars = bars[["sym", "ts", "tf", "session", "year", "open", "high", "low",
                 "close", "volume", "adj_factor", "is_roll"]]
    bars.to_parquet(OUTROOT, partition_cols=["sym", "tf", "session", "year"], index=False)

    n_files = len(glob.glob(os.path.join(OUTROOT, "**", "*.parquet"), recursive=True))
    print(f"\nWROTE {len(bars):,} bars -> {OUTROOT}/  ({n_files} partition files)")
    print("\nPER-TF / SESSION COUNTS:")
    print(bars.groupby(["tf", "session"]).size().unstack(fill_value=0).to_string())
    # spot sanity: daily RTH should be ~one bar per trading day
    drth = bars[(bars.tf == "1d") & (bars.session == "rth")]
    print(f"\ndaily-RTH bars: {len(drth):,}  span {drth.ts.min()} .. {drth.ts.max()}")
    print(drth.tail(3)[["ts", "open", "high", "low", "close", "volume"]].to_string(index=False))


if __name__ == "__main__":
    main()
