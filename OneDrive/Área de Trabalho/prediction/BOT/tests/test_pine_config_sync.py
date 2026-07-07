"""PINE <-> BOT CONFIG SYNC (2026-07-06 final misconfig check).

The per-asset entry knobs live in THREE hand-synced places: bot/strategy/asset_config.py and the
`auto_asset` derivation blocks in production/HIGHSTRIKE_ORB_STACK.pine + HIGHSTRIKE_ORB_AUTO.pine.
That is exactly the drift class that shipped the F75 bug ("abc" missing from one surface), so this
test machine-verifies the tables instead of trusting the hand-sync:

  1. both Pines carry an IDENTICAL auto-asset derivation block (8 knobs);
  2. the values parsed out of the Pine equal asset_config/layer3_kwargs for NQ, MNQ, ES, QQQ, SPY;
  3. the auto_asset tooltip cites the CURRENT STRATEGY_VERSION (a version bump without a Pine
     update fails here on purpose — the Pine claims must move with the rule).
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from bot.strategy.asset_config import asset_config, layer3_kwargs
from bot.strategy.orb_candidates import STRATEGY_VERSION

ROOT = Path(__file__).resolve().parents[2]
PINES = [ROOT / "production" / "HIGHSTRIKE_ORB_STACK.pine",
         ROOT / "production" / "HIGHSTRIKE_ORB_AUTO.pine"]

# the derived knob names, in the order they appear in the auto block
KNOBS = ("chase_max", "stale_n", "cooldown_n", "wait_ft", "instant_fill", "block_range",
         "retest_atr", "retest_target")
PINE_TO_MODE = {"Impulse midpoint": "impulse_mid", "OR edge": "edge", "VWAP": "vwap"}


def _auto_block(text: str) -> dict[str, str]:
    """Extract `<name> = auto_asset ? <expr> : <name>_in` derivations, keyed by knob name."""
    out = {}
    for name in KNOBS:
        m = re.search(rf"^\s*(?:float|int|bool|string)\s+{name}\s*=\s*auto_asset\s*\?\s*(.+?)\s*:\s*{name}_in\s*$",
                      text, re.M)
        assert m, f"auto_asset derivation for '{name}' missing"
        out[name] = re.sub(r"\s+", " ", m.group(1).strip())
    return out


def _pine_effective(block: dict[str, str], sym: str) -> dict:
    """Evaluate the Pine ternaries for one symbol (the way the script's _a* flags resolve)."""
    is_nq = sym in ("NQ", "MNQ")
    is_es = sym in ("ES", "MES")
    is_fut = sym in ("NQ", "MNQ", "ES", "MES", "GC")
    flags = {"_aNQ": is_nq, "_aES": is_es, "_aQQQ": sym == "QQQ", "_aSPY": sym == "SPY"}

    def num_ternary(expr, flag):
        m = re.fullmatch(rf"\(({flag}) \? ([\d.]+) : ([\d.]+)\)", expr)
        assert m, f"unexpected Pine expr: {expr}"
        return float(m.group(2)) if flags[flag] else float(m.group(3))

    eff = {"chase_max": num_ternary(block["chase_max"], "_aNQ"),
           "stale_n": int(num_ternary(block["stale_n"], "_aES")),
           "cooldown_n": int(num_ternary(block["cooldown_n"], "_aES")),
           "retest_atr": num_ternary(block["retest_atr"], "_aES")}
    assert block["wait_ft"] == "not _aQQQ"
    eff["wait_ft"] = not flags["_aQQQ"]
    assert block["instant_fill"] == "not (_aES or _aSPY)"
    eff["instant_fill"] = not (flags["_aES"] or flags["_aSPY"])
    assert block["block_range"] == 'syminfo.type != "futures"'
    eff["block_range"] = not is_fut
    m = re.fullmatch(r'\(_aNQ \? "([^"]+)" : "([^"]+)"\)', block["retest_target"])
    assert m, f"unexpected retest_target expr: {block['retest_target']}"
    eff["retest_target"] = m.group(1) if is_nq else m.group(2)
    return eff


@pytest.fixture(scope="module")
def blocks():
    return {p.name: _auto_block(p.read_text(encoding="utf-8")) for p in PINES}


def test_stack_and_auto_carry_identical_auto_blocks(blocks):
    names = list(blocks)
    assert blocks[names[0]] == blocks[names[1]], "STACK and AUTO auto-asset blocks diverged"


@pytest.mark.parametrize("sym", ["NQ", "MNQ", "ES", "QQQ", "SPY"])
def test_pine_auto_values_match_asset_config(blocks, sym):
    a = asset_config(sym)
    l3 = layer3_kwargs(a)
    for fname, block in blocks.items():
        eff = _pine_effective(block, sym)
        ctx = f"{fname}:{sym}"
        assert eff["chase_max"] == pytest.approx(a.chase_atr), f"{ctx} chase"
        assert eff["stale_n"] == l3["stale_bars"], f"{ctx} stale"
        assert eff["cooldown_n"] == l3["cooldown_bars"], f"{ctx} cooldown"
        assert eff["retest_atr"] == pytest.approx(l3["retest_atr"]), f"{ctx} retest_atr"
        assert eff["wait_ft"] == a.ft_confirm, f"{ctx} wait_ft/ft_confirm"
        assert eff["instant_fill"] == a.instant_fill, f"{ctx} instant_fill"
        assert eff["block_range"] == a.block_range, f"{ctx} block_range"
        assert PINE_TO_MODE[eff["retest_target"]] == l3["retest_mode"], f"{ctx} retest_target"


def test_auto_tooltip_cites_current_rule_version():
    for p in PINES:
        text = p.read_text(encoding="utf-8")
        m = re.search(r"auto_asset\s*=\s*input\.bool\((.*?)\)\n", text, re.S)
        assert m, f"{p.name}: auto_asset input not found"
        assert STRATEGY_VERSION in m.group(1), (
            f"{p.name}: auto_asset tooltip cites a stale rule version — update the Pine claims "
            f"to {STRATEGY_VERSION} (this failing is the point: Pine must move with the rule)")
