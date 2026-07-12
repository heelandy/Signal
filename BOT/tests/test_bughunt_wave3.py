"""BUG HUNT — Wave 3 (data pipeline & persister chaos).

Poison-frame the live-bar persister and assert it fails CLOSED — a store is either old or new,
never corrupt, and provenance is never silently wiped:

  W3.1  a WRONG SYMBOL's prices (a mis-routed fetch) must be REFUSED, not appended — an NQ store
        (~20000) can never continue into SPY prices (~550). No continuity guard existed.
  W3.2  inf prices slip past `(cols > 0).all()` (inf > 0 is True) — must be dropped like NaN.
  W3.3  duplicate timestamps inside one fetched frame must dedup, not double-append a bar.
  W3.4  L7 — the manifest write must be ATOMIC and a corrupt manifest must FAIL LOUD, never
        silently reset to {} and lose every symbol's provenance.
"""
from __future__ import annotations

import json

import pytest

pd = pytest.importorskip("pandas")
import numpy as np  # noqa: E402

from bot.market_data import live_persist as LP  # noqa: E402

ET = "America/New_York"


def _store(tmp_path, last_close=20_000.0, n=30):
    """A minimal NQ-like continuous store (ts_et tz-aware + ohlcv + volume)."""
    ts = pd.date_range("2026-06-01 09:30", periods=n, freq="5min", tz=ET)
    df = pd.DataFrame({"ts_et": ts, "open": last_close, "high": last_close + 1,
                       "low": last_close - 1, "close": last_close, "volume": 1000})
    p = tmp_path / "nq_continuous_1m.parquet"
    df.to_parquet(p, index=False)
    return p


def _fetch(start="2026-06-01 12:00", n=5, px=20_000.0, freq="5min"):
    ts = pd.date_range(start, periods=n, freq=freq, tz=ET)
    return pd.DataFrame({"ts_et": ts, "open": px, "high": px + 1, "low": px - 1,
                         "close": px, "volume": 500})


def test_w3_wrong_symbol_prices_are_refused(tmp_path):
    p = _store(tmp_path, last_close=20_000.0)
    before = len(pd.read_parquet(p))
    r = LP.append_bars(p, _fetch(px=550.0), "NQ")          # SPY-level prices into an NQ store
    assert r.get("appended", 0) == 0 and "continu" in str(r.get("error", "")).lower(), r
    assert len(pd.read_parquet(p)) == before, "a discontinuous (wrong-symbol) frame must not touch the store"


def test_w3_inf_prices_are_dropped(tmp_path):
    p = _store(tmp_path)
    f = _fetch(px=20_000.0, n=3)
    f.loc[1, "high"] = np.inf                              # one poisoned bar
    r = LP.append_bars(p, f, "NQ")
    assert r.get("appended", 0) == 2, f"the inf bar must be dropped, the 2 sane bars kept: {r}"
    assert np.isfinite(pd.read_parquet(p)[["open", "high", "low", "close"]].to_numpy()).all()


def test_w3_duplicate_timestamps_dedup(tmp_path):
    p = _store(tmp_path)
    f = _fetch(px=20_000.0, n=3)
    dup = pd.concat([f, f.iloc[[1]]], ignore_index=True)   # bar #1 duplicated
    r = LP.append_bars(p, dup, "NQ")
    assert r.get("appended", 0) == 3, f"duplicate timestamps must collapse to one bar each: {r}"
    out = pd.read_parquet(p)
    assert out["ts_et"].duplicated().sum() == 0, "no duplicate timestamps may enter the store"


def test_w3_manifest_atomic_and_corrupt_fails_loud(tmp_path, monkeypatch):
    man = tmp_path / "manifest.json"
    monkeypatch.setattr(LP, "MANIFEST", man)
    p = _store(tmp_path)
    # a healthy pre-existing manifest with ANOTHER symbol's provenance must survive an append
    man.write_text(json.dumps({"SPY_5m_append": {"appended": 42}}), encoding="utf-8")
    LP.append_bars(p, _fetch(px=20_000.0, n=2), "NQ")
    m = json.loads(man.read_text(encoding="utf-8"))
    assert m.get("SPY_5m_append", {}).get("appended") == 42, "an append must not wipe other provenance"
    assert m.get("NQ_5m_append", {}).get("appended") == 2, m
    # a CORRUPT manifest must fail loud, never silently reset to {} (that hides provenance loss)
    man.write_text("{ this is not json", encoding="utf-8")
    with pytest.raises(Exception):
        LP._manifest("NQ", _fetch(px=20_000.0, n=1), 1)
