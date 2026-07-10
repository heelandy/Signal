"""Regression tests for the 2026-07-09 full panel review (Training Lab + dashboard).

One test per bug, runnable independently:
    python -m pytest tests/test_review_bugs_2.py -v -k t1_pit_plumbing
Bugs (docs/BUGS_AND_FAILURE_MODES.md · UI/API-serving plane):
    T1  pit_features never plumbed into scan proposals -> journal untrainable
    T2  phase78 study report hijacked the "latest training run" panel
    T3  duel daily frames frozen at the hs_db snapshot end (no live extension)
    T4  orphaned daily_volbreak duel state after the module split
    T5  stale 1-day volbreak arms resolving on wrong-day bars
    D1  dashboard read s.vol_exp (field is vol_expansion) -> always "narrow OR"
    D2  duplicate id="alerts" -> alert history written into the checkbox
    D3  equity/attribution read the replay journal that live never writes
"""
from __future__ import annotations

import inspect
import re
import sys
from pathlib import Path

BOT_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BOT_DIR))

DASH = (BOT_DIR / "bot" / "api" / "static" / "dashboard.html").read_text(encoding="utf-8")
TRAIN = (BOT_DIR / "bot" / "api" / "static" / "training.html").read_text(encoding="utf-8")


def test_t1_pit_plumbing_scan_proposals():
    """The proposal dict scan_watchlist builds must carry pit_features — without it every
    tracked decision stores null features and the journal->training feed starves."""
    import bot.live as lv
    src = inspect.getsource(lv.scan_watchlist)
    assert '"pit_features": s.get("pit_features")' in src


def test_t1_pit_features_reach_the_tracker_record():
    """End-to-end: a proposal-shaped dict through the autotrack key set keeps pit_features."""
    proposal = {"symbol": "QQQ", "side": "long", "family": "breakout", "session": "rth",
                "entry": 1.0, "stop": 0.9, "tp1": 1.1, "tp2": 1.2, "grade": "A",
                "pit_features": {"side_long": 1.0}, "timeframe": "5m",
                "candidate": {"candidate_id": "x", "generated_at": "2026-01-01T00:00:00Z"}}
    assert proposal.get("pit_features"), "autotrack reads s.get('pit_features') off the proposal"


def test_t2_reports_list_excludes_untimestamped_studies():
    """list_reports must drop reports without created_at (phase78 re-saves hourly and, sorted
    by mtime, permanently hijacked the 'latest training run' panel with an empty report)."""
    from bot.ml.registry import list_reports
    for r in list_reports():
        assert r["created_at"] is not None, f"study report leaked into the runs list: {r['name']}"


def test_t3_duel_frames_extend_with_live_bars():
    """run_duel_once must load frames via _live_daily_frame (hs_db + live daily extension) —
    the raw hs_db frame ends at the snapshot (equities 2026-06-08) and froze the duel."""
    from bot.strategy import duel
    src = inspect.getsource(duel.run_duel_once)
    assert "_live_daily_frame" in src
    ext = inspect.getsource(duel._live_daily_frame)
    assert "get_bars" in ext and "add_daily_indicators" in ext
    # completed bars only: today's forming daily bar must never resolve 1-day positions early
    assert "today_et" in ext


def test_t4_orphaned_modules_are_migrated_on_load():
    """_load() must remap renamed-module history (daily_volbreak split) and drop open
    positions whose module is no longer in DUELISTS."""
    from bot.strategy.duel import _migrate, DUELISTS
    st = {"open": [{"module": "daily_volbreak", "symbol": "QQQ"},
                   {"module": "futures_volbreak", "symbol": "NQ"}],
          "closed": [{"module": "daily_volbreak", "symbol": "NQ", "r": -0.8},
                     {"module": "daily_volbreak", "symbol": "SPY", "r": 0.5}],
          "last_day": None}
    out = _migrate(st)
    assert all(p["module"] in DUELISTS for p in out["open"])
    assert len(out["open"]) == 1                                   # orphan armed marker dropped
    assert out["closed"][0]["module"] == "futures_volbreak"        # NQ -> futures book
    assert out["closed"][1]["module"] == "equities_volbreak"       # SPY -> equities book


