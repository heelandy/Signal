"""Deep order-flow features (Evidence §"Feature formulas"): event-level OFI, add/cancel imbalance
ACI, multi-level OFI, microprice velocity/acceleration, and a liquidity-sweep detector.

Built on the L3 book reconstruction in `features.py` — we replay the MBO event stream, maintain the
full book, and emit per-snapshot OFI/ACI/MLOFI plus sweep flags. OFI follows Cont et al. (best-level
quantity changes from adds/cancels/trades); MLOFI extends it across depth; ACI is the signed
add/cancel pressure (Evidence). These are the predictive order-flow signals (stronger than 1-min
trade delta).

    from bot.orderflow.deep import deep_book_features, detect_sweeps
    df = deep_book_features("2026-05-26", ("09:30","09:35"))   # qi, ofi, aci, mlofi, micro, dmu, vel, accel
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from bot.orderflow.features import _load_book_events


def _best(bids: dict, asks: dict):
    bb = max(bids) if bids else None
    aa = min(asks) if asks else None
    return bb, aa


def _ofi_inc(pbid, pbsz, pask, pasz, bid, bsz, ask, asz) -> float:
    """Cont et al. event OFI from consecutive best-quote snapshots."""
    if None in (pbid, pask, bid, ask):
        return 0.0
    e_bid = bsz if bid > pbid else (bsz - pbsz if bid == pbid else -pbsz)
    e_ask = asz if ask < pask else (asz - pasz if ask == pask else -pasz)
    return float(e_bid - e_ask)


def _mlofi(prev: dict, cur: dict, side: str, levels: int) -> float:
    """Depth-weighted OFI across top `levels` (w_m = 1/m)."""
    pk = sorted(prev, reverse=(side == "bid"))[:levels]
    ck = sorted(cur, reverse=(side == "bid"))[:levels]
    val = 0.0
    for m, p in enumerate(ck, 1):
        prev_sz = prev.get(p, 0)
        val += (cur[p] - prev_sz) / m
    for m, p in enumerate(pk, 1):
        if p not in cur:
            val -= prev[p] / m
    return val


def deep_book_features(date: str, hhmm=("09:30", "09:35"), every_ms: int = 1000,
                       mlofi_levels: int = 5, symbol: str = "QQQ") -> pd.DataFrame:
    ev = _load_book_events(date, hhmm, symbol)
    orders: dict[int, tuple[str, float, int]] = {}
    bids: dict[float, int] = {}
    asks: dict[float, int] = {}
    # ACI counters accumulated since last snapshot
    bid_add = ask_add = bid_can = ask_can = 0
    rows = []
    snap_ns = every_ms * 1_000_000
    next_snap = None
    prev = None             # (bid,bsz,ask,asz, bids_copy, asks_copy, ts)
    prev_micro = prev_t = None
    prev_vel = 0.0
    for ts, action, side, price, size, oid in ev:
        if action == "A" and side in ("B", "A") and price == price:
            orders[oid] = (side, price, int(size))
            (bids if side == "B" else asks)[price] = (bids if side == "B" else asks).get(price, 0) + int(size)
            if side == "B":
                bid_add += int(size)
            else:
                ask_add += int(size)
        elif action in ("C", "F") and oid in orders:
            s, p, sz = orders.pop(oid)
            book = bids if s == "B" else asks
            book[p] = book.get(p, 0) - sz
            if book[p] <= 0:
                book.pop(p, None)
            if s == "B":
                bid_can += sz
            else:
                ask_can += sz
        elif action == "M" and oid in orders:
            s, p, sz = orders[oid]
            book = bids if s == "B" else asks
            book[p] = book.get(p, 0) - sz
            if book[p] <= 0:
                book.pop(p, None)
            orders[oid] = (s, price, int(size))
            (bids if s == "B" else asks)[price] = (bids if s == "B" else asks).get(price, 0) + int(size)

        if next_snap is None:
            next_snap = ts.value + snap_ns
            continue
        if ts.value < next_snap:
            continue
        bb, aa = _best(bids, asks)
        if bb is not None and aa is not None and aa > bb:
            bsz, asz = bids[bb], asks[aa]
            mid = (bb + aa) / 2
            micro = (aa * bsz + bb * asz) / (bsz + asz)
            qi = (bsz - asz) / (bsz + asz)
            ofi = aci = mlofi = vel = accel = 0.0
            if prev is not None:
                ofi = _ofi_inc(*prev[:4], bb, bsz, aa, asz)
                mlofi = _mlofi(prev[4], bids, "bid", mlofi_levels) - _mlofi(prev[5], asks, "ask", mlofi_levels)
                tot = bid_add + ask_can + ask_add + bid_can
                aci = ((bid_add + ask_can) - (ask_add + bid_can)) / tot if tot else 0.0
                dt = (ts.value - prev_t) / 1e9
                if dt > 0:
                    vel = (micro - prev_micro) / dt
                    accel = (vel - prev_vel) / dt
            rows.append((ts, bb, aa, bsz, asz, qi, ofi, aci, mlofi, micro, (micro - mid) / 0.01, vel, accel))
            prev = (bb, bsz, aa, asz, dict(bids), dict(asks))
            prev_micro, prev_t, prev_vel = micro, ts.value, vel
            bid_add = ask_add = bid_can = ask_can = 0
        next_snap += snap_ns
    return pd.DataFrame(rows, columns=["ts_et", "bid", "ask", "bid_sz", "ask_sz", "qi", "ofi",
                                       "aci", "mlofi", "micro", "dmu", "vel", "accel"])


def detect_sweeps(date: str, hhmm=("09:30", "10:00"), min_levels: int = 3, min_ticks: float = 0.02,
                  window_ms: int = 100, symbol: str = "QQQ") -> pd.DataFrame:
    """Liquidity-sweep flags: a burst of same-side aggressive trades crossing >= min_levels prices
    with price jump >= min_ticks inside window_ms (Evidence sweep heuristic). side 'B'=buy sweep up."""
    ev = _load_book_events(date, hhmm, symbol)
    trades = [(ts, side, price, size) for ts, action, side, price, size, _ in ev
              if action == "T" and side in ("A", "B") and price == price]
    out = []
    i = 0
    win_ns = window_ms * 1_000_000
    while i < len(trades):
        ts0, s0, p0, _ = trades[i]
        j = i
        prices = set()
        while j < len(trades) and trades[j][0].value - ts0.value <= win_ns and trades[j][1] == s0:
            prices.add(trades[j][2]); j += 1
        if len(prices) >= min_levels and (max(prices) - min(prices)) >= min_ticks:
            out.append((ts0, "B" if s0 == "B" else "A", len(prices), round(max(prices) - min(prices), 2)))
            i = j
        else:
            i += 1
    return pd.DataFrame(out, columns=["ts_et", "side", "levels", "px_jump"])


if __name__ == "__main__":
    df = deep_book_features("2026-05-26", ("09:30", "09:33"))
    print(f"deep book features: {len(df)} snapshots")
    print(df[["ts_et", "qi", "ofi", "aci", "mlofi", "dmu", "vel"]].head(5).to_string())
    if len(df) > 5:
        nxt = df["micro"].pct_change().shift(-1)
        for col in ("qi", "ofi", "aci", "mlofi"):
            ic = pd.Series(df[col]).corr(nxt)
            print(f"  IC {col:6} -> next-microprice move: {ic:+.3f}")
    sw = detect_sweeps("2026-05-26", ("09:30", "09:45"))
    print(f"\nsweeps detected (09:30-09:45): {len(sw)}")
    print(sw.head(4).to_string())
    print("deep order-flow OK")
