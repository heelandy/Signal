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
     "symbols": ["QQQ", "SPY"], "status": "gauntlet_pass",
     "strategy_version": "options-0.1", **_ORB_CONTRACT,
     "entry_logic": "underlying ORB signal -> NAKED 0DTE buy (call long / put short) ONLY — the "
                    "payoff replay (research/options_replay.py 2026-07-06) PASSES naked on both "
                    "(QQQ +0.268 ret/premium PF 2.05 9/9 yrs, IV-robust; SPY +0.123 PF 1.5 9/9, "
                    "marginal at IV .30) and REJECTS debit+credit verticals (capping the 4R tail "
                    "/ selling the breakout direction kills the low-WR big-winner edge). IV is "
                    "model-approximated — paper must verify real fills before sizing",
     "notes": "ladder lineage: options-0.1; translation layer bot/options; leg shadow-recording "
              "already rides every tracked signal"},
    {"id": "options_native_vrp", "asset_class": "options", "style": "options_trading",
     "symbols": ["SPY", "QQQ"], "status": "research_candidate",
     "notes": "OPTIONS-ONLY strategy search (research/options_native.py 2026-07-06): short daily "
              "ATM straddle (variance risk premium) PASSES the numeric gate huge — SPY +0.376 "
              "ret/premium win 81.6% PF 5.35 9/9 yrs OOS +0.412; QQQ +0.307 PF 3.69 9/9. "
              "NOT adoptable from this test: VIX (30d implied) priced a 1-DAY straddle, which "
              "likely OVERPRICES premium and inflates the short side; worst day -7.15x premium "
              "(unbounded tail, no sizing model). Long straddle = dead (mirror confirms VRP). "
              "Needs real 0DTE chain IV + tail-risk sizing before any ladder",
     "approval_requirements": "real chain data confirm -> then full AITP ladder from research"},
    {"id": "equities_scalping", "asset_class": "equities", "style": "scalping",
     "symbols": [], "status": "spec_only",
     "notes": "requires 1m execution loop + tighter cost model; research not started",
     "approval_requirements": "full AITP ladder from research"},
    {"id": "futures_scalping", "asset_class": "futures", "style": "scalping",
     "symbols": [], "status": "spec_only",
     "notes": "candidate base: 1m ORB micro-breaks + L2 flow features once depth data is wired",
     "approval_requirements": "full AITP ladder from research"},
    {"id": "equities_swing", "asset_class": "equities", "style": "swing_trading",
     "symbols": ["QQQ"], "status": "gauntlet_pass", "strategy_version": "swing-1d-0.1",
     "notes": "FULL 7/7 GAUNTLET PASS (research/swing_gauntlet.py 2026-07-05): QQQ daily EMA20>50 "
              "pullback-reclaim, stop 1.5ATR tgt 2R horizon 20 — n77 +0.538R PF 2.23 OOS +0.687 "
              "dd -7R, survives 2x costs, 8/9 years positive. SPY FAILS (4/9 years, IS half "
              "negative) — not adopted. OPTIONS (cross-test 2026-07-06): 21-DTE passes in TWO "
              "structures — naked +0.311 ret/risk 6/6 yrs AND debit vertical +0.236 6/6 (the "
              "higher-WR defined-target profile carries a spread; the only stream where one "
              "works). Ladder lineage: swing-1d-0.1",
     "approval_requirements": "full AITP ladder from research"},
    {"id": "futures_swing", "asset_class": "futures", "style": "swing_trading",
     "symbols": ["NQ"], "status": "gauntlet_pass", "strategy_version": "swing-fut-1d-0.1",
     "notes": "FULL 7/7 GAUNTLET PASS (2026-07-05): NQ daily 20-day BREAKOUT + EMA50 side (the "
              "pullback rules fail futures dailies) — n222 +0.123R PF 1.21 dd -12.6R, 2x-cost "
              "+0.103, 11/17 years positive. ES FAILS years (9/17). Execution still needs "
              "continuous-contract roll handling before paper. Ladder lineage: swing-fut-1d-0.1",
     "approval_requirements": "full AITP ladder from research"},
    {"id": "daily_volbreak", "asset_class": "multi", "style": "day_trading",
     "symbols": ["NQ", "QQQ", "SPY"], "status": "gauntlet_pass", "strategy_version": "volbreak-1d-0.1",
     "notes": "F52 GRADUATE re-confirmed under the current engine 2026-07-05 (research/"
              "strat_daily.py): volatility breakout, stop-entry at open ± 0.3x prior-day range, "
              "EOD exit, gap-aware fills. NQ +0.094R PF 1.54 17/17 YEARS · QQQ +0.103R PF 1.69 "
              "9/9 · SPY +0.086R PF 1.55 9/9, all OOS+. ES/GC FAIL — not included. CAVEAT: thin "
              "(~12 bps/trade) => slippage-sensitive; paper must verify live fills before sizing. "
              "OPTIONS (cross-test 2026-07-06): 0DTE NAKED is its BEST expression — QQQ +1.01 "
              "ret/premium PF 3.30 9/9 yrs OOS +1.11, SPY +0.63 PF 2.51 9/9 (debit/credit fail). "
              "Ladder lineage: volbreak-1d-0.1",
     "approval_requirements": "full AITP ladder from research"},
    {"id": "equities_connors_rsi2", "asset_class": "equities", "style": "swing_trading",
     "symbols": ["QQQ", "SPY"], "status": "gauntlet_pass", "strategy_version": "connors-1d-0.1",
     "notes": "F52 GRADUATE re-confirmed 2026-07-05: Connors RSI-2 (close>SMA200 & RSI2<10 long / "
              "mirror short), 1-5 day hold. QQQ +0.325R PF 1.97 win 73% 7/8 years · SPY +0.334R "
              "PF 2.14 win 77% 7/8, both OOS+. CAVEAT: REGIME-DEPENDENT — rides the post-2018 "
              "dip-buy regime, fails NQ/ES over 2010+ history; equities-only, size small, revisit "
              "if the dip-buy regime breaks. Ladder lineage: connors-1d-0.1",
     "approval_requirements": "full AITP ladder from research"},
]


def modules(status: str | None = None) -> list[dict]:
    return [m for m in STRATEGY_MODULES if status is None or m["status"] == status]


if __name__ == "__main__":
    for m in STRATEGY_MODULES:
        print(f"{m['id']:22} {m['asset_class']:8} {m['style']:15} [{m['status']}] {m.get('symbols')}")
    print(f"{len(STRATEGY_MODULES)} modules — contract keys: {sorted(_ORB_CONTRACT)}")
