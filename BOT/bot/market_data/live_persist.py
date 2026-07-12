"""LIVE-BAR PERSISTER (user decision 2026-07-12): the store's forward edge grows from the SCAN's
own delayed feeds (Webull equities / Yahoo futures) — no historical re-pulls. One EOD append per
trading day per symbol; after enough days the QA freshness gate clears ON ITS OWN and paper
approvals stop needing the frozen-span override.

Contract (Phase 4 rules inherited):
  * APPEND-AFTER-LAST only — rows strictly newer than the store's last bar; overlap is dropped
    (official bars win); a no-op day returns appended=0, never corrupts.
  * ATOMIC — tmp write + os.replace; a crash mid-write cannot half-update a store.
  * SCHEMA-MIRRORING — each store keeps its own layout (equities: ts_et/ohlcv/adj/session;
    futures: ts_utc/ts_et/date_et/symbol/... ). New rows carry adj_factor=1.0 / is_roll=False.
  * PROVENANCE — the `{SYM}_5m_append` manifest row (same key as pipeline/hs_append_5m, so the
    QA 1m-grain exception stays valid) records the span, counts and the live-router source.

KNOWN LIMITATION (accepted, same as the 5m-append precedent): bars land at 5m granularity in the
nominal-1m store (resampled tfs stay exact), and a futures ROLL after the freeze appears
unadjusted until a proper continuous rebuild — the adjusted-analytics layer sees that jump.

    from bot.market_data.live_persist import persist_day
    persist_day()                      # EOD: appends today's bars for every store symbol
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path
from zoneinfo import ZoneInfo

import numpy as np
import pandas as pd

from bot.config import BOT_ROOT

REPO = BOT_ROOT.parent
ET = ZoneInfo("America/New_York")
STORE_SYMS = ("QQQ", "SPY", "NQ", "ES", "GC")     # every continuous store QA watches
MANIFEST = REPO / "data" / "mbo_bars_manifest.json"
LOG = BOT_ROOT / "data" / "live_persist.log"


def _store_path(sym: str) -> Path:
    return REPO / "data" / f"{sym.lower()}_continuous_1m.parquet"


def append_bars(path: Path | str, fetched: pd.DataFrame, sym: str) -> dict:
    """Append strictly-newer sane bars from a router frame (ts_et + ohlcv[+volume]) into the
    store at `path`, mirroring ITS schema. Pure file-level core — the tests drive this."""
    path = Path(path)
    if not path.exists():
        return {"sym": sym, "appended": 0, "error": "store missing — never create one implicitly"}
    old = pd.read_parquet(path)
    if "ts_et" not in old.columns:
        return {"sym": sym, "appended": 0, "error": "store has no ts_et column"}
    new = fetched.copy()
    ts = pd.to_datetime(new["ts_et"])
    if ts.dt.tz is None:
        ts = ts.dt.tz_localize(ET)
    new["ts_et"] = ts.dt.tz_convert(ET)
    # sanity (Phase 4 spirit): broken candles never enter the store
    for c in ("open", "high", "low", "close"):
        new[c] = pd.to_numeric(new[c], errors="coerce")
    new = new[(new["high"] >= new["low"]) & (new[["open", "high", "low", "close"]] > 0).all(axis=1)
              & new[["open", "high", "low", "close"]].notna().all(axis=1)]
    old_ts = pd.to_datetime(old["ts_et"])
    if old_ts.dt.tz is None:                         # some stores keep naive ET
        last = old_ts.max()
        new_key = new["ts_et"].dt.tz_localize(None)
    else:
        last = old_ts.max()
        new_key = new["ts_et"]
    add = new[new_key > last].sort_values("ts_et")
    if not len(add):
        return {"sym": sym, "appended": 0, "last": str(last)}
    et = add["ts_et"]
    mins = et.dt.hour * 60 + et.dt.minute
    wk = et.dt.dayofweek < 5
    rows = pd.DataFrame(index=add.index)
    for col in old.columns:                          # SCHEMA MIRROR — the store's layout wins
        if col == "ts_et":
            rows[col] = et.dt.tz_localize(None) if old_ts.dt.tz is None else et
        elif col == "ts_utc":
            rows[col] = et.dt.tz_convert("UTC").dt.tz_localize(None) \
                if str(old["ts_utc"].dtype).find("UTC") < 0 else et.dt.tz_convert("UTC")
        elif col == "date_et":
            _sample = old[col].dropna().iloc[0] if old[col].notna().any() else None
            rows[col] = (et.dt.strftime("%Y-%m-%d") if isinstance(_sample, str)
                         else pd.Series(et.dt.date, index=add.index))   # date32 stores keep dates
        elif col in ("open", "high", "low", "close"):
            rows[col] = add[col].astype("float64")
        elif col == "volume":
            v = pd.to_numeric(add.get("volume", 0), errors="coerce").fillna(0)
            rows[col] = v.astype(old["volume"].dtype if old["volume"].dtype.kind in "if" else "int64")
        elif col == "adj_factor":
            rows[col] = 1.0
        elif col == "is_roll":
            rows[col] = False
        elif col == "session":
            rows[col] = np.where(wk & (mins >= 570) & (mins < 960), "RTH", "ETH")
        elif col == "symbol":
            rows[col] = sym.upper()
        else:
            rows[col] = pd.Series([None] * len(add), index=add.index)  # e.g. instrument_id
    out = pd.concat([old, rows], ignore_index=True)
    tmp = path.with_suffix(".parquet.tmp")
    out.to_parquet(tmp, index=False)                 # ATOMIC: tmp + replace
    os.replace(tmp, path)
    _manifest(sym, rows, len(add))
    return {"sym": sym, "appended": int(len(add)),
            "span": [str(rows['ts_et'].min()), str(rows['ts_et'].max())]}


def _manifest(sym: str, rows: pd.DataFrame, n: int) -> None:
    """Extend the `{SYM}_5m_append` provenance row — the SAME key pipeline/hs_append_5m uses, so
    the data-QA 1m grain exception keeps covering the whole live-appended span."""
    try:
        m = json.loads(MANIFEST.read_text(encoding="utf-8"))
    except Exception:
        m = {}
    k = f"{sym.upper()}_5m_append"
    rec = m.get(k) or {"appended": 0, "appended_range": [str(rows["ts_et"].min()), None]}
    rec["appended"] = int(rec.get("appended", 0)) + n
    rng = rec.get("appended_range") or [str(rows["ts_et"].min()), None]
    rng[1] = str(rows["ts_et"].max())
    rec["appended_range"] = rng
    rec["source"] = "live router (delayed Webull equities / Yahoo futures) — EOD persister"
    rec["granularity"] = "5m-as-1m rows (resampled tfs exact)"
    rec["updated_at"] = pd.Timestamp.now("UTC").isoformat()
    m[k] = rec
    MANIFEST.parent.mkdir(parents=True, exist_ok=True)
    MANIFEST.write_text(json.dumps(m, indent=1), encoding="utf-8")


def persist_day(syms=STORE_SYMS, spawn_post: bool = True, period: str = "60d") -> dict:
    """EOD job: fetch the recent 5m bars per store symbol from the live router and append the
    strictly-new ones; then spawn resample + QA in the background so the hive and the freshness
    verdict catch up without stalling the scan loop."""
    from bot.market_data.providers import get_bars
    out = {}
    changed = []
    for sym in syms:
        try:
            bars = get_bars(sym, tf="5m", period=period)   # 60d bridges the June freeze-gap
                                                           # (a 5d fetch would leave a permanent
                                                           # calendar hole in NQ/ES/GC)
            if bars is None or not len(bars):
                out[sym] = {"appended": 0, "error": "router returned no bars"}
                continue
            r = append_bars(_store_path(sym), bars, sym)
            out[sym] = r
            if r.get("appended"):
                changed.append(sym)
        except Exception as e:
            out[sym] = {"appended": 0, "error": str(e)[:160]}
    if changed and spawn_post:
        _spawn_post(changed)
        out["_post"] = f"resample+QA spawned for {changed}"
    return out


def _spawn_post(syms) -> None:
    """Background: resample each changed symbol's hive, then refresh the QA report — the
    freshness gate clears the moment spans catch up (no scan-loop stall; log -> live_persist.log).
    ONE self-contained python child runs the whole sequence (the old cmd.exe `&&` chain died with
    its short-lived parent on Windows); CREATE_NEW_PROCESS_GROUP detaches it from the caller."""
    runner = (
        "import runpy, sys, time, os\n"
        # SINGLE-FLIGHT (2026-07-12): a resample must never overlap another (overlapping runs lock
        # each other out on Windows). A stale lock (>30min = crashed run) is reclaimed.
        "lock = os.path.join('data', '.resample.lock')\n"
        "if os.path.exists(lock) and (time.time() - os.path.getmtime(lock)) < 1800:\n"
        "    print('resample already in flight — skipping (single-flight)'); sys.exit(0)\n"
        "open(lock, 'w').write(str(os.getpid()))\n"
        "try:\n"
        f" syms = {list(syms)!r}\n"
        " for s in syms:\n"
        # RESAMPLE-vs-SCAN-READ race (2026-07-12): on Windows the live scan holds read locks on
        # the hive parquet, so a rewrite can WinError 5. Retry with backoff instead of dying.
        "  for attempt in range(6):\n"
        "   sys.argv = ['hs_resample.py', s]\n"
        "   try:\n"
        "    runpy.run_path('pipeline/hs_resample.py', run_name='__main__'); break\n"
        "   except SystemExit: break\n"
        "   except PermissionError: time.sleep(10)\n"
        " sys.argv = ['hs_data_qa.py']\n"
        " runpy.run_path('pipeline/hs_data_qa.py', run_name='__main__')\n"
        "finally:\n"
        " try: os.remove(lock)\n"
        " except OSError: pass\n")
    log = open(LOG, "a", encoding="utf-8")
    flags = getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0)
    subprocess.Popen([sys.executable, "-c", runner], cwd=str(REPO),
                     stdout=log, stderr=subprocess.STDOUT, creationflags=flags)


if __name__ == "__main__":
    print(json.dumps(persist_day(), indent=1, default=str))
