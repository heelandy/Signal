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


def test_d5_tracker_resolver_cannot_be_stranded():
    """D5 ('positions still open', 2026-07-10): _walk_trail used np without importing numpy — the
    first trail-eq row NameError'd EVERY track_outcomes run, stranding all opens; the crash also
    leaked a mid-transaction sqlite handle ('database is locked'). Guards: numpy imported at module
    level; per-row try/except so one poisoned row never strands the rest; bars prefetched before
    the write pass; polled endpoints are read-only."""
    import bot.tracker as tk
    assert hasattr(tk, "np"), "numpy must be a module-level import in tracker.py"
    src = inspect.getsource(tk.track_outcomes)
    assert "PREFETCH" in src and src.index("get_bars(") < src.index("UPDATE decisions")
    assert "except Exception:" in src            # per-row walk guard
    assert src.count("finally:") >= 2            # both db handles always close
    server = (BOT_DIR / "bot" / "api" / "server.py").read_text(encoding="utf-8")
    for ep in ("def decisions()", "def scorecard()"):
        seg = server[server.index(ep):server.index(ep) + 700]
        assert "track_outcomes()" not in seg, f"{ep} must be read-only (scan loop owns resolution)"


def test_p1_no_undefined_names_anywhere():
    """PREVENTION (D5's class, killed for good): pyflakes 'undefined name' across every bot module.
    The np NameError lived in a code path that only ran when a trail-eq row existed — invisible to
    import-time and to every endpoint probe. Static analysis sees ALL paths without running them."""
    import subprocess, sys, glob
    files = []
    for pat in ("bot/*.py", "bot/**/*.py"):
        files += glob.glob(str(BOT_DIR / pat), recursive=True)
    files = [f for f in files if "__pycache__" not in f]
    r = subprocess.run([sys.executable, "-m", "pyflakes", *files],
                       capture_output=True, text=True, cwd=str(BOT_DIR))
    bad = [l for l in (r.stdout + r.stderr).splitlines() if "undefined name" in l]
    assert not bad, "undefined names found (the np-NameError class):\n" + "\n".join(bad)


def test_p2_training_plane_heartbeats():
    """PREVENTION, lab plane (user 2026-07-10 'same test for the training lab'): the slow-cadence
    governance steps (market context, reconcile, DUEL, phase78, boss, journal integrity) must run
    through _beat_val so their failures surface in beats_failing — and the Training Lab status
    endpoint must expose them."""
    server = (BOT_DIR / "bot" / "api" / "server.py").read_text(encoding="utf-8")
    loop = server[server.index("def _scan_loop"):server.index("def _startup")]
    for name in ('"market_context"', '"reconcile"', '"duel"', '"phase78"', '"boss"',
                 '"journal_integrity"'):
        assert f"_beat_val({name}" in loop, f"{name} step is not heartbeat-wrapped"
    i = server.index("def training_status")
    assert "beats_failing" in server[i:i + 800], "lab status endpoint must expose failing beats"
    assert "beats_failing" in (BOT_DIR / "bot" / "api" / "static" / "training.html").read_text(encoding="utf-8")


def test_p3_parked_worker_writes_no_journal_rows():
    """PARK (user 2026-07-10): a parked worker's shadow study is paused — identical signals must
    produce rows for un-parked workers only. Park is state-only: history/approvals untouched."""
    from bot.boss import shadow_decisions, park, _load
    prior = bool(_load().get("workers", {}).get("worker-n", {}).get("parked"))
    park("worker-n", True)
    try:
        fake = [{"tradeable": True, "grade": "A", "signal_state": "active", "bars_ago": 2,
                 "symbol": sym, "side": "long", "entry": 100.0, "stop": 99.0, "session": "rth",
                 "slope_grade": "A", "candidate": {"generated_at": "2026-07-10T10:00:00-04:00"}}
                for sym in ("NQ", "QQQ", "SPY")]
        fams = sorted(r["family"] for r in shadow_decisions(fake))
        assert "worker-n" not in fams, "parked worker still writing rows"
        assert fams == ["worker-q", "worker-s"], f"un-parked workers must keep running: {fams}"
    finally:
        park("worker-n", prior)                        # restore the user's actual state
