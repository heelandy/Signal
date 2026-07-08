#!/usr/bin/env python3
"""
HIGHSTRIKE F31 — two user questions on the production STACK (NQ 5m, adopted config:
structure stop + 2ATR trail, VWAP cap 2.0, struct trend gate), all three sessions:

  TEST 1 — MACRO REGIME SLICE: production BLOCKS macro regime B (and D). Is there edge
           hiding in the discarded regime-B trades? Disable the macro_allow gate, run each
           session, slice the trade list by the per-trade regime tag (A/B/C/D), and apply
           the standard gate (both sides>0, lower-90% CI>0, >=70% of years positive) to B.
           Run on BOTH the adopted exit (trail+struct stop) and the scale_be baseline so the
           conclusion isn't an artifact of one exit config.

  TEST 2 — ENTRY EXECUTION: current entry is an INTRABAR TOUCH of the OR level (stop order).
           Does waiting for confirmation help? Variants per session:
             stop     intrabar touch, fill at the level                      (production)
             close    breakout bar must CLOSE beyond the level; fill at that close
             nb_open  close-confirm, then enter the NEXT bar at its open
             nb_high  close-confirm, then stop-entry above the confirm bar's high
                      (the "wait for the next candle to take out the breakout candle" entry)
             retest   break, then pull back to the OR edge; fill at the edge (F19 redux)

    python research/orb_regimeb_entries.py
"""
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "engine"))
import numpy as np, pandas as pd
import hs_db, hs_harness as H, hs_backtest as B, hs_validate as V
from orb_optimize import state

rng = np.random.default_rng(7)
KCAP = 2.0
# name, OR open, OR close, cutoff/EOD (trade-day mins for asia/london), tradeday flag
SESSIONS = [
    ("RTH",    570, 600, 900, False, 958),
    ("Asia",   60,  120, 540, True,  540),
    ("London", 540, 570, 840, True,  840),
]

# ---------------------------------------------------------------- entry-exec extension
EXEC_EXT = None                       # None -> original engine behavior
_orig_orb_signals = B._orb_signals


