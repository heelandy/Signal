#!/usr/bin/env python3
"""
HIGHSTRIKE Phase 1 — Python reconcile harness (port of the V44 chart logic).

Recomputes V44's per-bar STATE from OHLCV so it can be diffed bar-by-bar against the
Pine (TradingView "Export chart data" CSV with the V44 reconcile plots). Identical bars
=> any mismatch is a pure logic difference (see hs_reconcile.py).

Ported faithfully (computable from OHLCV alone):
  indicators  atr14/7/28, DMI/ADX, EMA 9/20/50/21/trend, vol MA, bar features
  structure   pivots (HH/HL/LH/LL), st_state machine, BOS/CHoCH, live-break, struct_*_ok
  local regime, sweep (with-structure), triggers (VWAP/EMA reclaim + confluence)
  bias spine  dir_bias -> master_bias (N-bar confirm)
  macro       A/B/C/D regime (+ persistence), macro stand-down gate

TAKEN FROM EXPORT (request.security in Pine — TV's external data; pass as columns, else
proxies are computed for a standalone smoke test):
  vwap_sess, vwap_wk            (session/weekly VWAP)
  spy_close, spy_e20, spy_e50, spy_adx   (Daily macro trend ref = SPY)
  vix_sma5, vix_prev5           (Daily VIX 5d sma + close[5])
  htf_bull, htf_bear, sig_htf_bull, sig_htf_bear   (higher-TF bias/overlay)

Pine ta.* equivalents: ema=ewm(span,adjust=False); rma=ewm(alpha=1/n); atr=rma(TR);
dmi per TradingView; pivots = strict local extreme with left=right lookback.

CLI smoke test (uses DuckDB bars + vix_daily; proxies for SPY/HTF/VWAP):
    python hs_harness.py NQ 5m full 2022
Reconcile use: feed a TV-export DataFrame to compute_state(df, P).
"""
import sys
import numpy as np, pandas as pd
from dataclasses import dataclass, field, asdict


# ───────────────────────── Pine ta.* equivalents ─────────────────────────
def ema(s, n):  return s.ewm(span=n, adjust=False).mean()
def rma(s, n):  return s.ewm(alpha=1.0 / n, adjust=False).mean()
def sma(s, n):  return s.rolling(n, min_periods=1).mean()


def true_range(h, l, c):
    pc = c.shift(1)
    return pd.concat([h - l, (h - pc).abs(), (l - pc).abs()], axis=1).max(axis=1)


def dmi(h, l, c, length, adxlen):
    up, dn = h.diff(), -l.diff()
    plus_dm  = np.where((up > dn) & (up > 0), up, 0.0)
    minus_dm = np.where((dn > up) & (dn > 0), dn, 0.0)
    trur = rma(true_range(h, l, c), length)
    plus_di  = 100 * rma(pd.Series(plus_dm,  index=h.index), length) / trur
    minus_di = 100 * rma(pd.Series(minus_dm, index=h.index), length) / trur
    dx = 100 * (plus_di - minus_di).abs() / (plus_di + minus_di).replace(0, np.nan)
    return plus_di, minus_di, rma(dx.fillna(0), adxlen)


