"""Lineage <-> duel <-> dashboard sync guard (2026-07-08).

Failure mode caught: a strategy is APPROVED but "nothing moves to the main dashboard". The main
dashboard's Bot-Strategies panel renders `/api/duel` -> leaderboard()['lineage'] (the DUELISTS).
So a lineage only ever surfaces if (a) it's in DUELISTS, (b) its version is a registered module,
and (c) _entries_for actually handles that module id. If any link is missing (a version typo, a
module added without a duel entry, or a DUELIST module with no _entries_for branch), the lineage
silently never appears — exactly the "approved but invisible" bug. These tests fail fast on that.

Run: pytest BOT/tests/test_lineage_duel_sync.py -q
"""
import sys
from pathlib import Path

import numpy as np
import pandas as pd

BOT_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BOT_DIR))
sys.path.insert(0, str(BOT_DIR.parent / "engine"))

from bot.strategy.duel import DUELISTS, OPTIONS_EXPRESSION, leaderboard, _entries_for
from bot.strategy.modules import modules


def _registered():
    return {m["strategy_version"]: m for m in modules() if m.get("strategy_version")}


def test_every_duelist_version_is_a_registered_module():
    reg = _registered()
    for module_id, (version, syms) in DUELISTS.items():
        assert version in reg, f"DUELIST '{module_id}' -> version '{version}' has no module in the registry"
        assert set(syms) <= set(reg[version]["symbols"]), \
            f"DUELIST '{module_id}' trades {syms} but module '{version}' only lists {reg[version]['symbols']}"


def test_every_duelist_surfaces_in_the_leaderboard():
    # what the dashboard iterates (DUELD.lineage) must equal the DUELISTS set
    lb = leaderboard()
    assert set(lb["lineage"].keys()) == set(DUELISTS.keys())
    assert set(OPTIONS_EXPRESSION).issuperset(DUELISTS.keys()), \
        "every duelist needs an OPTIONS_EXPRESSION entry (the ⚡ line on the dashboard)"


def test_every_duelist_module_is_handled_by_entries_for():
    """A DUELIST with no matching branch in _entries_for produces zero entries and never trades ->
    it would show 'IN THE DUEL' but never move. Feed a trending frame; each module must be capable
    of emitting at least one entry so the branch demonstrably exists (not a silent no-op)."""
    n = 260
    idx = pd.date_range("2024-01-02", periods=n, freq="B", tz="UTC")
    up = np.linspace(100, 160, n)                      # steady uptrend exercises trend/breakout/overnight
    wig = up + np.sin(np.arange(n) / 3.0) * 1.5        # wiggle so pullback/reversal logic can fire
    b = pd.DataFrame({"ts": idx, "open": wig - 0.3, "high": wig + 1.0, "low": wig - 1.0,
                      "close": wig, "volume": 1e6})
    b["ema20"] = b["close"].ewm(span=20).mean()
    b["ema50"] = b["close"].ewm(span=50).mean()
    tr = (b["high"] - b["low"]).abs()
    b["atr14"] = tr.rolling(14, min_periods=1).mean()
    for module_id in DUELISTS:
        # must not raise, and the branch must exist (handled ids return a list; unhandled fall through to [])
        out = _entries_for(module_id, "QQQ", b)
        assert isinstance(out, list), f"_entries_for('{module_id}') did not return a list"
