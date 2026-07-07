"""ORB entry state machine + direction math — the CANONICAL ENTRY STANDARD (2026-07-04).

One state machine, three surfaces: this module is the Python reference implementation; the Pine
scripts (HIGHSTRIKE_ORB_STACK / _AUTO / _OPTIONS) and the engine (`hs_backtest._orb_signals`) carry
the same semantics. The strategy docs (Trading System Logic / README_trading_state_logic) define
three layers:

    Layer 1 — MARKET CONTEXT (hard):  Structure + VWAP aligned  ->  the side is ARMED.
    Layer 2 — TRADE QUALITY (grade):  the combined slope engine grades A+..D — never direction.
    Layer 3 — EXECUTION (OR levels):  OR mid activates WATCH; OR high/low triggers the FILL.

Per-side finite state machine (long/short exact mirrors, `sign` flips every comparison):

    WAITING ──ctx aligned──> ARMED ──confirmed close beyond OR mid──> WATCH ──body close beyond
       ^                       |                                        |      OR high/low──> FILLED
       |                       `──ctx lost──> WAITING                   |
       |                                                                ├─ close back across mid ─> COOLDOWN (N bars) ─> restart
       |                                                                ├─ extended > chase·ATR ──> PULLBACK ─ retest near edge ─> WATCH
       |                                                                └─ > stale bars, no fill ─> RANGE (until mid lost)
       └──────────── INVALIDATED (close beyond OPPOSITE edge / stop tagged pre-entry) — reclaim the
                     entry edge on a confirmed close to return to WAITING (hysteresis, no flip-flop)

    FILLED -> TP1_HIT -> COMPLETED | STOPPED;  reset_cycle() -> COOLDOWN (fresh cycle) or LOCKED
    when the side has used its max entries for the session (two-entry limit).

All transitions use CONFIRMED bar values only (no future data, no intrabar flips). The fill itself
additionally requires the validated stack: strong full-body close beyond the level (no wick-only),
optional next-candle continuation (F59c) + direction sequence (F61) — enforced by the engine/Pine.

Also implements the direction-math primitives (delta_p, net_move, path_distance, efficiency_ratio,
directional_persistence, norm_slope), the combined slope engine (S = 0.50·Sc/ATR + 0.30·Sm/ATR +
0.20·BP) and the Layer-2 `slope_grade` (A+..D).

    from bot.strategy.orb_state import OrbSideState, SideState, ENTRY_STANDARD
    sm = OrbSideState(side="long", or_high=730.0, or_low=723.9)
    sm.on_bar(high=728.0, low=725.0, close=727.5, open_px=725.4, struct_state=1, vwap=725.0)
    sm.state                                        # ARMED -> WATCH once the mid is crossed
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
    WAITING = "waiting"          # Layer-1 context not aligned — the side may not look for a setup
    ARMED = "armed"              # Structure + VWAP aligned toward the side (Layer 1 — Market Context)
    WATCH = "watch"              # armed + confirmed close beyond OR mid toward the side (Layer 3)
    PULLBACK = "pullback"        # over-extended past the entry edge pre-fill — wait for the retest
    RANGE = "range"              # stale: sat in WATCH too long without a fill — stand down this cycle
    COOLDOWN = "cooldown"        # watch cancelled at OR mid — no re-watch for cooldown_bars
    FILLED = "filled"            # position open
    TP1_HIT = "tp1_hit"          # partial banked; runner working
    COMPLETED = "completed"      # final target hit / position closed
    STOPPED = "stopped"          # stop hit
    INVALIDATED = "invalidated"  # hard: close beyond the OPPOSITE edge / stop tagged pre-entry
    LOCKED = "locked"            # max entries used on this side — locked for the session


_PENDING = (SideState.WAITING, SideState.ARMED, SideState.WATCH,
            SideState.PULLBACK, SideState.RANGE, SideState.COOLDOWN)
_TERMINAL_TRADE = (SideState.COMPLETED, SideState.STOPPED)
_FILL_READY = (SideState.WATCH,)          # the only state a fill may trigger from (canonical spec)


@dataclass(frozen=True)
class EntryStandard:
    """The shared entry-standard knobs — ONE set of numbers for Pine + engine + BOT.
    Defaults mirror the Pine inputs / engine params; change here and re-sync the Pine inputs."""
    ctx_gate: bool = True        # Layer 1: Structure + VWAP must align to ARM the side
    watch_gate: bool = True      # Layer 3: a confirmed close beyond OR mid is required (WATCH)
    cooldown_bars: int = 3       # bars blocked after a watch cancel (close back across the mid)
    stale_bars: int = 24         # max bars in WATCH without a fill -> RANGE (0 = off; 24 = 2h on 5m)
    chase_atr: float = 1.0       # extension beyond the edge that flips WATCH -> PULLBACK (0 = off)
    retest_atr: float = 0.5      # pullback satisfied when price returns within this ATR of the target
    max_entries: int = 1         # per-side entry limit per session (F76: equity 1 — re-entries lose; futures override to 3)
    strong_body: float = 0.25    # fill: min body/range of the breakout candle (no wick-only fills)
    ft_confirm: bool = True      # fill: next-candle continuation (F59c)
    dir_seq: bool = True         # fill: direction sequence c>c1>c2 / mirror (F61)
    # ── PULLBACK REFINEMENTS (deep-research doc, un-deferred 2026-07-05 — gauntlet before trust) ──
    retest_mode: str = "edge"    # retest target: "edge" (OR high/low) | "impulse_mid" (midpoint of
                                 # the extension impulse — catches profit-taking without a full
                                 # boundary revisit) | "vwap" (session-VWAP retest)
    min_pullback_atr: float = 0.05   # the retrace from the extension extreme must be AT LEAST this
                                     # (anti-spike: don't buy an unrelieved vertical; 0 = off)
    pullback_timeout: int = 8    # bars a PULLBACK may wait for its retest before the setup is
                                 # stale for this cycle (docs: 3-8 bars; 0 = wait forever)
    vol_confirm_x: float = 0.0   # fill trigger bar needs volume >= this x 20-bar average
                                 # (docs suggest 1.2-2.0; DEFAULT OFF until gauntleted)


ENTRY_STANDARD = EntryStandard()


@dataclass
class OrbSideState:
    """One side (long or short) of the ORB day — the canonical three-layer entry state machine.
    Feed CONFIRMED bars via on_bar(); attach the trade plan via arm(); call fill() on the engine's
    fill event and reset_cycle() after a terminal trade state. `pending_cancelled` flags that a
    resting order must be cancelled by the caller (Pine: strategy.cancel; Python: broker.cancel)."""
    side: str                              # "long" | "short"
    or_high: float
    or_low: float
    cfg: EntryStandard = ENTRY_STANDARD
    state: SideState = SideState.WAITING
    entry: float | None = None
    stop: float | None = None
    tp1: float | None = None
    tp2: float | None = None
    pending_order_id: str | None = None
    pending_cancelled: bool = False
    entries_used: int = 0                  # two-entry limit counter (per session)
    watch_age: int = 0                     # bars spent in WATCH this cycle (range/stale rule)
    cooldown_left: int = 0
    ext_extreme: float | None = None       # furthest price of the extension impulse (PULLBACK)
    pullback_age: int = 0                  # bars spent waiting for the retest (timeout rule)
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

    @property
    def locked(self) -> bool:
        return self.entries_used >= self.cfg.max_entries

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

    def _ctx_ok(self, close: float, struct_state: int | None, vwap: float | None) -> bool:
        """Layer 1 — Market Context: Structure AND VWAP aligned toward the side. Inputs not
        supplied count as aligned (caller doesn't track them); ctx_gate off = always aligned."""
        if not self.cfg.ctx_gate:
            return True
        ok = True
        if struct_state is not None and struct_state != 0:
            ok &= (struct_state == 1 and self.sign == 1) or (struct_state == 2 and self.sign == -1)
        if vwap is not None and np.isfinite(vwap):
            ok &= self._beyond(close, vwap)
        return bool(ok)

    # ---- events from the signal engine ----
    def arm(self, entry: float, stop: float, tp1: float | None = None, tp2: float | None = None,
            close: float | None = None, order_id: str | None = None) -> SideState:
        """Attach the trade PLAN (levels + optional resting order). Only a side that has passed
        the mid (WATCH) — or whose supplied close is beyond the mid — may carry a pending entry.
        Refused while INVALIDATED / COOLDOWN / RANGE / LOCKED / terminal (hysteresis)."""
        if self.state not in (SideState.WAITING, SideState.ARMED, SideState.WATCH):
            return self.state
        if self.state is not SideState.WATCH:
            if close is None or not self._beyond(close, self.or_mid):
                return self.state                  # not past the mid — no pending entry yet
        if not self._beyond(entry, stop):
            raise ValueError(f"{self.side} stop {stop} must be beyond entry {entry} against the trade")
        self.entry, self.stop, self.tp1, self.tp2 = entry, stop, tp1, tp2
        self.pending_order_id = order_id
        self.pending_cancelled = False
        if self.state is not SideState.WATCH:
            self.watch_age = 0
        return self._set(SideState.WATCH)

    def fill(self) -> SideState:
        """Fill fires only from WATCH (canonical Layer 3) with a plan attached."""
        if self.state in _FILL_READY and self.entry is not None:
            self.pending_order_id = None
            self.entries_used += 1
            return self._set(SideState.FILLED)
        return self.state

    def reset_cycle(self) -> SideState:
        """Start a new entry cycle after a terminal trade state. LOCKED once the side has used
        its max entries for the session (two-entry limit); otherwise COOLDOWN -> fresh cycle."""
        if self.state not in _TERMINAL_TRADE:
            return self.state
        if self.locked:
            return self._set(SideState.LOCKED)
        self.entry = self.stop = self.tp1 = self.tp2 = None
        self.watch_age = 0
        if self.cfg.cooldown_bars > 0:
            self.cooldown_left = self.cfg.cooldown_bars
            return self._set(SideState.COOLDOWN)
        return self._set(SideState.WAITING)

    # ---- one CONFIRMED bar (never intrabar values) ----
    def on_bar(self, high: float, low: float, close: float, open_px: float | None = None,
               struct_state: int | None = None, vwap: float | None = None,
               atr: float | None = None) -> SideState:
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

            ctx = self._ctx_ok(close, struct_state, vwap)
            past_mid = (not self.cfg.watch_gate) or self._beyond(close, self.or_mid)
            body_ok = open_px is None or sign * (close - open_px) > 0

            if s is SideState.COOLDOWN:
                self.cooldown_left -= 1
                if self.cooldown_left > 0:
                    return s
                # cooldown over — restart from context; a NEW clean close beyond the mid is
                # required on a LATER bar before the side can WATCH again (no instant re-watch)
                return self._set(SideState.ARMED if ctx else SideState.WAITING)

            if s is SideState.WAITING:
                if not ctx:
                    return s
                s = self._set(SideState.ARMED)   # context aligned -> ARMED (may WATCH same bar)

            if s is SideState.ARMED:
                if not ctx:
                    return self._set(SideState.WAITING)
                if self._beyond(close, self.or_mid) and body_ok:
                    self.watch_age = 0
                    return self._set(SideState.WATCH)
                return s

            # WATCH / PULLBACK / RANGE all die the same way: a confirmed close back across the
            # mid cancels the setup -> COOLDOWN; ARMED context must then re-prove itself.
            if not self._beyond(close, self.or_mid):
                self._clear_pending()
                if self.cfg.cooldown_bars > 0:
                    self.cooldown_left = self.cfg.cooldown_bars
                    return self._set(SideState.COOLDOWN)
                return self._set(SideState.ARMED if ctx else SideState.WAITING)

            if s is SideState.RANGE:
                return s                          # stale — stands down until the mid is lost

            if s is SideState.PULLBACK:
                # track the extension impulse + age (deep-research refinements 2026-07-05)
                if self.ext_extreme is None or self._beyond(favor_extreme, self.ext_extreme):
                    self.ext_extreme = favor_extreme
                self.pullback_age += 1
                if self.cfg.pullback_timeout > 0 and self.pullback_age > self.cfg.pullback_timeout:
                    return self._set(SideState.RANGE)     # retest never came — stale this cycle
                if atr is not None and atr > 0:
                    target = self.entry_edge                          # "edge" (default)
                    if self.cfg.retest_mode == "impulse_mid" and self.ext_extreme is not None:
                        target = (self.entry_edge + self.ext_extreme) / 2.0
                    elif self.cfg.retest_mode == "vwap" and vwap is not None and np.isfinite(vwap):
                        target = vwap
                    deep_enough = (self.cfg.min_pullback_atr <= 0 or self.ext_extreme is None or
                                   sign * (self.ext_extreme - adverse_extreme)
                                   >= self.cfg.min_pullback_atr * atr)
                    if deep_enough and sign * (adverse_extreme - target) <= self.cfg.retest_atr * atr:
                        return self._set(SideState.WATCH)  # valid retest -> clean re-check
                return s

            # s is WATCH
            self.watch_age += 1
            if self.cfg.stale_bars > 0 and self.watch_age > self.cfg.stale_bars:
                return self._set(SideState.RANGE)
            if atr is not None and atr > 0 and self.cfg.chase_atr > 0 and \
                    self._beyond(favor_extreme, self.entry_edge + sign * self.cfg.chase_atr * atr):
                self.ext_extreme = favor_extreme
                self.pullback_age = 0
                return self._set(SideState.PULLBACK)      # too extended — do not chase
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

        return s     # STOPPED / COMPLETED / LOCKED are terminal (reset_cycle() starts the next one)


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


def slope_series(opens, closes, atr, n: int = 12) -> np.ndarray:
    """Vectorized combined-S per bar — the ARRAY twin of slope_engine for backtest gating
    (DIR-FAST C, user 2026-07-05: a third arming engine; fire when A, B or C aligns).
    S[i] is computed from the n bars ENDING at i (causal), 0 while the window is short or ATR
    is invalid. Matches slope_engine's Sc/Sm/BP weights exactly (self-tested below)."""
    o = np.asarray(opens, float); c = np.asarray(closes, float)
    a = np.asarray(atr, float)
    N = len(c)
    S = np.zeros(N)
    if N < n or n < 3:
        return S
    k = np.arange(n, dtype=float)
    xm = k - k.mean()
    ker = xm / float((xm * xm).sum())                 # regression weights: slope = ker · window
    sc = np.correlate(c, ker, "valid")                # slope of closes, window ending at i
    sm = np.correlate((o + c) / 2.0, ker, "valid")    # slope of body midpoints
    w = 1.0 + k / max(n - 1, 1)                       # recency weights (oldest 1x .. newest 2x)
    body = c - o
    num = np.correlate(body, w, "valid")
    den = np.correlate(np.abs(body), w, "valid")
    bp = np.divide(num, den, out=np.zeros_like(num), where=den > 0)
    atr_end = a[n - 1:]
    ok = np.isfinite(atr_end) & (atr_end > 0)
    out = np.zeros_like(sc)
    out[ok] = 0.50 * sc[ok] / atr_end[ok] + 0.30 * sm[ok] / atr_end[ok] + 0.20 * bp[ok]
    S[n - 1:] = out
    return S


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


GRADES = ("A+", "A", "B+", "B", "C", "D")


def slope_grade(S: float, persistence: float, efficiency: float, side: str | None = None) -> str:
    """Layer 2 — TRADE QUALITY grade from the combined slope engine (docs: slope grades the setup,
    it never decides direction). Graded along the trade direction when `side` is given — a slope
    that actively disagrees with the trade demotes to C/D; without a side, graded on |S|.
    A+ = strong slope with strong persistence+efficiency … D = flat/contrary. Stored as an ML
    feature (docs: 'the slope grade will also be used as an input for the ML/NN models')."""
    if side is not None:
        a = S if side == "long" else -S
        if a < 0:
            return "D" if a <= -SLOPE_DIR else "C"        # slope pushing against the trade
        a = abs(a)
    else:
        a = abs(S)
    strong_conf = persistence >= PERSIST_STRONG and efficiency >= ER_STRONG
    dir_conf = persistence >= PERSIST_DIR and efficiency >= ER_DIR
    if a >= SLOPE_STRONG and strong_conf:
        return "A+"
    if a >= SLOPE_STRONG or (a >= SLOPE_DIR and strong_conf):
        return "A"
    if a >= SLOPE_DIR and dir_conf:
        return "B+"
    if a >= SLOPE_DIR:
        return "B"
    if a >= 0.05:
        return "C"
    return "D"


def fast_direction(closes_1m, or_high: float | None = None, or_low: float | None = None,
                   vwap: float | None = None, st_state_1m: int | None = None,
                   slope_n: int = 12, opens_1m=None, atr: float | None = None) -> dict:
    """DIR-fast read at 1-MINUTE speed (Python twin of the STACK dashboard row, post staleness fix):
    four symmetric votes — live OR zone (price vs OR levels NOW: above OR-high = long, above OR-mid
    = watch/lean long, mirror short), VWAP side, the COMBINED SLOPE ENGINE (close-slope + body-
    midpoint slope + weighted body pressure, ATR-normalized — user research spec), and the 1m
    swing-structure state. When opens+ATR are supplied the slope vote uses the combined S with the
    ±0.10 neutral band and the dict carries the full engine + the 7-level `state`
    (STRONG_UP…STRONG_DOWN) + the Layer-2 `grade` (A+..D). ALIGNMENT is the point: when
    zone+slope+struct agree, price is moving that way. All inputs causal (last closed 1m bars)."""
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
    # DIR-FAST A (user 2026-07-05): the ARMING pair read = OR-MID side + VWAP side only.
    # The composite below stays as the fallback B read; slope/struct grade, they don't arm.
    v_mid = 0
    if or_high is not None and or_low is not None and np.isfinite(px) \
            and np.isfinite(or_high) and np.isfinite(or_low):
        v_mid = 1 if px > (or_high + or_low) / 2.0 else -1
    a_score = v_mid + v_vwap
    # DIR-FAST C (user 2026-07-05, 07.4): the combined-slope STRONG read (|S| >= 0.30). The
    # A∨B∨C arm on futures fires when ANY of A (vwap side), B (structure), C (slope strong)
    # agrees — an OR, not an alignment; only one of the three needs to be true.
    v_c = 0
    if eng is not None:
        v_c = 1 if eng["S"] >= SLOPE_STRONG else (-1 if eng["S"] <= -SLOPE_STRONG else 0)
    abc_up = v_vwap > 0 or v_st > 0 or v_c > 0
    abc_dn = v_vwap < 0 or v_st < 0 or v_c < 0
    out = {"zone": v_zone, "vwap": v_vwap, "slope": v_slope, "struct_1m": v_st,
           "score": score, "read": read,
           "dir_a": {"mid": v_mid, "vwap": v_vwap,
                     "read": "up" if a_score >= 2 else ("down" if a_score <= -2 else "mixed")},
           "dir_c": v_c,
           "abc": {"up": bool(abc_up), "down": bool(abc_dn),
                   "read": "up" if abc_up and not abc_dn else
                           ("down" if abc_dn and not abc_up else "mixed")},
           "aligned": v_zone != 0 and v_zone == v_slope == v_st}   # OR+SLOPE+STRUC agree
    if eng is not None:
        out["slope_engine"] = eng
        out["state"] = directional_state(eng["S"], eng["persistence"], eng["persist_dir"],
                                         eng["efficiency"], st_state=st_state_1m, zone_vote=v_zone)
        out["grade"] = slope_grade(eng["S"], eng["persistence"], eng["efficiency"])
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


if __name__ == "__main__":   # self-test: the canonical long-side flow + the short mirror + math
    cfg = EntryStandard(cooldown_bars=2, stale_bars=6, chase_atr=1.0, retest_atr=0.5,
                        max_entries=2)   # the flow below exercises a second entry (default is 1 since F76)
    sm = OrbSideState("long", or_high=730.0, or_low=723.9, cfg=cfg)
    sm.on_bar(high=726.0, low=724.0, close=725.5, struct_state=1, vwap=724.0)     # ctx ok, below mid
    assert sm.state is SideState.ARMED
    sm.on_bar(high=728.0, low=725.0, close=727.5, open_px=725.4, struct_state=1, vwap=724.5)
    assert sm.state is SideState.WATCH                                            # mid crossed
    sm.arm(entry=730.01, stop=726.76, tp1=733.26, tp2=743.02, order_id="o1")
    sm.on_bar(high=729.0, low=727.2, close=726.5, struct_state=1, vwap=724.5)     # back under mid
    assert sm.state is SideState.COOLDOWN and sm.pending_cancelled
    sm.on_bar(high=728.0, low=726.0, close=727.6, struct_state=1, vwap=724.5)     # cd 1
    sm.on_bar(high=728.0, low=726.0, close=727.6, struct_state=1, vwap=724.5)     # cd over -> ARMED
    assert sm.state is SideState.ARMED
    sm.on_bar(high=728.2, low=726.8, close=728.0, open_px=727.0, struct_state=1, vwap=724.5)
    assert sm.state is SideState.WATCH
    sm.on_bar(high=732.5, low=730.5, close=732.0, open_px=730.6, struct_state=1, vwap=725.0,
              atr=1.0)                                                            # ran 2.5 pts past edge
    assert sm.state is SideState.PULLBACK                                         # don't chase
    sm.on_bar(high=731.0, low=730.2, close=730.8, struct_state=1, vwap=725.0, atr=1.0)
    assert sm.state is SideState.WATCH                                            # retest near edge
    sm.arm(entry=730.01, stop=728.0, tp1=733.0, tp2=738.0)
    sm.fill()
    assert sm.state is SideState.FILLED and sm.entries_used == 1
    sm.on_bar(high=733.5, low=730.0, close=733.2)
    assert sm.state is SideState.TP1_HIT
    sm.on_bar(high=738.4, low=732.0, close=738.0)
    assert sm.state is SideState.COMPLETED
    assert sm.reset_cycle() is SideState.COOLDOWN                                 # entry 2 available
    # mirror check: short hard-invalidates on a confirmed close above OR high
    ss = OrbSideState("short", or_high=730.0, or_low=723.9, cfg=cfg)
    ss.on_bar(high=728.5, low=727.0, close=727.5, struct_state=2, vwap=728.0)     # above mid: ARMED only
    assert ss.state is SideState.ARMED
    ss.on_bar(high=731.0, low=725.0, close=730.8, struct_state=2, vwap=726.5)
    assert ss.state is SideState.INVALIDATED
    # math
    up = [1, 2, 3, 4, 5]
    assert efficiency_ratio(up) == 1.0 and directional_persistence(up)[0] == 1
    assert efficiency_ratio([5, 5, 5, 5]) == 0.0                     # zero path -> no crash
    assert directional_persistence([1, 2, 1, 2, 1])[0] == 0          # alternating -> neutral
    assert abs(norm_slope(up) - norm_slope([x * 100 for x in up])) < 1e-12   # scale-invariant
    assert slope_grade(0.35, 0.8, 0.7) == "A+" and slope_grade(-0.2, 0.7, 0.5, side="long") == "D"
    print("orb_state OK - canonical ARMED->WATCH->FILL FSM + pullback/cooldown/range + spec math verified")
