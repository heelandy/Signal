"""BUG HUNT — Wave 4 (clocks & calendars).

W4.1  the daily/weekly loss gates bucket realized fills by the ET TRADE DAY. Fills store the
      broker's UTC `updated_at`; an overnight (futures) fill after ~20:00 ET has a NEXT-day UTC
      date. Bucketing on the raw UTC date put such a loss in the wrong ET day and mis-fed the
      loss gates. (armor + fix)
W4.2  `_trade_date` / idem trade-date are ET and DST-safe (a submit does not change its ET day
      across the spring-forward instant). (armor)
W4.3  persister session tagging converts to ET before tagging RTH, so DST does not shift the
      RTH window. (armor)
"""
from __future__ import annotations

from datetime import datetime
from zoneinfo import ZoneInfo

import pytest

pd = pytest.importorskip("pandas")

from bot.brokers.base import AccountInfo  # noqa: E402
from bot.contracts import Mode, OrderEvent, OrderState, PositionState  # noqa: E402
from bot.execution.service import ExecutionService, _fill_et_date  # noqa: E402
from bot.market_data import live_persist as LP  # noqa: E402

ET = ZoneInfo("America/New_York")


class MockBroker:
    name = "mock"; is_paper = True

    def __init__(self):
        self.book: list[PositionState] = []

    def account(self):
        return AccountInfo(equity=25_000.0, buying_power=50_000.0, cash=25_000.0,
                           open_position_count=0, is_paper=True)

    def positions(self):
        return list(self.book)

    def submit(self, order):
        return OrderEvent(order_id=order.order_id, state=OrderState.SUBMITTED, broker_order_id="B1")

    def recent_orders(self):
        return []


@pytest.fixture()
def svc(tmp_path):
    # clock fixed to 2026-07-13 12:00 ET (a Monday) -> _trade_date() == "2026-07-13"
    t = datetime(2026, 7, 13, 12, 0, tzinfo=ET).timestamp()
    s = ExecutionService(MockBroker(), db_path=tmp_path / "exec.db", mode=Mode.PAPER, now=lambda: t)
    return s


def test_w4_overnight_fill_buckets_by_et_day_not_utc(svc):
    """A losing futures fill at 01:xx UTC == 21:xx ET the PRIOR evening belongs to that ET trade
    day. With today ET = 2026-07-13, a fill stamped 2026-07-14T01:05Z (= 2026-07-13 21:05 ET) must
    count in TODAY's daily P&L — the raw-UTC bucket wrongly dropped it into 07-14."""
    assert svc._trade_date() == "2026-07-13"
    fills = [("f0", "o0", "B", "NQ", "long", 1, 20_000.0, "2026-07-14T01:00:00+00:00"),
             ("f1", "o1", "B", "NQ", "short", 1, 19_950.0, "2026-07-14T01:05:00+00:00")]  # -50pts*$20
    svc.db.executemany("INSERT INTO exec_fills VALUES(?,?,?,?,?,?,?,?)", fills)
    svc.db.commit()
    acct = svc.account_truth()
    assert acct.daily_pnl == pytest.approx(-1000.0), (
        f"an ET-evening loss must count in today's ET daily bucket, got {acct.daily_pnl}")
    assert acct.weekly_pnl == pytest.approx(-1000.0)


def test_w4_fill_et_date_helper():
    assert _fill_et_date("2026-07-14T01:05:00+00:00") == "2026-07-13"   # 1am UTC -> 9pm ET prior day
    assert _fill_et_date("2026-07-13T15:00:00") == "2026-07-13"          # naive = local
    assert _fill_et_date("2026-07-13T20:00:00Z") == "2026-07-13"         # 8pm UTC = 4pm ET, same day


def test_w4_trade_date_is_et_and_dst_safe(tmp_path):
    """Across the 2026-03-08 spring-forward, the ET trade date is stable and correct — 01:30 ET
    (before the skip) and 03:30 ET (after) are the SAME calendar day."""
    for hhmm, expect in ((1, "2026-03-08"), (3, "2026-03-08"), (23, "2026-03-08")):
        t = datetime(2026, 3, 8, hhmm, 30, tzinfo=ET).timestamp()
        s = ExecutionService(MockBroker(), db_path=tmp_path / f"e{hhmm}.db", mode=Mode.PAPER,
                             now=lambda tt=t: tt)
        assert s._trade_date() == expect


def test_w4_persister_session_tag_is_dst_safe(tmp_path):
    """A bar at 10:00 ET on the spring-forward day tags RTH regardless of the DST shift — the
    persister converts to ET before computing the session window."""
    store = pd.DataFrame({
        "ts_et": pd.date_range("2026-03-06 09:30", periods=5, freq="5min", tz=ET),
        "open": 100.0, "high": 101.0, "low": 99.0, "close": 100.0, "volume": 1000,
        "session": "RTH"})
    p = tmp_path / "spy_continuous_1m.parquet"
    store.to_parquet(p, index=False)
    # a fetch on the DST day, at 10:00 ET (RTH) and 08:00 ET (pre-market)
    ts = pd.to_datetime(["2026-03-09 08:00", "2026-03-09 10:00"]).tz_localize(ET)
    fetched = pd.DataFrame({"ts_et": ts, "open": 100.0, "high": 101.0, "low": 99.0,
                            "close": 100.0, "volume": 500})
    LP.append_bars(p, fetched, "SPY")
    out = pd.read_parquet(p)
    tags = out.set_index(out["ts_et"].astype(str))["session"]
    rth = tags[tags.index.str.contains("10:00")]
    eth = tags[tags.index.str.contains("08:00")]
    assert (rth == "RTH").all() and (eth == "ETH").all(), out[["ts_et", "session"]].to_dict("records")