def pivots(values, left, right, kind, tie="strict"):
    """Pine ta.pivothigh/low with PER-BAR lookback (left==right==lookback[i]).
    tie='strict' = strict > / < on BOTH sides; tie='tv' = TradingView ta.pivothigh exactly (a TIE is
    allowed on the LEFT, strict on the RIGHT — so an equal-high plateau pivots at its first bar).
    Returns a Series: at the confirm bar (right bars after the pivot) the pivot price, else NaN."""
    v = values.to_numpy(); n = len(v); out = np.full(n, np.nan)
    lb = (left.to_numpy() if hasattr(left, "to_numpy") else np.full(n, left)).astype(int)
    # FAST PATH (perf review 2026-07): constant lookback -> vectorized rolling max/min. Identical
    # output to the bar loop below (regression-tested); the loop remains for the adaptive case.
    if n and (lb == lb[0]).all():
        L = int(lb[0])
        s = pd.Series(v)
        lm = (s.rolling(L).max() if kind == "high" else s.rolling(L).min()).shift(1).to_numpy()
        rrev = pd.Series(v[::-1])
        rm = ((rrev.rolling(L).max() if kind == "high" else rrev.rolling(L).min())
              .shift(1).to_numpy()[::-1])
        valid = ~np.isnan(lm) & ~np.isnan(rm)
        if kind == "high":
            okL = (v >= lm) if tie == "tv" else (v > lm)
            hit = valid & okL & (v > rm)
        else:
            okL = (v <= lm) if tie == "tv" else (v < lm)
            hit = valid & okL & (v < rm)
        centers = np.where(hit)[0]
        confirms = centers + L                      # pivot confirms L bars after the center
        keep = confirms < n
        out[confirms[keep]] = v[centers[keep]]
        return pd.Series(out, index=values.index)
    for i in range(n):
        L = lb[i]
        ci = i - L                      # candidate (center) index
        if ci - L < 0:
            continue
        c = v[ci]
        seg = v[ci - L: i + 1]          # L left + center + L right
        if kind == "high":
            okL = c >= seg[:L].max() if tie == "tv" else c > seg[:L].max()
            if okL and c > seg[L + 1:].max():
                out[i] = c
        else:
            okL = c <= seg[:L].min() if tie == "tv" else c < seg[:L].min()
            if okL and c < seg[L + 1:].min():
                out[i] = c
    return pd.Series(out, index=values.index)


# ───────────────────────────── parameters (V44 defaults) ─────────────────────────────
@dataclass
class P:
    struct_lb_fix: int = 5; struct_adaptive: bool = False   # adaptive OFF = exact reconcile baseline
    struct_tol_pct: float = 0.10
    pivot_tie: str = "strict"          # 'strict' (both sides) or 'tv' = TradingView ta.pivothigh (tie OK on left)
    # GAP-AWARE CHoCH (STRUC fix 2026-07): the old reset required a detected CROSSING bar
    # (close[i-1] on the other side of the swing) — in a fast move the swing reference itself steps
    # toward price via newly confirmed pivots, so the crossing bar can never exist and st_state
    # stayed UP below the last swing low (measured: 41 stale bars on the diagnostic tape).
    # True (default) = flip whenever price CLOSES beyond the last swing against the trend (the
    # st_state_prev guard keeps it once-only). False = the old crossing-only rule (research A/B).
    choch_gap_aware: bool = True
    momo_en: bool = True; momo_thresh: float = 0.3
    trend_ema_f: int = 21; trend_ema_s: int = 50; trendfilter_en: bool = True
    livebreak_en: bool = True
    local_adx_min: float = 20.0; local_atr_hi: float = 2.5
    sweep_en: bool = True; sweep_depth_atr: float = 0.3
    ob_body_atr: float = 0.3; ob_vol_mult: float = 0.7; ob_keep: int = 5; ob_dist_atr: float = 3.0  # order-block params (F41 robustness; defaults = V44, unchanged)
    w_htf: int = 2; w_trend: int = 2; w_dmi: int = 1; bias_thresh: int = 2; bias_confirm_bars: int = 2
    use_vwap2: bool = True; use_ema3: bool = True
    trig_confluence: str = "VWAP+EMA (both)"
    macro_en: bool = True; macro_standdown: bool = True
    vix_calm: float = 15.0; vix_volatile: float = 25.0; vix_extreme: float = 35.0
    spy_adx_min: float = 25.0; macro_persist_n: int = 3


