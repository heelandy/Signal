#!/usr/bin/env python3
"""
HIGHSTRIKE Phase 0.2 — Futures continuity (the silent corruptor).

Builds a continuous front-month NQ series from the raw Databento 1m file:
  * keeps OUTRIGHT contracts only (drops calendar spreads)
  * keys the roll on instrument_id (the symbol code repeats every 10y -> collisions)
  * roll rule = daily VOLUME crossover, monotonic forward-only (no OI in the file)
  * RATIO back-adjustment, computed at each roll boundary
  * keeps the UNADJUSTED OHLCV plus an `adj_factor` column:
        adjusted price = raw price * adj_factor   (volume is never adjusted)
    -> level logic (VWAP/zones/round numbers) uses raw; momentum uses adjusted.
  * tags ET session (RTH 09:30-16:00 ET Mon-Fri, else ETH)

Output: data/nq_continuous_1m.parquet  +  data/nq_roll_schedule.csv
Two streaming passes over the ~800MB file; memory-safe.

Usage: python hs_build_continuous.py [path-to-csv]
"""
import sys, os
import pandas as pd, numpy as np

PATH   = sys.argv[1] if len(sys.argv) > 1 else "data/raw/glbx-mdp3-20100606-20260607.ohlcv-1m.csv"
SYM    = (sys.argv[2] if len(sys.argv) > 2 else "nq").lower()   # symbol namespace for outputs
CHUNK  = 1_000_000
ET     = "America/New_York"
OUTDIR = "data"
os.makedirs(OUTDIR, exist_ok=True)
OUT_PARQUET = os.path.join(OUTDIR, f"{SYM}_continuous_1m.parquet")
OUT_ROLLS   = os.path.join(OUTDIR, f"{SYM}_roll_schedule.csv")

USE = ["ts_event", "instrument_id", "symbol", "open", "high", "low", "close", "volume"]


def et_date_series(ts_utc):
    """UTC tz-aware Series -> python date in America/New_York (DST-correct)."""
    return ts_utc.dt.tz_convert(ET).dt.date


# ======================================================================
# PASS 1 — per (ET-date, instrument_id): summed volume + last close
# ======================================================================
print("PASS 1/2  scanning for daily volume + closes per contract ...")
vol_acc, close_acc, sym_acc = {}, {}, {}   # key=(date, iid)

for ch in pd.read_csv(PATH, usecols=USE, chunksize=CHUNK):
    ch = ch[~ch["symbol"].str.contains("-", na=False)]          # outrights only
    t  = pd.to_datetime(ch["ts_event"], utc=True, errors="coerce")
    ch = ch.assign(_d=et_date_series(t), _ts=t)

    gv = ch.groupby(["_d", "instrument_id"])["volume"].sum()
    for (d, iid), v in gv.items():
        vol_acc[(d, iid)] = vol_acc.get((d, iid), 0) + int(v)

    # last close per group in this chunk (globally latest wins)
    idx  = ch.groupby(["_d", "instrument_id"])["_ts"].idxmax()
    last = ch.loc[idx, ["_d", "instrument_id", "_ts", "close", "symbol"]]
    for _, r in last.iterrows():
        k = (r["_d"], r["instrument_id"])
        prev = close_acc.get(k)
        if prev is None or r["_ts"] > prev[0]:
            close_acc[k] = (r["_ts"], float(r["close"]))
        sym_acc[r["instrument_id"]] = r["symbol"]

daily = pd.DataFrame(
    [(d, iid, v, close_acc[(d, iid)][1]) for (d, iid), v in vol_acc.items()],
    columns=["date", "iid", "volume", "close"],
).sort_values(["date", "volume"], ascending=[True, False]).reset_index(drop=True)
print(f"  {len(daily):,} (date,contract) rows over {daily['date'].nunique():,} sessions")

# ----- contract ranking by first-seen date (= expiry order) -----------
first_seen = daily.groupby("iid")["date"].min().sort_values()
rank = {iid: i for i, iid in enumerate(first_seen.index)}

# ======================================================================
# Build the front-month map (monotonic, volume-led)
# ======================================================================
front = {}                    # date -> iid
chosen_iid, chosen_rank = None, -1
for d, grp in daily.groupby("date"):
    leader = grp.iloc[0]["iid"]               # already sorted by volume desc
    iids_today = set(grp["iid"])
    if rank[leader] > chosen_rank:            # volume crossed to a later contract
        chosen_iid, chosen_rank = leader, rank[leader]
    if chosen_iid not in iids_today:          # safety: chosen expired -> take leader
        chosen_iid, chosen_rank = leader, rank[leader]
    front[d] = chosen_iid

front_s = pd.Series(front).sort_index()
front_s.index.name = "date"

# ----- roll boundaries + ratio factors --------------------------------
def close_on(iid, d):
    """Closest available close for `iid` within +/-3 days of d."""
    for off in (0, -1, 1, -2, 2, -3, 3):
        dd = (pd.Timestamp(d) + pd.Timedelta(days=off)).date()
        v = close_acc.get((dd, iid))
        if v is not None:
            return v[1]
    return None

dates_sorted = list(front_s.index)
segments = []            # list of dict: start, end, iid, sym
cur = front_s.iloc[0]; seg_start = dates_sorted[0]
for d in dates_sorted[1:]:
    if front_s[d] != cur:
        segments.append({"iid": cur, "start": seg_start, "end_prev": d})
        seg_start = d; cur = front_s[d]
