"""SIMULATOR EXECUTION-SEMANTIC TESTS (remediation Phase 2, T2.1-T2.4 — written RED-first).

Each fixture engineers synthetic 5m days through the REAL `hs_backtest.backtest()` and pins one
audited defect:
  S2  overnight leak — an EOD-flat day trade must exit on its entry day's last bar, never let the
      next morning's gap "fill" yesterday's stop/target (on the 5m RTH store the eod_min check
      never fires, so EVERY carried trade previously exited on next-day prices).
  S3  short-side MFE/MAE must use the favorable/adverse extremes for the SIDE.
  S4  a stop gapped through fills at the open, not at the stop price.
  S5  same-bar stop+target ambiguity: STOP WINS uniformly (was target-first after TP1) and the
      run reports its ambiguous-bar count.
  S1  touch-mode entry bars evaluate their remainder (favorable side provable post-touch;
      adverse only on a beyond-stop close).
  S6  max drawdown starts the equity curve at 0 (first-trade losses ARE drawdown).
  T2.2 determinism · T2.3 policy doc-test · T2.4 trade-day/timezone grouping.
"""
from __future__ import annotations

import os
import sys

import numpy as np
import pandas as pd

ENGINE = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", "engine"))
if ENGINE not in sys.path:
    sys.path.insert(0, ENGINE)

import hs_backtest as B  # noqa: E402
import hs_validate as V  # noqa: E402

ET = "America/New_York"
ATR = 8.0
BASE = 102.0     # inside the OR (100..104)


def _frame(days_spec, freq="5min", start="09:30", end="15:55", tradeday=False):
    """days_spec: {date_str: {time_str: (o, h, l, c)}} — unlisted times get flat BASE bars."""
    rows = []
    for day, spec in days_spec.items():
        times = pd.date_range(f"{day} {start}", f"{day} {end}", freq=freq, tz=ET)
        for t in times:
            o = h = l = c = BASE
            key = t.strftime("%H:%M")
            if key in spec:
                o, h, l, c = spec[key]
            rows.append({"ts": t.tz_convert("UTC"), "open": float(o), "high": float(h),
                         "low": float(l), "close": float(c), "volume": 1_000.0})
    d = pd.DataFrame(rows)
    n = len(d)
    d["atr14"] = ATR
    for col in ("vwap_sess", "vwap_wk", "ema9", "ema20", "ema50"):
        d[col] = np.nan
    d["macro_regime"] = "A"
    d["macro_allow_trades"] = True
    d["macro_long_ok"] = True
    d["macro_short_ok"] = True
    d["local_regime"] = 0
    d["trend_up"] = True
    d["trend_down"] = True
    d.attrs["sym"] = "NQ"
    return d


OR = {t: (BASE, 104.0, 100.0, BASE) for t in ("09:30", "09:35", "09:40", "09:45", "09:50", "09:55")}


def _bt(d, mode="tp2_full", execm="close", **kw):
    return B.backtest(d, mode, "both", False, "orb", 0, 1.0, 2.0, 570, 600, 0.0, 960, execm,
                      eod_min=958, stop_mode="or", **kw)


def test_s4_gap_through_stop_fills_at_open():
    """Long entry 104.5, stop 97.6; next bar opens at 90 — the fill is 90, not the stop price."""
    d = _frame({"2026-01-05": {**OR,
                               "10:00": (104.4, 105.2, 104.0, 104.5),     # close-confirm break
                               "10:05": (90.0, 91.0, 89.0, 90.5)}})       # gap through the stop
    tr = _bt(d)
    assert len(tr) == 1
    t = tr.iloc[0]
    assert t.exit_price == 90.0, f"stop gapped through must fill at the open (got {t.exit_price})"
    exp = (90.0 - t.entry_price) / t.risk_pts
    assert abs(t.gross_R - exp) < 1e-3, f"gap loss must exceed -1R (got {t.gross_R:+.3f}, want {exp:+.3f})"
    assert t.gross_R < -1.5