# ───────────────────────────── the port ─────────────────────────────
def compute_state(df, p: P = P()):
    d = df.copy().reset_index(drop=True)
    h, l, c, o, vol = d["high"], d["low"], d["close"], d["open"], d["volume"]
    hlc3 = (h + l + c) / 3.0

    # --- indicators ---
    d["atr14"] = rma(true_range(h, l, c), 14)
    atr_fast, atr_slow = rma(true_range(h, l, c), 7), rma(true_range(h, l, c), 28)
    _, _, d["adx"] = dmi(h, l, c, 14, 14)
    diplus, diminus, _ = dmi(h, l, c, 14, 14)
    d["atr_pct"] = np.where(c > 0, d["atr14"] / c * 100.0, 0.0)
    d["ema9"], d["ema20"], d["ema50"] = ema(c, 9), ema(c, 20), ema(c, 50)
    trnd_f, trnd_s = ema(c, p.trend_ema_f), ema(c, p.trend_ema_s)
    d["trend_up"]   = (c > trnd_s) & (trnd_f > trnd_s)
    d["trend_down"] = (c < trnd_s) & (trnd_f < trnd_s)
    vol_ma = sma(vol, 20)
    c_body = (c - o).abs(); c_lwick = pd.concat([o, c], axis=1).min(axis=1) - l
    c_uwick = h - pd.concat([o, c], axis=1).max(axis=1)

    # adaptive (or fixed) pivot lookback
    vol_ratio = np.where((atr_fast > 0) & (atr_slow > 0), atr_fast / atr_slow, 1.0)
    lb_adp = np.clip(np.round(14.0 / np.maximum(vol_ratio, 0.5)), 5, 30).astype(int)
    struct_lb = pd.Series(lb_adp if p.struct_adaptive else p.struct_lb_fix, index=d.index)
    d["struct_lb"] = struct_lb

    # momentum veto
    momo = np.where(d["atr14"] > 0, (c - c.shift(5)) / d["atr14"], 0.0)
    momo_long_ok  = (~np.bool_(p.momo_en)) | (momo > p.momo_thresh)
    momo_short_ok = (~np.bool_(p.momo_en)) | (momo < -p.momo_thresh)

    # --- external inputs (from TV export) or proxies for smoke test ---
    d = _ensure_externals(d, hlc3, h, l, c)

    # --- pivots ---
    ph = pivots(h, struct_lb, struct_lb, "high", p.pivot_tie)
    pl = pivots(l, struct_lb, struct_lb, "low", p.pivot_tie)

    # --- structure state machine (bar loop = exact Pine sequential semantics) ---
    n = len(d)
    st_ph_last = st_ph_prev = st_pl_last = st_pl_prev = np.nan
    st_state = 0
    is_hh = np.zeros(n, bool); is_lh = np.zeros(n, bool)
    is_hl = np.zeros(n, bool); is_ll = np.zeros(n, bool)
    state_arr = np.zeros(n, int)
    bos_bull = np.zeros(n, bool); bos_bear = np.zeros(n, bool)
    choch_bull = np.zeros(n, bool); choch_bear = np.zeros(n, bool)
    choch_bull_bar = choch_bear_bar = live_up_bar = live_down_bar = -9999
    up_break = np.zeros(n, bool); dn_break = np.zeros(n, bool)
    choch_b_act = np.zeros(n, bool); choch_s_act = np.zeros(n, bool)
    sph_arr = np.full(n, np.nan); spl_arr = np.full(n, np.nan)   # per-bar running swing levels
    hv, lv = h.to_numpy(), l.to_numpy(); cv = c.to_numpy()
    phv, plv = ph.to_numpy(), pl.to_numpy()
    for i in range(n):
        st_state_prev = st_state
        if not np.isnan(phv[i]):
            if np.isnan(st_ph_last) or abs(phv[i] - st_ph_last) / st_ph_last * 100.0 >= p.struct_tol_pct:
                st_ph_prev, st_ph_last = st_ph_last, phv[i]
        if not np.isnan(plv[i]):
            if np.isnan(st_pl_last) or abs(plv[i] - st_pl_last) / st_pl_last * 100.0 >= p.struct_tol_pct:
                st_pl_prev, st_pl_last = st_pl_last, plv[i]
        hh = not np.isnan(st_ph_last) and not np.isnan(st_ph_prev) and st_ph_last > st_ph_prev
        lh = not np.isnan(st_ph_last) and not np.isnan(st_ph_prev) and st_ph_last < st_ph_prev
        hl = not np.isnan(st_pl_last) and not np.isnan(st_pl_prev) and st_pl_last > st_pl_prev
        ll = not np.isnan(st_pl_last) and not np.isnan(st_pl_prev) and st_pl_last < st_pl_prev
        is_hh[i], is_lh[i], is_hl[i], is_ll[i] = hh, lh, hl, ll
        # gap-aware claim guard (STRUC fix 2026-07): a state can only be (re)claimed while price is
        # on the right side of its own defining swing — UP requires close >= last swing low, DOWN
        # requires close <= last swing high. Without this, HH/HL pairs left over from the old leg
        # kept re-claiming UP every bar of a dump (the oscillating stale state).
        ok_up = (not p.choch_gap_aware) or np.isnan(st_pl_last) or cv[i] >= st_pl_last
        ok_dn = (not p.choch_gap_aware) or np.isnan(st_ph_last) or cv[i] <= st_ph_last
        if hh and hl and ok_up:   st_state = 1
        elif ll and lh and ok_dn: st_state = 2
        elif (hh and ll) or (hl and lh): st_state = 3
        if st_state == 1 and not np.isnan(st_ph_last) and hv[i] > st_ph_last and (i == 0 or hv[i-1] <= st_ph_last):
            bos_bull[i] = True
        if st_state == 2 and not np.isnan(st_pl_last) and lv[i] < st_pl_last and (i == 0 or lv[i-1] >= st_pl_last):
            bos_bear[i] = True
        if st_state_prev == 2 and not np.isnan(st_ph_last) and cv[i] > st_ph_last and \
                (p.choch_gap_aware or i == 0 or cv[i-1] <= st_ph_last):
            choch_bull[i] = True; st_state = 0
        if st_state_prev == 1 and not np.isnan(st_pl_last) and cv[i] < st_pl_last and \
                (p.choch_gap_aware or i == 0 or cv[i-1] >= st_pl_last):
            choch_bear[i] = True; st_state = 0
        if choch_bull[i]: choch_bull_bar = i
        if choch_bear[i]: choch_bear_bar = i
        choch_b_act[i] = (i - choch_bull_bar) <= 5
        choch_s_act[i] = (i - choch_bear_bar) <= 5
        live_up = not np.isnan(st_ph_last) and cv[i] > st_ph_last and (i == 0 or cv[i-1] <= st_ph_last)
        live_dn = not np.isnan(st_pl_last) and cv[i] < st_pl_last and (i == 0 or cv[i-1] >= st_pl_last)
        if live_dn or choch_bear[i]: live_down_bar = i
        if live_up or choch_bull[i]: live_up_bar = i
        up_break[i] = p.livebreak_en and (i - live_up_bar) <= 8
        dn_break[i] = p.livebreak_en and (i - live_down_bar) <= 8
        state_arr[i] = st_state
        sph_arr[i] = st_ph_last; spl_arr[i] = st_pl_last
    d["st_state"] = state_arr
    d["sph"] = sph_arr; d["spl"] = spl_arr     # running last swing high / low levels (for structure-anchored stops)
    for k, a in [("is_hh", is_hh), ("is_lh", is_lh), ("is_hl", is_hl), ("is_ll", is_ll),
                 ("bos_bull", bos_bull), ("bos_bear", bos_bear),
                 ("choch_bull", choch_bull), ("choch_bear", choch_bear)]:
        d[k] = a
    struct_long_ok  = ((state_arr == 1) | choch_b_act | up_break) & np.asarray(momo_long_ok)
    struct_short_ok = ((state_arr == 2) | choch_s_act | dn_break) & np.asarray(momo_short_ok)
    d["struct_long_ok"], d["struct_short_ok"] = struct_long_ok, struct_short_ok

    # --- Modules 3/5/6/7: sweep, order blocks, FVG, patterns (feed the grade) ---
    _zones_sweep_patterns(d, p, sph_arr, spl_arr, struct_long_ok, struct_short_ok)

    # --- local regime ---
    local_regime = np.where(d["atr_pct"] >= p.local_atr_hi, 3, np.where(d["adx"] >= p.local_adx_min, 1, 2))
    d["local_regime"] = local_regime

    # --- macro regime (uses exported SPY/VIX; persistence loop) ---
    _macro_regime(d, p)

    # --- bias spine ---
    dmi_bull = (diplus > diminus) & (d["adx"] >= p.local_adx_min)
    dmi_bear = (diminus > diplus) & (d["adx"] >= p.local_adx_min)
    dir_bias = (np.where(d["htf_bull"], p.w_htf, np.where(d["htf_bear"], -p.w_htf, 0))
                + (np.where(d["trend_up"], p.w_trend, np.where(d["trend_down"], -p.w_trend, 0)) if p.trendfilter_en else 0)
                + np.where(dmi_bull, p.w_dmi, np.where(dmi_bear, -p.w_dmi, 0)))
    d["dir_bias"] = dir_bias
    mb_raw = np.where(dir_bias >= p.bias_thresh, "LONG", np.where(dir_bias <= -p.bias_thresh, "SHORT", "NONE"))
    master = []; mb, pend, cnt = "NONE", "NONE", 0
    for r in mb_raw:
        if r == pend: cnt += 1
        else: pend, cnt = r, 1
        if cnt >= p.bias_confirm_bars: mb = r
        master.append(mb)
    d["master_bias"] = master

    # --- SCORING -> grade/floor (the V44 selectivity that the bare entry lacks) ---
    _scoring(d, p)

    # --- triggers (VWAP from export, EMA computed) + confluence ---
    vs, vw = d["vwap_sess"], d["vwap_wk"]
    e9, e20, e50 = d["ema9"], d["ema20"], d["ema50"]
    tvl = ((l <= vs) & (c > vs)) | (p.use_vwap2 & (l <= vw) & (c > vw))
    tvs = ((h >= vs) & (c < vs)) | (p.use_vwap2 & (h >= vw) & (c < vw))
    tel = ((l <= e9) & (c > e9)) | ((l <= e20) & (c > e20)) | (p.use_ema3 & (l <= e50) & (c > e50))
    tes = ((h >= e9) & (c < e9)) | ((h >= e20) & (c < e20)) | (p.use_ema3 & (h >= e50) & (c < e50))
    up_bar = c > o; dn_bar = c < o
    d["trig_vwap_long"], d["trig_vwap_short"] = tvl & up_bar, tvs & dn_bar
    d["trig_ema_long"],  d["trig_ema_short"]  = tel & up_bar, tes & dn_bar
    if p.trig_confluence == "Any (OR)":
        cl = d["trig_vwap_long"] | d["trig_ema_long"]; cs = d["trig_vwap_short"] | d["trig_ema_short"]
    else:   # VWAP+EMA both  (== >=2 with cons off)
        cl = d["trig_vwap_long"] & d["trig_ema_long"]; cs = d["trig_vwap_short"] & d["trig_ema_short"]
    d["trigger_long"], d["trigger_short"] = cl, cs

    return d


