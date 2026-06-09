#!/usr/bin/env python3
"""
Phase 0.2 recon — inventory every instrument in the 1m file so we can design
the roll correctly. Outright vs spread, per-instrument date range + volume.
"""
import sys, pandas as pd, numpy as np

PATH  = sys.argv[1] if len(sys.argv) > 1 else "glbx-mdp3-20100606-20260607.ohlcv-1m.csv"
CHUNK = 1_000_000
use = ["ts_event","instrument_id","symbol","close","volume"]

# accumulators keyed by instrument_id
first_ts, last_ts, tot_vol, n_bars, sym_of = {}, {}, {}, {}, {}

for ch in pd.read_csv(PATH, usecols=use, chunksize=CHUNK):
    t = pd.to_datetime(ch["ts_event"], utc=True, errors="coerce")
    ch = ch.assign(_t=t)
    g = ch.groupby("instrument_id")
    for iid, sub in g:
        tmn, tmx = sub["_t"].min(), sub["_t"].max()
        first_ts[iid] = tmn if iid not in first_ts else min(first_ts[iid], tmn)
        last_ts[iid]  = tmx if iid not in last_ts  else max(last_ts[iid],  tmx)
        tot_vol[iid]  = tot_vol.get(iid,0) + int(sub["volume"].sum())
        n_bars[iid]   = n_bars.get(iid,0)  + len(sub)
        sym_of[iid]   = sub["symbol"].iloc[0]

inv = pd.DataFrame({
    "instrument_id": list(sym_of.keys()),
    "symbol":   [sym_of[i] for i in sym_of],
    "first":    [first_ts[i] for i in sym_of],
    "last":     [last_ts[i]  for i in sym_of],
    "bars":     [n_bars[i]   for i in sym_of],
    "volume":   [tot_vol[i]  for i in sym_of],
})
inv["is_spread"] = inv["symbol"].str.contains("-")
inv = inv.sort_values("first").reset_index(drop=True)

outr = inv[~inv["is_spread"]].copy()
sprd = inv[inv["is_spread"]].copy()

print(f"TOTAL instruments:    {len(inv)}")
print(f"  outrights:          {len(outr)}   (volume {outr['volume'].sum():,})")
print(f"  spreads:            {len(sprd)}   (volume {sprd['volume'].sum():,})")
print(f"  duplicate symbols across instrument_ids? "
      f"{outr['symbol'].duplicated().any()}  "
      f"(year-code collision check over 16y)")
dups = outr[outr['symbol'].duplicated(keep=False)].sort_values('symbol')
if len(dups):
    print("  -> colliding outright symbols (same code, different instrument_id):")
    print(dups[['symbol','instrument_id','first','last','volume']].to_string(index=False))

print("\nOUTRIGHT CONTRACTS (sorted by first-seen), all rows:")
with pd.option_context('display.max_rows', None, 'display.width', 200):
    print(outr[['symbol','instrument_id','first','last','bars','volume']].to_string(index=False))

outr.to_csv("hs_outright_inventory.csv", index=False)
print("\nwrote hs_outright_inventory.csv")
