"""Strategy-module registry (AITP-001 §6 — the module contract, machine-readable).

Every asset-class × trading-style combination is a MODULE with the full AITP contract: market
context, setup, entry, pullback, exit, stop, target, risk rules, trade limits, learning labels
and approval requirements. `status` tells the truth: only the ORB day-trading modules are
implemented; the rest are SPECS awaiting research. Served at /api/strategy/modules.
"""
from __future__ import annotations

from bot.strategy.orb_candidates import STRATEGY_VERSION

_ORB_CONTRACT = {
    "market_context": "Layer 1 — Structure (1m-fed swing state) + session-VWAP side must align "
                      "(hard on equities, grade-only on futures — A/B 2026-07-04)",
    "setup_rules": "Opening-range breakout: OR 09:30-10:00 ET; vol-expansion OR-width>=2.4 ATR; "
                   "OR-mid day bias; macro regime gates (block D)",
    "entry_logic": "Layer 3 — confirmed close beyond OR mid (WATCH) -> strong full-body close "
                   "beyond OR high/low + next-candle continuation + direction sequence (FILL)",
    "pullback_logic": "chase cap 1.0 ATR -> PULLBACK state -> OR-edge retest within 0.5 ATR "
                      "(deep-research refinements deferred by user)",
    "exit_logic": "full position to the TP2 cap (F34b); session-end flat",
    "stop_loss": "structure-anchored swing stop (F25b), min 0.5/0.75 ATR, max 2.5/1.5 ATR",
    "profit_target": "TP1 1.5R (advisory scale point), TP2 4R cap",
    "risk_rules": "bot.risk gate: 0.25% risk/trade, daily 0.75%, weekly 2%, trailing 3%, "
                  "streak lockout 2, correlated-exposure buckets, kill switch, news lockout",
    "trade_limits": "max 3 trades/day; 2 entries/side/session equities, 3 futures; "
                    "one position at a time; one bet per correlation bucket",
    "performance_tracking": "tracker first-touch outcomes + scorecard vs backtest + Training Lab",
    "ml_nn_labels": "y_win / y_tp2 / y_stop / net_R / rejects(block reason + missed outcome) / "
                    "live_outcomes(missed_winner|missed_loser)",
    "approval_requirements": "AITP ladder research->replay->paper->live; paper autotrade "
                             "hard-blocked without 'paper'; live needs the lock file + 'live' stage",
}

STRATEGY_MODULES = [
    {"id": "equities_day_orb", "asset_class": "equities", "style": "day_trading",
     "symbols": ["QQQ", "SPY"], "status": "implemented", "strategy_version": STRATEGY_VERSION,
     **_ORB_CONTRACT},
    {"id": "futures_day_orb", "asset_class": "futures", "style": "day_trading",
     "symbols": ["NQ", "MNQ", "ES"], "status": "implemented", "strategy_version": STRATEGY_VERSION,
     **_ORB_CONTRACT,
     "market_context": _ORB_CONTRACT["market_context"] + " — futures run 3 OR sessions "
                       "(Asia 19:00, London 03:00, RTH 09:30 ET)"},
    {"id": "futures_day_orb_gold", "asset_class": "futures", "style": "day_trading",
     "symbols": ["GC", "MGC"], "status": "unverified_edge", "strategy_version": STRATEGY_VERSION,
     **_ORB_CONTRACT,
     "setup_rules": _ORB_CONTRACT["setup_rules"] + " — F30 gold edge NOT reproduced; signals for context only"},
    {"id": "options_day_orb", "asset_class": "options", "style": "options_trading",
     "symbols": ["QQQ", "SPY"], "status": "implemented_translation",
     "strategy_version": STRATEGY_VERSION, **_ORB_CONTRACT,
     "entry_logic": "underlying ORB signal translated to 0-4 DTE structures "
                    "(naked/debit/credit via bot.options; exit plan at underlying TP1/TP2/stop)"},
    {"id": "equities_scalping", "asset_class": "equities", "style": "scalping",
     "symbols": [], "status": "spec_only",
     "notes": "requires 1m execution loop + tighter cost model; research not started",
     "approval_requirements": "full AITP ladder from research"},
    {"id": "futures_scalping", "asset_class": "futures", "style": "scalping",
     "symbols": [], "status": "spec_only",
     "notes": "candidate base: 1m ORB micro-breaks + L2 flow features once depth data is wired",
     "approval_requirements": "full AITP ladder from research"},
    {"id": "equities_swing", "asset_class": "equities", "style": "swing_trading",
     "symbols": [], "status": "spec_only",
     "notes": "daily-bar structure + regime module; labels = multi-day triple-barrier",
     "approval_requirements": "full AITP ladder from research"},
    {"id": "futures_swing", "asset_class": "futures", "style": "swing_trading",
     "symbols": [], "status": "spec_only",
     "notes": "needs continuous-contract roll handling in the execution layer (data already rolls)",
     "approval_requirements": "full AITP ladder from research"},
]


def modules(status: str | None = None) -> list[dict]:
    return [m for m in STRATEGY_MODULES if status is None or m["status"] == status]


if __name__ == "__main__":
    for m in STRATEGY_MODULES:
        print(f"{m['id']:22} {m['asset_class']:8} {m['style']:15} [{m['status']}] {m.get('symbols')}")
    print(f"{len(STRATEGY_MODULES)} modules — contract keys: {sorted(_ORB_CONTRACT)}")
