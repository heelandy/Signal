"""PIT NO-LOOKAHEAD CANARIES (remediation Phase 1, tests T1.1-T1.3 — written RED-first).

The 2026-07-11 audit confirmed `engine/hs_backtest._externals` merged daily VIX / ES / HTF values
onto every intraday bar of the SAME date — a 09:35 signal saw that day's 16:00 daily close. These
tests pin the corrected invariant: every daily-derived column on a bar dated D must come from the
most recent COMPLETED session strictly BEFORE D (and must actually arrive on D+1 — over-lagging or
dropping the join entirely also fails).

Synthetic in-memory DuckDB only (CI runs without the data drive), shaped like the real store:
a `vix_daily` table and a `bars` table serving the 1d/full frames `_externals` queries.
"""
from __future__ import annotations

import os
import sys

import duckdb
import numpy as np
import pandas as pd

ENGINE = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", "engine"))
if ENGINE not in sys.path:
    sys.path.insert(0, ENGINE)

import hs_backtest as B  # noqa: E402
import hs_harness as H  # noqa: E402

ET = "America/New_York"
SYM = "NQ"


def _days(n=14, start="2026-01-05"):
    return list(pd.bdate_range(start, periods=n))


def _synth_con(days, vix_sma5, vix_close, es_close, sym_close):
    """In-memory store: vix_daily(date, sma5, close) + bars(1d, full) for ES and SYM."""
    con = duckdb.connect()
    vix = pd.DataFrame({"date": pd.to_datetime(days), "sma5": np.asarray(vix_sma5, float),
                        "close": np.asarray(vix_close, float)})
    con.register("vix_src", vix)
    con.execute("CREATE TABLE vix_daily AS SELECT * FROM vix_src")

    def daily(sym, closes):
        ts = [pd.Timestamp(d, tz=ET).tz_convert("UTC") + pd.Timedelta(hours=21) for d in days]
        c = np.asarray(closes, float)
        return pd.DataFrame({"ts": ts, "open": c, "high": c * 1.01, "low": c * 0.99, "close": c,
                             "volume": 1_000.0, "sym": sym, "tf": "1d", "session": "full",
                             "year": [d.year for d in days]})

    dr = pd.concat([daily("ES", es_close), daily(SYM, sym_close)], ignore_index=True)
    con.register("bars_src", dr)
    con.execute("CREATE TABLE bars AS SELECT * FROM bars_src")
    return con


def _intraday(days):
    """Three 5m bars per day (09:35 / 10:30 / 15:55 ET), flat prices."""
    rows = []
    for d in days:
        for hm in (575, 630, 955):
            t = pd.Timestamp(d, tz=ET) + pd.Timedelta(minutes=hm)
            rows.append({"ts": t.tz_convert("UTC"), "open": 100.0, "high": 101.0,
                         "low": 99.0, "close": 100.5, "volume": 10.0})
    return pd.DataFrame(rows)


def _bar_dates(out):
    return pd.to_datetime(out["ts"]).dt.tz_convert(ET).dt.normalize().dt.tz_localize(None)


def test_t11_poison_canary_daily_values_invisible_same_day():
    """T1.1: a sentinel planted in day P's daily VIX/ES/HTF must NOT appear on day P's intraday
    bars — and MUST appear on day P+1's (guards against over-lagging / dropping the join)."""
    days = _days()
    P = 9
    vix = [11.0] * len(days)
    vix[P] = 999.0                                   # poison VIX sma5 on day P
    es = [100.0] * len(days)
    es[P] = 55_555.0                                 # poison ES daily close on day P
    sym = [100.0] * P + [200.0] * (len(days) - P)    # HTF alignment flips bullish ON day P
    con = _synth_con(days, vix, vix, es, sym)
    out = B._externals(con, _intraday(days), SYM)
    con.close()
    bd = _bar_dates(out)
    on_p, on_p1 = out[bd == days[P]], out[bd == days[P + 1]]
    assert len(on_p) and len(on_p1), "fixture broken: no bars on the poison day"

    assert not (on_p["vix_sma5"] == 999.0).any(), (
        "LOOKAHEAD: day P's intraday bars carry day P's own daily VIX sma5 — a morning signal is "
        "reading the not-yet-closed daily candle")
    assert not (on_p["spy_close"] == 55_555.0).any(), (
        "LOOKAHEAD: day P's intraday bars carry day P's own ES daily close")
    assert not on_p["htf_bull"].any(), (
        "LOOKAHEAD: day P's intraday bars carry day P's own daily EMA50/200 alignment")

    assert (on_p1["vix_sma5"] == 999.0).all(), "day P's VIX value never arrived on day P+1 (over-lagged?)"
    assert (on_p1["spy_close"] == 55_555.0).all(), "day P's ES close never arrived on day P+1"
    assert on_p1["htf_bull"].all(), "day P's HTF flip never arrived on day P+1"


def test_t12_property_every_daily_value_predates_its_bar():
    """T1.2: encode each daily row's value AS its date ordinal — after the join, every bar's
    daily-derived value must decode to a date strictly BEFORE the bar's date, and to the most
    recent such session (no stale skips)."""
    days = _days()
    ords = [float(d.toordinal()) for d in days]
    con = _synth_con(days, ords, ords, ords, [100.0] * len(days))
    out = B._externals(con, _intraday(days), SYM)
    con.close()
    bd = _bar_dates(out)
    prev = {days[i]: days[i - 1] for i in range(1, len(days))}
    got = out[["vix_sma5", "spy_close"]].to_numpy(float)
    for col in range(got.shape[1]):
        for bar_date, val in zip(bd, got[:, col]):
            if np.isnan(val) or bar_date not in prev:      # first day has no prior session
                continue
            src = pd.Timestamp.fromordinal(int(val))
            assert src < bar_date, (
                f"LOOKAHEAD: bar dated {bar_date.date()} carries a daily value from "
                f"{src.date()} (not strictly prior)")
            assert src == prev[bar_date], (
                f"WRONG SESSION: bar dated {bar_date.date()} should carry {prev[bar_date].date()} "
                f"(most recent completed), got {src.date()}")


def test_t13_regime_shift_gates_next_day_not_same_day():
    """T1.3: a VIX regime flip to D (extreme) on day P must first affect gating on day P+1 —
    with the lookahead, day P's own morning bars are already blocked by an afternoon reading."""
    days = _days()
    P = 9
    vix = [12.0] * len(days)
    for i in range(P, len(days)):
        vix[i] = 99.0                                # >= vix_extreme (35) from day P onward
    con = _synth_con(days, vix, vix, [100.0] * len(days), [100.0] * len(days))
    out = B._externals(con, _intraday(days), SYM)
    con.close()
    d = H.compute_state(out, H.P(struct_lb_fix=3))
    bd = _bar_dates(d)
    reg_p = d.loc[(bd == days[P]).to_numpy(), "macro_regime"]
    reg_p1 = d.loc[(bd == days[P + 1]).to_numpy(), "macro_regime"]
    assert not (reg_p == "D").any(), (
        "LOOKAHEAD: day P is already regime-D on its own bars — the flip used day P's daily data")
    assert (reg_p1 == "D").all(), "regime flip never arrived on day P+1"
