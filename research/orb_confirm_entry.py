#!/usr/bin/env python3
"""
HIGHSTRIKE F31c — user-spec CONFIRMATION entry, side-by-side vs the production touch entry.
NQ 5m, adopted stack (struct gate + VWAP cap 2.0 + struct stop + 2ATR trail), all 3 sessions.

User ruleset (long; short mirrored):
  1. Breakout candle BODY must CLOSE beyond the OR level (wick-only break = no setup).
  2. Wait for the next candle(s): entry = stop order at the breakout candle's HIGH.
  3. Invalidation: if price CLOSES back inside the range (below the level) before the
     entry triggers, the setup is cancelled. New body-close breakout can re-arm it.
  4. Optional: breakout candle volume >= 1.2x 20-bar average.
  5. Optional: retest-and-hold — after the breakout candle, price must touch the broken
     level (low <= level) and CLOSE back beyond it at least once before the entry triggers.
Variants: confirm / confirm_next (strict next-candle-only) / confirm+vol / confirm+retest.

    python research/orb_confirm_entry.py
"""
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "engine"))
import numpy as np, pandas as pd
import hs_db, hs_harness as H, hs_backtest as B, hs_validate as V
from orb_optimize import state

rng = np.random.default_rng(7)
KCAP = 2.0
SESSIONS = [
    ("RTH",    570, 600, 900, False, 958),
    ("Asia",   60,  120, 540, True,  540),
    ("London", 540, 570, 840, True,  840),
]

MODE = None        # None -> engine original; else dict(next_only, vol, retest)
_orig = B._orb_signals


def _signals(d, or_s=570, or_e=600, brk_buf_atr=0.0, tod_end=960, execm="close",
             tradeday=False, reentry=False, vol_conf=False, vol_mult=1.2, vol_len=20):
    if MODE is None:
        return _orig(d, or_s, or_e, brk_buf_atr, tod_end, execm, tradeday,
                     reentry, vol_conf, vol_mult, vol_len)
    et = pd.to_datetime(d["ts"]).dt.tz_convert("America/New_York")
    if tradeday:
        sd = et + pd.Timedelta(hours=6)
        date = sd.dt.date.to_numpy()
        mins = (((et.dt.hour - 18) % 24) * 60 + et.dt.minute).to_numpy()
        wkday = (sd.dt.dayofweek < 5).to_numpy()
    else:
        date = et.dt.date.to_numpy()
        mins = (et.dt.hour * 60 + et.dt.minute).to_numpy()
        wkday = (et.dt.dayofweek < 5).to_numpy()
    in_or = wkday & (mins >= or_s) & (mins < or_e)
    rth = wkday & (mins >= or_s) & (mins < tod_end)
    hp, lp = d["high"].to_numpy(), d["low"].to_numpy()
    c = d["close"].to_numpy()
    df = pd.DataFrame({"date": date, "h": hp, "l": lp, "in_or": in_or})
    org = df[df.in_or].groupby("date").agg(orh=("h", "max"), orl=("l", "min"))
    m = pd.DataFrame({"date": date}).merge(org, on="date", how="left")
    orh, orl = m["orh"].to_numpy(), m["orl"].to_numpy()
    tup = d["trend_up"].to_numpy(); tdn = d["trend_down"].to_numpy()
    vol = d["volume"].to_numpy() if "volume" in d else np.full(len(d), np.nan)
    vavg = pd.Series(vol).rolling(20, min_periods=5).mean().to_numpy()
    n = len(d); lsig = np.zeros(n, bool); ssig = np.zeros(n, bool)
    lvl_l = np.full(n, np.nan); lvl_s = np.full(n, np.nan)
    cur = None; done_l = done_s = False
    pend_l = pend_s = np.nan          # stop level = breakout candle high/low
    age_l = age_s = 0                 # bars since the confirm candle (next_only variant)
    rt_l = rt_s = False               # retest-and-hold satisfied
    for i in range(n):
        if date[i] != cur:
            cur = date[i]; done_l = done_s = False
            pend_l = pend_s = np.nan; rt_l = rt_s = False
        if not rth[i] or mins[i] < or_e or np.isnan(orh[i]):
            continue
        lh, ll = orh[i], orl[i]
        # ---- manage a pending LONG setup
        if not done_l and not np.isnan(pend_l):
            age_l += 1
            if c[i] < lh:                                   # closed back inside the range -> invalid
                pend_l = np.nan; rt_l = False
            else:
                if lp[i] <= lh and c[i] >= lh:
                    rt_l = True                             # retest of the level + hold
                trig = hp[i] >= pend_l and (not MODE["next_only"] or age_l == 1) \
                       and (not MODE["retest"] or rt_l)
                if trig:
                    lsig[i] = True; lvl_l[i] = pend_l; done_l = True; pend_l = np.nan
                elif MODE["next_only"] and age_l >= 1:
                    pend_l = np.nan                          # strict: next candle only
        # ---- manage a pending SHORT setup
        if not done_s and not np.isnan(pend_s):
            age_s += 1
            if c[i] > ll:
                pend_s = np.nan; rt_s = False
            else:
                if hp[i] >= ll and c[i] <= ll:
                    rt_s = True
                trig = lp[i] <= pend_s and (not MODE["next_only"] or age_s == 1) \
                       and (not MODE["retest"] or rt_s)
                if trig:
                    ssig[i] = True; lvl_s[i] = pend_s; done_s = True; pend_s = np.nan
                elif MODE["next_only"] and age_s >= 1:
                    pend_s = np.nan
        # ---- arm on a body-close breakout candle (wick-only does NOT qualify)
        vok = (not MODE["vol"]) or (not np.isnan(vavg[i]) and vavg[i] > 0 and vol[i] >= 1.2 * vavg[i])
        if not done_l and np.isnan(pend_l) and c[i] > lh and tup[i] and vok:
            pend_l = hp[i]; age_l = 0; rt_l = False
        if not done_s and np.isnan(pend_s) and c[i] < ll and tdn[i] and vok:
            pend_s = lp[i]; age_s = 0; rt_s = False
    return lsig, ssig, orl, orh, lvl_l, lvl_s


