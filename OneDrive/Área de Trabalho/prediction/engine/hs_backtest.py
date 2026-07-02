#!/usr/bin/env python3
"""
HIGHSTRIKE Phase 3.1/3.2 — backtest the ported entry over 16y -> trade list.

PROVISIONAL until the Phase-1 reconcile (hs_reconcile.py) confirms the harness vs V44.
Uses the tractable V44 entry (roadmap 3.1): VWAP+EMA reclaim confluence + the hard gates
(structure, macro regime + stand-down, local regime, bias-not-opposing), a trigger-relative
stop (nearest VWAP/EMA), and the V44 exit engine (50% at TP1=1R, runner to TP2=2R, stop->BE).
Real costs (MNQ): commission 0.52/order, slippage 2 ticks. One position at a time.

External macro inputs (request.security in Pine) approximated for the standalone backtest:
  VIX     -> vix_daily (front-month/spot), merged by ET date
  SPY ref -> ES daily proxy (S&P futures ~ SPY for the trend/ADX), merged by ET date
  HTF     -> the symbol's own DAILY EMA50/200 alignment, merged by ET date
These approximations are what the reconcile will quantify; expectancy in R is the headline.

    python hs_backtest.py [SYM=NQ] [TF=15m] [SESSION=full]
Output: data/bt_<sym>_<tf>.csv  (one row per trade) + summary.
"""
import sys
import numpy as np, pandas as pd
import hs_harness as H
import hs_db

# --- MNQ economics / exit params (V44 defaults) ---
PT_VALUE, TICK, SLIP_TICKS, COMM = 2.0, 0.25, 2, 0.52
CONTRACTS = 2
TP1_RR, TP2_RR = 1.0, 2.0
SL_BUF_ATR, MIN_STOP_ATR, SL_MAX_ATR = 0.3, 0.5, 2.5
TRAIL_MULT = 2.0   # ATR chandelier trail for exit mode "trail"


def _externals(con, bars, sym):
    et = pd.to_datetime(bars["ts"]).dt.tz_convert("America/New_York")
    bars["date"] = et.dt.normalize().dt.tz_localize(None)
    # VIX (sma5 + close[5])
    vix = con.execute("SELECT date, sma5, close FROM vix_daily ORDER BY date").df()
    vix["date"] = pd.to_datetime(vix["date"]); vix["prev5"] = vix["close"].shift(5)
    bars = bars.merge(vix[["date", "sma5", "prev5"]].rename(
        columns={"sma5": "vix_sma5", "prev5": "vix_prev5"}), on="date", how="left")
    # SPY proxy = ES daily (full session)
    es = hs_db.bars(con, "1d", "full", sym="ES")
    es["date"] = pd.to_datetime(es["ts"]).dt.tz_convert("America/New_York").dt.normalize().dt.tz_localize(None)
    es = es.sort_values("date")
    es["e20"], es["e50"] = H.ema(es["close"], 20), H.ema(es["close"], 50)
    _, _, es["adx"] = H.dmi(es["high"], es["low"], es["close"], 14, 14)
    bars = bars.merge(es[["date", "close", "e20", "e50", "adx"]].rename(columns={
        "close": "spy_close", "e20": "spy_e20", "e50": "spy_e50", "adx": "spy_adx"}),
        on="date", how="left")
    # HTF = this symbol's DAILY ema50/200 alignment (proxy for the Pine HTF spine)
    dd = hs_db.bars(con, "1d", "full", sym=sym)
    dd["date"] = pd.to_datetime(dd["ts"]).dt.tz_convert("America/New_York").dt.normalize().dt.tz_localize(None)
    dd = dd.sort_values("date")
    e50, e200 = H.ema(dd["close"], 50), H.ema(dd["close"], 200)
    dd["htf_bull"] = (dd["close"] > e50) & (e50 > e200)
    dd["htf_bear"] = (dd["close"] < e50) & (e50 < e200)
    bars = bars.merge(dd[["date", "htf_bull", "htf_bear"]], on="date", how="left")
    bars["htf_bull"] = bars["htf_bull"].fillna(False); bars["htf_bear"] = bars["htf_bear"].fillna(False)
    return bars