def _ensure_externals(d, hlc3, h, l, c):
    """Fill request.security-derived columns with proxies if the export didn't supply them."""
    if "vwap_sess" not in d:                                # daily-reset cumulative VWAP proxy
        date = pd.to_datetime(d["ts"]).dt.tz_convert("America/New_York").dt.date if "ts" in d else None
        grp = pd.Series(date).ne(pd.Series(date).shift()).cumsum() if date is not None else pd.Series(0, index=d.index)
        pv = (hlc3 * d["volume"]).groupby(grp).cumsum(); vv = d["volume"].groupby(grp).cumsum()
        d["vwap_sess"] = pv / vv.replace(0, np.nan)
        wgrp = (pd.to_datetime(d["ts"]).dt.isocalendar().week.diff().ne(0).cumsum()
                if "ts" in d else grp)
        d["vwap_wk"] = (hlc3 * d["volume"]).groupby(wgrp).cumsum() / d["volume"].groupby(wgrp).cumsum().replace(0, np.nan)
    for col, val in [("htf_bull", False), ("htf_bear", False),
                     ("sig_htf_bull", False), ("sig_htf_bear", False)]:
        if col not in d: d[col] = val
    for col in ["spy_close", "spy_e20", "spy_e50", "spy_adx", "vix_sma5", "vix_prev5"]:
        if col not in d: d[col] = np.nan
    return d


