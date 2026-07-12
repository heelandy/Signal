"""FAIL-CLOSED DATA PIPELINE TESTS (remediation Phase 4, T4.1-T4.3 — RED-first).

The audit: intake records subprocess return codes but continues (fail-open); QA counts
zero-volume and short days without failing on them and has NO freshness or grain gate — which is
exactly why `data_qa_all_ok=true` coexisted with a store ending 2026-06-08; equity ingest never
checks instrument identity. These tests pin the corrected gates.
"""
from __future__ import annotations

import json
import os
import sys

import duckdb
import numpy as np
import pandas as pd
import pytest

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
for p in (os.path.join(ROOT, "pipeline"), os.path.join(ROOT, "engine")):
    if p not in sys.path:
        sys.path.insert(0, p)

import hs_data_qa as QA  # noqa: E402
import intake  # noqa: E402

ET = "America/New_York"


def _bars_con(days_back_end=1, n_days=10, bars_per_day=78, zero_vol_bars=0,
              short_days=0, spacing_min=5, sym="QQQ"):
    """In-memory store shaped like the bars hive: n_days ending `days_back_end` bdays ago."""
    end = pd.Timestamp.now(tz=ET).tz_localize(None).normalize() - pd.tseries.offsets.BDay(days_back_end)
    days = pd.bdate_range(end=end, periods=n_days)
    rows = []
    for di, day in enumerate(days):
        nb = bars_per_day if di >= short_days else 40          # first `short_days` days are short
        for k in range(nb):
            t = day + pd.Timedelta(minutes=570 + k * spacing_min)
            vol = 0.0 if (zero_vol_bars and di == n_days - 1 and k < zero_vol_bars) else 1000.0
            rows.append({"ts": t.tz_localize(ET).tz_convert("UTC"), "open": 100.0, "high": 101.0,
                         "low": 99.0, "close": 100.5, "volume": vol,
                         "sym": sym, "tf": "5m", "session": "rth", "year": day.year})
    con = duckdb.connect()
    con.register("src", pd.DataFrame(rows))
    con.execute("CREATE TABLE bars AS SELECT * FROM src")
    return con


def _issues(r):
    return " | ".join(r.get("issues", []))


def test_t42_healthy_store_is_ok():
    con = _bars_con()
    r = QA.qa_symbol(con, "QQQ")
    con.close()
    assert r["ok"], f"healthy fixture must pass, got issues: {_issues(r)}"


def test_t42_stale_span_fails_freshness():
    con = _bars_con(days_back_end=20)                          # last bar ~a month of bdays ago
    r = QA.qa_symbol(con, "QQQ")
    con.close()
    assert not r["ok"] and "stale" in _issues(r).lower(), (
        f"a store ending 20 trading days ago must FAIL freshness (issues: {_issues(r) or 'none'}) "
        f"— this is the exact defect that let data_qa_all_ok=true coexist with a June-08 store")


def test_t42_zero_volume_rth_bars_fail():
    con = _bars_con(zero_vol_bars=5)
    r = QA.qa_symbol(con, "QQQ")
    con.close()
    assert not r["ok"] and "volume" in _issues(r).lower(), (
        f"zero-volume RTH bars must be an issue, not just a counted field (issues: {_issues(r) or 'none'})")


def test_t42_short_days_above_threshold_fail():
    con = _bars_con(short_days=3, n_days=10)                   # 30% short days >> 2% threshold
    r = QA.qa_symbol(con, "QQQ")
    con.close()
    assert not r["ok"] and "short" in _issues(r).lower(), (
        f"30% short days must fail the session-completeness gate (issues: {_issues(r) or 'none'})")


def test_t42_wrong_grain_fails():
    con = _bars_con(spacing_min=10, bars_per_day=39)           # 10-minute rows in a nominal-5m table
    r = QA.qa_symbol(con, "QQQ")
    con.close()
    assert not r["ok"] and "grain" in _issues(r).lower(), (
        f"10-minute spacing in a 5m table must fail the grain gate (issues: {_issues(r) or 'none'})")


def test_t42_report_carries_fingerprint():
    con = _bars_con()
    r = QA.qa_symbol(con, "QQQ")
    con.close()
    assert r.get("fingerprint"), "every QA result must carry a store fingerprint (Phase 4 lineage)"


def test_t41_intake_step_failure_raises():
    with pytest.raises(Exception) as e:
        intake.run([sys.executable, "-c", "import sys; sys.exit(3)"])
    assert "rc=3" in str(e.value) or "3" in str(e.value), (
        "a failing intake step must raise (fail closed), not print rc and continue")


def test_t41_intake_qa_gate_blocks_on_red_report(tmp_path):
    bad = {"symbols": {"QQQ": {"ok": False, "issues": ["STALE: last bar 2026-06-08"]}}}
    p = tmp_path / "dataqa.json"
    p.write_text(json.dumps(bad), encoding="utf-8")
    with pytest.raises(Exception) as e:
        intake.qa_gate(p)
    assert "QQQ" in str(e.value), "a red QA report must abort the intake before datasets/training"
    p.write_text(json.dumps({"symbols": {"QQQ": {"ok": True, "issues": []}}}), encoding="utf-8")
    intake.qa_gate(p)                                          # green report passes


def test_t43_equity_ingest_rejects_mixed_symbols(tmp_path):
    import hs_ingest_equity as IE
    ts = pd.date_range("2026-01-05 14:30", periods=6, freq="1min", tz="UTC")
    df = pd.DataFrame({"ts_event": list(ts[:3]) + list(ts[:3]),   # duplicate timestamps = 2 instruments
                       "symbol": ["QQQ"] * 3 + ["AAPL"] * 3,
                       "open": 100.0, "high": 101.0, "low": 99.0, "close": 100.5,
                       "volume": 1000})
    csv = tmp_path / "mixed.csv"
    df.to_csv(csv, index=False)
    os.chdir(tmp_path)                                          # writes go to tmp data/
    os.makedirs("data", exist_ok=True)
    try:
        with pytest.raises(Exception) as e:
            IE.ingest(str(csv), "QQQ")
        assert "AAPL" in str(e.value) or "symbol" in str(e.value).lower() or "duplicate" in str(e.value).lower(), (
            f"mixed-instrument input must be rejected, got: {e.value}")
    finally:
        os.chdir(ROOT)


def test_t43_equity_ingest_refuses_silent_overwrite(tmp_path):
    import hs_ingest_equity as IE
    ts = pd.date_range("2026-01-05 14:30", periods=5, freq="1min", tz="UTC")
    df = pd.DataFrame({"ts_event": ts, "symbol": "QQQ", "open": 100.0, "high": 101.0,
                       "low": 99.0, "close": 100.5, "volume": 1000})
    csv = tmp_path / "q.csv"
    df.to_csv(csv, index=False)
    os.chdir(tmp_path)
    os.makedirs("data", exist_ok=True)
    try:
        IE.ingest(str(csv), "QQQ")                             # first write: fine
        with pytest.raises((SystemExit, Exception)):
            IE.ingest(str(csv), "QQQ")                         # existing store: must demand --replace
        IE.ingest(str(csv), "QQQ", replace=True)               # explicit intent: fine
    finally:
        os.chdir(ROOT)
