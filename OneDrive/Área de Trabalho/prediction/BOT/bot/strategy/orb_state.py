"""ORB zone state machine + direction math (staleness fix 2026-07).

Fixes the state-staleness bug: a pending LONG stayed "ARMED" while price had already broken the
opposite OR edge / tagged its own stop. This module is the Python twin of the Pine state machine
(HIGHSTRIKE_ORB_STACK / _AUTO): a finite state machine per side —

    WAITING -> ARMED -> FILLED -> TP1_HIT -> COMPLETED
        |        |         `-> STOPPED
        |        `-> WATCH        (soft: confirmed close on the wrong side of OR mid — pull the order)
        `-> INVALIDATED           (hard: confirmed close beyond the OPPOSITE OR edge, or the side's
                                   proposed stop tagged before entry — cancel + clear levels)
    INVALIDATED -> WAITING only when price RECLAIMS the side's breakout edge on a confirmed close;
    a completely new confirmation is then required to re-arm (hysteresis — no flip-flop).

LONG and SHORT are exact mirrors: one implementation, `sign` (+1 long / -1 short) flips every
comparison. All transitions use confirmed-bar values only (no future data, no negative offsets).

Also implements the direction-math primitives from the spec (all causal, all symmetric):
    delta_p, net_move, path_distance, efficiency_ratio (Kaufman ER, div-by-zero safe),
    directional_persistence (noise-thresholded), norm_slope (regression slope / mean price).

    from bot.strategy.orb_state import OrbSideState, SideState, zone_of, Zone
    sm = OrbSideState(side="long", or_high=730.0, or_low=723.9)
    sm.arm(entry=730.01, stop=726.76, tp1=733.26, tp2=743.02, close=730.5)
    sm.on_bar(high=731, low=718.9, close=719.0)     # confirmed close < OR low -> INVALIDATED
    sm.pending_cancelled                             # True -> caller cancels the broker order
"""
from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum

import numpy as np


# ─────────────────────────── direction math (spec formulas) ───────────────────────────

def delta_p(prices) -> np.ndarray:
    """ΔP_t = P_t − P_{t−1} (causal, first element dropped)."""
    p = np.asarray(prices, float)
    return np.diff(p)


def net_move(prices) -> float:
    """N = P_last − P_first."""
    p = np.asarray(prices, float)
    return float(p[-1] - p[0]) if len(p) else 0.0


def path_distance(prices) -> float:
    """D = Σ |ΔP| — total distance traveled."""
    d = delta_p(prices)
    return float(np.abs(d).sum())


def efficiency_ratio(prices) -> float:
    """Kaufman ER = |net| / path ∈ [0, 1]. 1 = straight line, 0 = pure chop.
    Zero path distance (flat tape) returns 0.0 — never divides by zero."""
    d = path_distance(prices)
    return abs(net_move(prices)) / d if d > 0 else 0.0


def directional_persistence(prices, noise: float = 0.0) -> tuple[int, float]:
    """(direction, persistence): direction = sign of the dominant side (+1/-1/0);
    persistence = max(U, D) / (U + D) over moves with |ΔP| > noise. Symmetric up/down.
    No meaningful moves -> (0, 0.0)."""
    d = delta_p(prices)
    if noise > 0:
        d = d[np.abs(d) > noise]
    u = int((d > 0).sum()); dn = int((d < 0).sum())
    tot = u + dn
    if tot == 0:
        return 0, 0.0
    if u == dn:
        return 0, 0.5
    return (1 if u > dn else -1), max(u, dn) / tot


def norm_slope(prices) -> float:
    """Least-squares slope of P vs t, normalized by mean price (scale-invariant, per-bar units).
    < 3 points or zero mean -> 0.0."""
    p = np.asarray(prices, float)
    if len(p) < 3:
        return 0.0
    m = float(p.mean())
    if m == 0:
        return 0.0
    t = np.arange(len(p), dtype=float)
    b = float(np.polyfit(t, p, 1)[0])
    return b / abs(m)


# ─────────────────────────── zones + states ───────────────────────────

class Zone(str, Enum):
    ABOVE_HIGH = "above_or_high"
    UPPER_HALF = "upper_or_half"
    LOWER_HALF = "lower_or_half"
    BELOW_LOW = "below_or_low"