def _macro_regime(d, p):
    spy_up = d["spy_close"].notna() & (d["spy_close"] > d["spy_e20"]) & (d["spy_e20"] > d["spy_e50"])
    spy_dn = d["spy_close"].notna() & (d["spy_close"] < d["spy_e20"]) & (d["spy_e20"] < d["spy_e50"])
    spy_trend = (spy_up | spy_dn) & d["spy_adx"].notna() & (d["spy_adx"] >= p.spy_adx_min)
    d["spy_uptrend"], d["spy_downtrend"] = spy_up, spy_dn
    vix = d["vix_sma5"]; vix_prev = d["vix_prev5"]
    chg = np.where(vix_prev.notna() & (vix_prev > 0), (vix - vix_prev) / vix_prev * 100.0, 0.0)
    raw = np.full(len(d), "—", dtype=object)
    vix_v = vix.to_numpy(float)                 # numpy views: the per-bar .iloc[] lookups were the
    st_v = spy_trend.to_numpy()                 # hottest line in compute_state (perf review 2026-07)
    for i in range(len(d)):
        v = vix_v[i]
        if v != v: continue
        if v >= p.vix_extreme: raw[i] = "D"
        elif v >= p.vix_volatile or chg[i] >= 30.0: raw[i] = "C"
        elif v < p.vix_calm and st_v[i]: raw[i] = "A"
        elif v < p.vix_volatile and not st_v[i]: raw[i] = "B"
        elif st_v[i]: raw[i] = "A"
        else: raw[i] = "B"
    conf = "—"; pend = "—"; cnt = 0; out = []
    for i in range(len(d)):
        need = 0 if raw[i] == "D" else (p.macro_persist_n * 2 if (conf == "C" and raw[i] == "A") else p.macro_persist_n)
        if raw[i] == "D": conf = pend = "D"; cnt = need
        elif raw[i] == pend:
            cnt += 1
            if cnt >= need: conf = raw[i]
        else: pend = raw[i]; cnt = 1
        out.append(conf if conf != "—" else raw[i])
    d["macro_regime"] = out
    reg = pd.Series(out)
    allow = ~((p.macro_en) & (((reg == "D")) | ((reg == "B"))))   # block_d + block_b_rng both default True
    d["macro_allow_trades"] = allow.to_numpy()
    d["macro_long_ok"]  = (~np.bool_(p.macro_en)) | (~np.bool_(p.macro_standdown)) | (~spy_dn.to_numpy())
    d["macro_short_ok"] = (~np.bool_(p.macro_en)) | (~np.bool_(p.macro_standdown)) | (~spy_up.to_numpy())
    return d