def test_w4_fall_back_duplicate_hour_buckets_to_one_et_day():
    """2026-11-01 fall-back: 01:30 ET happens TWICE (05:30Z EDT, then 06:30Z EST). Both instants
    are the SAME ET calendar day — the loss-gate bucket and the trade date must not split them."""
    assert _fill_et_date("2026-11-01T05:30:00+00:00") == "2026-11-01"   # 01:30 EDT (first)
    assert _fill_et_date("2026-11-01T06:30:00+00:00") == "2026-11-01"   # 01:30 EST (second)


def test_w4_fall_back_duplicate_walltime_keeps_both_bars(tmp_path):
    """The persister must keep BOTH fall-back 01:30 bars — they are distinct UTC instants (aware
    timestamps), not a duplicate to collapse. Dedup is on the timestamp, and these differ."""
    store = pd.DataFrame({
        "ts_et": pd.to_datetime(["2026-11-01T04:00:00Z", "2026-11-01T04:30:00Z"]).tz_convert(ET),
        "open": 100.0, "high": 101.0, "low": 99.0, "close": 100.0, "volume": 1000})
    p = tmp_path / "spy_continuous_1m.parquet"
    store.to_parquet(p, index=False)
    # two bars at 01:30 ET wall-clock: 05:30Z (EDT) and 06:30Z (EST) — different instants
    ts = pd.to_datetime(["2026-11-01T05:30:00Z", "2026-11-01T06:30:00Z"]).tz_convert(ET)
    fetched = pd.DataFrame({"ts_et": ts, "open": 100.0, "high": 101.0, "low": 99.0,
                            "close": 100.0, "volume": 500})
    r = LP.append_bars(p, fetched, "SPY")
    assert r.get("appended") == 2, f"both fall-back instants must persist (distinct UTC): {r}"


# ── half-days / early close ──

def _engine():
    import os
    import sys
    eng = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", "engine"))
    if eng not in sys.path:
        sys.path.insert(0, eng)
    import hs_backtest as B
    return B


def test_w4_half_day_flattens_on_the_last_bar_not_overnight():
    """A 13:00-ET early close (half-day): the store simply ends at 13:00, so `_last_of_day` fires
    there. A late entry must flatten at the 13:00 last bar's close — never carry into the next
    session (the EOD flatten is DATA-driven, so a short calendar day needs no special clock)."""
    import numpy as np
    B = _engine()
    OR = {t: (102.0, 104.0, 100.0, 102.0) for t in ("09:30", "09:35", "09:40", "09:45", "09:50", "09:55")}
    # half-day 09:30 -> 13:00, entry at 12:55, then next session opens with a huge gap
    times = list(pd.date_range("2026-11-27 09:30", "2026-11-27 13:00", freq="5min", tz=ET))
    times += list(pd.date_range("2026-11-30 09:30", "2026-11-30 09:45", freq="5min", tz=ET))
    rows = []
    for t in times:
        o = h = l = c = 102.0
        key = t.strftime("%H:%M") if t.date().isoformat() == "2026-11-27" else None
        if key in OR:
            o, h, l, c = OR[key]
        if t.date().isoformat() == "2026-11-27" and key == "12:55":
            o, h, l, c = 104.4, 105.2, 104.0, 104.5           # late break -> long
        if t.date().isoformat() == "2026-11-30":
            o = h = l = c = 130.0                              # next session gaps up huge
        rows.append({"ts": t.tz_convert("UTC"), "open": float(o), "high": float(h),
                     "low": float(l), "close": float(c), "volume": 1000.0})
    d = pd.DataFrame(rows)
    d["atr14"] = 8.0
    for col in ("vwap_sess", "vwap_wk", "ema9", "ema20", "ema50"):
        d[col] = np.nan
    d["macro_regime"] = "A"; d["macro_allow_trades"] = True
    d["macro_long_ok"] = True; d["macro_short_ok"] = True
    d["local_regime"] = 0; d["trend_up"] = True; d["trend_down"] = True
    d.attrs["sym"] = "NQ"
    tr = B.backtest(d, "tp2_full", "both", False, "orb", 0, 1.0, 2.0, 570, 600, 0.0, 960, "close",
                    eod_min=958, stop_mode="or")
    assert len(tr) == 1
    ext = pd.Timestamp(tr.iloc[0].exit_time).tz_convert(ET)
    assert ext.date().isoformat() == "2026-11-27" and ext.hour <= 13, (
        f"the half-day trade must flatten on its 13:00 last bar, not leak into 11-30 (exited {ext})")
