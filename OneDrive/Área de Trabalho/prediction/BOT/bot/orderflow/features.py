"""Order-flow features from the XNAS L3 MBO book (Evidence.docx microstructure spec).

Two groups:
  • Trade-print features (fast): aggressive-trade imbalance ATI, cumulative delta CD / zCD.
  • Book features (needs L3 reconstruction): best-level queue imbalance QI, microprice Δμ.

The book is rebuilt by tracking every order_id: A=add, C=cancel, M=modify, T/F handled via the
follow-on cancel/fill. We snapshot best-bid/ask + sizes at a chosen cadence so it stays tractable.

    from bot.orderflow.features import book_bbo, trade_features
    bbo = book_bbo("2026-05-26", ("09:30","09:35"))   # per-snapshot QI, microprice
    tf  = trade_features("2026-05-26", ("09:30","10:00"))   # per-minute ATI, delta, zCD
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from bot.market_data import databento_local as L

ET = "America/New_York"


# ── trade-print features (calibrated: side 'B' = buy-aggressor) ──────────────

def trade_features(date: str, hhmm=("09:30", "16:00"), freq: str = "1min", symbol: str = "QQQ") -> pd.DataFrame:
    tr = L.load_mbo_day(date, symbol, actions=("T",), hhmm=hhmm)
    if tr.empty:
        return pd.DataFrame()
    tr = tr.set_index("ts_et")
    buy = tr["size"].where(tr["side"] == "B", 0)
    sell = tr["size"].where(tr["side"] == "A", 0)
    g = pd.DataFrame({"buy": buy.resample(freq).sum(), "sell": sell.resample(freq).sum(),
                      "px": tr["price"].astype(float).resample(freq).last()}).dropna(how="all")
    tot = (g["buy"] + g["sell"]).replace(0, np.nan)
    g["ati"] = (g["buy"] - g["sell"]) / tot                  # aggressive-trade imbalance ∈ [-1,1]
    g["delta"] = g["buy"] - g["sell"]                        # cumulative-delta increment
    g["cum_delta"] = g["delta"].cumsum()
    base = g["delta"].rolling(20, min_periods=5)
    g["zcd"] = (g["delta"] - base.mean()) / (base.std() + 1e-9)   # z-scored continuation filter
    return g


# ── L3 book reconstruction → best-level QI + microprice ──────────────────────

def book_bbo(date: str, hhmm=("09:30", "09:35"), every_ms: int = 1000, symbol: str = "QQQ") -> pd.DataFrame:
    """Reconstruct best bid/ask + sizes from MBO add/cancel/modify, snapshot every `every_ms`.

    Returns: ts_et, bid, ask, bid_sz, ask_sz, qi (queue imbalance), micro (microprice), dmu
    (microprice−mid in ticks). Bounded windows only (full-day reconstruction is heavy)."""
    ev = _load_book_events(date, hhmm, symbol)      # (ts, action, side, price, size, order_id), ordered
    if not ev:
        return pd.DataFrame()
    orders: dict[int, tuple[str, float, int]] = {}     # order_id -> (side, price, size)
    bids: dict[float, int] = {}                         # price -> total size
    asks: dict[float, int] = {}
    rows = []
    next_snap = None
    snap_ns = every_ms * 1_000_000
    for ts, action, side, price, size, oid in ev:
        if action == "A" and side in ("B", "A") and price == price:    # add
            orders[oid] = (side, price, int(size))
            book = bids if side == "B" else asks
            book[price] = book.get(price, 0) + int(size)
        elif action in ("C", "F") and oid in orders:                   # cancel / fill removes resting qty
            s, p, sz = orders.pop(oid)
            book = bids if s == "B" else asks
            book[p] = book.get(p, 0) - sz
            if book[p] <= 0:
                book.pop(p, None)
        elif action == "M" and oid in orders:                          # modify = resize/replace
            s, p, sz = orders[oid]
            book = bids if s == "B" else asks
            book[p] = book.get(p, 0) - sz
            if book[p] <= 0:
                book.pop(p, None)
            orders[oid] = (s, price, int(size))
            book2 = bids if s == "B" else asks
            book2[price] = book2.get(price, 0) + int(size)
        # snapshot on cadence
        if next_snap is None:
            next_snap = ts.value + snap_ns
        elif ts.value >= next_snap:
            if bids and asks:
                bb = max(bids); aa = min(asks)
                if aa > bb:
                    bsz, asz = bids[bb], asks[aa]
                    qi = (bsz - asz) / (bsz + asz) if (bsz + asz) else 0.0
                    micro = (aa * bsz + bb * asz) / (bsz + asz) if (bsz + asz) else (aa + bb) / 2
                    mid = (bb + aa) / 2
                    rows.append((ts, bb, aa, bsz, asz, qi, micro, (micro - mid) / 0.01))
            next_snap += snap_ns
    return pd.DataFrame(rows, columns=["ts_et", "bid", "ask", "bid_sz", "ask_sz", "qi", "micro", "dmu"])


def _load_book_events(date, hhmm, symbol="QQQ"):
    """Yield (ts, action, side, price, size, order_id) for the window, ordered. Folder by symbol."""
    from bot.config import settings
    path = L._path_for("xnas", date, base=settings.mbo_dir_for(symbol))
    con = L._con()
    df = con.execute(
        f"SELECT ts_event, action, side, price, size, order_id "
        f"FROM read_csv_auto('{path.as_posix()}') "
        f"WHERE symbol='{symbol}' AND strftime(ts_event,'%H:%M') >= '{hhmm[0]}' "
        f"AND strftime(ts_event,'%H:%M') < '{hhmm[1]}' ORDER BY sequence"
    ).df()
    con.close()
    ts = pd.to_datetime(df["ts_event"], utc=True).dt.tz_convert(ET)
    return list(zip(ts, df["action"], df["side"], df["price"].astype(float),
                    df["size"].fillna(0).astype(int), df["order_id"].astype("int64")))


if __name__ == "__main__":
    tf = trade_features("2026-05-26", ("09:30", "10:00"))
    print("trade features (per-min):", len(tf), "rows")
    print(tf[["px", "ati", "delta", "cum_delta", "zcd"]].head(5).to_string())
    bb = book_bbo("2026-05-26", ("09:30", "09:33"))
    print(f"\nL3 book BBO snapshots: {len(bb)}")
    print(bb[["ts_et", "bid", "ask", "bid_sz", "ask_sz", "qi", "dmu"]].head(5).to_string())
    if len(bb):
        ic = bb[["qi", "dmu"]].corr().iloc[0, 1]
        print(f"\nQI vs microprice-displacement corr (should be +): {ic:+.3f}")
