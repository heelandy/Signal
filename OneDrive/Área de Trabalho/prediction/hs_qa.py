#!/usr/bin/env python3
"""
HIGHSTRIKE Phase 0.6 — Reusable data-QA module.

Instrument-agnostic checks to run on EVERY new data drop (NQ, ES, VIX, equities):
  * holiday-aware coverage  (expected vs present trading days, list the holes)
  * gap scan                (missing bars, weekend/holiday/CME-halt aware)
  * duplicate timestamps
  * OHLC integrity + non-positive prices
  * modal bar interval

Importable:
    from hs_qa import qa_frame
    report = qa_frame(df, name="ES 5m", tf_sec=300, ts="ts", tz="America/New_York")

CLI (runs the suite over the built NQ artifacts via the DuckDB layer):
    python hs_qa.py
"""
import os, sys
import numpy as np, pandas as pd
from pandas.tseries.holiday import (
    AbstractHolidayCalendar, Holiday, nearest_workday, GoodFriday,
    USMartinLutherKingJr, USPresidentsDay, USMemorialDay, USLaborDay,
    USThanksgivingDay,
)

ET = "America/New_York"


class USMarketCalendar(AbstractHolidayCalendar):
    """NYSE/CME equity-index full-holiday calendar (no early-close handling)."""
    rules = [
        Holiday("NewYears", month=1, day=1, observance=nearest_workday),
        USMartinLutherKingJr,
        USPresidentsDay,
        GoodFriday,
        USMemorialDay,
        Holiday("Juneteenth", month=6, day=19, start_date="2022-06-19",
                observance=nearest_workday),
        Holiday("Independence", month=7, day=4, observance=nearest_workday),
        USLaborDay,
        USThanksgivingDay,
        Holiday("Christmas", month=12, day=25, observance=nearest_workday),
    ]


_CAL = USMarketCalendar()


def expected_trading_days(start, end):
    """Set of expected US-market session dates in [start, end] (weekday minus holidays)."""
    days = pd.bdate_range(start, end, freq="C",
                          holidays=_CAL.holidays(start, end).to_pydatetime())
    return set(d.date() for d in days)


def qa_frame(df, name, tf_sec, ts="ts", tz=ET,
             o="open", h="high", l="low", c="close", v="volume", verbose=True):
    """Run the full QA suite on one OHLCV frame. Returns a dict; prints if verbose."""
    d = df[[ts, o, h, l, c] + ([v] if v in df.columns else [])].copy()
    t = pd.to_datetime(d[ts], utc=True)
    et = t.dt.tz_convert(tz)
    d["_dt"] = t
    d["_date"] = et.dt.date
    d = d.sort_values("_dt").reset_index(drop=True)

    R = {"name": name, "rows": len(d),
         "span": (et.min(), et.max())}

    # --- dup timestamps -------------------------------------------------
    R["dups"] = int(d["_dt"].duplicated().sum())

    # --- OHLC integrity -------------------------------------------------
    bad_hl = ((d[h] < d[l]) | (d[h] < d[o]) | (d[h] < d[c]) |
              (d[l] > d[o]) | (d[l] > d[c])).sum()
    R["ohlc_invalid"] = int(bad_hl)
    R["non_positive"] = int((d[[o, h, l, c]] <= 0).any(axis=1).sum())

    # --- modal bar interval --------------------------------------------
    deltas = d["_dt"].diff().dt.total_seconds().dropna()
    R["modal_sec"] = int(deltas.mode().iloc[0]) if len(deltas) else None

    # --- holiday-aware coverage ----------------------------------------
    present = set(d["_date"].unique())
    exp = expected_trading_days(min(present), max(present))
    missing = sorted(exp - present)
    extra   = sorted(present - exp)            # sessions on "holidays" (early opens etc.)
    R["sessions_present"]  = len(present)
    R["sessions_expected"] = len(exp)
    R["sessions_missing"]  = len(missing)
    R["missing_sample"]    = [str(x) for x in missing[:8]]
    R["noncal_sessions"]   = len(extra)

    # --- gap scan (intraday only) --------------------------------------
    if tf_sec and tf_sec < 86400:
        secs = deltas
        same_day = d["_dt"].dt.tz_convert(tz).dt.date.values[1:] == \
                   d["_dt"].dt.tz_convert(tz).dt.date.values[:-1]
        et_prev = et.values[:-1]
        # classify holes that are bigger than one bar
        big = secs > tf_sec
        # CME daily maintenance break 17:00-18:00 ET -> a bar ending ~16:59 then 18:00
        prev_min = (pd.Series(et_prev).dt.hour * 60 + pd.Series(et_prev).dt.minute).values
        halt = big.values & (prev_min >= 16 * 60) & (prev_min < 18 * 60)
        weekend = big.values & ~np.asarray(same_day) & ~halt
        intraday = big.values & np.asarray(same_day)        # same-day holes = true missing bars
        R["gaps_intraday"] = int(intraday.sum())
        R["gaps_halt"]     = int(halt.sum())
        R["gaps_overnight_weekend"] = int(weekend.sum())
        # worst same-day holes
        idx = np.where(intraday)[0]
        worst = sorted(((secs.iloc[i], et.iloc[i + 1]) for i in idx),
                       reverse=True)[:5]
        R["worst_intraday_gaps"] = [(int(s), str(ts_)) for s, ts_ in worst]
    if verbose:
        _print(R)
    return R