def test_t5_stale_volbreak_arm_is_dropped_not_resolved():
    """A 1-day volbreak marker >4 days old must be dropped as a scratch, never 'resolved'
    against a wrong-day bar."""
    from bot.strategy import duel
    src = inspect.getsource(duel.run_duel_once)
    assert "days > 4" in src and '"volbreak"' in src


def test_d1_dashboard_reads_vol_expansion():
    """Underlying Signals must read s.vol_expansion (the actual signal field) — s.vol_exp is
    undefined and rendered every signal as 'narrow OR'."""
    assert "s.vol_expansion" in DASH
    assert not re.search(r"s\.vol_exp\b(?!ansion)", DASH)


def test_d2_alerts_id_is_unique():
    """The 'alert on new' checkbox and the Alerts panel shared id='alerts'; querySelector
    returned the checkbox, so renderAlerts wrote history INTO THE CHECKBOX and the panel
    was stuck at 'no alerts yet'."""
    assert DASH.count('id="alerts"') == 1, "duplicate id='alerts' is back"
    assert 'id="alerton"' in DASH
    assert "$('#alerton').checked" in DASH


def test_d3_equity_attribution_prefer_tracker():
    """/api/equity + /api/attribution must build from the tracked live record (same source as
    /api/performance) — the replay journal they used is never written by live/paper."""
    server = (BOT_DIR / "bot" / "api" / "server.py").read_text(encoding="utf-8")
    assert "_tracked_closed" in server
    i = server.index("def attribution")
    assert "_tracked_closed()" in server[i:i + 900]
    j = server.index("def equity")
    assert "_tracked_closed()" in server[j:j + 900]


def test_t6_training_duel_shows_stage_not_blanket_badge():
    """The training-lab duel table must show the per-lineage approved STAGE, not a blanket
    'IN THE DUEL' for anything research-approved."""
    assert "IN THE DUEL" not in TRAIN.split("loadDuel")[1].split("</table>")[0]
    assert "(d.stage || {})" in TRAIN


def test_d4_market_context_never_serves_frozen_failure():
    """D4: a failed market_context ('unknown') was cached at the 16:00 yahoo rate-limit and served
    frozen for hours (header: 'market: unknown', dead feed dot). Three guards:
    (a) _series never raises, (b) last-good context served through hiccups (marked stale),
    (c) /api/market recomputes when the cache is a failure or >15 min old."""
    import bot.market_intel as mi
    src = inspect.getsource(mi._series)
    assert "except Exception" in src                                    # (a)
    ctx = inspect.getsource(mi.market_context)
    assert "_last_good" in ctx and '"stale": True' in ctx               # (b)
    server = (BOT_DIR / "bot" / "api" / "server.py").read_text(encoding="utf-8")
    i = server.index("def market()")
    seg = server[i:i + 1200]
    assert 'get("regime") != "unknown"' in seg and "900" in seg         # (c)
    # and the last-good path actually works
    mi._last_good.clear()
    mi._last_good.update({"regime": "risk_on", "spy": 750.0, "note": "test"})
    import pandas as pd
    empty = pd.Series(dtype=float)
    orig = mi._series
    mi._series = lambda *a, **k: empty                                  # simulate total provider outage
    try:
        out = mi.market_context()
    finally:
        mi._series = orig
    assert out["regime"] == "risk_on" and out.get("stale") is True


if __name__ == "__main__":
    fns = [v for k, v in sorted(globals().items()) if k.startswith("test_")]
    for f in fns:
        f()
        print(f"PASS {f.__name__}")
    print(f"\nall {len(fns)} review-2 regression tests OK")
