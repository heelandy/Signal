"""Intrabar direction score (0–100) + signal state machine — Evidence.docx §"Intrabar direction
score" and §"Signal state machine".

The score fuses the order-flow features into one directional conviction; the state machine turns a
persistent high score into an ARMED→ENTER decision and exits on an early imbalance flip. This is the
MBO confirmation layer that sits on top of the rule-based ORB candidate (per BUILD_PLAN §4 v2).

    from bot.orderflow.score import score_row, DirectionStateMachine, Dir
"""
from __future__ import annotations

from dataclasses import dataclass
from enum import Enum

# Evidence weights, restricted to the features we compute from L3 MBO (renormalised to 100).
# (HTF context + setup location are supplied by the ORB layer, not the order-flow layer.)
W = {"qi": 30.0, "ati": 25.0, "micro": 20.0, "zcd": 15.0, "vel": 10.0}

# thresholds (Evidence "recommended starting"): contribute full weight past the arm level
TH = {"qi": 0.15, "ati": 0.20, "micro": 0.10, "zcd": 1.0, "vel": 0.0}


def _contrib(val: float, weight: float, arm: float, sign_ref: float) -> float:
    """Signed contribution: full `weight` once |val|>=arm in the trade direction, scaled below."""
    if sign_ref == 0 or val == 0:
        return 0.0
    aligned = (val > 0) == (sign_ref > 0)
    mag = min(abs(val) / arm, 1.0) if arm > 0 else 1.0
    return (weight if aligned else -weight) * mag


def score_row(qi: float, ati: float, dmu: float, zcd: float, vel: float, direction: int) -> float:
    """0–100 conviction that price moves `direction` (+1 long / −1 short) right now."""
    raw = (_contrib(qi, W["qi"], TH["qi"], direction)
           + _contrib(ati, W["ati"], TH["ati"], direction)
           + _contrib(dmu, W["micro"], TH["micro"], direction)
           + _contrib(zcd, W["zcd"], TH["zcd"], direction)
           + _contrib(vel, W["vel"], 1.0, direction))
    return max(0.0, raw)            # only the aligned side scores; opposite evidence -> 0


class Dir(Enum):
    LONG = 1
    SHORT = -1


class State(str, Enum):
    FLAT = "flat"
    ARMED = "armed"
    ENTER = "enter"
    ACTIVE = "active"
    EARLY_FAILURE = "early_failure"
    LOCKOUT = "lockout"


@dataclass
class DirectionStateMachine:
    """Evidence signal states. Feed it the running score + a few flags each event/bar.

    arm_score: score to ARM (WATCH→ARMED). enter_score: to fire. persist: consecutive events the
    enter condition must hold (kills one-tick false signals). A quick opposite flip while ACTIVE →
    EARLY_FAILURE (the early-exit Evidence stresses)."""
    direction: Dir
    arm_score: float = 65.0
    enter_score: float = 80.0
    persist: int = 3
    state: State = State.FLAT
    _hits: int = 0

    def update(self, score: float, opposite_score: float = 0.0, filled: bool = False) -> State:
        if self.state in (State.LOCKOUT,):
            return self.state
        if self.state in (State.FLAT, State.ARMED):
            self.state = State.ARMED if score >= self.arm_score else State.FLAT
            self._hits = self._hits + 1 if score >= self.enter_score else 0
            if self._hits >= self.persist:
                self.state = State.ENTER
        elif self.state is State.ENTER:
            self.state = State.ACTIVE if filled else State.ENTER
        elif self.state is State.ACTIVE:
            if opposite_score >= self.enter_score:        # imbalance flipped hard -> bail early
                self.state = State.EARLY_FAILURE
        return self.state


if __name__ == "__main__":   # self-test + a live demo on the reconstructed book
    # score logic: aligned strong book scores high; opposing scores 0
    s_long = score_row(qi=0.4, ati=0.35, dmu=0.25, zcd=1.6, vel=1.2, direction=1)
    s_opp = score_row(qi=-0.4, ati=-0.35, dmu=-0.25, zcd=-1.6, vel=-1.2, direction=1)
    assert s_long > 90 and s_opp == 0, (s_long, s_opp)
    print(f"score: strong-aligned {s_long:.0f}/100, fully-opposed {s_opp:.0f}/100")

    sm = DirectionStateMachine(Dir.LONG, persist=3)
    seq = [60, 70, 82, 85, 88]   # warms up, then 3 consecutive >=80 -> ENTER
    states = [sm.update(s).value for s in seq]
    assert states[-1] == "enter", states
    print("state machine:", " -> ".join(states))
    assert sm.update(85, opposite_score=90).value in ("enter", "active", "early_failure")

    try:
        from bot.orderflow.features import book_bbo, trade_features
        bb = book_bbo("2026-05-26", ("09:30", "09:33"))
        tf = trade_features("2026-05-26", ("09:30", "09:33"))
        if len(bb) and len(tf):
            ati0 = float(tf["ati"].dropna().iloc[0]); zcd0 = 0.0
            row = bb.iloc[len(bb) // 2]
            sc = score_row(row["qi"], ati0, row["dmu"], zcd0, 0.0, direction=1)
            print(f"demo live score @ {row['ts_et'].time()} (long): {sc:.0f}/100  "
                  f"(qi {row['qi']:+.2f} dmu {row['dmu']:+.2f} ati {ati0:+.2f})")
    except Exception as e:
        print("live demo skipped:", e)
    print("orderflow score OK")
