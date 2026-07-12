"""PARITY GOLDEN PIN (P1.2, 2026-07-11): the engine's fixed-tape signal sequence is a
BEHAVIORAL CONTRACT — any change that moves one entry breaks this test on purpose (then either
the change is a bug, or the golden is regenerated deliberately WITH the Pine side re-verified).
research/parity_goldens.py regenerates; TradingView bar-replay diffs against the same JSON."""
from __future__ import annotations

import json
import os
import sys

import pytest

pd = pytest.importorskip("pandas")

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
GOLDEN = os.path.join(ROOT, "BOT", "tests", "goldens", "parity_signals.json")


def test_engine_matches_the_pinned_golden_sequence():
    sys.path.insert(0, os.path.join(ROOT, "research"))
    import parity_goldens as PG
    fresh = PG.build()
    pinned = json.loads(open(GOLDEN, encoding="utf-8").read())
    assert fresh["fires"] == pinned["fires"], (
        "the engine's fixed-tape signal sequence CHANGED — either a parity bug was introduced, "
        "or regenerate the golden deliberately (python research/parity_goldens.py) and "
        "re-verify the Pine side against it")
    assert len(pinned["fires"]) == 3
    assert [f["ts_et"][-5:] for f in pinned["fires"]] == ["10:20", "10:05", "10:35"]
    assert all(f["side"] == "long" for f in pinned["fires"])