def zone_of(price: float, or_high: float, or_low: float) -> Zone:
    mid = (or_high + or_low) / 2.0
    if price > or_high:
        return Zone.ABOVE_HIGH
    if price >= mid:
        return Zone.UPPER_HALF
    if price > or_low:
        return Zone.LOWER_HALF
    return Zone.BELOW_LOW


class SideState(str, Enum):
    WAITING = "waiting"          # no pending setup; needs a fresh breakout confirmation
    WATCH = "watch"              # pending pulled (wrong side of OR mid); needs a new confirmation
    ARMED = "armed"              # confirmed breakout; entry order pending
    FILLED = "filled"            # position open
    TP1_HIT = "tp1_hit"          # partial banked; runner working
    COMPLETED = "completed"      # final target hit / position closed
    STOPPED = "stopped"          # stop hit; block immediate re-entry
    INVALIDATED = "invalidated"  # structure broke against the pending side; cleared + blocked


_PENDING = (SideState.WAITING, SideState.WATCH, SideState.ARMED)
_TERMINAL_TRADE = (SideState.COMPLETED, SideState.STOPPED)


@dataclass
class OrbSideState:
    """One side (long or short) of the ORB day. Feed confirmed bars via on_bar(); call arm()/fill()
    on the engine's confirmation events. `pending_cancelled` flags that a resting order must be
    cancelled by the caller (Pine: strategy.cancel; Python: broker.cancel(order_id))."""
    side: str                              # "long" | "short"
    or_high: float
    or_low: float
    state: SideState = SideState.WAITING
    entry: float | None = None
    stop: float | None = None
    tp1: float | None = None
    tp2: float | None = None
    pending_order_id: str | None = None
    pending_cancelled: bool = False
    history: list[SideState] = field(default_factory=list)

    def __post_init__(self):
        if self.side not in ("long", "short"):
            raise ValueError("side must be 'long' or 'short'")
        if not (self.or_high > self.or_low):
            raise ValueError("or_high must be above or_low")

    # mirror helpers — every comparison goes through sign so long/short stay exact mirrors
    @property
    def sign(self) -> int:
        return 1 if self.side == "long" else -1

    @property
    def or_mid(self) -> float:
        return (self.or_high + self.or_low) / 2.0

    @property
    def entry_edge(self) -> float:          # the edge this side breaks OUT of
        return self.or_high if self.sign == 1 else self.or_low

    @property
    def opposite_edge(self) -> float:       # confirmed close beyond this = hard invalidation
        return self.or_low if self.sign == 1 else self.or_high

    def _beyond(self, a: float, b: float) -> bool:
        """a is beyond b in the trade direction."""
        return self.sign * (a - b) > 0

    def _set(self, s: SideState) -> SideState:
        if s is not self.state:
            self.history.append(s)
        self.state = s
        return s

    def _clear_pending(self) -> None:
        self.entry = self.stop = self.tp1 = self.tp2 = None
        if self.pending_order_id is not None:
            self.pending_cancelled = True
            self.pending_order_id = None

    # ---- events from the signal engine ----
    def arm(self, entry: float, stop: float, tp1: float | None = None, tp2: float | None = None,
            close: float | None = None, order_id: str | None = None) -> SideState:
        """A NEW confirmed breakout arms the side. Refused while INVALIDATED/STOPPED (hysteresis:
        those clear only via on_bar reclaim) and refused from WATCH unless price is back on the
        right side of OR mid (a re-breakout)."""
        if self.state in (SideState.INVALIDATED, SideState.STOPPED):
            return self.state
        if self.state not in _PENDING:
            return self.state
        if close is not None and not self._beyond(close, self.or_mid):
            return self.state                      # still on the wrong side of the mid — no re-arm
        if not self._beyond(entry, stop):
            raise ValueError(f"{self.side} stop {stop} must be beyond entry {entry} against the trade")
        self.entry, self.stop, self.tp1, self.tp2 = entry, stop, tp1, tp2
        self.pending_order_id = order_id
        self.pending_cancelled = False
        return self._set(SideState.ARMED)

    def fill(self) -> SideState:
        if self.state is SideState.ARMED:
            self.pending_order_id = None
            return self._set(SideState.FILLED)
        return self.state

    # ---- one CONFIRMED bar (never intrabar values) ----
    def on_bar(self, high: float, low: float, close: float) -> SideState:
        s, sign = self.state, self.sign
        adverse_extreme = low if sign == 1 else high     # how far the bar went AGAINST the side
        favor_extreme = high if sign == 1 else low       # how far it went WITH the side

        if s in _PENDING:
            # HARD invalidation: confirmed close beyond the opposite OR edge, or the proposed stop
            # tagged before entry (stale setup — the market already took the trade out).
            stop_tagged = self.stop is not None and not self._beyond(adverse_extreme, self.stop)
            if self._beyond(self.opposite_edge, close) or stop_tagged:
                self._clear_pending()
                return self._set(SideState.INVALIDATED)
            # SOFT cancel: pending entry and the bar closed on the wrong side of OR mid -> WATCH
            if s is SideState.ARMED and self._beyond(self.or_mid, close):
                self._clear_pending()
                return self._set(SideState.WATCH)
            return s

        if s is SideState.INVALIDATED:
            # reclaim of the breakout edge on a confirmed close -> WAITING (fresh confirmation needed)
            if self._beyond(close, self.entry_edge):
                return self._set(SideState.WAITING)
            return s

        if s in (SideState.FILLED, SideState.TP1_HIT):
            # stop first on same-bar ambiguity (conservative — matches engine/tracker convention)
            if self.stop is not None and not self._beyond(adverse_extreme, self.stop):
                return self._set(SideState.STOPPED)
            if self.tp2 is not None and not self._beyond(self.tp2, favor_extreme):
                return self._set(SideState.COMPLETED)
            if s is SideState.FILLED and self.tp1 is not None and not self._beyond(self.tp1, favor_extreme):
                return self._set(SideState.TP1_HIT)
            return s

        return s     # STOPPED / COMPLETED are terminal for the setup (block immediate re-entry)


