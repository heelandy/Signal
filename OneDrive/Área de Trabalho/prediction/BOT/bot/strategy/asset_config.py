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
    ladder: bool = False        # F66 SIZING LADDER (AUTO per side-of-edge): EQUITIES take the UNCONFIRMED break as a
                                # 0.4x STARTER tranche (that cohort is +0.34R QQQ / +0.16R SPY) and ADD to full on
                                # structure confirm; FUTURES stay BINARY (wait for structure — their unconfirmed
                                # cohort is flat/negative). v2 cut-on-opposite REJECTED — starter rides its normal exit.
    clean_air: bool = False     # F67 CLEAN-AIR (GRADUATED: 2x-slip + walk-forward pass on NQ+QQQ): a breakout into
                                # CLEAR air (no MAJOR/STRONG liquidity zone within ~2-3 ATR ahead) lifts exp+CIlo and
                                # the WALL cohort (zone overhead) is negative. NQ/QQQ/SPY on (SPY by-twin, 1m-data
                                # pending). ES/GC OFF (marginal/dead base). from-zone origin = irrelevant.
    ctx_gate: bool = True       # ENTRY STANDARD Layer-1 context (Structure+VWAP hard arm) PER ASSET — A/B 2026-07-04:
                                # helps EQUITIES (QQQ +0.34->+0.45 avgR PF 1.7, SPY +0.24->+0.33, both with lower DD)
                                # but HURTS FUTURES (NQ +0.155->+0.109, ES +0.087->+0.041 — chart-TF structure lags).
                                # Equities ON / futures OFF (context stays a GRADE there). Mirrors the Pine ctx_auto.
    cooldown_bars: int | None = None   # per-asset Layer-3 overrides (None = ENTRY_STANDARD default).
    stale_bars: int | None = None      # SPY: sweep candidate cd0/stale12/retest0.25 PASSED the full
    retest_atr: float | None = None    # 7-check gauntlet 2026-07-05 (OOS +0.753 vs +0.572, PF 2.4) -> adopted.
    instant_fill: bool = True          # fill the aligned breakout candle immediately (07.2). ES
                                       # keeps the F59c wait: instant flipped it +0.090 -> +0.057
                                       # avg R (rebuild A/B 2026-07-05) — the fragile-execution
                                       # instrument needs the continuation confirm.
    ctx_mode: str | None = None        # DIR-FAST A (user 2026-07-05): Layer-1 arming pair.
                                       # "mid_vwap" = OR-MID side + VWAP side (the NEW standard; structure
                                       # and slope become GRADES: struct aligned = A+, slope aligned = A).
                                       # "struct_vwap" = the previous standard (fallback B). "none" = plain.
                                       # None = derive from ctx_gate (True->struct_vwap, False->none).
    note: str = ""


def resolve_ctx_mode(a: "Asset") -> str:
    """The side-arming pair for this asset: explicit ctx_mode wins; else legacy ctx_gate mapping."""
    if a.ctx_mode:
        return a.ctx_mode
    return "struct_vwap" if a.ctx_gate else "none"


_FUT3 = (ASIA_FUT, LON_FUT, RTH_FUT)     # futures trade all 3 sessions

# entry_delay = 0 (arm at OR close, delay-0) + chase_atr guard so an early break doesn't chase — it waits
# for a retest near the level. Equities take a tight 1.5-ATR max stop (reversal cap); futures keep 2.5 (room).
# ctx_mode (DIR-FAST pairs test 2026-07-05, OOS-ranked): equities arm best from STRUCT+VWAP
# (QQQ +0.374 / SPY +0.753 OOS avg R); futures from the user's MID+VWAP pair (NQ +0.213 vs
# +0.104 struct; ES +0.153) — MID+VWAP UPGRADES NQ/ES vs the old no-context arming.
ASSETS = {
    # NQ gauntlet 7/7 (07.2, 2026-07-05): cd0/stale12/retest0.25 — OOS +0.117 vs +0.109, PF 1.20,
    # maxDD -9.8 vs -11.1R (fewer trades: 174 vs 226 OOS — per-trade quality over volume). MNQ mirrors.
    "NQ":  Asset("NQ",  True,  20.0, 0.50, 0, sessions=_FUT3, options_root=None, status="validated", max_entries=3, clean_air=True, ctx_gate=True, ctx_mode="mid_vwap",
                 cooldown_bars=0, stale_bars=12, retest_atr=0.25),
    "MNQ": Asset("MNQ", True,   2.0, 0.50, 0, sessions=_FUT3, options_root=None, status="validated", max_entries=3, ctx_gate=True, ctx_mode="mid_vwap",
                 cooldown_bars=0, stale_bars=12, retest_atr=0.25),
    "ES":  Asset("ES",  True,  50.0, 0.50, 0, sessions=_FUT3, options_root=None, status="validated", max_entries=3, ctx_gate=True, ctx_mode="mid_vwap", instant_fill=False),
    # QQQ gauntlet 7/7 (07.2, 2026-07-05): cd5/stale12/retest0.25 — OOS +0.419 vs +0.374, PF 1.66,
    # maxDD -6.2 vs -9.1R (fewer trades: 61 vs 82 OOS — per-trade quality over volume).
    "QQQ": Asset("QQQ", False,  1.0, 0.75, 0, sessions=(RTH_EQ,), options_root="QQQ", status="validated", max_entries=2, sl_max_atr=1.5, ladder=True, clean_air=True, ctx_mode="struct_vwap",
                 cooldown_bars=5, stale_bars=12, retest_atr=0.25),
    "SPY": Asset("SPY", False,  1.0, 0.75, 0, sessions=(RTH_EQ,), options_root="SPY", status="validated", max_entries=2, sl_max_atr=1.5, ladder=True, clean_air=True, ctx_mode="struct_vwap",
                 cooldown_bars=0, stale_bars=12, retest_atr=0.25),
    "GC":  Asset("GC",  True, 100.0, 0.50, 0,  sessions=(RTH_FUT,), options_root="GLD", status="unverified", max_entries=3, ctx_gate=True, ctx_mode="mid_vwap",
                 note="F30 gold edge NOT reproduced under the current engine (fails all configs "
                      "2026-06-29) — US-morning only, signals shown for context, edge NOT validated"),
}

DEFAULT = Asset("?", False, 1.0, 0.75, 0, sessions=(RTH_EQ,), status="unverified", max_entries=1, note="no per-asset config")


def asset_config(symbol: str) -> Asset:
    return ASSETS.get(symbol.upper(), DEFAULT)


def struct_lb(symbol: str) -> int:
    """Structure pivot lookback per instrument (fast-direction study 2026-07): futures use lb=3 — the faster
    swing keeps the FULL structure edge (NQ +0.285 vs +0.290 at lb5) while catching MORE + EARLIER breakouts;
    equity uses lb=5 (QQQ needs it — lb=3 fails its gauntlet; SPY ~tied). Mirrors the Pine auto_lb toggle."""
    return 3 if asset_config(symbol).is_futures else 5


if __name__ == "__main__":
    for s in ("NQ", "QQQ", "SPY", "GC", "TSLA"):
        a = asset_config(s)
        print(f"{s:5} {'FUT' if a.is_futures else 'EQ ':3} pv {a.point_value:>5} minStop {a.min_stop_atr} "
              f"delay {a.entry_delay} opt {str(a.options_root):4} [{a.status}]" + (f"  {a.note[:60]}" if a.note else ""))
    print("asset config OK")
