#!/usr/bin/env python3
"""PROBABLE LIQUIDITY ZONE engine + bounce-vs-reversal state machine (user research 2026-07-03,
'Research over probabilistic area'). PROMOTED into the BOT package 2026-07-06 (repo-hygiene item:
production `liquidity.py` (F67 clean-air, GRADUATED) must not import from research/). This file is
now the single source of truth; `research/orb_liquidity_zones.py` is a thin re-export shim so the
research drivers (zone_bounce, orb_zones_additive, orb_zone_entries) keep working unchanged.

From 1m OHLCV alone we infer WHERE entries/stops/resting liquidity PROBABLY sit — never claiming
to see actual pending orders (that needs L2/MBO data). All outputs use the doc's wording rule:
PROBABLE BUY/SELL LIQUIDITY · POTENTIAL STOP CLUSTER · POTENTIAL BREAKOUT/RETEST ENTRY.

Evidence detectors (each causal, window = tail of the one 1m array):
    pivot clusters · equal highs/lows · rejection/absorption bars · OR + session levels
    (OR H/M/L, prev-day H/L/C, session VWAP) · volume-by-price nodes (POC/HVN/LVN approx)
Zones are MERGED (overlap within an ATR-scaled tolerance) and SCORED 0-100:

    L = 0.25*T + 0.20*V + 0.20*R + 0.15*S + 0.10*H + 0.10*A          (doc's 'useful starting score')
        T touches · V relative volume · R rejection strength · S structural importance
        H higher-window alignment · A age/recency
    (the doc also lists two variants swapping S/H/A/M — WEIGHTS is a dict, tune per gauntlet)
    80-100 MAJOR · 60-79 STRONG · 40-59 MODERATE · <40 WEAK

REVERSAL machine (mirrored): TREND_DOWN -> DOWN_DECELERATING -> POSSIBLE_BOTTOM ->
BULLISH_REVERSAL_CANDIDATE -> CONFIRMED | FAILED_BOUNCE, on the doc's six checks (slope
deceleration, no new low, 2-of-3 close persistence, micro structure break, retracement depth,
recovery efficiency). Candidate/confirm respect the noise-control rule (2 of last 3 evaluations).

    python BOT/bot/strategy/liquidity_zones.py --selftest      # synthetic checks (run anywhere)
    python BOT/bot/strategy/liquidity_zones.py NQ ES           # data-drive: zone hit-rate vs
                                                               # random-level control, per symbol
"""
import os
import sys
from dataclasses import dataclass, field

import numpy as np
import pandas as pd

WEIGHTS = {"T": 0.25, "V": 0.20, "R": 0.20, "S": 0.15, "H": 0.10, "A": 0.10}
WINDOWS = (5, 15, 30, 60, 240)          # 1m-bar windows (micro .. broader intraday)
TOUCH_MIN = 2                           # touches to form a zone (doc: >= 2)
WICK_BODY = 2.0                         # rejection bar: wick >= 2x body
REL_VOL = 1.5                           # rejection bar: volume >= 1.5x rolling average
MERGE_ATR = 0.25                        # merge zones closer than 0.25 * ATR(1m)
HALF_W_ATR = 0.15                       # half-width of a level-seeded zone, in ATR
AGE_HALF_LIFE = 120.0                   # bars: recency decay half-life for A

SCORE_BANDS = ((80, "MAJOR"), (60, "STRONG"), (40, "MODERATE"), (0, "WEAK"))


def _label(score: float) -> str:
    for lo, name in SCORE_BANDS:
        if score >= lo:
            return name
    return "WEAK"


