#!/usr/bin/env python3
"""OBI EXECUTION study (uses 1-4) on the QQQ L3 MBO book — EXPLORATORY (few days, per F63).
Reconstructs the order book from MBO (order_id-matched A/C/M/F, skip T) → best bid/ask + top-5 depth,
snapshotted every second. Then the 4 execution uses:
  1 FILL/slippage : contemporaneous corr(OBI, microprice-mid skew) — how much of the spread OBI lets you shade.
  2 LIQUIDITY veto: spread distribution + forward 5s |move| conditioned on spread (wide book -> worse fills).
  3 STOP-RUN/fakeout: at new local highs/lows (level touch), does OBI predict a REVERT (fakeout) over 30s?
  4 EXIT/continuation: IC(OBI, forward mid-return) at 1/5/30s — does OBI predict the next move (F63 said ~0)?

    python research/orb_obi_book.py [N_DAYS]        (default 2, window 09:30-11:30)
"""
import sys, os, gc
sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "BOT"))
import numpy as np, pandas as pd
from bot.market_data import databento_local as L

WIN = ("09:30", "09:40")   # load from file start up to WIN[1]; analyze RTH snapshots only

def load_events(date, sym="QQQ"):
    path = L._path_for("xnas", date, base=L.settings.mbo_dir_for(sym))
    con = L._con()
    q = (f"SELECT ts_event, action, side, price, size, CAST(order_id AS VARCHAR) AS order_id, sequence "
         f"FROM read_csv_auto('{path.as_posix()}') WHERE symbol='{sym}' AND price IS NOT NULL "        # from file start (need pre-open book)
         f"AND strftime(ts_event,'%H:%M') < '{WIN[1]}' ORDER BY sequence")
    df = con.execute(q).df(); con.close()
    return df

def reconstruct(df):
    act = df["action"].to_numpy().astype("U1"); side = df["side"].to_numpy().astype("U1")
    px = df["price"].to_numpy(float); sz = df["size"].to_numpy(float)
    oid = df["order_id"].to_numpy(); ts = pd.to_datetime(df["ts_event"], utc=True).astype("int64").to_numpy()
    sec = ts // 1_000_000_000
    orders = {}; bids = {}; asks = {}
    snaps = []; cur = sec[0]
    def book_of(s): return bids if s == "B" else asks
    def snapshot(t):
        if not bids or not asks:
            return
        bb = max(bids); ba = min(asks)
        if bb >= ba:
            return
        bl = sorted((p for p in bids if bids[p] > 0), reverse=True)[:5]
        al = sorted(p for p in asks if asks[p] > 0)[:5]
        bd = sum(bids[p] for p in bl); ad = sum(asks[p] for p in al)
        b1 = bids[bb]; a1 = asks[ba]
        micro = (bb * a1 + ba * b1) / (b1 + a1) if (b1 + a1) > 0 else (bb + ba) / 2
        obi = (bd - ad) / (bd + ad) if (bd + ad) > 0 else 0.0
        snaps.append((t, bb, ba, (bb + ba) / 2, micro, obi, ba - bb, bd, ad))
    for i in range(len(act)):
        a = act[i]; s = side[i]; p = px[i]; q = sz[i]; o = oid[i]
        if a == "R":
            bids.clear(); asks.clear(); orders.clear()
        elif s in ("B", "A"):
            bk = book_of(s)
            if a == "A":
                orders[o] = (s, p, q); bk[p] = bk.get(p, 0.0) + q
            elif a == "C":
                if o in orders:
                    so, po, qo = orders.pop(o); b2 = book_of(so)
                    b2[po] = b2.get(po, 0.0) - qo
                    if b2.get(po, 0.0) <= 0: b2.pop(po, None)
            elif a == "F":
                if o in orders:
                    so, po, qo = orders[o]; b2 = book_of(so); b2[po] = b2.get(po, 0.0) - q
                    if b2.get(po, 0.0) <= 0: b2.pop(po, None)
                    if qo - q <= 0: orders.pop(o, None)
                    else: orders[o] = (so, po, qo - q)
            elif a == "M":
                if o in orders:
                    so, po, qo = orders[o]; b2 = book_of(so); b2[po] = b2.get(po, 0.0) - qo
                    if b2.get(po, 0.0) <= 0: b2.pop(po, None)
                orders[o] = (s, p, q); bk[p] = bk.get(p, 0.0) + q
        if sec[i] != cur:
            snapshot(sec[i] * 1_000_000_000)
            cur = sec[i]
            if len(bids) > 200:                    # prune far/stale levels
                bb = max(bids); [bids.pop(k) for k in [k for k in bids if bids[k] <= 0 or k < bb - 0.6]]
            if len(asks) > 200:
                ba = min(asks); [asks.pop(k) for k in [k for k in asks if asks[k] <= 0 or k > ba + 0.6]]
    s = pd.DataFrame(snaps, columns=["ts", "bb", "ba", "mid", "micro", "obi", "spread", "bidD", "askD"])
    return s.drop_duplicates("ts").reset_index(drop=True)

