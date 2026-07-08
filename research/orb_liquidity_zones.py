#!/usr/bin/env python3
"""SHIM — the liquidity-zone engine was PROMOTED to `BOT/bot/strategy/liquidity_zones.py`
(2026-07-06 repo-hygiene: production F67 clean-air must not import from research/). This
re-export keeps the research drivers (zone_bounce, orb_zones_additive, orb_zone_entries) and
the old CLI working unchanged; the BOT file is the single source of truth — edit THAT one.

    python research/orb_liquidity_zones.py --selftest
    python research/orb_liquidity_zones.py NQ ES
"""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "BOT"))
from bot.strategy.liquidity_zones import *                                   # noqa: F401,F403,E402
from bot.strategy.liquidity_zones import (_atr, _label, detect_zones,        # noqa: F401,E402
                                          evaluate, selftest,
                                          ReversalStateMachine, Zone,
                                          WEIGHTS, WINDOWS, TOUCH_MIN, WICK_BODY, REL_VOL,
                                          MERGE_ATR, HALF_W_ATR, AGE_HALF_LIFE, SCORE_BANDS)

if __name__ == "__main__":
    args = [a for a in sys.argv[1:] if not a.startswith("-")]
    if "--selftest" in sys.argv or not args:
        selftest()
    for s in args:
        evaluate(s)