def attach_mtf(con, sym, d):
    """Higher-TF trend confirmation: per bar, how many of {1h,4h,D} are bull/bear
    (EMA50>EMA200 stack on the PRIOR closed HTF bar -> no lookahead). Adds mtf_up/mtf_down."""
    d = d.sort_values("ts").reset_index(drop=True)
    up = np.zeros(len(d), int); dn = np.zeros(len(d), int)
    base = d[["ts"]].copy(); base["ts"] = pd.to_datetime(base["ts"], utc=True)
    for tf in ["1h", "4h", "1d"]:
        b = hs_db.bars(con, tf, "full", sym=sym).sort_values("ts").reset_index(drop=True)
        e50, e200 = H.ema(b["close"], 50), H.ema(b["close"], 200)
        dir_ = np.where((b["close"] > e50) & (e50 > e200), 1,
                        np.where((b["close"] < e50) & (e50 < e200), -1, 0))
        b["dir"] = pd.Series(dir_).shift(1).fillna(0).to_numpy()      # prior CLOSED HTF bar
        b["ts"] = pd.to_datetime(b["ts"], utc=True)
        m = pd.merge_asof(base, b[["ts", "dir"]], on="ts", direction="backward")
        dd = m["dir"].fillna(0).to_numpy()
        up += (dd == 1); dn += (dd == -1)
    d["mtf_up"], d["mtf_down"] = up, dn
    return d