def _print(R):
    print(f"\n=== QA: {R['name']} ===")
    print(f"  rows {R['rows']:,}   span {R['span'][0]} .. {R['span'][1]}")
    print(f"  modal bar (sec):   {R['modal_sec']}")
    print(f"  dup timestamps:    {R['dups']:,}")
    print(f"  OHLC invalid:      {R['ohlc_invalid']:,}    non-positive: {R['non_positive']:,}")
    print(f"  sessions:          present {R['sessions_present']:,} / expected "
          f"{R['sessions_expected']:,}   missing {R['sessions_missing']:,}"
          f"   non-calendar {R['noncal_sessions']:,}")
    if R["sessions_missing"]:
        print(f"    missing sample:  {R['missing_sample']}")
    if "gaps_intraday" in R:
        print(f"  gaps: intraday(missing-bar) {R['gaps_intraday']:,}   "
              f"daily-halt {R['gaps_halt']:,}   overnight/weekend {R['gaps_overnight_weekend']:,}")
        if R["worst_intraday_gaps"]:
            print(f"    worst same-day holes (sec @ end): {R['worst_intraday_gaps']}")


def main():
    import hs_db
    con = hs_db.connect()
    # symbols: CLI arg (e.g. `python hs_qa.py ES`) or every continuous-1m view on disk
    if len(sys.argv) > 1:
        syms = [s.upper() for s in sys.argv[1:]]
    else:
        syms = [r[0].split("_")[0].upper() for r in con.execute(
            "SELECT table_name FROM information_schema.tables "
            "WHERE table_name LIKE '%_1m' ORDER BY table_name").fetchall()]
    for sym in syms:
        df1 = con.execute(f"SELECT ts_utc AS ts, open, high, low, close, volume "
                          f"FROM {sym.lower()}_1m").df()
        qa_frame(df1, f"{sym} continuous 1m", tf_sec=60)
        for tf, sess, sec in [("5m", "rth", 300), ("1d", "full", 86400)]:
            d = con.execute("SELECT ts, open, high, low, close, volume FROM bars "
                            "WHERE sym=? AND tf=? AND session=? ORDER BY ts",
                            [sym, tf, sess]).df()
            qa_frame(d, f"{sym} {tf} {sess}", tf_sec=sec)
    con.close()


if __name__ == "__main__":
    main()
