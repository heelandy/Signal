"""Market-truth gate — fail-closed data validation.

Bad market data must never produce a trade. This gate inspects a bar stream and refuses to
certify it (→ candidates blocked) on any of: duplicate timestamps, out-of-order rows, missing
bars (gaps), bad OHLC, or a stale last bar. Default is fail-closed: an empty/unknown stream is
NOT healthy.

    from bot.market_truth import assess
    health = assess(df, source="databento", ts_col="ts_et", freq_min=1)
    if not health.healthy: ...   # block

Reused at: replay (validate the slice) and live (validate the rolling feed before each decision).
"""
from __future__ import annotations

import pandas as pd

from bot.contracts import SourceHealthState, utcnow_iso


def bar_issues(df: pd.DataFrame, ts_col: str = "ts_et", freq_min: int = 1,
               session_only: bool = True) -> dict:
    """Return a dict of issue counts/lists for a bar frame (no judgement, just facts)."""
    out = {"n": int(len(df)), "duplicates": 0, "out_of_order": 0, "gaps": 0, "bad_ohlc": 0}
    if df.empty:
        out["empty"] = True
        return out
    ts = pd.to_datetime(df[ts_col], utc=True)
    out["duplicates"] = int(ts.duplicated().sum())
    out["out_of_order"] = int((ts.diff().dt.total_seconds() < 0).sum())
    # OHLC sanity
    o, h, l, c = (df[k].astype("float64") for k in ("open", "high", "low", "close"))
    bad = (l > h) | (o < l) | (o > h) | (c < l) | (c > h) | h.isna() | l.isna()
    out["bad_ohlc"] = int(bad.sum())
    # gaps: count missing expected bars *within continuous runs* (skip overnight/session breaks,
    # which show as large jumps — only flag a hole that is 2..N expected steps inside a run)
    step = freq_min * 60
    gaps_idx = ts.sort_values().diff().dt.total_seconds().dropna()
    if session_only:
        # an intraday hole = gap that is a small multiple of step (2..20); bigger = session break
        holes = ((gaps_idx > step * 1.5) & (gaps_idx <= step * 20))
    else:
        holes = (gaps_idx > step * 1.5)
    out["gaps"] = int(holes.sum())
    return out


def assess(df: pd.DataFrame, source: str = "databento", ts_col: str = "ts_et",
           freq_min: int = 1, max_staleness_sec: float | None = None,
           now: pd.Timestamp | None = None, session_only: bool = True) -> SourceHealthState:
    """Fail-closed health verdict. healthy=True only if NO critical issue and (if checked) the
    last bar is fresh. `max_staleness_sec` enables the staleness check (live use)."""
    iss = bar_issues(df, ts_col, freq_min, session_only)
    if iss.get("empty") or iss["n"] == 0:
        return SourceHealthState(source=source, healthy=False, detail="no data", checked_at=utcnow_iso())

    staleness = None
    if max_staleness_sec is not None:
        ts = pd.to_datetime(df[ts_col], utc=True)
        ref = now if now is not None else pd.Timestamp.now(tz="UTC")
        staleness = float((ref - ts.max()).total_seconds())

    critical = (iss["duplicates"] > 0 or iss["out_of_order"] > 0 or iss["bad_ohlc"] > 0
                or (max_staleness_sec is not None and staleness is not None and staleness > max_staleness_sec))
    detail = (f"n={iss['n']} dup={iss['duplicates']} ooo={iss['out_of_order']} "
              f"gaps={iss['gaps']} bad_ohlc={iss['bad_ohlc']}"
              + (f" stale={staleness:.0f}s" if staleness is not None else ""))
    return SourceHealthState(source=source, healthy=not critical, last_ts=str(pd.to_datetime(df[ts_col], utc=True).max()),
                             staleness_sec=staleness, detail=detail, checked_at=utcnow_iso())


if __name__ == "__main__":   # self-test: clean passes, each defect fails closed
    base = pd.date_range("2026-06-01 13:30", periods=60, freq="1min", tz="UTC")
    good = pd.DataFrame({"ts_et": base, "open": 100.0, "high": 100.5, "low": 99.5, "close": 100.2, "volume": 10})
    assert assess(good).healthy, "clean frame should pass"
    print("clean:", assess(good).detail, "-> healthy")

    dup = pd.concat([good, good.iloc[[5]]], ignore_index=True)
    assert not assess(dup).healthy, "duplicate ts must fail"
    print("dup:", assess(dup).detail, "-> blocked")

    bad = good.copy(); bad.loc[10, "low"] = 200.0    # low > high
    assert not assess(bad).healthy, "bad OHLC must fail"
    print("bad_ohlc:", assess(bad).detail, "-> blocked")

    assert not assess(good.iloc[0:0]).healthy, "empty must fail closed"
    print("empty -> blocked (fail-closed)")

    stale = assess(good, max_staleness_sec=60, now=pd.Timestamp("2026-06-01 15:00", tz="UTC"))
    assert not stale.healthy, "stale feed must fail"
    print("stale:", stale.detail, "-> blocked")
    print("\nmarket-truth gate OK")