@dataclass
class Zone:
    """One probable liquidity zone (doc's zone data structure)."""
    low: float
    high: float
    kind: str                       # "PROBABLE BUY LIQUIDITY" | "PROBABLE SELL LIQUIDITY"
    evidence: list = field(default_factory=list)   # ("pivot_high", "eq_low", "or_high", ...)
    touches: int = 0
    rel_volume: float = 0.0
    rejection: float = 0.0          # 0-1 mean rejection strength at the zone
    structural: float = 0.0         # 0-1 structural importance (session/OR/pivot > eq > vol node)
    windows: set = field(default_factory=set)
    last_touch_age: float = 1e9     # bars since last test (recency)
    score: float = 0.0

    @property
    def center(self) -> float:
        return (self.low + self.high) / 2.0

    def to_dict(self, sym: str = "?", i: int = 0) -> dict:
        tags = [self.kind]
        if "eq_high" in self.evidence:
            tags.append("POTENTIAL STOP CLUSTER above")   # short stops / breakout buys above eq highs
        if "eq_low" in self.evidence:
            tags.append("POTENTIAL STOP CLUSTER below")   # long stops / breakdown sells below eq lows
        return {"zone_id": f"{sym}_Z{i:03d}", "type": self.kind, "tags": tags,
                "low": round(self.low, 4), "high": round(self.high, 4),
                "center": round(self.center, 4), "touches": int(self.touches),
                "relative_volume": round(self.rel_volume, 2),
                "rejection_score": round(self.rejection, 2),
                "windows": sorted(f"{w}M" for w in self.windows),
                "evidence": sorted(set(self.evidence)),
                "liquidity_score": round(self.score, 1), "label": _label(self.score),
                "status": "ACTIVE"}


# ───────────────────────── evidence detectors (all causal) ─────────────────────────

def _atr(h, l, c, n=14):
    tr = np.maximum(h[1:] - l[1:], np.maximum(np.abs(h[1:] - c[:-1]), np.abs(l[1:] - c[:-1])))
    return float(pd.Series(tr).ewm(alpha=1 / n, adjust=False).mean().iloc[-1]) if len(tr) else 0.0


def _pivots(x: np.ndarray, lb: int, high: bool):
    """Indices of strict swing extremes (both sides, confirmed lb bars late — causal)."""
    out = []
    for i in range(lb, len(x) - lb):
        seg = x[i - lb:i + lb + 1]
        if (high and x[i] == seg.max() and (seg < x[i]).sum() == 2 * lb) or \
           (not high and x[i] == seg.min() and (seg > x[i]).sum() == 2 * lb):
            out.append(i)
    return out


def _seed(level, atr, kind, ev, touch_i, n):
    hw = HALF_W_ATR * atr
    z = Zone(low=level - hw, high=level + hw, kind=kind, evidence=[ev])
    z.touches = 1
    z.last_touch_age = n - 1 - touch_i if touch_i is not None else 1e9
    return z


