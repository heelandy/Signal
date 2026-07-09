"""Deep order-flow features for TRAINING — the depth half the l2_features flow path can't produce.

`bot/ml/l2_features` only pulls TRADE prints from an MBO file, so `l2_depth_imb` / `l2_book_pressure`
come out 100% NaN even on the QQQ L3 we hold. Here we use the real L3 book reconstruction in
`bot/orderflow` (replay every add/cancel/modify, maintain the book) and summarise the book state
LEADING UP TO each signal into `of_*` features, then join them onto the ORB candidate set exactly
like `attach_l2`.

CAUSAL by construction: the window ENDS at the signal minute — `[entry − window, entry]` — so the
features describe the book the model would have seen at (not after) entry. No lookahead.

HEAVY: L3 replay costs ~1 min of wall-clock per candidate, and only QQQ has L3 on disk today
(2024-07 → 2026-06). So results CACHE to a FeatureStore parquet keyed by (symbol, minute); a
symbol with no store just gets NaN `of_*` (median-imputed at train time), same contract as L2.

    from bot.ml.deep_orderflow import candidate_features, backfill_deep, attach_deep
    candidate_features("QQQ", ts)     # one candidate's of_* vector (live L3 replay)
    backfill_deep("QQQ")              # one-time: replay every covered candidate -> cache
    df = attach_deep(df, "QQQ")       # join of_* onto the dataset
"""
from __future__ import annotations

import re
from pathlib import Path

import numpy as np
import pandas as pd

from bot.ml.registry import FeatureStore

ET = "America/New_York"
RTH_OPEN = "09:30"

# The of_* training columns (aggregates of the per-second book snapshots over the pre-signal window).
OF_COLUMNS = ["of_qi_mean", "of_qi_last", "of_ofi_sum", "of_aci_mean", "of_mlofi_mean", "of_dmu_mean"]


def _covered_dates(symbol: str) -> set[str]:
    """The YYYY-MM-DD dates for which an L3 MBO file exists on disk for `symbol` (so a candidate
    outside this set is skipped rather than reconstructed from nothing)."""
    from bot.config import settings
    try:
        d = Path(settings.mbo_dir_for(symbol))
    except Exception:
        return set()
    if not d.is_dir():
        return set()
    out = set()
    for f in d.iterdir():
        m = re.search(r"(20\d{6})", f.name)
        if m and ".mbo" in f.name.lower():
            s = m.group(1)
            out.add(f"{s[:4]}-{s[4:6]}-{s[6:8]}")
    return out


def candidate_features(symbol: str, ts, window_min: int = 15, every_ms: int = 1000) -> dict | None:
    """Replay the L3 book over the CAUSAL pre-signal window [entry − window_min, entry] (clamped to
    the RTH open) and aggregate the deep features into one of_* vector. None if the window has no
    reconstructable book (missing file / pre-market-only / empty)."""
    from bot.orderflow.deep import deep_book_features
    et = pd.Timestamp(ts)
    et = et.tz_localize("UTC").tz_convert(ET) if et.tz is None else et.tz_convert(ET)
    t1 = et.strftime("%H:%M")
    t0_dt = et - pd.Timedelta(minutes=window_min)
    open_dt = et.normalize() + pd.Timedelta(hours=9, minutes=30)
    if t0_dt < open_dt:                       # never reach into the pre-market book
        t0_dt = open_dt
    t0 = t0_dt.strftime("%H:%M")
    if t0 >= t1:                              # signal at/near the open — nothing before it to summarise
        return None
    try:
        bk = deep_book_features(et.strftime("%Y-%m-%d"), (t0, t1), every_ms=every_ms, symbol=symbol)
    except Exception:
        return None
    if bk is None or not len(bk):
        return None
    return {"of_qi_mean": float(bk["qi"].mean()),
            "of_qi_last": float(bk["qi"].iloc[-1]),
            "of_ofi_sum": float(bk["ofi"].sum()),
            "of_aci_mean": float(bk["aci"].mean()),
            "of_mlofi_mean": float(bk["mlofi"].mean()),
            "of_dmu_mean": float(bk["dmu"].mean())}


def _candidate_minutes(symbol: str) -> pd.DataFrame:
    """(ts) of every executed ORB candidate for `symbol`, WITHOUT the deep join (no recursion) —
    from the cached dataset if present, else a fresh build (attach_deep returns NaN when the store
    is empty, so building here is safe)."""
    from bot.ml.dataset import build
    df = build(symbol, include_live=False, save=False)
    return df[["ts"]].copy() if len(df) else pd.DataFrame(columns=["ts"])


def backfill_deep(symbol: str = "QQQ", window_min: int = 15, every_ms: int = 1000,
                  limit: int | None = None, verbose: bool = True) -> dict:
    """One-time L3 reconstruction over every covered candidate minute -> cache to deepof_{SYM} v1.
    Only dates with an MBO file on disk are attempted. HEAVY (~1 min/candidate); run when the
    server is idle. `limit` caps the number of candidates (for a bounded first pass)."""
    cand = _candidate_minutes(symbol)
    if not len(cand):
        return {"symbol": symbol, "error": "no candidates"}
    covered = _covered_dates(symbol)
    ts_all = pd.to_datetime(cand["ts"], utc=True)
    todo = [t for t in ts_all if t.tz_convert(ET).strftime("%Y-%m-%d") in covered]
    if limit:
        todo = todo[-limit:]                  # most-recent first when bounded
    rows, done = [], 0
    for t in todo:
        f = candidate_features(symbol, t, window_min, every_ms)
        done += 1
        if f:
            rows.append({"minute": t.floor("min"), **f})
        if verbose and done % 10 == 0:
            print(f"  [{symbol}] {done}/{len(todo)} candidates, {len(rows)} with features")
    df = pd.DataFrame(rows)
    if len(df):
        FeatureStore().save(f"deepof_{symbol.upper()}", "v1", df)
    return {"symbol": symbol, "candidates_total": int(len(ts_all)),
            "covered_attempted": len(todo), "feature_rows": int(len(df)),
            "span": [str(df["minute"].min())[:16], str(df["minute"].max())[:16]] if len(df) else None}


def attach_deep(df: pd.DataFrame, symbol: str) -> pd.DataFrame:
    """Left-join the symbol's cached of_* features onto candidate rows by signal minute. No store
    -> the of_* columns stay NaN (median-imputed at train time). Mirrors attach_l2."""
    try:
        feat = FeatureStore().load(f"deepof_{symbol.upper()}", "v1")
    except FileNotFoundError:
        for c in OF_COLUMNS:
            df[c] = np.nan
        return df
    feat = feat.copy()
    feat["minute"] = pd.to_datetime(feat["minute"], utc=True)
    key = pd.to_datetime(df["ts"], utc=True).dt.floor("min")
    merged = df.drop(columns=[c for c in OF_COLUMNS if c in df.columns]).copy()
    merged["__minute"] = key
    merged = merged.merge(feat, left_on="__minute", right_on="minute", how="left")
    return merged.drop(columns=["__minute", "minute"], errors="ignore")


if __name__ == "__main__":
    import sys
    if len(sys.argv) >= 2 and sys.argv[1] == "backfill":
        sym = sys.argv[2] if len(sys.argv) > 2 else "QQQ"
        lim = int(sys.argv[3]) if len(sys.argv) > 3 else None
        import json
        print(json.dumps(backfill_deep(sym, limit=lim), indent=1))
    else:
        print("usage: python -m bot.ml.deep_orderflow backfill QQQ [limit]")