def _zones_sweep_patterns(d, p, sph, spl, slo, sso):
    """Module 3 sweep + Module 5 OB + Module 6 FVG (bar loop) + Module 7 patterns (vectorized)."""
    h, l, c, o = (d[k].to_numpy() for k in ("high", "low", "close", "open"))
    atr = d["atr14"].to_numpy(); vol = d["volume"].to_numpy()
    vma = sma(d["volume"], 20).to_numpy(); cbody = np.abs(c - o)
    lb = d["struct_lb"].to_numpy().astype(int); n = len(d)
    at_bull = np.zeros(n, bool); at_bear = np.zeros(n, bool)
    in_bull_ob = np.zeros(n, bool); in_bear_ob = np.zeros(n, bool)
    bsa = np.zeros(n, bool); ssa = np.zeros(n, bool)
    bull_obs = []; bear_obs = []; bull_fvg = []; bear_fvg = []
    bsweep_b = bsweep2 = -9999; brsweep_b = -9999
    # precomputed rolling extremes (perf review 2026-07): replaces per-bar np.max/np.min slices.
    # roll_hi[i] == max(h[i-L:i]) when i >= L+1 (the loop's guard), NaN otherwise — L constant here
    # in practice (struct_lb fixed); recompute per-bar only if lb varies.
    lb_const = n and (lb == lb[0]).all()
    if lb_const:
        L0 = int(lb[0])
        _rh = pd.Series(h).rolling(L0).max().shift(1).to_numpy()
        _rl = pd.Series(l).rolling(L0).min().shift(1).to_numpy()
    for i in range(n):
        ai = atr[i] if not np.isnan(atr[i]) else 0.0
        vm = vma[i] if not np.isnan(vma[i]) else 0.0
        ob_strong = cbody[i] >= ai * p.ob_body_atr and vol[i] >= vm * p.ob_vol_mult
        if i >= 1 and c[i] > h[i-1] and c[i-1] < o[i-1] and ob_strong:
            bull_obs.append((o[i-1], l[i-1]));  bull_obs[:] = bull_obs[-p.ob_keep:]
        if i >= 1 and c[i] < l[i-1] and c[i-1] > o[i-1] and ob_strong:
            bear_obs.append((h[i-1], o[i-1]));  bear_obs[:] = bear_obs[-p.ob_keep:]
        bull_obs[:] = [b for b in bull_obs if not (c[i] < b[1] or abs(c[i] - b[0]) > ai * p.ob_dist_atr)]
        bear_obs[:] = [b for b in bear_obs if not (c[i] > b[0] or abs(c[i] - b[1]) > ai * p.ob_dist_atr)]
        in_bull_ob[i] = any(l[i] <= t and h[i] >= bt for t, bt in bull_obs)
        in_bear_ob[i] = any(l[i] <= t and h[i] >= bt for t, bt in bear_obs)
        if i >= 2 and l[i] > h[i-2]: bull_fvg.append((l[i], h[i-2])); bull_fvg[:] = bull_fvg[-8:]
        if i >= 2 and h[i] < l[i-2]: bear_fvg.append((l[i-2], h[i])); bear_fvg[:] = bear_fvg[-8:]
        bull_fvg[:] = [f for f in bull_fvg if not c[i] < f[1]]
        bear_fvg[:] = [f for f in bear_fvg if not c[i] > f[0]]
        in_bf = any(l[i] <= t and h[i] >= bt for t, bt in bull_fvg)
        in_sf = any(l[i] <= t and h[i] >= bt for t, bt in bear_fvg)
        at_bull[i] = in_bull_ob[i] or in_bf; at_bear[i] = in_bear_ob[i] or in_sf
        L = lb[i]
        if lb_const:
            roll_hi = _rh[i] if i >= L + 1 else np.nan
            roll_lo = _rl[i] if i >= L + 1 else np.nan
        else:
            roll_hi = np.max(h[i-L:i]) if i >= L + 1 else np.nan
            roll_lo = np.min(l[i-L:i]) if i >= L + 1 else np.nan
        swing_lo = spl[i] if not np.isnan(spl[i]) else roll_lo
        swing_hi = sph[i] if not np.isnan(sph[i]) else roll_hi
        smin = ai * p.sweep_depth_atr
        if p.sweep_en and not np.isnan(swing_lo) and l[i] < swing_lo - smin and c[i] > swing_lo and slo[i]:
            bsweep_b = i
        if p.sweep_en and not np.isnan(swing_hi) and h[i] > swing_hi + smin and c[i] < swing_hi and sso[i]:
            brsweep_b = i
        win = min(L, 8)
        bsa[i] = (i - bsweep_b) <= win; ssa[i] = (i - brsweep_b) <= win
    d["at_bull_zone"], d["at_bear_zone"] = at_bull, at_bear
    d["in_bull_ob"], d["in_bear_ob"] = in_bull_ob, in_bear_ob
    d["bull_sweep_active"], d["bear_sweep_active"] = bsa, ssa
    # patterns (Morning/Evening Star), active for 4 bars
    a = d["atr14"]; cb = np.abs(c - o)
    c1b = np.abs(pd.Series(c).shift(1) - pd.Series(o).shift(1))
    c2b = np.abs(pd.Series(c).shift(2) - pd.Series(o).shift(2))
    msmid = (pd.Series(o).shift(2) + pd.Series(c).shift(2)) / 2.0
    ms = ((pd.Series(c).shift(2) < pd.Series(o).shift(2)) & (c2b >= a * 0.8) & (c1b <= a * 0.4)
          & (c > o) & (cb >= a * 0.6) & (c >= msmid))
    es = ((pd.Series(c).shift(2) > pd.Series(o).shift(2)) & (c2b >= a * 0.8) & (c1b <= a * 0.4)
          & (c < o) & (cb >= a * 0.6) & (c <= msmid))
    d["ms_active"] = ms.fillna(False).rolling(5, min_periods=1).max().astype(bool).to_numpy()
    d["es_active"] = es.fillna(False).rolling(5, min_periods=1).max().astype(bool).to_numpy()


