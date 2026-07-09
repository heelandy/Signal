"""Independent regression tests for the dashboard-review fixes (U1-U5 in
docs/BUGS_AND_FAILURE_MODES.md, 2026-07-09). One test per bug — each runs on its own.

    pytest BOT/tests/test_review_bugs.py -q
"""
import re
import sys
from pathlib import Path

import numpy as np
import pandas as pd

BOT_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BOT_DIR))

STATIC = BOT_DIR / "bot" / "api" / "static"


# ── U1 — latest_price/get_bars used without importing -> NameError aborts the whole endpoint ──
def test_u1_no_serving_nameerror():
    src = (BOT_DIR / "bot" / "api" / "server.py").read_text(encoding="utf-8").splitlines()
    funcs, cur = [], None
    for ln in src:
        if ln.startswith(("def ", "async def ")):
            cur = {"name": ln.split("(")[0].split()[-1], "lines": []}
            funcs.append(cur)
        if cur is not None:
            cur["lines"].append(ln)
    for f in funcs:
        body = "\n".join(f["lines"])
        for nm in ("latest_price", "get_bars"):
            if re.search(rf"\b{nm}\(", body):
                assert re.search(rf"import[^\n]*\b{nm}\b", body), \
                    f"{f['name']} uses {nm} without importing it (NameError -> endpoint aborts)"


# ── U2 — live-vs-backtest gate judged a tiny grade-A subset -> "insufficient sample" hid negatives ──
def test_u2_thin_gradeA_falls_back_to_full_book():
    from bot.tracker import _judge_target
    overall = {"n": 18, "exp_R": 0.10, "hi": 0.5}
    by_grade = {"A": {"n": 3, "exp_R": -0.2, "hi": 0.1}}   # only 3 grade-A -> below MIN_SAMPLE
    target, judged = _judge_target(overall, by_grade)
    assert judged == "all taken trades" and target["n"] == 18   # judges the 18, not the tiny A


def test_u2_fat_gradeA_is_used():
    from bot.tracker import _judge_target
    target, judged = _judge_target({"n": 30}, {"A": {"n": 15}})
    assert judged == "grade A" and target["n"] == 15


# ── U3 — Selected Contract "only QQQ": underlying picker must exist ──
def test_u3_dashboard_has_underlying_picker():
    html = (STATIC / "dashboard.html").read_text(encoding="utf-8")
    assert 'id="ctrund"' in html and "setCtrUnd" in html
    assert "underlying=" in html                              # feed is called with the picked symbol


# ── U4 — approval didn't reflect: the one-time /api/duel cache is gone (always re-fetch) ──
def test_u4_dashboard_refetches_duel():
    html = (STATIC / "dashboard.html").read_text(encoding="utf-8")
    assert "if(!DUELD) DUELD=await" not in html               # the stale one-time cache
    assert "DUELD=await J('/api/duel')" in html               # always re-fetch


# ── U5 — MBP-10 unsigned-size underflow + quote_rate double-write ──
def test_u5_synth_window_size_underflow_bounded():
    from bot.ml.databento_api import _synth_window
    rows = []
    for _ in range(20):
        r = {"bid_px_00": 500.0, "ask_px_00": 500.1}
        for j in range(10):                                   # ask > bid at every level (would underflow if unsigned)
            r[f"bid_sz_0{j}"] = np.uint32(10)
            r[f"ask_sz_0{j}"] = np.uint32(50)
        rows.append(r)
    out = _synth_window(pd.DataFrame(rows), pd.Timestamp("2026-03-02 14:05", tz="UTC"))
    assert out is not None
    assert -1.0 <= out["l2_depth_imb"] <= 1.0                 # ~ -0.667, NOT ~+4e9
    assert -1.0 <= out["l2_book_pressure"] <= 1.0


def test_u5_depth_cols_exclude_quote_rate():
    from bot.ml.databento_api import DEPTH_COLS
    assert "l2_quote_rate" not in DEPTH_COLS                  # left to flow synthesis (one meaning per column)
    assert set(DEPTH_COLS) == {"l2_spread_bps", "l2_depth_imb", "l2_book_pressure"}
