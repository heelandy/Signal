"""CANONICAL ENTRY GROUP ID (Signal-Certificate T2, 2026-07-12).

ONE stable identifier per entry group, shared by every path — backtest, live scanner, tracker,
execution order, broker fill, profitability matrix, removal registry. Resolves the audited name
mismatch (backtest `orb@5m`, live family `breakout`, execution setup `orb_stack` all denote the
SAME ORB continuation group and must share one id):

    PR-{CAT}-{SESSION}-{TF}-{PATTERN}-{SIDE}-v{n}      e.g. PR-FT-RTH-5M-ORB_C-L-v1

    from bot.strategy.entry_group import entry_group_id
    entry_group_id("NQ", "long", "rth", "5m", "orb@5m")   # == same id for "breakout"/"orb_stack"
"""
from __future__ import annotations

PATTERN_VERSION = "v1"          # the pattern-recognition version (separate from strategy_version)

# legacy family/setup names -> the canonical pattern code. ORB is empirically ONE pattern (PR1
# 2026-07-12: ORB-C and ORB-RT do not separate); the retest is a per-asset timing knob, not a group.
_PATTERN = {
    "orb": "ORB_C", "orb_c": "ORB_C", "orb-c": "ORB_C",
    "breakout": "ORB_C", "orb_stack": "ORB_C", "orb-stack": "ORB_C", "orb_break": "ORB_C",
    # reserved for future certified groups:
    "orb_rt": "ORB_RT", "lq_sr": "LQ_SR", "fail_bo": "FAIL_BO", "comp_x": "COMP_X", "vw_r": "VW_R",
}


def canonical_pattern(family: str | None) -> str:
    """Map any legacy family/setup name to the canonical pattern code (UNKNOWN if unrecognized —
    never guessed)."""
    f = str(family or "").lower().strip()
    if f in _PATTERN:
        return _PATTERN[f]
    base = f.split("@")[0].strip()            # 'orb@5m' -> 'orb'
    return _PATTERN.get(base, "UNKNOWN")


def entry_group_id(symbol: str, side: str, session: str | None, tf: str,
                   family: str | None, pattern_version: str = PATTERN_VERSION) -> str:
    """The canonical group id. Case/format-normalized so the SAME group always resolves identically
    regardless of which path (backtest/scan/execution) supplied the family name."""
    from bot.strategy.asset_config import asset_category
    cat = asset_category(symbol, family).upper()             # EQ / FT / OP
    pat = canonical_pattern(family)
    sess = (str(session or "rth").lower() or "rth").upper()
    tfu = str(tf or "5m").lower().replace("m", "M").replace("h", "H").replace("d", "D")
    sd = str(side or "").lower()
    s = "L" if sd.startswith("l") else ("S" if sd.startswith("s") else "?")
    return f"PR-{cat}-{sess}-{tfu}-{pat}-{s}-{pattern_version}"


if __name__ == "__main__":
    for fam in ("orb@5m", "breakout", "orb_stack"):
        print(f"{fam:10} -> {entry_group_id('NQ', 'long', 'rth', '5m', fam)}")
    print("QQQ:", entry_group_id("QQQ", "short", "rth", "15m", "breakout"))
