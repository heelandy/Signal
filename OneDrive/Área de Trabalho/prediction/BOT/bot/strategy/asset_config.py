"""Per-asset setup — each instrument trades the breakout with its own params + validation status.

Validated (F58/F61/F62): NQ/MNQ, QQQ, SPY — the close-confirm + dir-seq ORB, struct stop, cap-4R,
skip-first-hour. Equities are commission-free with a 0.75-ATR min-stop floor; futures use MNQ costs
and a 0.5-ATR floor. GOLD is flagged UNVERIFIED: the F30 edge does NOT reproduce under the current
engine (fails every config tried 2026-06-29) — tracked for signals but NOT a validated edge.
"""
from __future__ import annotations

from dataclasses import dataclass


# Session OR windows. Equity = calendar minutes (tradeday=False). Futures = trade-day minutes since
# 18:00 ET (tradeday=True): 18:00=0, 19:00=60, 20:00=120, 03:00=540, 09:30=930, 16:00=1320.
# (name, or_start, or_end, cut, tradeday)
RTH_EQ   = ("rth",    570, 600,  900, False)         # 09:30-10:00 OR, stop new 15:00 (F62)
ASIA_FUT = ("asia",    60, 120,  540, True)          # 19:00-20:00 OR, trade to 03:00 (F22)
LON_FUT  = ("london", 540, 570,  840, True)          # 03:00-03:30 OR, trade to 08:00 (F29)
RTH_FUT  = ("rth",    930, 960, 1260, True)           # 09:30-10:00 OR, trade to 15:00 (F62)


@dataclass(frozen=True)
class Asset:
    symbol: str
    is_futures: bool
    point_value: float          # $ per 1.0 point (sizing)
    min_stop_atr: float         # min-stop floor (F51): futures 0.5, equity 0.75
    entry_delay: int            # arm delay: minutes after OR close before the break can fire (0 = arm at OR close)
    sessions: tuple = (RTH_EQ,)  # OR windows to scan (futures = 3, equity = 1)
    options_root: str | None = None   # OPRA root for the options play (None = futures-only)
    status: str = "validated"   # "validated" | "unverified"
    max_entries: int = 1        # entries per side per SESSION with re-test re-arm (user: futures 3, equity 2)
    sl_max_atr: float = 2.5     # MAX stop width (reversal cap): equity 1.5 (tight — arm-timing test), futures 2.5 (need room, tight whipsaws)
    chase_atr: float = 1.0      # no-chase guard (F57): only fire within N*ATR of the level, else wait for a retest near it
    note: str = ""


_FUT3 = (ASIA_FUT, LON_FUT, RTH_FUT)     # futures trade all 3 sessions

# entry_delay = 0 (arm at OR close, delay-0) + chase_atr guard so an early break doesn't chase — it waits
# for a retest near the level. Equities take a tight 1.5-ATR max stop (reversal cap); futures keep 2.5 (room).
ASSETS = {
    "NQ":  Asset("NQ",  True,  20.0, 0.50, 0, sessions=_FUT3, options_root=None, status="validated", max_entries=3),
    "MNQ": Asset("MNQ", True,   2.0, 0.50, 0, sessions=_FUT3, options_root=None, status="validated", max_entries=3),
    "ES":  Asset("ES",  True,  50.0, 0.50, 0, sessions=_FUT3, options_root=None, status="validated", max_entries=3),
    "QQQ": Asset("QQQ", False,  1.0, 0.75, 0, sessions=(RTH_EQ,), options_root="QQQ", status="validated", max_entries=2, sl_max_atr=1.5),
    "SPY": Asset("SPY", False,  1.0, 0.75, 0, sessions=(RTH_EQ,), options_root="SPY", status="validated", max_entries=2, sl_max_atr=1.5),
    "GC":  Asset("GC",  True, 100.0, 0.50, 0,  sessions=(RTH_FUT,), options_root="GLD", status="unverified", max_entries=3,
                 note="F30 gold edge NOT reproduced under the current engine (fails all configs "
                      "2026-06-29) — US-morning only, signals shown for context, edge NOT validated"),
}

DEFAULT = Asset("?", False, 1.0, 0.75, 0, sessions=(RTH_EQ,), status="unverified", max_entries=1, note="no per-asset config")


def asset_config(symbol: str) -> Asset:
    return ASSETS.get(symbol.upper(), DEFAULT)


if __name__ == "__main__":
    for s in ("NQ", "QQQ", "SPY", "GC", "TSLA"):
        a = asset_config(s)
        print(f"{s:5} {'FUT' if a.is_futures else 'EQ ':3} pv {a.point_value:>5} minStop {a.min_stop_atr} "
              f"delay {a.entry_delay} opt {str(a.options_root):4} [{a.status}]" + (f"  {a.note[:60]}" if a.note else ""))
    print("asset config OK")
