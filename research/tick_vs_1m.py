"""TICK vs 1-MINUTE direction agreement (F106 — decides whether tick_dir replaces the 1m reads
in the grade layer). Runs nightly in the battery; matures as the forward tick archive
(data/ticks/<date>/) accrues market-hours data.

Per archived RTH day/symbol: minute-bucket the 3s ticks -> tick direction per minute (slope sign)
-> compare with the 1m bar direction (provider) for the same minutes:
  agreement%        — do they say the same thing?
  tick LEAD test    — tick dir at minute t vs BAR dir at t+1 (does tick see it first?)
The swap bar: agreement >= 80% AND lead accuracy > coincident accuracy on >= 5 RTH days.

    python research/tick_vs_1m.py
"""
import glob
import json
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "BOT"))
import numpy as np
import pandas as pd

ARCHIVE = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                       "BOT", "data", "ticks")


def tick_minutes(path):
    pts = [json.loads(l) for l in open(path, encoding="utf-8")]
    if len(pts) < 100:
        return None
    df = pd.DataFrame(pts)
    df["dt"] = pd.to_datetime(df["ts"], unit="s").dt.tz_localize("UTC").dt.tz_convert("America/New_York")
    df["minute"] = df["dt"].dt.floor("1min")
    out = {}
    for m, g in df.groupby("minute"):
        if len(g) < 4 or g["px"].nunique() < 2:
            continue
        out[m] = 1 if g["px"].iloc[-1] > g["px"].iloc[0] else -1 if g["px"].iloc[-1] < g["px"].iloc[0] else 0
    return out


def main():
    days = sorted(glob.glob(os.path.join(ARCHIVE, "*")))
    if not days:
        print("tick_vs_1m: no archive yet — the watcher fills data/ticks/ during market hours")
        return
    from bot.market_data.providers import get_bars
    judged = 0
    for dpath in days[-5:]:
        date = os.path.basename(dpath)
        for f in sorted(glob.glob(os.path.join(dpath, "*.jsonl"))):
            sym = os.path.basename(f)[:-6]
            tm = tick_minutes(f)
            if not tm or len(tm) < 60:
                print(f"  {date} {sym}: insufficient market-hours ticks ({0 if not tm else len(tm)} active minutes)")
                continue
            try:
                b = get_bars(sym, tf="1m", period="5d")
            except Exception as e:
                print(f"  {date} {sym}: no 1m bars ({str(e)[:50]})")
                continue
            tcol = "ts_et" if "ts_et" in b.columns else "ts"
            et = pd.to_datetime(b[tcol])
            b = b.assign(minute=et.dt.floor("1min"),
                         bdir=np.sign(b["close"].astype(float) - b["open"].astype(float)))
            bmap = dict(zip(b["minute"], b["bdir"]))
            bmins = sorted(bmap)
            agree = lead = coin = n = 0
            for m, td in tm.items():
                bd = bmap.get(m)
                if bd is None or td == 0 or bd == 0:
                    continue
                n += 1
                agree += int(td == bd)
                coin += int(td == bd)
                nxt = bmap.get(m + pd.Timedelta(minutes=1))
                if nxt not in (None, 0):
                    lead += int(td == nxt)
            if n >= 60:
                judged += 1
                print(f"  {date} {sym}: n={n} minutes · agreement {100*agree/n:.0f}% · "
                      f"tick->NEXT-bar accuracy {100*lead/max(n,1):.0f}% (coincident {100*coin/n:.0f}%)")
    if not judged:
        print("tick_vs_1m: archive still maturing — PASS/no-verdict until >=5 RTH days judged")
    else:
        print(f"\njudged {judged} symbol-days · swap bar: agreement>=80% AND lead > coincident on >=5 days")


if __name__ == "__main__":
    main()