def window_zones(o, h, l, c, v, atr, lb: int = 3) -> list:
    """All evidence zones from ONE window of 1m bars (side assigned vs the LAST close)."""
    n = len(c)
    px = c[-1]
    zones = []
    side = lambda lv: "PROBABLE SELL LIQUIDITY" if lv >= px else "PROBABLE BUY LIQUIDITY"
    # 1) swing pivot clusters
    for i in _pivots(h, lb, True):
        z = _seed(h[i], atr, side(h[i]), "pivot_high", i, n); z.structural = 1.0; zones.append(z)
    for i in _pivots(l, lb, False):
        z = _seed(l[i], atr, side(l[i]), "pivot_low", i, n); z.structural = 1.0; zones.append(z)
    # 2) equal highs / equal lows (near-equal extremes within 0.1 ATR)
    tol = 0.10 * atr
    for x, ev in ((h, "eq_high"), (l, "eq_low")):
        order = np.argsort(x)
        run = [order[0]]
        for j in order[1:]:
            if abs(x[j] - x[run[-1]]) <= tol:
                run.append(j)
            else:
                if len(run) >= TOUCH_MIN and (ev == "eq_high" and x[run[0]] >= np.percentile(h, 80)
                                              or ev == "eq_low" and x[run[0]] <= np.percentile(l, 20)):
                    lv = float(np.mean(x[run]))
                    z = _seed(lv, atr, side(lv), ev, max(run), n)
                    z.touches = len(run); z.structural = 0.6
                    zones.append(z)
                run = [j]
    # 3) rejection / absorption bars (long wick + high relative volume)
    if n >= 20:
        v_avg = pd.Series(v).rolling(20, min_periods=5).mean().to_numpy()
        body = np.abs(c - o)
        up_w = h - np.maximum(o, c)
        dn_w = np.minimum(o, c) - l
        for i in range(5, n):
            if v_avg[i] > 0 and v[i] >= REL_VOL * v_avg[i]:
                if dn_w[i] >= WICK_BODY * max(body[i], 1e-9):       # absorbed selling at the tail
                    z = _seed(l[i], atr, side(l[i]), "absorption_low", i, n)
                    z.rejection = min(dn_w[i] / max(body[i], 1e-9) / 3.0, 1.0)
                    z.rel_volume = v[i] / v_avg[i]; zones.append(z)
                if up_w[i] >= WICK_BODY * max(body[i], 1e-9):
                    z = _seed(h[i], atr, side(h[i]), "absorption_high", i, n)
                    z.rejection = min(up_w[i] / max(body[i], 1e-9) / 3.0, 1.0)
                    z.rel_volume = v[i] / v_avg[i]; zones.append(z)
    # 4) volume-by-price nodes (approx: bar volume spread uniformly low->high)
    if n >= 30 and atr > 0:
        bw = max(0.10 * atr, 1e-6)
        lo_all, hi_all = float(l.min()), float(h.max())
        nb = max(int((hi_all - lo_all) / bw) + 1, 1)
        vol = np.zeros(nb)
        for i in range(n):
            a = int((l[i] - lo_all) / bw); b = int((h[i] - lo_all) / bw)
            k = max(b - a + 1, 1)
            vol[a:b + 1] += v[i] / k
        if vol.sum() > 0:
            poc = int(np.argmax(vol))
            lvl = lo_all + (poc + 0.5) * bw
            z = _seed(lvl, atr, side(lvl), "poc", None, n)
            z.structural = 0.3; z.rel_volume = float(vol[poc] / max(vol.mean(), 1e-9))
            zones.append(z)
            hvn_cut = np.percentile(vol[vol > 0], 80)
            for j in np.where(vol >= hvn_cut)[0]:
                if j != poc:
                    lv = lo_all + (j + 0.5) * bw
                    z = _seed(lv, atr, side(lv), "hvn", None, n)
                    z.structural = 0.3; z.rel_volume = float(vol[j] / max(vol.mean(), 1e-9))
                    zones.append(z)
    return zones


def session_zones(bars: pd.DataFrame, atr: float, or_minutes: int = 30) -> list:
    """OR H/M/L of the CURRENT session + prev-day H/L/C + session VWAP (doc §4/§5)."""
    tcol = "ts_et" if "ts_et" in bars.columns else "ts"
    ts = pd.to_datetime(bars[tcol])
    if ts.dt.tz is None:
        ts = ts.dt.tz_localize("UTC")
    et = ts.dt.tz_convert("America/New_York")
    day = et.dt.date
    px = float(bars["close"].iloc[-1])
    side = lambda lv: "PROBABLE SELL LIQUIDITY" if lv >= px else "PROBABLE BUY LIQUIDITY"
    zones = []
    today = day.iloc[-1]
    cur = bars.loc[(day == today).to_numpy()]
    cur_et = et[(day == today).to_numpy()]
    mins = cur_et.dt.hour * 60 + cur_et.dt.minute
    orb = cur.loc[((mins >= 570) & (mins < 570 + or_minutes)).to_numpy()]
    n = len(bars)
    if len(orb):
        oh, ol = float(orb["high"].max()), float(orb["low"].min())
        for lv, ev in ((oh, "or_high"), (ol, "or_low"), ((oh + ol) / 2, "or_mid")):
            z = _seed(lv, atr, side(lv), ev, None, n); z.structural = 1.0; zones.append(z)
    prev = bars.loc[(day < today).to_numpy()]
    if len(prev):
        pd_day = day[(day < today).to_numpy()].iloc[-1]
        pv = bars.loc[(day == pd_day).to_numpy()]
        for lv, ev in ((float(pv["high"].max()), "pd_high"), (float(pv["low"].min()), "pd_low"),
                       (float(pv["close"].iloc[-1]), "pd_close")):
            z = _seed(lv, atr, side(lv), ev, None, n); z.structural = 1.0; zones.append(z)
    if len(cur) and "volume" in bars.columns and float(cur["volume"].sum()) > 0:
        tp = (cur["high"] + cur["low"] + cur["close"]).to_numpy(float) / 3.0
        vw = float((tp * cur["volume"].to_numpy(float)).sum() / cur["volume"].sum())
        z = _seed(vw, atr, side(vw), "session_vwap", None, n); z.structural = 0.8; zones.append(z)
    return zones