def _scoring(d, p):
    slo = np.asarray(d["struct_long_ok"]); sso = np.asarray(d["struct_short_ok"])
    mb = np.asarray(d["master_bias"]); reg = np.asarray(d["macro_regime"])
    spy_up = d["spy_uptrend"].to_numpy(); spy_dn = d["spy_downtrend"].to_numpy()
    sL = (np.where(slo, 2, 0) + np.where(mb == "LONG", 2, np.where(mb == "NONE", 1, 0))
          + np.where(d["at_bull_zone"], np.where(d["in_bull_ob"], 2, 1), 0)
          + np.where(d["bull_sweep_active"], 2, 0) + np.where(d["ms_active"], 1, 0)
          + np.where((reg == "A") & spy_up, 1, 0))
    sS = (np.where(sso, 2, 0) + np.where(mb == "SHORT", 2, np.where(mb == "NONE", 1, 0))
          + np.where(d["at_bear_zone"], np.where(d["in_bear_ob"], 2, 1), 0)
          + np.where(d["bear_sweep_active"], 2, 0) + np.where(d["es_active"], 1, 0)
          + np.where((reg == "A") & spy_dn, 1, 0))
    long_score = np.where(slo, sL, 0); short_score = np.where(sso, sS, 0)
    long_floor = np.where(mb == "LONG", 6, 9); short_floor = np.where(mb == "SHORT", 6, 9)
    gL = np.where(long_score >= 9, "A+", np.where(long_score >= 7, "A", "B"))
    gS = np.where(short_score >= 9, "A+", np.where(short_score >= 7, "A", "B"))
    lf = np.where(slo & (long_score >= long_floor), gL, "")
    sf = np.where(sso & (short_score >= short_floor), gS, "")
    only_a = (reg == "C") & p.macro_en                       # macro_only_a_in_c default True
    lf = np.where(only_a & (lf != "A+"), "", lf)
    sf = np.where(only_a & (sf != "A+"), "", sf)
    d["long_score"], d["short_score"] = long_score, short_score
    d["lf_raw"], d["sf_raw"] = lf, sf
    d["grade_long_ok"], d["grade_short_ok"] = (lf != ""), (sf != "")