def _orb_signals(d, or_s=570, or_e=600, brk_buf_atr=0.0, tod_end=960, execm="close", tradeday=False,
                 reentry=False, vol_conf=False, vol_mult=1.2, vol_len=20, entry_delay=0, ob_l=None, ob_s=None,
                 chase_atr=0.0, strong_body=0.0, ft_confirm=False, dir_seq=False, min_or_width=0.0, max_entries=99,
                 or_mid_bias=False):
    """Opening-Range Breakout: break of the [or_s,or_e) range after it closes, once/day, before
    tod_end. brk_buf_atr = clear OR by this x ATR. execm 'close'|'stop'.
    tradeday=False: minutes-from-midnight ET + calendar-date (US RTH session).
    tradeday=True : minutes-since-18:00-ET + CME trade-day grouping (sessions that cross midnight,
                    e.g. Asia/London). In trade-day mins: 18:00=0, 20:00=120, 00:00=360, 09:30=930."""
    et = pd.to_datetime(d["ts"]).dt.tz_convert("America/New_York")
    if tradeday:
        sd = et + pd.Timedelta(hours=6)                       # 18:00 ET -> 00:00 of the trade-day
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
    op = d["open"].to_numpy()                                    # for the no-chase guard (F57)
    df = pd.DataFrame({"date": date, "h": hp, "l": lp, "in_or": in_or})
    org = df[df.in_or].groupby("date").agg(orh=("h", "max"), orl=("l", "min"))
    m = pd.DataFrame({"date": date}).merge(org, on="date", how="left")
    orh, orl = m["orh"].to_numpy(), m["orl"].to_numpy()
    c = d["close"].to_numpy(); tup = d["trend_up"].to_numpy(); tdn = d["trend_down"].to_numpy()
    atr = d["atr14"].to_numpy()
    vol = d["volume"].to_numpy() if "volume" in d else np.full(len(d), np.nan)
    vavg = pd.Series(vol).rolling(vol_len, min_periods=5).mean().to_numpy()    # relative-volume baseline
    n = len(d); lsig = np.zeros(n, bool); ssig = np.zeros(n, bool)
    lvl_l = np.full(n, np.nan); lvl_s = np.full(n, np.nan)
    # vol-expansion filter: OR-width / ATR-at-OR-close (per day, matches the Pine which freezes it at or_set).
    # ATR at the entry bar drifts intraday, so use the first post-OR bar's ATR as the day's reference.
    orw_atr = np.full(n, np.nan)
    if min_or_width > 0:
        df_oc = pd.DataFrame({"date": date, "atr": atr, "after": (mins >= or_e)})
        oc = df_oc[df_oc["after"]].groupby("date")["atr"].first()
        oc_map = pd.Series(date).map(oc).to_numpy()
        with np.errstate(invalid="ignore", divide="ignore"):
            orw_atr = np.where((oc_map > 0), (orh - orl) / oc_map, np.nan)
    # OR-mid BIAS (ICT premium/discount / equilibrium, GRADUATED 2026-07): the OR closed in its UPPER half
    # (last OR-bar close > OR-mid) => day biased LONG (block shorts); lower half => biased SHORT (block longs).
    or_bull = None
    if or_mid_bias:
        ocdf = pd.DataFrame({"date": date, "c": c, "in_or": in_or, "mins": mins})
        oc_close = ocdf[ocdf["in_or"]].sort_values("mins").groupby("date")["c"].last()   # last OR-bar close
        ocm = pd.Series(date).map(oc_close).to_numpy()
        with np.errstate(invalid="ignore"):
            or_bull = ocm > ((orh + orl) / 2.0)          # per-bar (day-broadcast); False where OR undefined
    cur = None; done_l = done_s = broke_l = broke_s = False; armed_l = armed_s = True; reclaimed_l = reclaimed_s = False
    n_l = n_s = 0                                       # re-entry counters per date (cap at max_entries)
    for i in range(n):
        if date[i] != cur:
            cur = date[i]; done_l = done_s = broke_l = broke_s = False; armed_l = armed_s = True; reclaimed_l = reclaimed_s = False; n_l = n_s = 0
        if not rth[i] or mins[i] < or_e + entry_delay or np.isnan(orh[i]):   # entry_delay = F38 skip-opening-hour
            continue
        buf = (atr[i] * brk_buf_atr) if not np.isnan(atr[i]) else 0.0
        lh, ll = orh[i] + buf, orl[i] - buf
        if hp[i] >= lh: broke_l = True            # price has cleared the breakout level today
        if lp[i] <= ll: broke_s = True
        if reentry:                                # re-arm after price falls back INSIDE the OR (fresh break)
            if c[i] < orh[i]: armed_l = True
            if c[i] > orl[i]: armed_s = True
        if execm == "retest":                      # require break THEN pullback to the OR edge
            l_cross, ll_lvl = (broke_l and lp[i] <= orh[i]), orh[i]   # enter at OR high on the retest
            s_cross, ls_lvl = (broke_s and hp[i] >= orl[i]), orl[i]
        elif execm == "stop":                       # fill at the breakout level on the touch
            l_cross, ll_lvl = hp[i] >= lh, lh
            s_cross, ls_lvl = lp[i] <= ll, ll
        elif execm == "fade":                       # FALSE-BREAKOUT fade: swept the OR edge (by k*ATR), then CLOSED back inside
            l_cross, ll_lvl = (broke_s and c[i] > orl[i]), orl[i]   # failed down-break -> LONG  (buy the reclaim)
            s_cross, ls_lvl = (broke_l and c[i] < orh[i]), orh[i]   # failed up-break   -> SHORT (sell the reclaim)
        elif execm == "sweepgo":                     # LIQUIDITY GRAB: swept the OPPOSITE edge first, then break THIS edge
            l_cross, ll_lvl = (broke_s and hp[i] >= lh), lh         # swept low -> break high  -> LONG  (stop-run then go)
            s_cross, ls_lvl = (broke_l and lp[i] <= ll), ll         # swept high -> break low  -> SHORT
        elif execm == "rebreak":                     # SECOND break only: broke, reclaimed back inside, breaks again
            l_cross, ll_lvl = (reclaimed_l and hp[i] >= lh), lh
            s_cross, ls_lvl = (reclaimed_s and lp[i] <= ll), ll
        else:                                       # close-confirm (optionally strong full-body + next-bar follow-through)
            if ft_confirm:                          # F59c: prior bar = strong breakout close, THIS bar CONTINUES the trend (no one-bar pop-and-reverse)
                pq_l = i > 0 and date[i-1] == date[i] and c[i-1] > lh and c[i-1] > op[i-1] and (strong_body <= 0 or (hp[i-1]-lp[i-1]) <= 0 or abs(c[i-1]-op[i-1]) >= strong_body*(hp[i-1]-lp[i-1]))
                pq_s = i > 0 and date[i-1] == date[i] and c[i-1] < ll and c[i-1] < op[i-1] and (strong_body <= 0 or (hp[i-1]-lp[i-1]) <= 0 or abs(c[i-1]-op[i-1]) >= strong_body*(hp[i-1]-lp[i-1]))
                l_cross, ll_lvl = (pq_l and c[i] > c[i-1]), lh
                s_cross, ls_lvl = (pq_s and c[i] < c[i-1]), ll
            elif strong_body > 0:                   # F59b: a strong full-body, right-colour close beyond the level
                bigb = (hp[i]-lp[i]) <= 0 or abs(c[i]-op[i]) >= strong_body*(hp[i]-lp[i])
                l_cross, ll_lvl = (c[i] > lh and c[i] > op[i] and bigb), lh
                s_cross, ls_lvl = (c[i] < ll and c[i] < op[i] and bigb), ll
            else:
                l_cross, ll_lvl = c[i] > lh, lh
                s_cross, ls_lvl = c[i] < ll, ll
        ok_l = (n_l < max_entries) and (armed_l if reentry else (not done_l))
        ok_s = (n_s < max_entries) and (armed_s if reentry else (not done_s))
        vok = (not vol_conf) or (not np.isnan(vavg[i]) and vavg[i] > 0 and vol[i] >= vol_mult * vavg[i])
        # F57 no-chase guard: skip if price has already run > chase_atr·ATR past the level (buying exhaustion);
        # done_l NOT set, so a later PULLBACK bar near the level can still fire (waits instead of chasing)
        near_l = chase_atr <= 0 or (not np.isnan(atr[i]) and lp[i] <= ll_lvl + atr[i] * chase_atr)
        near_s = chase_atr <= 0 or (not np.isnan(atr[i]) and hp[i] >= ls_lvl - atr[i] * chase_atr)
        # direction sequence (example.txt / Evidence early-entry): only fire while price is
        # actually pushing the trade way — long needs 101->102->103 (c>c[-1]>c[-2]) same day; short mirror
        seq_l = (not dir_seq) or (i >= 2 and date[i-1] == date[i] and date[i-2] == date[i] and c[i] > c[i-1] and c[i-1] > c[i-2])
        seq_s = (not dir_seq) or (i >= 2 and date[i-1] == date[i] and date[i-2] == date[i] and c[i] < c[i-1] and c[i-1] < c[i-2])
        # vol-expansion conditioner (graduated 2026-07): require a WIDE opening range (OR-width/ATR >= min,
        # using ATR at the OR close per the Pine); the narrow-OR third is dead. 0 = off.
        wide_ok = min_or_width <= 0 or (not np.isnan(orw_atr[i]) and orw_atr[i] >= min_or_width)
        bias_l = or_bull is None or bool(or_bull[i])          # OR-mid bias: long only if OR closed upper-half
        bias_s = or_bull is None or not bool(or_bull[i])      # short only if OR closed lower-half
        if ok_l and l_cross and near_l and seq_l and wide_ok and bias_l and tup[i] and (ob_l is None or ob_l[i]) and vok:   # ob_l = F41 OB confluence (gated WITH the latch)
            lsig[i] = True; lvl_l[i] = ll_lvl; done_l = True; armed_l = False; n_l += 1
        if ok_s and s_cross and near_s and seq_s and wide_ok and bias_s and tdn[i] and (ob_s is None or ob_s[i]) and vok:
            ssig[i] = True; lvl_s[i] = ls_lvl; done_s = True; armed_s = False; n_s += 1
        # update reclaim state AFTER firing (so a re-break must come on a LATER bar than the reclaim)
        if broke_l and c[i] < orh[i]: reclaimed_l = True
        if broke_s and c[i] > orl[i]: reclaimed_s = True
    return lsig, ssig, orl, orh, lvl_l, lvl_s


