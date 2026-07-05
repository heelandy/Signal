"""Historical data-QA report (AITP-001 §Immediate-Priority 1 — Validate Historical Data).

DuckDB checks over the partitioned bar store, per symbol/timeframe/session:
coverage + span, duplicate timestamps, bad candles (high<low, wick geometry), zero/negative
volume, null OHLCV, calendar gaps (> max_gap_days between consecutive trade dates), and
intraday completeness (bars per day vs the session's expected grid).

    python pipeline/hs_data_qa.py QQQ SPY NQ ES GC          # writes the JSON report + prints
    from hs_data_qa import qa_report                        # API/dashboard entry point

Report -> BOT/data/ml/reports/dataqa.json (the Training Lab reads it).
"""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "engine"))
os.chdir(ROOT)                                    # hs_db uses repo-root-relative data/ paths

import hs_db  # noqa: E402

REPORT = ROOT / "BOT" / "data" / "ml" / "reports" / "dataqa.json"
EXPECTED_BARS = {("5m", "rth"): 78, ("1m", "rth"): 390}     # full RTH grid per trade day


def qa_symbol(con, sym: str, tf: str = "5m", sess: str = "rth", max_gap_days: int = 5) -> dict:
    base = "FROM bars WHERE sym=? AND tf=? AND session=?"
    args = [sym.upper(), tf, sess]
    n = con.execute(f"SELECT count(*) {base}", args).fetchone()[0]
    if not n:
        return {"rows": 0, "error": "no bars for this sym/tf/session"}
    span = con.execute(f"SELECT min(ts), max(ts) {base}", args).fetchone()
    dupes = con.execute(f"SELECT count(*) - count(DISTINCT ts) {base}", args).fetchone()[0]
    bad = con.execute(
        f"SELECT sum(CASE WHEN high < low THEN 1 ELSE 0 END),"
        f" sum(CASE WHEN high < greatest(open, close) OR low > least(open, close) THEN 1 ELSE 0 END),"
        f" sum(CASE WHEN volume <= 0 THEN 1 ELSE 0 END),"
        f" sum(CASE WHEN open IS NULL OR high IS NULL OR low IS NULL OR close IS NULL THEN 1 ELSE 0 END)"
        f" {base}", args).fetchone()
    # calendar gaps between consecutive trade dates (weekends ~2-3 days, long holidays ~4)
    gaps = con.execute(
        f"WITH d AS (SELECT DISTINCT CAST(ts AS DATE) dt {base})"
        f" SELECT count(*) FROM (SELECT dt, lag(dt) OVER (ORDER BY dt) p FROM d)"
        f" WHERE p IS NOT NULL AND date_diff('day', p, dt) > ?", args + [max_gap_days]).fetchone()[0]
    # intraday completeness: bars per trade day vs the expected session grid
    per_day = con.execute(
        f"WITH d AS (SELECT CAST(ts AS DATE) dt, count(*) nb {base} GROUP BY 1)"
        f" SELECT avg(nb), min(nb), max(nb),"
        f" sum(CASE WHEN nb < ? THEN 1 ELSE 0 END), count(*) FROM d",
        args + [int(0.9 * EXPECTED_BARS.get((tf, sess), 0)) or 1]).fetchone()
    exp = EXPECTED_BARS.get((tf, sess))
    issues = []
    if dupes:
        issues.append(f"{dupes} duplicate timestamps")
    if bad[0]:
        issues.append(f"{bad[0]} bars with high<low")
    if bad[1]:
        issues.append(f"{bad[1]} bars with broken wick geometry")
    if bad[3]:
        issues.append(f"{bad[3]} bars with null OHLC")
    if gaps:
        issues.append(f"{gaps} calendar gaps > {max_gap_days} days")
    return {"rows": int(n), "span": [str(span[0])[:19], str(span[1])[:19]],
            "dupe_ts": int(dupes), "high_lt_low": int(bad[0] or 0),
            "bad_wick_geometry": int(bad[1] or 0), "zero_or_neg_volume": int(bad[2] or 0),
            "null_ohlc": int(bad[3] or 0), "calendar_gaps": int(gaps),
            "bars_per_day": {"avg": round(float(per_day[0]), 1), "min": int(per_day[1]),
                             "max": int(per_day[2]), "expected": exp,
                             "short_days": int(per_day[3] or 0), "days": int(per_day[4])},
            "issues": issues, "ok": not issues}


def qa_report(syms: list[str], tf: str = "5m", sess: str = "rth", save: bool = True) -> dict:
    import pandas as pd
    con = hs_db.connect()
    out = {"generated_at": pd.Timestamp.now("UTC").isoformat(), "tf": tf, "session": sess,
           "symbols": {}}
    for sym in syms:
        try:
            out["symbols"][sym.upper()] = qa_symbol(con, sym, tf, sess)
        except Exception as e:
            out["symbols"][sym.upper()] = {"error": str(e)[:200]}
    con.close()
    if save:
        REPORT.parent.mkdir(parents=True, exist_ok=True)
        REPORT.write_text(json.dumps(out, indent=1), encoding="utf-8")
    return out


if __name__ == "__main__":
    syms = [s.upper() for s in (sys.argv[1:] or ["QQQ", "SPY", "NQ", "ES", "GC"])]
    rep = qa_report(syms)
    for sym, r in rep["symbols"].items():
        if r.get("error"):
            print(f"{sym}: ERROR {r['error']}")
            continue
        flag = "OK " if r["ok"] else "!! "
        print(f"{flag}{sym}: {r['rows']:,} bars {r['span'][0][:10]}..{r['span'][1][:10]} | "
              f"dupes {r['dupe_ts']} | bad candles {r['high_lt_low']}/{r['bad_wick_geometry']} | "
              f"gaps {r['calendar_gaps']} | bars/day avg {r['bars_per_day']['avg']} "
              f"(exp {r['bars_per_day']['expected']}, short days {r['bars_per_day']['short_days']})")
        for i in r["issues"]:
            print(f"     - {i}")
    print(f"\nsaved -> {REPORT}")
