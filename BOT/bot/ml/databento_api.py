"""On-demand Databento MBP-10 depth features — no bulk download, no raw data on disk.

The full MBP-10 batch for the window is ~413 GB; we have neither the disk nor the budget for it.
But the model only joins depth at each candidate's SIGNAL MINUTE, so we stream just the narrow
CAUSAL window [signal - W, signal) per candidate via the Databento Historical API, aggregate the
l2_* depth features in memory, and persist ONLY those (a few KB total). Raw book data never lands.

Cost-safe: every run is preceded by a FREE cost quote (metadata.get_cost) and ABORTS if the total
would exceed `budget`. The 79 candidates over 2026-01-08..2026-05-08 quote at ~$9 (mbp-10, 15-min
windows) — vs $83 of credit.

Causal by construction: each window is aggregated into ONE row keyed at floor(signal) but computed
from data strictly BEFORE the signal — no lookahead. attach_l2 then joins it like any l2_* feature.

    from bot.ml.databento_api import estimate_cost, backfill_depth_api
    estimate_cost("NQ")                      # free $ quote
    backfill_depth_api("NQ", budget=6.0)     # stream -> synth -> merge into l2feat_NQ
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from bot.config import settings
from bot.ml.registry import FeatureStore

WINDOW = ("2026-01-08", "2026-05-08")          # the MBP-10 purchase window
# Depth-only columns we OWN. l2_quote_rate is left to the flow synthesis (it means trade-rate there);
# writing a book-update rate into that same column would give it two definitions across rows.
DEPTH_COLS = ["l2_spread_bps", "l2_depth_imb", "l2_book_pressure"]


def _client():
    import databento as db
    return db.Historical(settings.require_databento())


def _retry(fn, tries: int = 4, base: float = 1.5):
    """Databento's host resets connections under load — retry with exponential backoff so one blip
    doesn't abort a whole symbol (the failure mode on the first run: SPY/NQ/ES lost to timeouts)."""
    import time
    last = None
    for k in range(tries):
        try:
            return fn()
        except Exception as e:                 # network layer: ConnectTimeout / ConnectionReset / ...
            last = e
            if k < tries - 1:
                time.sleep(base * (2 ** k))    # 1.5s, 3s, 6s (no sleep after the final try)
    raise last


def _route(sym: str):
    """(dataset, symbols, stype_in) — futures use continuous front-month symbology so a window can
    never straddle two contract months."""
    s = sym.upper()
    return {"QQQ": ("XNAS.ITCH", ["QQQ"], "raw_symbol"),
            "SPY": ("XNAS.ITCH", ["SPY"], "raw_symbol"),
            "NQ": ("GLBX.MDP3", ["NQ.c.0"], "continuous"),
            "ES": ("GLBX.MDP3", ["ES.c.0"], "continuous")}[s]


def _candidates(sym: str, lo=WINDOW[0], hi=WINDOW[1]) -> list[pd.Timestamp]:
    from bot.ml.dataset import load_or_build
    df = load_or_build(sym, "5m")
    if not len(df):
        return []
    ts = pd.to_datetime(df["ts"], utc=True)
    lo_t, hi_t = pd.Timestamp(lo, tz="UTC"), pd.Timestamp(hi, tz="UTC")
    return sorted(ts[(ts >= lo_t) & (ts <= hi_t)].tolist())


def estimate_cost(sym: str, window_min: int = 15, lo=WINDOW[0], hi=WINDOW[1]) -> dict:
    """FREE per-window cost quotes summed over the symbol's candidates. Spends nothing."""
    ds, symbols, st = _route(sym)
    cli = _client()
    W = pd.Timedelta(minutes=window_min)
    cands = _candidates(sym, lo, hi)
    total = 0.0
    for t in cands:
        total += float(_retry(lambda t=t: cli.metadata.get_cost(dataset=ds, symbols=symbols,
                        schema="mbp-10", start=(t - W).isoformat(), end=t.isoformat(), stype_in=st)))
    return {"symbol": sym, "candidates": len(cands), "est_usd": round(total, 4)}


def _synth_window(df: pd.DataFrame, signal_ts: pd.Timestamp) -> dict | None:
    """Aggregate one MBP-10 window into a single CAUSAL depth row keyed at floor(signal). Ratios so
    price scaling is irrelevant; sizes null-safe. None if the window has no two-sided book."""
    if df is None or not len(df):
        return None
    df = df.rename(columns={c: c.lower() for c in df.columns})
    if "bid_px_00" not in df.columns or "ask_px_00" not in df.columns:
        return None
    df = df[(df["bid_px_00"] > 0) & (df["ask_px_00"] > 0) & (df["ask_px_00"] >= df["bid_px_00"])]
    if not len(df):
        return None
    # Databento to_df returns sizes as UNSIGNED ints — `bid_sz - ask_sz` underflows to ~4e9 when
    # ask > bid. Cast every size column to float64 before any subtraction (found on window #1).
    df = df.copy()
    for c in [c for c in df.columns if c.startswith(("bid_sz_", "ask_sz_"))]:
        df[c] = df[c].astype("float64")
    mid = (df["ask_px_00"] + df["bid_px_00"]) / 2.0
    spread_bps = (df["ask_px_00"] - df["bid_px_00"]) / mid.replace(0, np.nan) * 10000
    top = (df["bid_sz_00"] + df["ask_sz_00"]).replace(0, np.nan)
    depth_imb = (df["bid_sz_00"] - df["ask_sz_00"]) / top
    lvl10 = "bid_sz_09" in df.columns and "ask_sz_09" in df.columns
    if lvl10:
        deep_b = sum(df[f"bid_sz_0{i}"].fillna(0) for i in range(10))
        deep_a = sum(df[f"ask_sz_0{i}"].fillna(0) for i in range(10))
    else:
        deep_b, deep_a = df["bid_sz_00"].fillna(0), df["ask_sz_00"].fillna(0)
    denom = float((deep_b + deep_a).mean())
    return {"minute": pd.Timestamp(signal_ts).tz_convert("UTC").floor("min"),
            "l2_spread_bps": float(spread_bps.mean()),
            "l2_depth_imb": float(depth_imb.mean()),
            "l2_book_pressure": float((deep_b - deep_a).mean() / denom) if denom else np.nan}