def pear(a, b):
    m = np.isfinite(a) & np.isfinite(b)
    return float(np.corrcoef(a[m], b[m])[0, 1]) if m.sum() > 30 else float("nan")

def main():
    nd = int(sys.argv[1]) if len(sys.argv) > 1 else 2
    days = L.list_days("xnas")[:nd]
    allsnap = []
    for d in days:
        try:
            ev = load_events(d)
            if ev.empty: print(f"{d}: no data"); continue
            s = reconstruct(ev); s["day"] = d; allsnap.append(s)
            print(f"{d}: {len(ev):,} events -> {len(s):,} 1s snapshots  (spread med {s['spread'].median():.3f}, "
                  f"OBI std {s['obi'].std():.3f})")
            del ev; gc.collect()
        except Exception as e:
            import traceback; traceback.print_exc(); print(f"{d}: ERR {e}")
    if not allsnap:
        print("no snapshots"); return
    S = pd.concat(allsnap, ignore_index=True)
    _et = pd.to_datetime(S["ts"], utc=True).dt.tz_convert("America/New_York")   # analyze only the RTH window
    S = S[(_et.dt.hour * 60 + _et.dt.minute) >= 570].reset_index(drop=True)
    tick = 0.01
    print(f"\n{'='*80}\nOBI EXECUTION TESTS — QQQ, {len(days)} days, {len(S):,} 1s snapshots (EXPLORATORY)\n{'='*80}")
    # forward mid returns per day (no cross-day)
    S["f1"] = S.groupby("day")["mid"].shift(-1) - S["mid"]
    S["f5"] = S.groupby("day")["mid"].shift(-5) - S["mid"]
    S["f30"] = S.groupby("day")["mid"].shift(-30) - S["mid"]
    skew = (S["micro"] - S["mid"]).to_numpy()
    print("\n[1] FILL/slippage — OBI vs contemporaneous microprice skew (how much of the spread OBI lets you shade):")
    print(f"    corr(OBI, micro-mid) = {pear(S['obi'].to_numpy(), skew):+.3f}   "
          f"median |skew| = {np.nanmedian(np.abs(skew))/tick:.2f} ticks   median spread = {S['spread'].median()/tick:.1f} ticks")
    print("\n[2] LIQUIDITY veto — spread distribution + forward 5s |move| by spread bucket:")
    for lo, hi, lab in [(0, 1.5, "<=1 tick"), (1.5, 2.5, "2 tick"), (2.5, 99, ">=3 tick")]:
        m = (S["spread"]/tick >= lo) & (S["spread"]/tick < hi)
        if m.sum() > 30:
            print(f"    spread {lab:9}: {100*m.mean():4.1f}% of time   fwd5s |move| = {np.nanmedian(np.abs(S['f5'][m]))/tick:4.2f} ticks")
    print("\n[3] STOP-RUN/fakeout — at a new 15-min mid HIGH/LOW (level touch), does OBI predict a 30s REVERT?")
    for day, g in S.groupby("day"):
        pass
    hi15 = S.groupby("day")["mid"].transform(lambda x: x.rolling(900, min_periods=60).max())
    lo15 = S.groupby("day")["mid"].transform(lambda x: x.rolling(900, min_periods=60).min())
    at_hi = S["mid"] >= hi15 - tick; at_lo = S["mid"] <= lo15 + tick
    rev_hi = (S["f30"] < 0)                          # after tagging a high, price falls = fakeout/revert
    rev_lo = (S["f30"] > 0)
    mh = at_hi & np.isfinite(S["f30"]); ml = at_lo & np.isfinite(S["f30"])
    print(f"    at new HIGH (n={int(mh.sum())}): OBI<0 (ask-heavy=pull) revert-rate {100*rev_hi[mh & (S['obi']<0)].mean():.0f}% "
          f"vs OBI>0 {100*rev_hi[mh & (S['obi']>0)].mean():.0f}%   (fakeout if OBI-negative reverts MORE)")
    print(f"    at new LOW  (n={int(ml.sum())}): OBI>0 (bid-heavy=pull) revert-rate {100*rev_lo[ml & (S['obi']>0)].mean():.0f}% "
          f"vs OBI<0 {100*rev_lo[ml & (S['obi']<0)].mean():.0f}%")
    print("\n[4] EXIT/continuation — IC(OBI, forward mid-return) at 1/5/30s (F63 said ~0 = not predictive):")
    print(f"    IC f1s {pear(S['obi'].to_numpy(), S['f1'].to_numpy()):+.3f}   "
          f"f5s {pear(S['obi'].to_numpy(), S['f5'].to_numpy()):+.3f}   "
          f"f30s {pear(S['obi'].to_numpy(), S['f30'].to_numpy()):+.3f}")
    print("\nKEY: [1]/[2] are CONTEMPORANEOUS/observable (usable for fills/veto). [3]/[4] need OBI to PREDICT "
          "(F63: ~0). |IC|<0.05 ahead = no timing edge; a strong contemporaneous [1] = real fill-shading value.")

if __name__ == "__main__":
    main()
