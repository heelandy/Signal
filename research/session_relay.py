"""SESSION RELAY (F95, user 2026-07-10): "open and close RTH — analyse how ASIA receives and
reacts; open and close ASIA — analyse how LONDON reacts; open and close LONDON — analyse how RTH
reacts; make the cycle and define any pattern." The 24h futures day is a relay: each session
inherits the previous one's tape. This quantifies every hand-off so the system can BIAS its
entries by relay state (a qualifying cell -> the gauntlet -> only then wired).

Segments (ET, chronological relay):  ASIA 18:00->03:00  ·  LONDON 03:00->09:30  ·  RTH 09:30->16:00
Per segment: return, direction, range, close-location (where it closed inside its range).
Hand-offs tested (receiver return conditioned on the sender):
  A) sender DIRECTION        -> receiver mean ret / WR(continuation)
  B) sender CLOSE-LOCATION   -> strong close (top third) vs weak close (bottom third)
  C) sender RANGE EXPANSION  -> big-range sender (top tercile) vs quiet
PASS bar per cell: n>=150 AND bootstrap CI(mean) excludes 0 AND OOS(30%) same sign.

    python research/session_relay.py [SYM ...]     (default NQ)
"""
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "engine"))
import numpy as np
import pandas as pd
import hs_db

rng = np.random.default_rng(11)
SEGS = [("ASIA", 18 * 60, 27 * 60), ("LONDON", 3 * 60, 9 * 60 + 30), ("RTH", 9 * 60 + 30, 16 * 60)]


def segments(con, sym):
    b = hs_db.bars(con, "5m", "full", sym=sym).sort_values("ts").reset_index(drop=True)
    dt = pd.to_datetime(b["ts"], utc=True).dt.tz_convert("America/New_York")
    hm = dt.dt.hour * 60 + dt.dt.minute
    # ASIA spans midnight: shift the clock so 18:00 -> 0, giving one continuous segment key
    shifted = (hm - 18 * 60) % (24 * 60)
    seg_id = np.where(shifted < 9 * 60, "ASIA",
                      np.where(hm.between(3 * 60, 9 * 60 + 29), "LONDON",
                               np.where(hm.between(9 * 60 + 30, 15 * 60 + 59), "RTH", "off")))
    b = b.assign(seg=seg_id, dt=dt)
    b = b[b["seg"] != "off"]
    # a session INSTANCE = consecutive bars of the same seg (day boundaries handled by continuity)
    inst = (b["seg"] != b["seg"].shift()).cumsum()
    rows = []
    for _, g in b.groupby(inst):
        o, c = float(g["open"].iloc[0]), float(g["close"].iloc[-1])
        h, l = float(g["high"].max()), float(g["low"].min())
        rgn = h - l
        rows.append({"seg": g["seg"].iloc[0], "start": g["dt"].iloc[0], "o": o, "c": c,
                     "ret": (c - o) / o, "dir": 1 if c > o else -1,
                     "range": rgn, "close_loc": (c - l) / rgn if rgn > 0 else 0.5})
    return pd.DataFrame(rows)


def ci(x):
    if len(x) < 30:
        return 0.0, 0.0
    m = rng.choice(x, (2000, len(x)), replace=True).mean(1)
    return float(np.percentile(m, 5)), float(np.percentile(m, 95))


def cell(tag, recv):
    x = np.asarray(recv, float)
    if len(x) < 150:
        return f"  {tag:44} n={len(x):>4}  (thin)"
    lo, hi = ci(x)
    cut = int(len(x) * 0.7); oos = x[cut:]
    sig = lo > 0 or hi < 0
    oos_ok = len(oos) and np.sign(oos.mean()) == np.sign(x.mean())
    mark = " <== PASS" if (sig and oos_ok) else ""
    return (f"  {tag:44} n={len(x):>4} mean {1e4*x.mean():+6.1f}bps WR {100*(x>0).mean():3.0f}% "
            f"CI[{1e4*lo:+.1f},{1e4*hi:+.1f}] OOS {1e4*(oos.mean() if len(oos) else 0):+6.1f}bps{mark}")


def relay(df, sender, receiver):
    print(f"\n--- {sender} -> {receiver} ---")
    s = df[df["seg"] == sender].reset_index(drop=True)
    r = df[df["seg"] == receiver].reset_index(drop=True)
    # pair each sender instance with the NEXT receiver instance in time
    pairs = []
    ri = 0
    for _, srow in s.iterrows():
        while ri < len(r) and r.loc[ri, "start"] <= srow["start"]:
            ri += 1
        if ri >= len(r):
            break
        pairs.append((srow, r.loc[ri]))
    if not pairs:
        print("  no pairs"); return
    P = pd.DataFrame({"s_dir": [a["dir"] for a, b in pairs], "s_ret": [a["ret"] for a, b in pairs],
                      "s_loc": [a["close_loc"] for a, b in pairs], "s_rng": [a["range"] for a, b in pairs],
                      "r_ret": [b["ret"] for a, b in pairs]})
    print(cell("baseline (all)", P["r_ret"]))
    print(cell(f"after {sender} UP  -> {receiver} ret", P[P.s_dir > 0]["r_ret"]))
    print(cell(f"after {sender} DOWN-> {receiver} ret", P[P.s_dir < 0]["r_ret"]))
    print(cell(f"continuation (recv ret x sender dir)", P["r_ret"] * P["s_dir"]))
    q1, q2 = P["s_loc"].quantile([1 / 3, 2 / 3])
    print(cell(f"after STRONG close (top 1/3) -> follow dir", P[P.s_loc >= q2]["r_ret"] * P[P.s_loc >= q2]["s_dir"]))
    print(cell(f"after WEAK close (bot 1/3)  -> follow dir", P[P.s_loc <= q1]["r_ret"] * P[P.s_loc <= q1]["s_dir"]))
    rq = P["s_rng"].quantile(2 / 3)
    print(cell(f"after BIG-range sender -> follow dir", P[P.s_rng >= rq]["r_ret"] * P[P.s_rng >= rq]["s_dir"]))


def main():
    syms = [s.upper() for s in (sys.argv[1:] or ["NQ"])]
    con = hs_db.connect()
    for sym in syms:
        df = segments(con, sym)
        n = {k: int((df['seg'] == k).sum()) for k in ("ASIA", "LONDON", "RTH")}
        print(f"\n######## {sym} — session relay ({n}) ########")
        relay(df, "RTH", "ASIA")
        relay(df, "ASIA", "LONDON")
        relay(df, "LONDON", "RTH")
    con.close()
    print("\nread: 'follow dir' > 0 = the receiver CONTINUES the sender; < 0 = it FADES it. "
          "PASS = n>=150, CI excludes 0, OOS same sign — pass cells go to the gauntlet as entry-bias "
          "candidates before anything is wired.")


if __name__ == "__main__":
    main()