# ───────────────────────── merge + score ─────────────────────────

def merge_zones(zones: list, atr: float) -> list:
    if not zones:
        return []
    pad = MERGE_ATR * atr
    zones = sorted(zones, key=lambda z: z.center)
    out = [zones[0]]
    for z in zones[1:]:
        m = out[-1]
        if z.low - pad <= m.high:                      # overlap (padded) -> merge
            m.low, m.high = min(m.low, z.low), max(m.high, z.high)
            m.touches += z.touches
            m.evidence += z.evidence
            m.rejection = max(m.rejection, z.rejection)
            m.rel_volume = max(m.rel_volume, z.rel_volume)
            m.structural = max(m.structural, z.structural)
            m.windows |= z.windows
            m.last_touch_age = min(m.last_touch_age, z.last_touch_age)
        else:
            out.append(z)
    return out


def score_zones(zones: list, n_windows: int) -> list:
    for z in zones:
        T = min(z.touches / 5.0, 1.0)
        V = min(max(z.rel_volume, 0.0) / 2.0, 1.0)
        R = min(max(z.rejection, 0.0), 1.0)
        S = min(max(z.structural, 0.0), 1.0)
        H = (len(z.windows) - 1) / max(n_windows - 1, 1) if z.windows else 0.0
        A = float(np.exp(-min(z.last_touch_age, 1e6) * np.log(2) / AGE_HALF_LIFE))
        z.score = 100.0 * (WEIGHTS["T"] * T + WEIGHTS["V"] * V + WEIGHTS["R"] * R
                           + WEIGHTS["S"] * S + WEIGHTS["H"] * H + WEIGHTS["A"] * A)
    return sorted(zones, key=lambda z: -z.score)


def detect_zones(bars_1m: pd.DataFrame, windows=WINDOWS, sym: str = "?") -> list:
    """Full pipeline on the single 1m array: per-window evidence + session levels ->
    merged, scored, ranked PROBABLE zones (list of dicts, best first). Causal: uses
    completed bars only — call it after each 1m close (doc cadence)."""
    if bars_1m is None or len(bars_1m) < 10:
        return []
    o = bars_1m["open"].to_numpy(float); h = bars_1m["high"].to_numpy(float)
    l = bars_1m["low"].to_numpy(float); c = bars_1m["close"].to_numpy(float)
    v = (bars_1m["volume"].to_numpy(float) if "volume" in bars_1m.columns
         else np.ones(len(c)))
    atr = _atr(h, l, c)
    if not np.isfinite(atr) or atr <= 0:
        return []
    zones = []
    for w in windows:
        if len(c) < w:
            continue
        lb = 2 if w <= 15 else 3
        for z in window_zones(o[-w:], h[-w:], l[-w:], c[-w:], v[-w:], atr, lb=lb):
            z.windows = {w}
            zones.append(z)
    zones += session_zones(bars_1m, atr)
    merged = merge_zones(zones, atr)
    ranked = score_zones(merged, len(windows))
    return [z.to_dict(sym, i) for i, z in enumerate(ranked)]


# ───────────────────────── bounce vs reversal state machine (mirrored) ─────────────────────────

