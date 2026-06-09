#!/usr/bin/env python3
"""
HIGHSTRIKE Stage 0 — QA the Databento 1m NQ file.
Usage: python hs_qa_data.py /path/to/glbx-mdp3-20100606-20260607.ohlcv-1m.csv
Streams in 1M-row chunks; safe on ~800MB.
"""
import sys, pandas as pd, numpy as np

PATH  = sys.argv[1] if len(sys.argv) > 1 else "glbx-mdp3-20100606-20260607.ohlcv-1m.csv"
CHUNK = 1_000_000

# --- sniff schema ----------------------------------------------------------
head = pd.read_csv(PATH, nrows=5)
cols = {c.lower(): c for c in head.columns}
print("RAW COLUMNS:", list(head.columns))
print(head.to_string(), "\n")

def pick(*cands):
    for c in cands:
        if c in cols: return cols[c]
    return None
ts  = pick("ts_event","timestamp","date","datetime","time")
o,h,l,c = pick("open"),pick("high"),pick("low"),pick("close")
vol = pick("volume","vol")
sym = pick("symbol","raw_symbol","ticker","instrument")
print(f"detected -> ts={ts} O={o} H={h} L={l} C={c} V={vol} sym={sym}\n")
use = [x for x in [ts,o,h,l,c,vol,sym] if x]

def to_dt(s):
    if pd.api.types.is_numeric_dtype(s):       # Databento ns-since-epoch
        return pd.to_datetime(s, unit="ns", utc=True, errors="coerce")
    return pd.to_datetime(s, utc=True, errors="coerce")  # ISO string

rows=0; tmin=tmax=None; cmin=cmax=None
bad_hl=0; bad_pos=0; dups=0; symbols=set(); deltas={}; tail=None

for ch in pd.read_csv(PATH, usecols=use, chunksize=CHUNK):
    rows += len(ch)
    t = to_dt(ch[ts])
    tmin = t.min() if tmin is None else min(tmin, t.min())
    tmax = t.max() if tmax is None else max(tmax, t.max())
    if all([o,h,l,c]):
        bad_hl += int(((ch[h]<ch[o])|(ch[h]<ch[c])|(ch[h]<ch[l])|
                       (ch[l]>ch[o])|(ch[l]>ch[c])).sum())
        bad_pos += int((ch[[o,h,l,c]]<=0).any(axis=1).sum())
        cmn,cmx = ch[c].min(), ch[c].max()
        cmin = cmn if cmin is None else min(cmin,cmn)
        cmax = cmx if cmax is None else max(cmax,cmx)
    if sym: symbols.update(ch[sym].dropna().unique().tolist())
    d = t.diff().dropna().dt.total_seconds()
    for k,v in d.value_counts().items(): deltas[k]=deltas.get(k,0)+int(v)
    dups += int(t.duplicated().sum())
    tail = ch.tail(3)

bar = max(deltas, key=deltas.get) if deltas else None
print(f"ROWS:             {rows:,}")
print(f"DATE SPAN:        {tmin}  ->  {tmax}")
print(f"MODAL BAR (sec):  {bar}  ({'1-min OK' if bar==60 else 'CHECK'})")
print(f"CLOSE RANGE:      {cmin} .. {cmax}   (NQ ~1500..23000; giant ints => unscaled prices)")
print(f"DISTINCT SYMBOLS: {len(symbols)}  {sorted(map(str,symbols))[:8]}")
print(f"DUP TIMESTAMPS:   {dups:,}")
print(f"OHLC invalid:     {bad_hl:,}    non-positive prices: {bad_pos:,}")
print("\nTAIL:\n", tail.to_string())
print("\nBAR-INTERVAL HISTOGRAM (sec : count), top 8:")
for k in sorted(deltas, key=deltas.get, reverse=True)[:8]:
    print(f"  {int(k):>8} : {deltas[k]:,}")
