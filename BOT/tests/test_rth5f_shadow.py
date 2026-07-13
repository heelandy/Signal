"""RTH5F SHADOW BOOK (operator go 2026-07-13) — watch-only journal of the tuned 5-filter
confluence book (NQ RTH: body>=40% + half-body-beyond + wick<=25% + structure direction +
RVOL>=1.20 + ADX>=18; distance recorded as a SOFT warn, never blocking).

Freeze-safe by construction: advisory/shadow lineage (like the 15m/worker studies) — it records
tracker decisions under its OWN strategy_version (dataset version-purity keeps it out of the core
training corpus), places no orders, changes no gates. Evidence: research battery 2026-07-13 —
IS 2024-26 +29.9R PF 2.14 (n=66); OOS 2016-23 +27.5R PF 1.23 (n=239), positive both OOS eras.
"""
from __future__ import annotations

import numpy as np
import pytest

pd = pytest.importorskip("pandas")

from bot.strategy import rth5f_shadow as R  # noqa: E402


def _frame(break_body_frac=0.8, rvol_mult=2.0, n_trend=34):
    """Synthetic NQ 5m RTH day engineered to fire the book on the last bar. Shape: the
    09:30-10:00 OR carries an early SPIKE HIGH (20100) price then leaves alone; a gentle
    uptrend (ADX warm, HH/HL swings) climbs BELOW the OR high; the final bar is a strong-body
    crossing close through 20100 on elevated volume. break_body_frac/rvol_mult degrade exactly
    one filter for the negative tests."""
    rows = []
    ts = pd.Timestamp("2026-07-13 09:30", tz="America/New_York")
    # OR window (6 bars): first bar spikes to the session high 20100, then quiet
    rows.append((ts, 20000.0, 20100.0, 19990.0, 20010.0, 1200.0)); ts += pd.Timedelta(minutes=5)
    px = 20010.0
    for _ in range(5):
        rows.append((ts, px, px + 8.0, px - 8.0, px + 2.0, 1000.0))
        px += 2.0; ts += pd.Timedelta(minutes=5)
    for i in range(n_trend):                            # gentle rise BELOW the OR high
        o = px
        c = px + 3.0
        h = c + 3.0
        l = o - 3.0
        if i % 10 == 9:                                 # spiky-low pullbacks carve RISING swing
            c = o - 8.0; h = o + 1.0; l = c - 8.0       # lows without drowning ADX in -DM
        rows.append((ts, o, h, l, c, 1000.0))
        px = c; ts += pd.Timedelta(minutes=5)
    assert px <= 20100.0, "trend must stay below the OR high until the break"
    # the breakout bar: strong body closing through the OR high on volume; the open sits just
    # under the level so more than half the body clears it
    o = 20092.0
    c = 20120.0
    full = (c - o) / break_body_frac                    # body = frac * range
    h = c + (full - (c - o)) * 0.4
    l = o - (full - (c - o)) * 0.6
    rows.append((ts, o, max(h, c), min(l, o), c, 1000.0 * rvol_mult))
    df = pd.DataFrame(rows, columns=["ts_et", "open", "high", "low", "close", "volume"])
    df["ts_et"] = df["ts_et"].astype(str)
    return df


def test_evaluate_fires_on_a_qualifying_break(monkeypatch):
    sig, why = R.evaluate_bars(_frame())
    assert sig is not None, f"a qualifying crossing candle must fire (why={why})"
    assert sig["side"] == "long" and sig["family"] == R.FAMILY
    assert sig["strategy_version"] == R.VERSION, "shadow lineage must carry its OWN version"
    assert sig["stop"] < sig["entry"] < sig["tp2"]
    assert "dist_warn" in sig, "distance is a SOFT warn field, never a gate"


def test_weak_body_blocks(monkeypatch):
    sig, why = R.evaluate_bars(_frame(break_body_frac=0.2))     # body 20% of range < 40%
    assert sig is None and "body" in why


