#!/usr/bin/env python3
"""
tradovate_fills_to_trades.py
============================
Convert a Tradovate "Fills" report (one row per execution) into round-trip
trades (one row per entry+exit) in the schema hs_validation.py ingests.

Handles:
  - flexible column-name detection (Tradovate's headers vary by export)
  - futures contract-code normalization: NQM6 -> NQ, MNQU5 -> MNQ, ESZ5 -> ES
  - FIFO matching of opening vs closing fills (scaling in/out, partials)
  - both long-first and short-first round trips

Output columns: entry_time, exit_time, direction, entry_price, exit_price,
                symbol, contracts

NOTE: broker fills carry NO indicator values. ADX/VIX must be backfilled
separately (reconstruction module) before regime stratification on them works.

    python3 tradovate_fills_to_trades.py --fills Fills.csv --out nq_trades.csv
"""
from __future__ import annotations
import argparse
import re
import sys
from collections import deque, defaultdict
import pandas as pd

# Candidate header names (lowercased) -> canonical field
COLUMN_CANDIDATES = {
    "timestamp": ["timestamp", "fill time", "filltime", "date/time", "datetime",
                  "time", "date", "execution time", "exec time"],
    "side":      ["b/s", "buy/sell", "side", "bs", "action", "buysell"],
    "symbol":    ["contract", "symbol", "product", "instrument"],
    "qty":       ["qty", "filledqty", "filled qty", "quantity", "fill qty",
                  "fillqty", "size"],
    "price":     ["price", "avgprice", "avg price", "fill price", "fillprice",
                  "avgpx", "execution price"],
}

MONTH_CODE = re.compile(r"([FGHJKMNQUVXZ]\d{1,2})$")


def _find_col(cols, candidates):
    norm = {c.lower().strip(): c for c in cols}
    for cand in candidates:
        if cand in norm:
            return norm[cand]
    # loose contains-match fallback
    for cand in candidates:
        for low, orig in norm.items():
            if cand in low:
                return orig
    return None


def normalize_symbol(raw: str) -> str:
    s = str(raw).upper().strip()
    s = s.split(":")[-1]                # drop exchange prefix CME:NQM6 -> NQM6
    s = s.lstrip("/")                   # drop /NQ style
    s = MONTH_CODE.sub("", s)           # strip month+year code
    return s or str(raw).upper().strip()


def detect_side(val) -> int:
    """Return +1 for buy, -1 for sell."""
    v = str(val).strip().lower()
    if v in ("buy", "b", "bot", "long", "1", "+1"):
        return 1
    if v in ("sell", "s", "sld", "short", "-1"):
        return -1
    raise ValueError(f"Unrecognized side value: {val!r}")


def load_fills(path: str) -> pd.DataFrame:
    df = pd.read_csv(path)
    if df.empty:
        sys.exit("ERROR: fills file is empty. Re-export the Fills report with a "
                 "date range that covers your trades (not the Positions report).")
    cols = list(df.columns)
    mapping = {}
    for field, cands in COLUMN_CANDIDATES.items():
        found = _find_col(cols, cands)
        if found is None and field in ("timestamp", "side", "symbol", "qty", "price"):
            sys.exit(f"ERROR: could not find a '{field}' column. Headers seen: {cols}\n"
                     f"Edit COLUMN_CANDIDATES['{field}'] to add your column name.")
        mapping[field] = found

    out = pd.DataFrame({
        "timestamp": pd.to_datetime(df[mapping["timestamp"]]),
        "side": df[mapping["side"]].map(detect_side),
        "symbol": df[mapping["symbol"]].map(normalize_symbol),
        "qty": df[mapping["qty"]].astype(float).abs(),
        "price": df[mapping["price"]].astype(float),
    })
    return out.sort_values("timestamp").reset_index(drop=True)


def match_fifo(fills: pd.DataFrame) -> pd.DataFrame:
    """FIFO-match opening and closing fills per symbol into round trips.
    Each output row = one matched lot chunk (qty contracts)."""
    trades = []
    # open lots per symbol: deque of dicts {time, price, qty, dir}
    books = defaultdict(deque)

    for _, f in fills.iterrows():
        sym, side, qty, price, ts = f.symbol, int(f.side), f.qty, f.price, f.timestamp
        book = books[sym]

        # current net direction of the book (sign of first open lot)
        net_dir = book[0]["dir"] if book else 0

        if net_dir == 0 or side == net_dir:
            # opening or adding in same direction
            book.append({"time": ts, "price": price, "qty": qty, "dir": side})
        else:
            # closing against existing lots, FIFO
            remaining = qty
            while remaining > 1e-9 and book:
                lot = book[0]
                matched = min(lot["qty"], remaining)
                direction = "long" if lot["dir"] == 1 else "short"
                trades.append({
                    "entry_time": lot["time"],
                    "exit_time": ts,
                    "direction": direction,
                    "entry_price": lot["price"],
                    "exit_price": price,
                    "symbol": sym,
                    "contracts": int(matched) if float(matched).is_integer() else matched,
                })
                lot["qty"] -= matched
                remaining -= matched
                if lot["qty"] <= 1e-9:
                    book.popleft()
            # leftover qty flips the book into a new opposite position
            if remaining > 1e-9:
                book.append({"time": ts, "price": price, "qty": remaining, "dir": side})

    # report unmatched (still-open) lots so nothing is silently dropped
    leftovers = sum(len(b) for b in books.values())
    if leftovers:
        print(f"[note] {leftovers} fill-lot(s) left open at end of data "
              f"(position not yet closed) -- excluded from round trips.")

    res = pd.DataFrame(trades)
    if res.empty:
        sys.exit("ERROR: no closed round trips found. Are these orders-only "
                 "(no fills) or all same-side opens?")
    return res.sort_values("entry_time").reset_index(drop=True)


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--fills", required=True, help="Tradovate Fills CSV")
    ap.add_argument("--out", default="trades_from_fills.csv")
    a = ap.parse_args()

    fills = load_fills(a.fills)
    print(f"Loaded {len(fills)} fills across symbols: {sorted(fills.symbol.unique())}")
    trades = match_fifo(fills)
    trades.to_csv(a.out, index=False)
    print(f"Reconstructed {len(trades)} round-trip trades -> {a.out}")
    print(f"Range: {trades.entry_time.min()} .. {trades.exit_time.max()}")
    print("\nFirst 6:")
    print(trades.head(6).to_string(index=False))
    print("\nNext: python3 hs_validation.py --trades "
          f"{a.out} --symbol NQ --capital 50000")