B._orb_signals = _signals


def run(d, ors, ore, cut, tdy, eod, mode):
    global MODE
    MODE = mode
    tr = B.backtest(d, "trail", "both", False, "orb", 0, 1.0, 4.0, ors, ore, 0.0, cut, "stop",
                    tradeday=tdy, eod_min=eod, vwap_cap=KCAP, stop_mode="struct")
    MODE = None
    return tr


def loci(r):
    return np.percentile(rng.choice(r, (3000, len(r)), replace=True).mean(1), 5) if len(r) else 0.0


def report(tag, tr, min_n=30):
    if tr is None or len(tr) < min_n:
        print(f"    {tag:16} n={0 if tr is None else len(tr):>4}  (<{min_n} — no read)")
        return
    r = tr["net_R"].to_numpy()
    L = tr[tr.direction == "long"]["net_R"].to_numpy()
    S = tr[tr.direction == "short"]["net_R"].to_numpy()
    both = len(L) > 5 and L.mean() > 0 and len(S) > 5 and S.mean() > 0
    lo = loci(r)
    t = tr.copy()
    t["year"] = pd.to_datetime(t["entry_time"], utc=True).dt.tz_convert("America/New_York").dt.year
    yrs = [(int(y), g["net_R"].mean()) for y, g in t.groupby("year") if len(g) >= 8]
    pos = sum(1 for _, e in yrs if e > 0); tot = len(yrs)
    g = "PASS" if (both and lo > 0 and tot and pos >= 0.7 * tot) else "----"
    print(f"    {tag:16} n={len(r):>4} exp {r.mean():+.3f} PF {V.pf(r):>4.2f} win {100*np.mean(r>0):>2.0f}% "
          f"CI {lo:+.3f}  L {L.mean() if len(L) else 0:+.2f}({len(L)}) S {S.mean() if len(S) else 0:+.2f}({len(S)})  "
          f"yrs +{pos}/{tot}  {g}")


def main():
    d = state("NQ", "5m")
    print(f"NQ 5m — {len(d):,} bars. Side-by-side: production touch entry vs user confirmation spec.\n")
    base = dict(next_only=False, vol=False, retest=False)
    for name, ors, ore, cut, tdy, eod in SESSIONS:
        print(f"\n  {name}")
        report("touch (prod)", run(d, ors, ore, cut, tdy, eod, None))
        report("confirm", run(d, ors, ore, cut, tdy, eod, dict(base)))
        report("confirm_next", run(d, ors, ore, cut, tdy, eod, dict(base, next_only=True)))
        report("confirm+vol", run(d, ors, ore, cut, tdy, eod, dict(base, vol=True)))
        report("confirm+retest", run(d, ors, ore, cut, tdy, eod, dict(base, retest=True)))


if __name__ == "__main__":
    main()
