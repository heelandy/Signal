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
MANIFEST = ROOT / "data" / "mbo_bars_manifest.json"
EXPECTED_BARS = {("5m", "rth"): 78, ("1m", "rth"): 390}     # full RTH grid per trade day
TF_SECONDS = {"1m": 60, "3m": 180, "5m": 300, "15m": 900, "30m": 1800,
              "1h": 3600, "2h": 7200, "4h": 14400}
FRESHNESS_BDAYS = 3            # Phase 4: span end older than this many trading days = STALE
SHORT_DAY_PCT = 2.0            # Phase 4: more than this % of days under 90% expected bars = FAIL


def _grain_exception(sym: str, tf: str) -> str | None:
    """Registered grain exceptions (e.g. the documented 5m-as-1m NQ append) live in the
    provenance manifest — an exception is DECLARED, never inferred."""
    try:
        m = json.loads(MANIFEST.read_text(encoding="utf-8"))
    except Exception:
        return None
    k = f"{sym.upper()}_5m_append"
    if tf == "1m" and k in m:
        rng = m[k].get("appended_range")
        return f"registered exception {k}: {rng}"
    return None


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
    # intra-day bar spacing (grain): a nominal-5m table must actually tick in 5-minute steps
    grain = con.execute(
        f"WITH s AS (SELECT date_diff('second', lag(ts) OVER (PARTITION BY CAST(ts AS DATE)"
        f" ORDER BY ts), ts) dsec {base})"
        f" SELECT median(dsec), quantile_cont(dsec, 0.95) FROM s WHERE dsec IS NOT NULL",
        args).fetchone()
    exp = EXPECTED_BARS.get((tf, sess))
    import numpy as _np
    import pandas as _pd
    issues = []
    if dupes:
        issues.append(f"{dupes} duplicate timestamps")
    if bad[0]:
        issues.append(f"{bad[0]} bars with high<low")
    if bad[1]:
        issues.append(f"{bad[1]} bars with broken wick geometry")
    if bad[2]:
        # Phase 4: zero/negative volume is a FAILURE, not a statistic (fail-open audit defect)
        issues.append(f"{bad[2]} zero/negative-volume bars")
    if bad[3]:
        issues.append(f"{bad[3]} bars with null OHLC")
    if gaps:
        issues.append(f"{gaps} calendar gaps > {max_gap_days} days")
    # Phase 4 FRESHNESS gate: the span must end within FRESHNESS_BDAYS trading days of today
    end_day = _pd.Timestamp(str(span[1])[:10]).date()
    stale_bd = int(_np.busday_count(end_day, _pd.Timestamp.now(tz="America/New_York").date()))
    if stale_bd > FRESHNESS_BDAYS:
        issues.append(f"STALE: last bar {end_day} is {stale_bd} trading days old "
                      f"(max {FRESHNESS_BDAYS})")
    # Phase 4 SESSION-COMPLETENESS gate: too many short days = broken sessions, not noise
    short_pct = 100.0 * (per_day[3] or 0) / max(per_day[4], 1)
    if exp and short_pct > SHORT_DAY_PCT:
        issues.append(f"{per_day[3]} short days = {short_pct:.1f}% of {per_day[4]} "
                      f"(max {SHORT_DAY_PCT}%) — sessions under 90% of the {exp}-bar grid")
    # Phase 4 GRAIN gate: median AND p95 intra-day spacing must equal the nominal tf
    exp_sec = TF_SECONDS.get(tf)
    grain_note = None
    if exp_sec and grain[0] is not None:
        med, p95 = float(grain[0]), float(grain[1])
        if med != exp_sec or p95 != exp_sec:
            exc = _grain_exception(sym, tf)
            if exc:
                grain_note = exc                        # declared exception: reported, not failed
            else:
                issues.append(f"GRAIN: median/p95 bar spacing {med:.0f}/{p95:.0f}s != nominal "
                              f"{exp_sec}s for tf={tf} (mixed timeframes or holes in the table)")
    import hashlib
    fp = hashlib.sha256("|".join([sym.upper(), tf, sess, str(int(n)), str(span[0]), str(span[1]),
                                  str(con.execute(f"SELECT sum(volume) {base}", args).fetchone()[0])
                                  ]).encode()).hexdigest()[:16]
    return {"rows": int(n), "span": [str(span[0])[:19], str(span[1])[:19]],
            "dupe_ts": int(dupes), "high_lt_low": int(bad[0] or 0),
            "bad_wick_geometry": int(bad[1] or 0), "zero_or_neg_volume": int(bad[2] or 0),
            "null_ohlc": int(bad[3] or 0), "calendar_gaps": int(gaps),
            "stale_trading_days": stale_bd, "short_day_pct": round(short_pct, 2),
            "grain_sec": {"median": float(grain[0]) if grain[0] is not None else None,
                          "p95": float(grain[1]) if grain[1] is not None else None,
                          "expected": exp_sec, "exception": grain_note},
            "bars_per_day": {"avg": round(float(per_day[0]), 1), "min": int(per_day[1]),
                             "max": int(per_day[2]), "expected": exp,
                             "short_days": int(per_day[3] or 0), "days": int(per_day[4])},
            "fingerprint": fp,
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
            # an unreadable symbol is a FAILED symbol (fail closed), never a silent skip
            out["symbols"][sym.upper()] = {"error": str(e)[:200], "ok": False,
                                           "issues": [f"QA crashed: {str(e)[:120]}"]}
    con.close()
    import hashlib
    out["store_fingerprint"] = hashlib.sha256("|".join(
        f"{s}:{r.get('fingerprint', 'ERR')}" for s, r in sorted(out["symbols"].items())
    ).encode()).hexdigest()[:16]
    out["all_ok"] = all(r.get("ok") for r in out["symbols"].values())
    out["thresholds"] = {"freshness_bdays": FRESHNESS_BDAYS, "short_day_pct": SHORT_DAY_PCT}
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
