"""Drop-in order-flow runner for ANY symbol/date — ready for SPY MBO when it arrives.

When you download the SPY equity MBO batch:
  1. put the folder at DATABENTO_XNAS_SPY_DIR (BOT/config/.env)
  2. run:  python -m bot.orderflow.run_symbol SPY 2026-07-01
It reconstructs the L3 book, computes the deep features (QI/OFI/ACI/MLOFI/microprice/sweeps), and
prints a quick contemporaneous sanity check. Works for QQQ today (data already on disk).

    python -m bot.orderflow.run_symbol QQQ 2026-05-26 09:30 09:35
"""
from __future__ import annotations

import sys

import pandas as pd

from bot.config import settings
from bot.market_data import databento_local as L
from bot.orderflow.deep import deep_book_features, detect_sweeps
from bot.orderflow.features import trade_features


def run(symbol: str, date: str, t0: str = "09:30", t1: str = "09:35") -> None:
    mdir = settings.mbo_dir_for(symbol)
    print(f"[{symbol}] MBO folder: {mdir}")
    if not mdir.exists():
        print(f"  ⚠ folder not found — download the {symbol} MBO batch there and re-run. "
              f"(set DATABENTO_XNAS_SPY_DIR in BOT/config/.env)")
        return
    try:
        L._path_for("xnas", date, base=mdir)
    except FileNotFoundError as e:
        print(f"  ⚠ {e}")
        return
    tf = trade_features(date, (t0, "16:00"), symbol=symbol)
    bb = deep_book_features(date, (t0, t1), symbol=symbol)
    sw = detect_sweeps(date, (t0, t1), symbol=symbol)
    print(f"  trade-feature minutes: {len(tf)} | book snapshots: {len(bb)} | sweeps: {len(sw)}")
    if len(bb):
        same = pd.Series(bb["qi"]).corr(bb["dmu"])
        print(f"  QI vs microprice-displacement corr (should be ~+1): {same:+.3f}")
        print(bb[["ts_et", "qi", "ofi", "aci", "mlofi", "dmu"]].head(3).to_string())


if __name__ == "__main__":
    a = sys.argv[1:]
    sym = a[0] if a else "QQQ"
    date = a[1] if len(a) > 1 else (L.list_days("xnas")[0] if L.list_days("xnas") else "2026-05-26")
    t0 = a[2] if len(a) > 2 else "09:30"
    t1 = a[3] if len(a) > 3 else "09:35"
    run(sym, date, t0, t1)