class ReversalStateMachine:
    """Doc's six-check machine, exact long/short mirror via sign (+1 = detecting BULLISH
    reversal of a DOWN trend; -1 = bearish mirror). Feed one COMPLETED 1m bar per update().
    Candidate/confirm require persistence (2 of the last 3 evaluations — noise control)."""
    STATES = ("TREND", "DECELERATING", "POSSIBLE_TURN", "REVERSAL_CANDIDATE",
              "REVERSAL_CONFIRMED", "FAILED_BOUNCE", "NEUTRAL")

    def __init__(self, sign: int = 1, n_slope: int = 8, recovery_min: float = 0.20):
        self.sign = 1 if sign >= 0 else -1              # +1 watches for the bullish turn
        self.n = n_slope
        self.recovery_min = recovery_min
        self.state = "NEUTRAL"
        self.o, self.h, self.l, self.c = [], [], [], []
        self.leg_ext = None                             # extreme of the down(up) leg
        self.leg_start = None                           # where the leg began
        self.micro_pivot = None                         # last lower-high (higher-low mirrored)
        self._votes = []                                # persistence window (2 of 3)

    def _slope(self, seg):
        if len(seg) < 3:
            return 0.0
        x = np.arange(len(seg), dtype=float)
        return float(np.polyfit(x, np.asarray(seg, float), 1)[0])

    def update(self, o, h, l, c) -> str:
        s = self.sign
        self.o.append(o); self.h.append(h); self.l.append(l); self.c.append(c)
        if len(self.c) < self.n + 3:                    # need one recent window + a stub of history
            return self.state
        cc = np.array(self.c[-4 * self.n:], float)
        hh = np.array(self.h[-4 * self.n:], float)
        ll = np.array(self.l[-4 * self.n:], float)
        adverse = ll if s == 1 else hh                  # the trend-direction extreme series
        slope_old = self._slope(cc[-2 * self.n:-self.n])
        slope_rec = self._slope(cc[-self.n:])
        dn_old = s * slope_old < 0                      # established leg against `s`
        dn_now = s * slope_rec < 0
        # leg bookkeeping (extreme + start of the move against `s`)
        ext = float(adverse.min() if s == 1 else adverse.max())
        if self.leg_ext is None or s * (ext - self.leg_ext) < 0:
            self.leg_ext = ext
        favor = hh if s == 1 else ll
        self.leg_start = float(favor.max() if s == 1 else favor.min())
        # micro pivot against the recovery: last lower-high (mirror: higher-low), lb=2.
        # FROZEN once a candidate exists — the hold test is against the BROKEN pivot.
        if self.state not in ("REVERSAL_CANDIDATE", "REVERSAL_CONFIRMED"):
            piv = _pivots(hh if s == 1 else ll, 2, s == 1)
            if piv:
                self.micro_pivot = float((hh if s == 1 else ll)[piv[-1]])
        # six checks (doc) — all mirrored through s
        decel = dn_old and abs(slope_old) - abs(slope_rec) > 0
        no_new_ext = s * (adverse[-1] - self.leg_ext) >= 0 and s * (adverse[-2] - self.leg_ext) >= 0
        d = np.diff(cc[-4:])
        persist = int((s * d > 0).sum()) >= 2                  # 2 of last 3 closes with the turn
        slope_pos = s * slope_rec > 0
        micro_break = self.micro_pivot is not None and s * (cc[-1] - self.micro_pivot) > 0
        rng = abs(self.leg_start - self.leg_ext)
        recovery = s * (cc[-1] - self.leg_ext) / rng if rng > 0 else 0.0
        deltas = np.abs(np.diff(cc[-self.n:]))
        eff = abs(cc[-1] - cc[-self.n]) / deltas.sum() if deltas.sum() > 0 else 0.0
        new_ext = s * (adverse[-1] - self.leg_ext) < 0
        # state transitions
        st = self.state
        if st in ("NEUTRAL", "TREND"):
            if decel and st == "TREND":
                st = "DECELERATING"                     # the leg is slowing (doc check 1)
            elif dn_now or (dn_old and dn_now):
                st = "TREND"
        elif st == "DECELERATING":
            if new_ext:
                st = "TREND"
            elif no_new_ext and persist and slope_pos:
                st = "POSSIBLE_TURN"
        elif st == "POSSIBLE_TURN":
            if new_ext:
                st = "TREND"; self._votes = []
            else:
                self._votes.append(micro_break and eff >= 0.35)
                if sum(self._votes[-3:]) >= 2:                 # noise control: 2 of last 3
                    st = "REVERSAL_CANDIDATE"; self._votes = []
        elif st == "REVERSAL_CANDIDATE":
            if new_ext or (self.micro_pivot is not None and s * (cc[-1] - self.micro_pivot) < 0) \
                    or eff < 0.15:
                st = "FAILED_BOUNCE"
            else:
                self._votes.append(recovery >= self.recovery_min and micro_break)
                if sum(self._votes[-3:]) >= 2:
                    st = "REVERSAL_CONFIRMED"; self._votes = []
        elif st == "FAILED_BOUNCE":
            st = "TREND" if new_ext else st
        # REVERSAL_CONFIRMED is terminal for this leg (caller resets/flips sign)
        self.state = st
        return st