# ─────────────────────────── combined slope engine (user research spec 2026-07) ───────────────────────────
# S = 0.50·(Sc/ATR) + 0.30·(Sm/ATR) + 0.20·BP   over the last N candles, where
#   Sc = regression slope of CLOSES, Sm = regression slope of BODY MIDPOINTS (open+close)/2,
#   BP = recency-weighted body pressure  Σw·(C−O) / Σw·|C−O|  ∈ [−1, +1],  w_i = 1 + i/(N−1)
# ATR normalization makes S comparable across instruments/timeframes (≈ ATRs advanced per bar).

SLOPE_STRONG = 0.30      # |S| ≥ 0.30 → STRONG (spec starting thresholds — per-TF tuning required)
SLOPE_DIR = 0.10         # |S| ≥ 0.10 → directional; below → neutral band
PERSIST_STRONG, PERSIST_DIR = 0.70, 0.60
ER_STRONG, ER_DIR = 0.60, 0.40


def _reg_slope(y: np.ndarray) -> float:
    """Least-squares slope of y vs bar index (uses every point, not just first/last)."""
    n = len(y)
    if n < 3:
        return 0.0
    x = np.arange(n, dtype=float)
    xm = x - x.mean()
    denom = float((xm * xm).sum())
    return float((xm * (y - y.mean())).sum() / denom) if denom > 0 else 0.0


def slope_engine(opens, closes, atr: float, n: int = 12) -> dict:
    """Combined slope read over the last n candles (causal, symmetric, div-by-zero safe).
    Returns Sc_atr, Sm_atr, body_pressure, S (combined), plus persistence + efficiency of the
    same window — the doc's four calculations in one call."""
    o = np.asarray(opens, float)[-n:]
    c = np.asarray(closes, float)[-n:]
    m = min(len(o), len(c))
    o, c = o[-m:], c[-m:]
    if m < 3 or not np.isfinite(atr) or atr <= 0:
        return {"sc_atr": 0.0, "sm_atr": 0.0, "body_pressure": 0.0, "S": 0.0,
                "persist_dir": 0, "persistence": 0.0, "efficiency": 0.0}
    sc = _reg_slope(c) / atr
    sm = _reg_slope((o + c) / 2.0) / atr
    w = 1.0 + np.arange(m, dtype=float) / max(m - 1, 1)          # recent candles weigh ~2x the oldest
    body = c - o
    denom = float((w * np.abs(body)).sum())
    bp = float((w * body).sum() / denom) if denom > 0 else 0.0
    S = 0.50 * sc + 0.30 * sm + 0.20 * bp
    pdir, pers = directional_persistence(c, noise=0.0)
    return {"sc_atr": round(sc, 4), "sm_atr": round(sm, 4), "body_pressure": round(bp, 4),
            "S": round(S, 4), "persist_dir": pdir, "persistence": round(pers, 3),
            "efficiency": round(efficiency_ratio(c), 3)}