segments.append({"iid": cur, "start": seg_start, "end_prev": None})

# ratio at each boundary i (between seg i-1 old and seg i new), using the
# last day the OLD contract was front (the day before the new seg starts)
ratios = [1.0]
for i in range(1, len(segments)):
    new_iid = segments[i]["iid"]
    old_iid = segments[i - 1]["iid"]
    roll_date = segments[i]["start"]
    prior = (pd.Timestamp(roll_date) - pd.Timedelta(days=1)).date()
    c_new = close_on(new_iid, prior)
    c_old = close_on(old_iid, prior)
    ratios.append((c_new / c_old) if (c_new and c_old) else 1.0)

# cumulative factor per segment (newest = 1.0, multiply backwards)
factor = [1.0] * len(segments)
cum = 1.0
for i in range(len(segments) - 1, -1, -1):
    factor[i] = cum
    cum *= ratios[i]

# map every date -> its segment's adj factor + roll flag
date_factor, date_isroll = {}, {}
for i, seg in enumerate(segments):
    f = factor[i]
    end = seg["end_prev"]
    seg_dates = [d for d in dates_sorted if d >= seg["start"] and (end is None or d < end)]
    for j, d in enumerate(seg_dates):
        date_factor[d] = f
        date_isroll[d] = (j == 0 and i > 0)

# ----- roll schedule report -------------------------------------------
roll_rows = []
for i in range(1, len(segments)):
    roll_rows.append({
        "roll_no":  i,
        "date":     segments[i]["start"],
        "from":     sym_acc.get(segments[i - 1]["iid"]),
        "to":       sym_acc.get(segments[i]["iid"]),
        "ratio":    round(ratios[i], 6),
        "cum_factor": round(factor[i - 1], 6),
    })
rolls_df = pd.DataFrame(roll_rows)
rolls_df.to_csv(OUT_ROLLS, index=False)

print(f"\nSEGMENTS: {len(segments)} front-month contracts; {len(rolls_df)} rolls")
print("first / last 6 rolls:")
with pd.option_context("display.width", 200):
    print(rolls_df.head(6).to_string(index=False))
    print("   ...")
    print(rolls_df.tail(6).to_string(index=False))

# ======================================================================
# PASS 2 — extract front-month bars, adjust, tag session, write parquet
# ======================================================================
print("\nPASS 2/2  extracting front-month bars ...")
front_iid_by_date = front_s.to_dict()
parts = []
kept = 0
for ch in pd.read_csv(PATH, usecols=USE, chunksize=CHUNK):
    ch = ch[~ch["symbol"].str.contains("-", na=False)]
    t  = pd.to_datetime(ch["ts_event"], utc=True, errors="coerce")
    d  = et_date_series(t)
    ch = ch.assign(ts_utc=t, date_et=d)
    want_iid = ch["date_et"].map(front_iid_by_date)
    keep = ch["instrument_id"] == want_iid
    sub = ch[keep].copy()
    if sub.empty:
        continue
    et = sub["ts_utc"].dt.tz_convert(ET)
    sub["ts_et"]      = et
    sub["adj_factor"] = sub["date_et"].map(date_factor).astype("float64")
    minutes = et.dt.hour * 60 + et.dt.minute
    rth = (et.dt.dayofweek < 5) & (minutes >= 570) & (minutes < 960)   # 09:30-16:00 ET
    sub["session"] = np.where(rth, "RTH", "ETH")
    parts.append(sub[["ts_utc", "ts_et", "date_et", "symbol", "instrument_id",
                      "open", "high", "low", "close", "volume",
                      "adj_factor", "session"]])
    kept += len(sub)

cont = pd.concat(parts, ignore_index=True).sort_values("ts_utc").reset_index(drop=True)
cont["is_roll"] = cont["date_et"].map(date_isroll).fillna(False)
cont.to_parquet(OUT_PARQUET, index=False)

# ======================================================================
# VALIDATION
# ======================================================================
dups = int(cont["ts_utc"].duplicated().sum())
adj_close = cont["close"] * cont["adj_factor"]
gaps = cont["ts_utc"].diff().dt.total_seconds()
intraday_gaps = int(((gaps > 60) & (gaps <= 3600)).sum())   # within-session holes
print(f"\nWROTE {OUT_PARQUET}   ({kept:,} front-month rows, {len(cont):,} after concat)")
print(f"DUP TIMESTAMPS:    {dups:,}   (target 0 -> one contract per minute)")
print(f"RAW CLOSE RANGE:   {cont['close'].min():.2f} .. {cont['close'].max():.2f}  (all positive, NQ-scaled)")
print(f"ADJ CLOSE RANGE:   {adj_close.min():.2f} .. {adj_close.max():.2f}")
print(f"NON-POSITIVE RAW:  {int((cont[['open','high','low','close']] <= 0).any(axis=1).sum()):,}")
print(f"RTH / ETH split:   {int((cont.session=='RTH').sum()):,} / {int((cont.session=='ETH').sum()):,}")
print(f"INTRADAY 1-60min GAPS: {intraday_gaps:,}")
print(f"DATE SPAN:         {cont['ts_et'].min()}  ->  {cont['ts_et'].max()}")
print(f"\nrolls written to {OUT_ROLLS}")
