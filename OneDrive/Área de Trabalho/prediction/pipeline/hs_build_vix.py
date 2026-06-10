#!/usr/bin/env python3
"""
HIGHSTRIKE 0.5 (VIX) — unified daily VIX series for the macro classifier.

Stitches two sources the user supplied into one 2011->2026 daily series:
  * SPOT VIX index (CBOE:VIX, what the V44 Pine reads)      2011-01 .. 2019-11   [tab CSV]
  * front-month VX (VIX futures, XCBF) where spot is absent  2019-12 .. 2026      [databento 1d]
NO back-adjust (VIX is a mean-reverting level; macro regime uses raw 15/25/35 thresholds).
A `source` column marks spot vs vx_future so the seam is explicit.

Output: data/vix_daily.parquet (date, open, high, low, close, sma5, chg5, source).

Usage: python hs_build_vix.py [vx-futures-1d.csv] [spot-vix-file]
NOTE: 2011-2019 is spot (exact Pine match); 2019-12+ is VX futures (term-premium proxy,
peaks below spot). Free daily spot ^VIX 2019+ would make the whole series spot-consistent.
"""
import sys, os
import pandas as pd

VX_PATH   = sys.argv[1] if len(sys.argv) > 1 else "data/raw/xcbf-pitch-20191204-20260608.ohlcv-1d.csv"
SPOT_PATH = sys.argv[2] if len(sys.argv) > 2 else "data/raw/2011-2018vix"
ET  = "America/New_York"
OUT = os.path.join("data", "vix_daily.parquet")
os.makedirs("data", exist_ok=True)


def build_vx_front(path):
    """Front-month VX (VIX futures) daily, volume-led monotonic monthly roll."""
    df = pd.read_csv(path, usecols=["ts_event", "instrument_id", "symbol",
                                    "open", "high", "low", "close", "volume"])
    df = df[~df["symbol"].str.contains("-", na=False)].copy()       # outrights only
    t  = pd.to_datetime(df["ts_event"], utc=True, errors="coerce")
    df["date"] = t.dt.tz_convert(ET).dt.date
    g = df.groupby(["date", "instrument_id"], as_index=False).agg(    # consolidate venues
        open=("open", "mean"), high=("high", "max"), low=("low", "min"),
        close=("close", "mean"), volume=("volume", "sum"))
    rank = {iid: i for i, iid in enumerate(
        g.groupby("instrument_id")["date"].min().sort_values().index)}
    front, chosen, chosen_rank = {}, None, -1
    for d, grp in g.sort_values(["date", "volume"], ascending=[True, False]).groupby("date"):
        leader = grp.iloc[0]["instrument_id"]; iids = set(grp["instrument_id"])
        if rank[leader] > chosen_rank: chosen, chosen_rank = leader, rank[leader]
        if chosen not in iids:         chosen, chosen_rank = leader, rank[leader]
        front[d] = chosen
    vx = g[g.apply(lambda r: front[r["date"]] == r["instrument_id"], axis=1)].copy()
    vx["source"] = "vx_future"
    return vx[["date", "open", "high", "low", "close", "source"]]


def parse_spot(path):
    """Investing-style tab CSV: 'Mon D, YYYY' O H L C AdjC Vol(-), descending."""
    s = pd.read_csv(path, sep="\t", header=None,
                    names=["date", "open", "high", "low", "close", "adj", "vol"])
    s["date"] = pd.to_datetime(s["date"], format="%b %d, %Y").dt.date
    s["source"] = "spot"
    return s[["date", "open", "high", "low", "close", "source"]]


vx   = build_vx_front(VX_PATH)
spot = parse_spot(SPOT_PATH)
seam = min(vx["date"])
spot = spot[spot["date"] < seam]                                    # spot only before VX starts

vix = (pd.concat([spot, vx], ignore_index=True)
       .drop_duplicates("date").sort_values("date").reset_index(drop=True))
vix["sma5"] = vix["close"].rolling(5).mean()
vix["chg5"] = vix["close"].pct_change(5) * 100.0
vix = vix[["date", "open", "high", "low", "close", "sma5", "chg5", "source"]]
vix.to_parquet(OUT, index=False)

print(f"WROTE {OUT}   ({len(vix):,} daily bars)")
print(f"DATE SPAN:  {vix['date'].min()}  ->  {vix['date'].max()}")
print(f"VIX RANGE:  {vix['close'].min():.2f} .. {vix['close'].max():.2f}")
print("BY SOURCE:")
print(vix.groupby("source").agg(n=("close", "size"), lo=("date", "min"),
                                hi=("date", "max")).to_string())
print(f"\nseam (last spot / first vx around {seam}):")
print(vix[(vix["date"] >= pd.Timestamp('2019-10-25').date()) &
          (vix["date"] <= pd.Timestamp('2019-12-10').date())]
      [["date", "close", "source"]].to_string(index=False))
print("\nregime-window spot-checks (peak VIX in each):")
for lbl, a, b in [("2011 (Aug debt-ceiling)", "2011-07-01", "2011-10-31"),
                  ("2015-16 (Aug/Jan)", "2015-08-01", "2016-02-29"),
                  ("2018-Q4", "2018-10-01", "2018-12-31"),
                  ("2020 COVID", "2020-02-15", "2020-04-15"),
                  ("2022 bear", "2022-01-01", "2022-12-31")]:
    m = vix[(vix["date"] >= pd.Timestamp(a).date()) & (vix["date"] <= pd.Timestamp(b).date())]
    if len(m):
        pk = m.loc[m["close"].idxmax()]
        print(f"  {lbl:26} peak {pk['close']:.1f} on {pk['date']} [{pk['source']}]")
    else:
        print(f"  {lbl:26} NO DATA")