# ───────────────────────────── CLI smoke test ─────────────────────────────
def main():
    sym  = sys.argv[1] if len(sys.argv) > 1 else "NQ"
    tf   = sys.argv[2] if len(sys.argv) > 2 else "5m"
    sess = sys.argv[3] if len(sys.argv) > 3 else "full"
    year = int(sys.argv[4]) if len(sys.argv) > 4 else None
    import hs_db
    con = hs_db.connect()
    bars = hs_db.bars(con, tf, sess, sym=sym, year=year)
    # attach Daily VIX (sma5 + close[5]) as the macro vol input
    vix = con.execute("SELECT date, sma5, close FROM vix_daily ORDER BY date").df()
    vix["date"] = pd.to_datetime(vix["date"]); vix["prev5"] = vix["close"].shift(5)
    bars["date"] = pd.to_datetime(bars["ts"]).dt.tz_convert("America/New_York").dt.normalize().dt.tz_localize(None)
    bars = bars.merge(vix.rename(columns={"sma5": "vix_sma5", "prev5": "vix_prev5"})[["date", "vix_sma5", "vix_prev5"]],
                      on="date", how="left")
    con.close()
    print(f"harness smoke test: {sym} {tf} {sess} {year or 'all'}  ({len(bars):,} bars)")
    out = compute_state(bars, P())
    print("\nstate counts:")
    print(f"  st_state:        {dict(pd.Series(out['st_state']).value_counts().sort_index())}")
    print(f"  HH/HL/LH/LL:     {int(out.is_hh.sum())}/{int(out.is_hl.sum())}/{int(out.is_lh.sum())}/{int(out.is_ll.sum())}")
    print(f"  BOS bull/bear:   {int(out.bos_bull.sum())}/{int(out.bos_bear.sum())}")
    print(f"  CHoCH bull/bear: {int(out.choch_bull.sum())}/{int(out.choch_bear.sum())}")
    print(f"  macro regime:    {dict(pd.Series(out['macro_regime']).value_counts())}")
    print(f"  master_bias:     {dict(pd.Series(out['master_bias']).value_counts())}")
    print(f"  trigger L/S:     {int(out.trigger_long.sum())}/{int(out.trigger_short.sum())}")
    print(f"  struct_ok L/S:   {int(out.struct_long_ok.sum())}/{int(out.struct_short_ok.sum())}")
    keep = ["ts", "open", "high", "low", "close", "st_state", "is_hh", "is_hl", "is_lh", "is_ll",
            "bos_bull", "bos_bear", "choch_bull", "choch_bear", "macro_regime", "dir_bias",
            "master_bias", "trigger_long", "trigger_short", "struct_long_ok", "struct_short_ok"]
    out[keep].to_parquet(f"data/harness_{sym.lower()}_{tf}_{sess}.parquet", index=False)
    print(f"\nwrote data/harness_{sym.lower()}_{tf}_{sess}.parquet")


if __name__ == "__main__":
    main()