def test_s5_stop_wins_after_tp1_and_ambiguity_is_counted():
    """Post-TP1 runner: a bar touching BOTH the BE stop and TP2 scratches at BE (stop wins)."""
    d = _frame({"2026-01-05": {**OR,
                               "10:00": (104.4, 105.2, 104.0, 104.5),     # entry
                               "10:05": (105.0, 112.5, 104.8, 112.0),     # TP1 only (+1R)
                               "10:10": (105.0, 125.0, 100.0, 118.0)}},   # touches BE AND TP2
                )
    tr = _bt(d, mode="scale_be")
    assert len(tr) == 1
    t = tr.iloc[0]
    assert abs(t.gross_R - 0.5) < 1e-9, (
        f"stop must win the ambiguous bar: runner scratched at BE -> 0.5*TP1 = +0.5R "
        f"(got {t.gross_R:+.3f} — TP2-first is the optimistic defect)")
    assert tr.attrs.get("ambiguous_bars", 0) >= 1, "the run must report its ambiguous-bar count"


def test_s3_short_mfe_uses_the_low():
    """Short from ~99: next bar drops to 92 — MFE must be ~(entry-92)/risk, not measured at the high."""
    d = _frame({"2026-01-05": {**OR,
                               "10:00": (100.2, 100.4, 98.8, 99.0),       # close below OR low -> short
                               "10:05": (98.0, 98.0, 92.0, 93.0)}})
    tr = _bt(d)
    assert len(tr) == 1
    t = tr.iloc[0]
    exp_mfe = (t.entry_price - 92.0) / t.risk_pts
    assert abs(t.mfe_R - exp_mfe) < 1e-3, (
        f"short MFE must use the LOW (favorable extreme): want {exp_mfe:+.3f}, got {t.mfe_R:+.3f}")


def test_s2_day_trade_flattens_on_entry_days_last_bar():
    """Late entry, nothing hit by 15:55; next morning gaps to TP2. The trade must exit on the
    ENTRY day's last bar close — not book the overnight gap as a +2R target fill."""
    d = _frame({"2026-01-05": {**OR, "15:45": (104.4, 105.2, 104.0, 104.5)},
                "2026-01-06": {"09:30": (125.0, 130.0, 124.0, 128.0)}})
    tr = _bt(d)
    assert len(tr) == 1
    t = tr.iloc[0]
    exit_et = pd.Timestamp(t.exit_time).tz_convert(ET)
    assert exit_et.date().isoformat() == "2026-01-05", (
        f"day trade leaked overnight: exited {exit_et} (the next morning's gap filled "
        f"yesterday's target)")
    exp = (BASE - t.entry_price) / t.risk_pts          # flatten at the 15:55 flat close
    assert abs(t.gross_R - exp) < 1e-3, f"EOD flatten must price at the last bar's close (got {t.gross_R:+.3f})"


def test_s1_touch_entry_bar_remainder_favorable_and_adverse():
    """execm='stop': the entry bar itself can finish the trade.
    (a) touch at 104 then the same bar runs beyond TP2 -> exit same bar at TP2.
    (b) touch at 104 then the same bar CLOSES below the stop -> stopped same bar."""
    da = _frame({"2026-01-05": {**OR, "10:00": (103.0, 125.0, 102.5, 120.0)}})
    tra = _bt(da, execm="stop")
    assert len(tra) == 1 and pd.Timestamp(tra.iloc[0].exit_time) == pd.Timestamp(tra.iloc[0].entry_time), \
        "favorable remainder of the touch-entry bar must be evaluated (TP2 was hit post-touch)"
    assert abs(tra.iloc[0].gross_R - 2.0) < 1e-9

    db = _frame({"2026-01-05": {**OR, "10:00": (103.0, 104.2, 90.0, 92.0),
                                "10:05": (92.0, 130.0, 91.0, 128.0)}})    # would be +2R if leaked
    trb = _bt(db, execm="stop")
    assert len(trb) == 1
    tb = trb.iloc[0]
    assert abs(tb.gross_R - (-1.0)) < 1e-9, (
        f"entry bar CLOSED beyond the stop — the trade was stopped same-bar, not rescued by the "
        f"next bar's rally (got {tb.gross_R:+.3f})")


def test_s6_maxdd_counts_initial_losses():
    assert V.maxdd(np.array([-1.0, -1.0, 3.0])) == -2.0, \
        "equity curve must start at 0: two opening losses = -2R drawdown"