def _nearest(close, levels, below):
    best = np.nan
    for v in levels:
        if not np.isnan(v) and (v <= close if below else v >= close):
            if np.isnan(best) or (v > best if below else v < best):
                best = v
    return best


def backtest(d, mode="scale_be", side="both", strict=False, entry_type="vwap_ema", mtf_min=0,
             tp1_rr=None, tp2_rr=None, or_s=570, or_e=600, brk_buf_atr=0.0, tod_end=960, execm="close",
             tradeday=False, eod_min=958, reentry=False, max_entries=2, vol_conf=False, vol_mult=1.2,
             time_stop=0, vwap_cap=0.0, skip_mask=None, stop_mode="or", scale_frac=0.5,
             entry_delay=0, ob_confluence=False, chase_atr=0.0, strong_body=0.0, ft_confirm=False, dir_seq=False,
             min_or_width=0.0, ext_long=None, ext_short=None, or_mid_bias=False):
    """Event-driven sim over harness-state DataFrame d. Returns trades DataFrame.
    mode: scale_be = 50% at TP1 then runner->BE->TP2 (V44 default);
          tp2_full = full position to TP2 with original stop (2R/-1R);
          trail    = full position, ATR chandelier trail (ride momentum, no TP cap).
    side: both | long | short (isolate a directional edge)."""
    h, l, c, o = d["high"].to_numpy(), d["low"].to_numpy(), d["close"].to_numpy(), d["open"].to_numpy()
    atr = d["atr14"].to_numpy()
    vs, vw = d["vwap_sess"].to_numpy(), d["vwap_wk"].to_numpy()
    vs_prev = np.concatenate([[np.nan], vs[:-1]])     # prior-bar session VWAP (causal: known before the fill)
    e9, e20, e50 = d["ema9"].to_numpy(), d["ema20"].to_numpy(), d["ema50"].to_numpy()
    ts = d["ts"].to_numpy(); reg = d["macro_regime"].to_numpy()
    spl_arr = d["spl"].to_numpy() if "spl" in d.columns else None    # structure-anchored stop (stop_mode="struct")
    sph_arr = d["sph"].to_numpy() if "sph" in d.columns else None
    # asset-aware economics: equities/ETFs trade in $0.01 ticks, commission-free; futures use MNQ costs
    sym_ = str(d.attrs.get("sym", "NQ")).upper()
    EQ = sym_ in ("SPY", "QQQ", "NVDA", "TSLA", "AVGO", "ORCL", "AAPL", "MSFT", "AMZN", "META",
                  "GOOGL", "DIA", "IWM", "AMD", "NFLX")
    pt_val_, tick_, comm_, slip_ = (1.0, 0.01, 0.0, 1) if EQ else (PT_VALUE, TICK, COMM, SLIP_TICKS)
    min_stop_atr_ = 0.75 if EQ else MIN_STOP_ATR    # F51: ticker-adaptive min-stop floor (0.5 ATR is noise-tight on equities) — matches the STACK Pine
    sl_max_atr_ = 1.5 if EQ else SL_MAX_ATR         # reversal cap: equities take a tight 1.5-ATR max stop (arm-timing test); futures need 2.5 (tight whipsaws)
    _et = pd.to_datetime(d["ts"]).dt.tz_convert("America/New_York")        # for EOD-flat (match Pine)
    if tradeday:        # sessions crossing midnight (Asia/London): trade-day coords, 18:00 ET = day start
        _sd = _et + pd.Timedelta(hours=6)
        daykey = (_sd.dt.year * 10000 + _sd.dt.month * 100 + _sd.dt.day).to_numpy()
        tod_ = (((_et.dt.hour - 18) % 24) * 60 + _et.dt.minute).to_numpy()
    else:
        daykey = (_et.dt.year * 10000 + _et.dt.month * 100 + _et.dt.day).to_numpy()
        tod_ = (_et.dt.hour * 60 + _et.dt.minute).to_numpy()
    # V44 firing: grade floor (encodes struct+bias+zone/sweep/pattern) AND trigger AND macro/regime gates
    or_low = or_high = lvl_l = lvl_s = None
    gate_l = (d["macro_allow_trades"] & d["macro_long_ok"] & (d["local_regime"] != 2)).to_numpy()
    gate_s = (d["macro_allow_trades"] & d["macro_short_ok"] & (d["local_regime"] != 2)).to_numpy()
    t1 = TP1_RR if tp1_rr is None else tp1_rr
    t2 = TP2_RR if tp2_rr is None else tp2_rr
    sf = scale_frac                               # fraction of the position banked at TP1 (rest runs to TP2/BE)
    if entry_type == "orb":                       # Opening-Range Breakout entry
        _obl = d["in_bull_ob"].shift(1).fillna(False).to_numpy().astype(bool) if (ob_confluence and "in_bull_ob" in d) else None
        _obs = d["in_bear_ob"].shift(1).fillna(False).to_numpy().astype(bool) if (ob_confluence and "in_bear_ob" in d) else None
        lo, so, or_low, or_high, lvl_l, lvl_s = _orb_signals(d, or_s, or_e, brk_buf_atr, tod_end, execm, tradeday, reentry, vol_conf, vol_mult, entry_delay=entry_delay, ob_l=_obl, ob_s=_obs, chase_atr=chase_atr, strong_body=strong_body, ft_confirm=ft_confirm, dir_seq=dir_seq, min_or_width=min_or_width, or_mid_bias=or_mid_bias)
        long_ok = lo & gate_l; short_ok = so & gate_s
        if mtf_min > 0 and "mtf_up" in d:         # higher-TF trend confirmation
            long_ok = long_ok & (d["mtf_up"].to_numpy() >= mtf_min)
            short_ok = short_ok & (d["mtf_down"].to_numpy() >= mtf_min)
    elif entry_type == "ext":                     # research hook: externally-supplied entry signals (SMC etc.)
        _z = np.zeros(len(d), bool)               # fills at close, struct stop, same exit/costs as ORB
        long_ok = (ext_long if ext_long is not None else _z) & gate_l
        short_ok = (ext_short if ext_short is not None else _z) & gate_s
    else:                                         # V44 VWAP/EMA reclaim + grade
        long_ok  = (d["trigger_long"]  & d["grade_long_ok"]).to_numpy()  & gate_l
        short_ok = (d["trigger_short"] & d["grade_short_ok"]).to_numpy() & gate_s
    if strict and entry_type != "orb":           # principled with-trend / RTH / A-grade (not param-mining)
        et = pd.to_datetime(d["ts"]).dt.tz_convert("America/New_York")
        mins = et.dt.hour * 60 + et.dt.minute
        rth = ((et.dt.dayofweek < 5) & (mins >= 570) & (mins < 960)).to_numpy()
        mb = np.asarray(d["master_bias"])
        long_ok = long_ok & d["htf_bull"].to_numpy() & (mb == "LONG") & rth & (d["long_score"].to_numpy() >= 7)
        short_ok = short_ok & d["htf_bear"].to_numpy() & (mb == "SHORT") & rth & (d["short_score"].to_numpy() >= 7)
    if side == "long":  short_ok = np.zeros(len(d), bool)
    if side == "short": long_ok = np.zeros(len(d), bool)

    trades = []; n = len(d); i = 0
    pos = 0  # 0 flat, +1 long, -1 short
    last_day = -1; day_n = 0   # per-day taken-entry count (re-entry cap)
    while i < n:
        if pos == 0:
            sig = 1 if long_ok[i] else (-1 if short_ok[i] else 0)
            if sig == 0 or np.isnan(atr[i]) or atr[i] <= 0:
                i += 1; continue
            if skip_mask is not None and skip_mask[i]:    # signal-level skip (e.g. clean-day filter) -> stay flat
                i += 1; continue
            if daykey[i] != last_day:
                last_day = daykey[i]; day_n = 0
            if reentry and day_n >= max_entries:
                i += 1; continue
            if entry_type == "orb" and execm in ("stop", "retest", "sweepgo", "rebreak"):
                _lvl = lvl_l[i] if sig == 1 else lvl_s[i]
                entry = max(_lvl, o[i]) if sig == 1 else min(_lvl, o[i])   # F-fix: gap-aware — a stop fills no better than the bar's open
            else:
                entry = c[i]
            if vwap_cap > 0 and not np.isnan(vs_prev[i]) and not np.isnan(atr[i]) and atr[i] > 0:
                ext = (entry - vs_prev[i]) / atr[i] if sig == 1 else (vs_prev[i] - entry) / atr[i]
                if ext > vwap_cap:                 # breakout already extended beyond prior-bar VWAP -> skip (stay flat)
                    i += 1; continue
            if entry_type in ("orb", "ext"):
                if stop_mode == "struct" and spl_arr is not None:        # anchor at the last HH/HL swing, not the OR edge
                    sa = spl_arr[i] if sig == 1 else sph_arr[i]
                    _fb = (or_low[i] if sig == 1 else or_high[i]) if or_low is not None else np.nan
                    anc = sa if not np.isnan(sa) else _fb
                elif stop_mode == "ormid" and or_low is not None:        # research: stop at the OR MIDPOINT (tighter)
                    anc = (or_low[i] + or_high[i]) / 2.0
                elif or_low is not None:
                    anc = (or_low[i] if sig == 1 else or_high[i])
                else:
                    anc = np.nan                                          # ext with no OR -> 1.5ATR fallback stop
            else:
                anc = _nearest(entry, [vs[i], vw[i], e9[i], e20[i], e50[i]], below=(sig == 1))
            if sig == 1:
                raw = (anc - atr[i] * SL_BUF_ATR) if not np.isnan(anc) else entry - atr[i] * 1.5
                stop = min(max(raw, entry - atr[i] * sl_max_atr_), entry - atr[i] * min_stop_atr_)
            else:
                raw = (anc + atr[i] * SL_BUF_ATR) if not np.isnan(anc) else entry + atr[i] * 1.5
                stop = max(min(raw, entry + atr[i] * sl_max_atr_), entry + atr[i] * min_stop_atr_)
            risk = abs(entry - stop)
            if risk <= 0:
                i += 1; continue
            day_n += 1                          # committed to an entry this day
            tp1 = entry + sig * risk * t1
            tp2 = entry + sig * risk * t2
            entry_i, entry_ts, entry_reg = i, ts[i], reg[i]
            entry_day = daykey[i]
            tp1_done = False; cur_stop = stop; mfe = mae = 0.0
            pos = sig; i += 1
            while i < n:
                mfe = max(mfe, sig * (h[i] - entry) / risk); mae = min(mae, sig * (l[i] - entry) / risk)
                hit_stop = (l[i] <= cur_stop) if sig == 1 else (h[i] >= cur_stop)
                hit_tp1  = (h[i] >= tp1) if sig == 1 else (l[i] <= tp1)
                hit_tp2  = (h[i] >= tp2) if sig == 1 else (l[i] <= tp2)
                if mode == "trail":                               # full position, ATR chandelier trail
                    if not np.isnan(atr[i]):
                        cur_stop = (max(cur_stop, c[i] - TRAIL_MULT * atr[i]) if sig == 1
                                    else min(cur_stop, c[i] + TRAIL_MULT * atr[i]))
                    if hit_stop or (l[i] <= cur_stop if sig == 1 else h[i] >= cur_stop):
                        gross_R = sig * (cur_stop - entry) / risk; orders = 2; exitpx = cur_stop; break
                elif mode == "tp2_full":                          # 2R / -1R, full position
                    if hit_stop: gross_R = -1.0; orders = 2; exitpx = cur_stop; break
                    if hit_tp2:  gross_R = t2; orders = 2; exitpx = tp2; break
                elif not tp1_done:
                    if hit_stop:                                  # full loss before TP1
                        gross_R = -1.0; orders = 2; exitpx = cur_stop; break
                    if hit_tp1:
                        tp1_done = True; cur_stop = entry          # BE on runner
                        if hit_tp2:
                            gross_R = sf * t1 + (1 - sf) * t2; orders = 3; exitpx = tp2; break
                else:
                    if hit_tp2:
                        gross_R = sf * t1 + (1 - sf) * t2; orders = 3; exitpx = tp2; break
                    if hit_stop:                                   # runner stopped at BE
                        gross_R = sf * t1; orders = 3; exitpx = cur_stop; break
                if (daykey[i] != entry_day or tod_[i] >= eod_min or
                        (time_stop and (i - entry_i) >= time_stop)):   # EOD flat (~15:58) or time-stop (research)
                    rem = sig * (c[i] - entry) / risk
                    gross_R = (sf * t1 + (1 - sf) * rem) if tp1_done else rem
                    orders = 3 if tp1_done else 2; exitpx = c[i]; break
                i += 1
            else:
                gross_R = sig * (c[n-1] - entry) / risk; orders = 2 if (mode == "tp2_full" or not tp1_done) else 3; exitpx = c[n-1]
            # slippage per CONTRACT-fill: entry fills CONTRACTS, exits fill CONTRACTS total -> ~2x position
            slip_d = slip_ * tick_ * pt_val_ * (2 * CONTRACTS)
            cost_d = comm_ * orders + slip_d
            cost_R = cost_d / (risk * pt_val_ * CONTRACTS)
            trades.append({
                "entry_time": entry_ts, "exit_time": ts[min(i, n-1)],
                "direction": "long" if sig == 1 else "short",
                "entry_price": round(entry, 2), "exit_price": round(float(exitpx), 2),
                "symbol": d.attrs.get("sym", "NQ"), "contracts": CONTRACTS,
                "gross_R": round(gross_R, 4), "net_R": round(gross_R - cost_R, 4),
                "mfe_R": round(mfe, 3), "mae_R": round(mae, 3),
                "risk_pts": round(risk, 2), "regime": entry_reg, "hold_bars": i - entry_i})
            pos = 0; i += 1
        else:
            i += 1
    return pd.DataFrame(trades)