def _orb_signals_ext(d, or_s=570, or_e=600, brk_buf_atr=0.0, tod_end=960, execm="close",
                     tradeday=False, reentry=False, vol_conf=False, vol_mult=1.2, vol_len=20):
    """Adds nb_open / nb_high confirmation entries; delegates everything else to the engine.
    Both: breakout bar must CLOSE beyond the level (trend gate checked on that confirm bar),
    then nb_open fills the NEXT bar at its open; nb_high rests a stop at the confirm bar's
    high (low for shorts) until filled or the session window ends. Once per side per day."""
    if EXEC_EXT is None:
        return _orig_orb_signals(d, or_s, or_e, brk_buf_atr, tod_end, execm, tradeday,
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
    op, c = d["open"].to_numpy(), d["close"].to_numpy()
    df = pd.DataFrame({"date": date, "h": hp, "l": lp, "in_or": in_or})
    org = df[df.in_or].groupby("date").agg(orh=("h", "max"), orl=("l", "min"))
    m = pd.DataFrame({"date": date}).merge(org, on="date", how="left")
    orh, orl = m["orh"].to_numpy(), m["orl"].to_numpy()
    tup = d["trend_up"].to_numpy(); tdn = d["trend_down"].to_numpy()
    atr = d["atr14"].to_numpy()
    n = len(d); lsig = np.zeros(n, bool); ssig = np.zeros(n, bool)
    lvl_l = np.full(n, np.nan); lvl_s = np.full(n, np.nan)
    cur = None; done_l = done_s = False
    pend_l = pend_s = np.nan          # resting confirmation entry (nb_high) / next-bar-open flag
    fire_l_next = fire_s_next = False
    for i in range(n):
        if date[i] != cur:
            cur = date[i]; done_l = done_s = False
            pend_l = pend_s = np.nan; fire_l_next = fire_s_next = False
        if not rth[i] or mins[i] < or_e or np.isnan(orh[i]):
            continue
        buf = (atr[i] * brk_buf_atr) if not np.isnan(atr[i]) else 0.0
        lh, ll = orh[i] + buf, orl[i] - buf
        # fill a pending confirmation entry FIRST (set on an earlier bar)
        if not done_l:
            if fire_l_next:
                lsig[i] = True; lvl_l[i] = op[i]; done_l = True; fire_l_next = False
            elif not np.isnan(pend_l) and hp[i] >= pend_l:
                lsig[i] = True; lvl_l[i] = pend_l; done_l = True; pend_l = np.nan
        if not done_s:
            if fire_s_next:
                ssig[i] = True; lvl_s[i] = op[i]; done_s = True; fire_s_next = False
            elif not np.isnan(pend_s) and lp[i] <= pend_s:
                ssig[i] = True; lvl_s[i] = pend_s; done_s = True; pend_s = np.nan
        # arm on a close-confirm breakout bar (once per side per day)
        if not done_l and not fire_l_next and np.isnan(pend_l) and c[i] > lh and tup[i]:
            if EXEC_EXT == "nb_open":
                fire_l_next = True
            else:                      # nb_high
                pend_l = hp[i]
        if not done_s and not fire_s_next and np.isnan(pend_s) and c[i] < ll and tdn[i]:
            if EXEC_EXT == "nb_open":
                fire_s_next = True
            else:
                pend_s = lp[i]
    return lsig, ssig, orl, orh, lvl_l, lvl_s


B._orb_signals = _orb_signals_ext     # transparent when EXEC_EXT is None

# ---------------------------------------------------------------- run + report helpers
def run(d, ors, ore, cut, tdy, eod, execm="stop", exit_mode="trail", stop_mode="struct"):
    global EXEC_EXT
    EXEC_EXT = execm if execm in ("nb_open", "nb_high") else None
    em = "stop" if execm in ("nb_open", "nb_high") else execm
    tr = B.backtest(d, exit_mode, "both", False, "orb", 0, 1.0, 4.0, ors, ore, 0.0, cut, em,
                    tradeday=tdy, eod_min=eod, vwap_cap=KCAP, stop_mode=stop_mode)
    EXEC_EXT = None
    return tr


def loci(r):
    return np.percentile(rng.choice(r, (3000, len(r)), replace=True).mean(1), 5) if len(r) else 0.0


def report(tag, tr, min_n=30):
    if tr is None or len(tr) < min_n:
        print(f"    {tag:18} n={0 if tr is None else len(tr):>4}  (<{min_n} — no read)")
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
    print(f"    {tag:18} n={len(r):>4} exp {r.mean():+.3f} PF {V.pf(r):>4.2f} win {100*np.mean(r>0):>2.0f}% "
          f"CI {lo:+.3f}  L {L.mean() if len(L) else 0:+.2f}({len(L)}) S {S.mean() if len(S) else 0:+.2f}({len(S)})  "
          f"yrs +{pos}/{tot}  {g}")


def main():
    d = state("NQ", "5m")
    print(f"NQ 5m — {len(d):,} bars. Stack = struct gate + VWAP cap {KCAP} + struct stop + 2ATR trail.\n")

    # ---------------- TEST 1: macro regime slice ----------------
    print("=" * 100)
    print("TEST 1 — MACRO REGIME SLICE (macro_allow gate DISABLED, stand-down kept; slice by entry regime)")
    d2 = d.copy(deep=False)
    d2["macro_allow_trades"] = True
    d2.attrs.update(d.attrs)
    for ex_name, exm, stm in (("trail+struct (adopted)", "trail", "struct"),
                              ("scale_be+OR (baseline)", "scale_be", "or")):
        print(f"\n  exit config: {ex_name}")
        for name, ors, ore, cut, tdy, eod in SESSIONS:
            tr_open = run(d2, ors, ore, cut, tdy, eod, "stop", exm, stm)
            tr_prod = run(d, ors, ore, cut, tdy, eod, "stop", exm, stm)
            print(f"\n  {name} — production (B+D blocked):")
            report("prod", tr_prod)
            print(f"  {name} — gate open, by regime:")
            for rg in ("A", "B", "C", "D"):
                report(f"regime {rg}", tr_open[tr_open.regime == rg], min_n=20)

    # ---------------- TEST 2: entry execution variants ----------------
    print("\n" + "=" * 100)
    print("TEST 2 — ENTRY EXECUTION (production gating; adopted exit = trail + struct stop)")
    for name, ors, ore, cut, tdy, eod in SESSIONS:
        print(f"\n  {name}")
        for v in ("stop", "close", "nb_open", "nb_high", "retest"):
            report(v, run(d, ors, ore, cut, tdy, eod, v))


if __name__ == "__main__":
    main()