def directional_state(S: float, persistence: float, persist_dir: int, efficiency: float,
                      st_state: int | None = None, zone_vote: int | None = None) -> str:
    """The spec's 7 directional states. STRONG requires slope + persistence + efficiency AND
    structure/location agreement; a conflicting structure or location demotes toward NEUTRAL.
    Symmetric up/down by construction (evaluated on sign·S)."""
    sign = 1 if S > 0 else (-1 if S < 0 else 0)
    if sign == 0:
        return "NEUTRAL"
    a = abs(S)
    aligned_p = persist_dir == sign and persistence >= PERSIST_DIR
    strong_p = persist_dir == sign and persistence >= PERSIST_STRONG
    st_agree = st_state is None or st_state == 0 or st_state == 3 or \
        (st_state == 1 and sign == 1) or (st_state == 2 and sign == -1)
    st_conflict = st_state in (1, 2) and not st_agree
    loc_agree = zone_vote is None or zone_vote == 0 or zone_vote == sign
    lab = "UP" if sign == 1 else "DOWN"
    if a >= SLOPE_STRONG and strong_p and efficiency >= ER_STRONG and st_agree and loc_agree \
            and st_state in (1, 2):                       # STRONG needs confirmed structure too
        return f"STRONG_{lab}"
    if a >= SLOPE_DIR and aligned_p and efficiency >= ER_DIR and not st_conflict and loc_agree:
        return lab
    if a >= SLOPE_DIR and (st_conflict or not loc_agree):
        return "NEUTRAL"                                  # spec §7: slope alone must NOT call direction
    if a >= SLOPE_DIR:
        return f"WEAK_{lab}"
    return "NEUTRAL"


def fast_direction(closes_1m, or_high: float | None = None, or_low: float | None = None,
                   vwap: float | None = None, st_state_1m: int | None = None,
                   slope_n: int = 12, opens_1m=None, atr: float | None = None) -> dict:
    """DIR-fast read at 1-MINUTE speed (Python twin of the STACK dashboard row, post staleness fix):
    four symmetric votes — live OR zone (price vs OR levels NOW: above OR-high = long, above OR-mid
    = watch/lean long, mirror short), VWAP side, the COMBINED SLOPE ENGINE (close-slope + body-
    midpoint slope + weighted body pressure, ATR-normalized — user research spec), and the 1m
    swing-structure state. When opens+ATR are supplied the slope vote uses the combined S with the
    ±0.10 neutral band and the dict carries the full engine + the 7-level `state`
    (STRONG_UP…STRONG_DOWN). ALIGNMENT is the point: when zone+slope+struct agree, price is moving
    that way. All inputs causal (last closed 1m bars)."""
    c = np.asarray(closes_1m, float)
    px = float(c[-1]) if len(c) else float("nan")
    eng = None
    if opens_1m is not None and atr is not None and np.isfinite(atr) and atr > 0 and len(c) >= 3:
        eng = slope_engine(opens_1m, c, atr, n=slope_n)
        S = eng["S"]
        v_slope = 1 if S >= SLOPE_DIR else (-1 if S <= -SLOPE_DIR else 0)
    else:
        slope = norm_slope(c[-slope_n:]) if len(c) >= 3 else 0.0
        v_slope = 1 if slope > 0 else (-1 if slope < 0 else 0)
    v_zone = 0
    if or_high is not None and or_low is not None and np.isfinite(px) \
            and np.isfinite(or_high) and np.isfinite(or_low):
        mid = (or_high + or_low) / 2.0
        v_zone = 1 if px > or_high else (-1 if px < or_low else (1 if px > mid else -1))
    v_vwap = 0
    if vwap is not None and np.isfinite(vwap) and np.isfinite(px):
        v_vwap = 1 if px > vwap else (-1 if px < vwap else 0)
    v_st = {1: 1, 2: -1}.get(int(st_state_1m) if st_state_1m is not None else 0, 0)
    score = v_zone + v_vwap + v_slope + v_st
    read = "up" if score >= 2 else ("down" if score <= -2 else "mixed")
    out = {"zone": v_zone, "vwap": v_vwap, "slope": v_slope, "struct_1m": v_st,
           "score": score, "read": read,
           "aligned": v_zone != 0 and v_zone == v_slope == v_st}   # OR+SLOPE+STRUC agree
    if eng is not None:
        out["slope_engine"] = eng
        out["state"] = directional_state(eng["S"], eng["persistence"], eng["persist_dir"],
                                         eng["efficiency"], st_state=st_state_1m, zone_vote=v_zone)
    return out