def test_t22_determinism_identical_runs():
    d1 = _frame({"2026-01-05": {**OR, "10:00": (104.4, 105.2, 104.0, 104.5),
                                "10:05": (90.0, 91.0, 89.0, 90.5)}})
    d2 = d1.copy(deep=True)
    d2.attrs["sym"] = "NQ"
    pd.testing.assert_frame_equal(_bt(d1), _bt(d2))


def test_t23_ordering_policy_is_documented():
    doc = (B.backtest.__doc__ or "") + (B.__doc__ or "")
    for phrase in ("BAR-EVENT ORDERING", "stop wins", "gap-aware"):
        assert phrase.lower() in doc.lower(), f"ordering policy missing from docstring: {phrase!r}"


def test_s7_sweepgo_state_is_prior_bar_for_touch_fills():
    """execm='sweepgo': a bar that sweeps the low AND breaks the high can't prove its sequence —
    no same-bar fire; sweep on one bar, break on the NEXT is a legitimate fill."""
    same = _frame({"2026-01-05": {**OR, "10:00": (102.0, 105.0, 99.0, 104.8)}})   # sweep+break, one bar
    assert len(_bt(same, execm="sweepgo")) == 0, \
        "same-bar sweep+break fired — intrabar sequence is unprovable, state must be prior-bar"
    seq = _frame({"2026-01-05": {**OR, "10:00": (102.0, 102.5, 99.0, 101.0),      # sweep the low
                                 "10:05": (101.0, 105.0, 100.8, 104.8)}})         # break the high
    assert len(_bt(seq, execm="sweepgo")) == 1, "sweep-then-break across bars must still fire"


def test_t24_tradeday_sunday_session_groups_to_one_trade_day():
    """tradeday=True: a Sunday-evening entry belongs to Monday's trade day — it must survive the
    ET midnight AND the UTC date boundary, exiting on the trade-day's last bar (Mon 17:45 ET)."""
    days = {}
    rows = {}
    for t in ("18:00", "18:15", "18:30"):
        rows[t] = (BASE, 104.0, 100.0, BASE)                       # 18:00-18:45 OR
    rows["19:00"] = (104.4, 105.2, 104.0, 104.5)                   # Sunday-evening break
    d1 = pd.date_range("2026-01-04 18:00", "2026-01-04 23:45", freq="15min", tz=ET)
    d2 = pd.date_range("2026-01-05 00:00", "2026-01-05 17:45", freq="15min", tz=ET)
    recs = []
    for t in list(d1) + list(d2):
        key = t.strftime("%H:%M") if t.date().isoformat() == "2026-01-04" else None
        o = h = l = c = BASE
        if key and key in rows:
            o, h, l, c = rows[key]
        recs.append({"ts": t.tz_convert("UTC"), "open": float(o), "high": float(h),
                     "low": float(l), "close": float(c), "volume": 1_000.0})
    d = pd.DataFrame(recs)
    d["atr14"] = ATR
    for col in ("vwap_sess", "vwap_wk", "ema9", "ema20", "ema50"):
        d[col] = np.nan
    d["macro_regime"] = "A"; d["macro_allow_trades"] = True
    d["macro_long_ok"] = True; d["macro_short_ok"] = True
    d["local_regime"] = 0; d["trend_up"] = True; d["trend_down"] = True
    d.attrs["sym"] = "NQ"
    tr = B.backtest(d, "tp2_full", "both", False, "orb", 0, 1.0, 2.0, 0, 45, 0.0, 1435, "close",
                    tradeday=True, eod_min=1430, stop_mode="or")
    assert len(tr) == 1
    t = tr.iloc[0]
    ent = pd.Timestamp(t.entry_time).tz_convert(ET)
    ext = pd.Timestamp(t.exit_time).tz_convert(ET)
    assert ent.date().isoformat() == "2026-01-04", "entry must be the Sunday-evening break"
    assert ext.date().isoformat() == "2026-01-05" and ext.hour >= 17, (
        f"Sunday entry must ride its trade day to Monday's last bar, not get cut at an ET/UTC "
        f"midnight (exited {ext})")