# ───────────────────────── self-test (synthetic — runs anywhere) ─────────────────────────

def _mk(closes, vol=None, spread=0.05, start="2026-06-01 09:30"):
    c = np.asarray(closes, float)
    op = np.concatenate([[c[0]], c[:-1]])
    return pd.DataFrame({"ts_et": pd.date_range(start, periods=len(c), freq="1min",
                                                tz="America/New_York"),
                         "open": op, "high": np.maximum(op, c) + spread,
                         "low": np.minimum(op, c) - spread, "close": c,
                         "volume": np.asarray(vol, float) if vol is not None
                                   else np.full(len(c), 1000.0)})


def selftest():
    rng = np.random.default_rng(5)
    # A) triple-tested support at 100 -> PROBABLE BUY LIQUIDITY zone containing 100
    c = [101.5, 101.2, 100.8, 100.4, 100.0, 100.5, 100.9, 100.6, 100.1, 100.0, 100.6, 101.0,
         100.7, 100.2, 100.0, 100.5, 101.1, 101.4, 101.2, 101.3] * 2
    zs = detect_zones(_mk(np.array(c) + rng.normal(0, 0.01, len(c))), windows=(15, 30), sym="T")
    sup = [z for z in zs if z["type"] == "PROBABLE BUY LIQUIDITY" and z["low"] <= 100.0 <= z["high"]]
    assert sup, zs[:3]
    assert sup[0]["touches"] >= 2
    # B) mirror: flipped tape flips the zone side at the mirrored level
    zs2 = detect_zones(_mk(202.6 - (np.array(c) + rng.normal(0, 0.01, len(c)))), windows=(15, 30))
    res = [z for z in zs2 if z["type"] == "PROBABLE SELL LIQUIDITY" and z["low"] <= 102.6 <= z["high"]]
    assert res, zs2[:3]
    # C) absorption bar: huge volume, long lower wick, tiny body -> zone at the tail
    n = 40
    base = 100 + 0.02 * np.arange(n)
    bars = _mk(base)
    bars.loc[30, ["low", "volume"]] = [base[30] - 1.2, 9000.0]     # the absorption print
    za = detect_zones(bars, windows=(30,))
    assert any("absorption_low" in z["evidence"] for z in za), za[:3]
    # D) doc's own reversal walkthrough: 100 -> 97.75 dump with a lower-high bounce (~98.35, the
    #    doc's pivot), decelerate at the low, hold 97.90 higher low, break the lower high, recover
    sm = ReversalStateMachine(sign=1)
    tape = [100.00, 99.70, 99.40, 99.10, 98.80, 98.50, 98.20,       # fast leg down
            98.30, 98.35, 98.25, 98.05, 97.90,                      # the LOWER-HIGH bounce (98.35)
            97.82, 97.78, 97.75, 97.76, 97.78,                      # decelerating tail, low 97.75
            97.90, 98.00, 97.95, 98.10, 98.20, 98.30,               # higher low + persistence
            98.45, 98.60, 98.55, 98.65, 98.70, 98.75, 98.80]        # micro break, efficient rise
    seen = set()
    for px in tape:
        seen.add(sm.update(px - 0.02, px + 0.05, px - 0.06, px))
    assert "DECELERATING" in seen and "POSSIBLE_TURN" in seen, seen
    assert sm.state in ("REVERSAL_CANDIDATE", "REVERSAL_CONFIRMED"), (sm.state, seen)
    # E) failed bounce: same setup, then a new low -> FAILED_BOUNCE/TREND, never CONFIRMED
    sm2 = ReversalStateMachine(sign=1)
    for px in tape[:24] + [97.9, 97.7, 97.5, 97.3, 97.2]:
        sm2.update(px - 0.02, px + 0.05, px - 0.06, px)
    assert sm2.state != "REVERSAL_CONFIRMED", sm2.state
    # F) bearish mirror reaches the same states on the flipped tape
    sm3 = ReversalStateMachine(sign=-1)
    seen3 = set()
    for px in [196.5 - t for t in tape]:
        seen3.add(sm3.update(px + 0.02, px + 0.06, px - 0.05, px))
    assert sm3.state == sm.state, (sm3.state, sm.state)
    # G) wording rule: every zone label uses PROBABLE/POTENTIAL, never 'confirmed order'
    for z in zs + zs2 + za:
        assert z["type"].startswith("PROBABLE")
    print("liquidity-zone engine + reversal machine OK — zones, mirror, absorption, doc walkthrough")