def fetch_window(sym: str, signal_ts: pd.Timestamp, window_min: int = 15) -> dict | None:
    """SPENDS: stream the [signal - window, signal) MBP-10 window and synthesize its depth row."""
    ds, symbols, st = _route(sym)
    cli = _client()
    t = pd.Timestamp(signal_ts).tz_convert("UTC")

    def _pull():
        data = cli.timeseries.get_range(dataset=ds, symbols=symbols, schema="mbp-10",
                                        start=(t - pd.Timedelta(minutes=window_min)).isoformat(),
                                        end=t.isoformat(), stype_in=st)
        return data.to_df()                    # in memory; raw never written to disk
    try:
        df = _retry(_pull)
    except Exception:
        return None
    return _synth_window(df, t)


def _merge_depth(sym: str, depth: pd.DataFrame) -> int:
    """Column-merge the depth rows into l2feat_{SYM} by minute WITHOUT clobbering existing flow
    columns (l2_flow_imb/absorption). New depth values win where present."""
    from bot.ml.l2_features import L2_COLUMNS
    fs = FeatureStore()
    depth = depth.copy()
    depth["minute"] = pd.to_datetime(depth["minute"], utc=True)
    try:
        old = fs.load(f"l2feat_{sym.upper()}", "v1")
        old["minute"] = pd.to_datetime(old["minute"], utc=True)
    except FileNotFoundError:
        old = pd.DataFrame(columns=["minute", *L2_COLUMNS])
    m = old.merge(depth, on="minute", how="outer", suffixes=("", "__n"))
    for c in DEPTH_COLS:
        n = f"{c}__n"
        if n in m.columns:
            m[c] = m[n].combine_first(m[c]) if c in m.columns else m[n]
            m = m.drop(columns=[n])
    for c in L2_COLUMNS:
        if c not in m.columns:
            m[c] = np.nan
    m = m.sort_values("minute").reset_index(drop=True)
    fs.save(f"l2feat_{sym.upper()}", "v1", m)
    return int(depth["minute"].nunique())


def backfill_depth_api(sym: str, window_min: int = 15, lo=WINDOW[0], hi=WINDOW[1],
                       budget: float = 12.0, known_cost: float | None = None,
                       max_windows: int | None = None, pause: float = 0.25,
                       verbose: bool = True) -> dict:
    """Budget-check -> stream+synthesize each window (retry-resilient, per-window isolated) -> merge.
    `known_cost`: skip the redundant live re-estimate when the quote is already known. `max_windows`
    bounds paid pulls; `pause` throttles requests to avoid the connection resets seen on run #1."""
    import time
    est_usd = known_cost if known_cost is not None else estimate_cost(sym, window_min, lo, hi)["est_usd"]
    if est_usd > budget:
        return {"aborted": True, "reason": f"estimate ${est_usd} > budget ${budget}", "est_usd": est_usd}
    cands = _candidates(sym, lo, hi)
    if max_windows:
        cands = cands[:max_windows]
    rows, ok, empty = [], 0, 0
    for i, t in enumerate(cands, 1):
        try:
            r = fetch_window(sym, t, window_min)   # already retry-wrapped; returns None on hard fail
        except Exception:
            r = None
        if r:
            rows.append(r); ok += 1
        else:
            empty += 1
        if pause:
            time.sleep(pause)
        if verbose and i % 5 == 0:
            print(f"  [{sym}] {i}/{len(cands)} windows, {ok} with depth", flush=True)
    merged = _merge_depth(sym, pd.DataFrame(rows)) if rows else 0
    return {"symbol": sym, "pulled": len(cands), "with_depth": ok, "empty": empty,
            "minutes_merged": merged, "est_usd": est_usd}


if __name__ == "__main__":
    import sys, json
    if len(sys.argv) >= 3 and sys.argv[1] == "backfill":
        print(json.dumps(backfill_depth_api(sys.argv[2],
              max_windows=int(sys.argv[3]) if len(sys.argv) > 3 else None), indent=1, default=str))
    elif len(sys.argv) >= 3 and sys.argv[1] == "estimate":
        print(json.dumps(estimate_cost(sys.argv[2]), indent=1))
    else:
        print("usage: python -m bot.ml.databento_api estimate|backfill SYM [max_windows]")