def signal_zone_state(side: str, price: float, or_high: float | None, or_low: float | None) -> str:
    """Stateless zone verdict for a LIVE proposal (dashboard/paper-autotrade): is this signal's
    direction still structurally valid at the CURRENT price?
      'invalid' = price beyond the OPPOSITE OR edge (long below OR low / short above OR high)
      'watch'   = price on the wrong side of OR mid
      'active'  = price still on the signal's side of the mid
    Missing OR levels -> 'unknown' (callers must not treat unknown as invalid)."""
    if or_high is None or or_low is None or not np.isfinite(or_high) or not np.isfinite(or_low):
        return "unknown"
    sign = 1 if side == "long" else -1
    mid = (or_high + or_low) / 2.0
    opposite = or_low if sign == 1 else or_high
    if sign * (price - opposite) < 0:
        return "invalid"
    if sign * (price - mid) < 0:
        return "watch"
    return "active"


if __name__ == "__main__":   # self-test: the spec's long-side table + the short mirror + math
    sm = OrbSideState("long", or_high=730.0, or_low=723.9)
    sm.arm(entry=730.01, stop=726.76, tp1=733.26, tp2=743.02, close=730.5, order_id="o1")
    assert sm.state is SideState.ARMED
    sm.on_bar(high=730.5, low=727.0, close=726.5)        # closed below OR mid (726.95) -> WATCH
    assert sm.state is SideState.WATCH and sm.pending_cancelled
    sm.on_bar(high=727.0, low=718.9, close=719.0)        # confirmed close < OR low -> INVALIDATED
    assert sm.state is SideState.INVALIDATED
    assert sm.arm(entry=730.01, stop=726.76, close=731.0) is SideState.INVALIDATED   # re-arm refused
    sm.on_bar(high=731.2, low=729.0, close=730.6)        # reclaim OR high -> WAITING
    assert sm.state is SideState.WAITING
    sm.arm(entry=730.01, stop=728.0, tp1=733.0, tp2=738.0, close=730.6)              # fresh confirm
    assert sm.state is SideState.ARMED
    sm.fill(); sm.on_bar(high=733.5, low=730.0, close=733.2)
    assert sm.state is SideState.TP1_HIT
    sm.on_bar(high=738.4, low=732.0, close=738.0)
    assert sm.state is SideState.COMPLETED
    # mirror check: identical path, negated
    ss = OrbSideState("short", or_high=730.0, or_low=723.9)
    ss.arm(entry=723.89, stop=727.15, close=723.0)
    ss.on_bar(high=731.0, low=722.0, close=730.8)        # confirmed close > OR high -> INVALIDATED
    assert ss.state is SideState.INVALIDATED
    # math
    up = [1, 2, 3, 4, 5]
    assert efficiency_ratio(up) == 1.0 and directional_persistence(up)[0] == 1
    assert efficiency_ratio([5, 5, 5, 5]) == 0.0                     # zero path -> no crash
    assert directional_persistence([1, 2, 1, 2, 1])[0] == 0          # alternating -> neutral
    assert abs(norm_slope(up) - norm_slope([x * 100 for x in up])) < 1e-12   # scale-invariant
    print("orb_state OK — mirrored FSM + spec math verified")