# ───────────────────────── data-drive evaluation (zones vs random-level control) ─────────────────────────

def evaluate(sym: str):
    """Per day: zones from the first 90 completed 1m RTH bars (post-OR), then measure on the REST
    of the day — hit rate (test then reverse >= 0.5 ATR before piercing > 0.5 ATR), false-breakout
    rate, and the SAME stats for random in-range control levels. Zones must beat the control."""
    # repo root = 4 levels up from BOT/bot/strategy/liquidity_zones.py (was 2 in the research home)
    sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(
        os.path.abspath(__file__))))), "engine"))
    import hs_db
    con = hs_db.connect()
    try:
        df = con.execute(f"SELECT * FROM {sym.lower()}_1m ORDER BY ts_et").df()
    except Exception as e:
        print(f"  {sym}: no continuous 1m view ({e})"); return
    tcol = "ts_et" if "ts_et" in df.columns else "ts"
    ts = pd.to_datetime(df[tcol], utc=True).dt.tz_convert("America/New_York")
    df = df.assign(_d=ts.dt.date, _m=ts.dt.hour * 60 + ts.dt.minute)
    rth = df[(df["_m"] >= 570) & (df["_m"] < 960)]
    rng = np.random.default_rng(11)
    hits = fakes = n_z = c_hits = c_fakes = n_c = 0
    days = 0
    for day, g in rth.groupby("_d"):
        g = g.reset_index(drop=True)
        if len(g) < 200:
            continue
        days += 1
        form, test = g.iloc[:90], g.iloc[90:]
        zs = [z for z in detect_zones(form, sym=sym) if z["label"] in ("MAJOR", "STRONG")]
        atr = _atr(form["high"].to_numpy(float), form["low"].to_numpy(float),
                   form["close"].to_numpy(float))
        th, tl, tc = (test["high"].to_numpy(float), test["low"].to_numpy(float),
                      test["close"].to_numpy(float))
        lo_r, hi_r = float(form["low"].min()), float(form["high"].max())
        ctl = [{"low": p - HALF_W_ATR * atr, "high": p + HALF_W_ATR * atr}
               for p in rng.uniform(lo_r, hi_r, size=max(len(zs), 1))]
        for pool, is_zone in ((zs, True), (ctl, False)):
            for z in pool:
                touched = np.where((tl <= z["high"]) & (th >= z["low"]))[0]
                if not len(touched):
                    continue
                i0 = touched[0]
                mid = (z["low"] + z["high"]) / 2.0
                seg = tc[i0:i0 + 30]
                if not len(seg):
                    continue
                react = np.max(np.abs(seg - mid))
                pierced = np.any((tl[i0:i0 + 30] < z["low"] - 0.5 * atr) |
                                 (th[i0:i0 + 30] > z["high"] + 0.5 * atr))
                hit = react >= 0.5 * atr and not pierced
                if is_zone:
                    n_z += 1; hits += hit; fakes += (pierced and react < 0.5 * atr)
                else:
                    n_c += 1; c_hits += hit; c_fakes += (pierced and react < 0.5 * atr)
    if n_z and n_c:
        print(f"  {sym}: days={days}  zones tested n={n_z} hit {100 * hits / n_z:.1f}% "
              f"fake {100 * fakes / n_z:.1f}%  |  random control n={n_c} hit {100 * c_hits / n_c:.1f}% "
              f"fake {100 * c_fakes / n_c:.1f}%  ->  edge {'YES' if hits / n_z > c_hits / n_c else 'no'}")
    else:
        print(f"  {sym}: not enough tested zones (n={n_z}, control={n_c})")


if __name__ == "__main__":
    args = [a for a in sys.argv[1:] if not a.startswith("-")]
    if "--selftest" in sys.argv or not args:
        selftest()
    for s in args:
        evaluate(s)