def main():
    sym  = (sys.argv[1] if len(sys.argv) > 1 else "NQ").upper()
    tf   = sys.argv[2] if len(sys.argv) > 2 else "15m"
    sess = sys.argv[3] if len(sys.argv) > 3 else "full"
    con = hs_db.connect()
    bars = hs_db.bars(con, tf, sess, sym=sym)
    bars = _externals(con, bars, sym); con.close()
    mode = sys.argv[4] if len(sys.argv) > 4 else "scale_be"
    side = sys.argv[5] if len(sys.argv) > 5 else "both"
    flags = sys.argv[6:]
    strict = "strict" in flags
    entry_type = "orb" if "orb" in flags else "vwap_ema"
    print(f"backtest {sym} {tf} {sess} exit={mode} side={side} entry={entry_type} strict={strict}: {len(bars):,} bars ...")
    d = H.compute_state(bars, H.P()); d.attrs["sym"] = sym
    tr = backtest(d, mode, side, strict, entry_type)
    out = f"data/bt_{sym.lower()}_{tf}.csv"; tr.to_csv(out, index=False)
    nR = tr["net_R"]
    wins = tr[nR > 0]; losses = tr[nR <= 0]
    pf = wins["net_R"].sum() / abs(losses["net_R"].sum()) if len(losses) and losses["net_R"].sum() != 0 else float("inf")
    print(f"\nTRADES: {len(tr):,}  ({(tr.direction=='long').sum()} long / {(tr.direction=='short').sum()} short)")
    print(f"span: {tr.entry_time.min()} .. {tr.entry_time.max()}")
    print(f"win rate:        {100*len(wins)/max(len(tr),1):.1f}%")
    print(f"expectancy:      gross {tr.gross_R.mean():+.3f}R   NET {nR.mean():+.3f}R / trade")
    print(f"profit factor:   {pf:.2f}   (net)")
    print(f"total net:       {nR.sum():+.0f}R")
    print(f"avg win / loss:  {wins.net_R.mean():+.2f}R / {losses.net_R.mean():+.2f}R")
    print(f"wrote {out}")


if __name__ == "__main__":
    main()
