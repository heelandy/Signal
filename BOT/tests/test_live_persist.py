"""LIVE-BAR PERSISTER TESTS (user decision 2026-07-12): the store grows append-after-last from
the live router — atomically, schema-mirrored, sanity-filtered, provenance-tracked. No network:
the file-level core (`append_bars`) is driven with synthetic router frames."""
from __future__ import annotations

import json

import pytest

pd = pytest.importorskip("pandas")
np = pytest.importorskip("numpy")

from bot.market_data import live_persist as LP  # noqa: E402

ET = "America/New_York"


def _equity_store(path, last="2026-07-06 15:55"):
    ts = pd.date_range("2026-07-06 09:30", last, freq="5min")
    pd.DataFrame({"ts_et": ts, "open": 100.0, "high": 101.0, "low": 99.0, "close": 100.5,
                  "volume": np.int64(1000), "adj_factor": 1.0, "is_roll": False,
                  "session": "RTH"}).to_parquet(path, index=False)


def _futures_store(path):
    ts = pd.date_range("2026-07-06 09:30", "2026-07-06 15:55", freq="5min")
    import datetime as _dt
    pd.DataFrame({"ts_utc": ts, "ts_et": ts,
                  "date_et": _dt.date(2026, 7, 6),   # real futures stores keep date32 objects
                  "symbol": "NQ",
                  "instrument_id": 123, "open": 100.0, "high": 101.0, "low": 99.0,
                  "close": 100.5, "volume": np.int64(50), "adj_factor": 1.0,
                  "is_roll": False, "session": "RTH"}).to_parquet(path, index=False)


def _router_frame(day="2026-07-07", bad_row=False):
    ts = pd.date_range(f"{day} 09:30", f"{day} 15:55", freq="5min", tz=ET)
    df = pd.DataFrame({"ts_et": ts, "open": 102.0, "high": 103.0, "low": 101.0,
                       "close": 102.5, "volume": 2000})
    if bad_row:
        df.loc[df.index[5], "high"] = 90.0            # high < low: must never enter the store
    return df


def test_append_after_last_and_idempotent(tmp_path, monkeypatch):
    monkeypatch.setattr(LP, "MANIFEST", tmp_path / "manifest.json")
    p = tmp_path / "qqq.parquet"
    _equity_store(p)
    r1 = LP.append_bars(p, _router_frame(), "QQQ")
    assert r1["appended"] == 78, r1
    r2 = LP.append_bars(p, _router_frame(), "QQQ")    # same frame again: full overlap
    assert r2["appended"] == 0, "append-after-last must make the daily job idempotent"
    df = pd.read_parquet(p)
    assert len(df) == 78 * 2 and str(df["ts_et"].max())[:10] == "2026-07-07"
    assert set(df.columns) == {"ts_et", "open", "high", "low", "close", "volume",
                               "adj_factor", "is_roll", "session"}, "schema mirrored exactly"
    tail = df.tail(78)
    assert (tail["adj_factor"] == 1.0).all() and (~tail["is_roll"]).all()
    assert (tail["session"] == "RTH").all(), "09:30-15:55 ET weekday bars are RTH"


def test_futures_schema_mirrored(tmp_path, monkeypatch):
    monkeypatch.setattr(LP, "MANIFEST", tmp_path / "manifest.json")
    p = tmp_path / "nq.parquet"
    _futures_store(p)
    r = LP.append_bars(p, _router_frame(), "NQ")
    assert r["appended"] == 78
    df = pd.read_parquet(p)
    tail = df.tail(78)
    assert (tail["symbol"] == "NQ").all() and str(tail["date_et"].iloc[0]) == "2026-07-07"
    assert tail["instrument_id"].isna().all(), "unknown columns fill None, never fake values"


def test_sanity_filter_drops_broken_candles(tmp_path, monkeypatch):
    monkeypatch.setattr(LP, "MANIFEST", tmp_path / "manifest.json")
    p = tmp_path / "qqq.parquet"
    _equity_store(p)
    r = LP.append_bars(p, _router_frame(bad_row=True), "QQQ")
    assert r["appended"] == 77, "the high<low candle must never enter the store"


def test_manifest_grain_exception_extended(tmp_path, monkeypatch):
    mf = tmp_path / "manifest.json"
    mf.write_text(json.dumps({"QQQ_5m_append": {"appended": 10,
                                                "appended_range": ["2026-07-01", "2026-07-05"]}}),
                  encoding="utf-8")
    monkeypatch.setattr(LP, "MANIFEST", mf)
    p = tmp_path / "qqq.parquet"
    _equity_store(p)
    LP.append_bars(p, _router_frame(), "QQQ")
    m = json.loads(mf.read_text(encoding="utf-8"))["QQQ_5m_append"]
    assert m["appended"] == 88 and "2026-07-07" in m["appended_range"][1], (
        "the provenance row must EXTEND (same key as hs_append_5m -> the QA grain exception "
        "keeps covering the live span)")
    assert "live router" in m["source"]


def test_missing_store_is_never_created(tmp_path, monkeypatch):
    monkeypatch.setattr(LP, "MANIFEST", tmp_path / "manifest.json")
    r = LP.append_bars(tmp_path / "nope.parquet", _router_frame(), "XX")
    assert r["appended"] == 0 and "never create" in r["error"]