def test_low_volume_blocks(monkeypatch):
    sig, why = R.evaluate_bars(_frame(rvol_mult=0.5))           # RVOL 0.5 < 1.20
    assert sig is None and "rvol" in why


def test_tick_records_once_and_dedups_per_book(tmp_path, monkeypatch):
    """Both books (NQ + SPY) record from the same beat; each dedups independently by bar."""
    import bot.tracker as T
    monkeypatch.setattr(T, "DB", tmp_path / "hs.db")
    monkeypatch.setattr(R, "_get_bars", lambda sym: _frame())
    monkeypatch.setattr(R, "_now", lambda tz: pd.Timestamp("2026-07-13 23:00", tz=tz))
    # the synthetic swings are carved at futures speed (lb=3); SPY's lb=5 is not what this
    # test covers (it covers per-book SETTINGS) — pin the swing speed
    monkeypatch.setattr("bot.strategy.asset_config.struct_lb", lambda s: 3)
    out1 = R.tick()
    assert set(out1) == set(R.BOOKS), "the beat must run every book"
    assert out1["NQ"].get("recorded"), out1
    assert out1["SPY"].get("recorded"), out1
    assert "NQ" in out1["NQ"]["candidate_id"] and "SPY" in out1["SPY"]["candidate_id"], \
        "candidate ids must be symbol-scoped so the books never collide"
    out2 = R.tick()                                             # same bars -> dedup, no second rows
    assert out2["NQ"].get("dup") and out2["SPY"].get("dup"), out2
    import sqlite3
    con = sqlite3.connect(str(T.DB))
    rows = con.execute("SELECT symbol, strategy_version FROM decisions WHERE family=?",
                       (R.FAMILY,)).fetchall()
    con.close()
    assert sorted(r[0] for r in rows) == ["NQ", "SPY"] and all(r[1] == R.VERSION for r in rows)


def test_spy_book_uses_its_own_tuned_settings(monkeypatch):
    """SPY's tuned RVOL is 0.90 (deep-search winner): a volume print that fails NQ's 1.20 gate
    must still fire the SPY book — the settings are per-symbol, not shared."""
    monkeypatch.setattr("bot.strategy.asset_config.struct_lb", lambda s: 3)
    f = _frame(rvol_mult=1.0)                                   # RVOL 1.0: < NQ 1.20, >= SPY 0.90
    sig_nq, why_nq = R.evaluate_bars(f, "NQ")
    sig_spy, why_spy = R.evaluate_bars(f, "SPY")
    assert sig_nq is None and "rvol" in why_nq
    assert sig_spy is not None, f"SPY book (rvol 0.90) must fire (why={why_spy})"
    assert sig_spy["symbol"] == "SPY" and sig_spy["candidate_id"].startswith("rth5f:SPY:")


def test_malformed_inputs_fail_closed(monkeypatch):
    """Bug hunt 3rd pass: a frame without volume must fail CLOSED at the rvol gate (never fire,
    never crash); a dead feed must return an error dict (never raise into the beat)."""
    f = _frame().drop(columns=["volume"])
    sig, why = R.evaluate_bars(f)
    assert sig is None and "rvol" in why, f"no volume -> rvol unprovable -> blocked (got {why})"
    monkeypatch.setattr(R, "_get_bars", lambda sym: (_ for _ in ()).throw(OSError("feed down")))
    out = R.tick()
    assert all("error" in v for v in out.values()), "a dead feed must degrade, never raise"


def test_no_fire_outside_rth_window(monkeypatch):
    df = _frame()
    et = pd.to_datetime(df["ts_et"])
    df["ts_et"] = (et + pd.Timedelta(hours=9)).astype(str)      # shift day into the evening
    sig, why = R.evaluate_bars(df)
    assert sig is None, "the book is RTH-only — evening bars must never fire"
