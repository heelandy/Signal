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
    {"id": "equities_qqq_composite", "asset_class": "equities", "style": "day_trading",
     "symbols": ["QQQ"], "status": "gauntlet_pass", "strategy_version": "qqq-composite-0.1",
     "notes": "QQQ CONFLUENCE AT THE OPEN (F108, gauntlet-passed 2026-07-10 after the equity "
              "cost-model fix — ALL 7): Monday + fade-yesterday votes |v|>=2 == LONG on a MONDAY "
              "AFTER A DOWN FRIDAY, 9:30 open -> 16:00 close. n=172 +19.6bps WR 61 PF 1.57 CI_lo "
              "+5.5 7/9 yrs OOS +24.0 2x-slip +18.9 — the equities twin of the NQ weekend "
              "complex; on QQQ the OPEN beats the 10:35 entry. EQ SHARES book (overnight "
              "precedent: option theta eats a 1-day ~20bps edge). Stop grid queued in the "
              "battery. Ladder lineage: qqq-composite-0.1",
     "approval_requirements": "full AITP ladder from research"},
    {"id": "equities_spy_monday", "asset_class": "equities", "style": "day_trading",
     "symbols": ["SPY"], "status": "gauntlet_pass", "strategy_version": "spy-monday-0.1",
     "notes": "SPY MONDAY DRIFT (F108, ALL 7 after the cost fix): LONG every Monday 9:30 open -> "
              "16:00 close. n=382 +9.0bps WR 59 PF 1.40 CI_lo +2.3 7/9 yrs OOS +11.9 2x +8.5. "
              "Single census cell — confluence needs >=2 votes and SPY has one, so this is a "
              "CALENDAR rule, not a composite. EQ SHARES book. Stop grid queued. "
              "Ladder lineage: spy-monday-0.1",
     "approval_requirements": "full AITP ladder from research"},
    {"id": "futures_nq_composite", "asset_class": "futures", "style": "day_trading",
     "symbols": ["NQ"], "status": "gauntlet_pass", "strategy_version": "nq-composite-0.1",
     "notes": "PATTERN COMPOSITE (F104, gauntlet-passed 2026-07-10 — ALL 7): the census pass-"
              "cells as VOTES at 10:30 ET (Monday drift + big-first-hour momentum + fade-"
              "yesterday + gap-up follow); trade ONLY on CONFLUENCE |votes|>=2, enter 10:35, exit "
              "the 16:00 close. n=1320 +6.3bps net WR 57 PF 1.22 CI_lo +2.2 **15/17 YEARS** OOS "
              "+9.5 2x-slip +4.4 — the most year-consistent rule in the book. Vol-cluster sizing "
              "overlay (high-vol days ~4x edge) is the V2 upgrade. Stacked-mining bias is real "
              "despite pre-registration -> shadow accrual judges (research/nq_composite_gauntlet"
              ".py). Ladder lineage: nq-composite-0.1",
     "approval_requirements": "full AITP ladder from research"},
    {"id": "futures_weekend_fade", "asset_class": "futures", "style": "session_trading",
     "symbols": ["NQ"], "status": "gauntlet_pass", "strategy_version": "weekend-fade-0.1",
     "notes": "WEEKEND FADE (F95->F97b, gauntlet-passed 2026-07-10 — ALL 7 WITH ITS STOP): weak "
              "FRIDAY RTH close (bottom third of the range) -> LONG NQ at the SUNDAY 18:00 reopen "
              "-> STOP at entry - 0.5x Friday's RTH range (the stop IMPROVES the edge: +8.5bps vs "
              "+7.9 no-stop, PF 1.50, CI_lo +2.6, OOS +22.5bps, worst capped -2.35%) -> else exit "
              "Monday 03:00. n=247, 12/17 yrs, WR 59%. NOTE: the daily 18:00->03:00 spec (F96) was "
              "DECOMPOSED — its weekday cohort is DEAD OOS (-0.3bps); Friday-only IS the edge "
              "(research/weekend_fade_gauntlet.py). Ladder lineage: weekend-fade-0.1",
     "approval_requirements": "full AITP ladder from research"},
    {"id": "futures_volbreak", "asset_class": "futures", "style": "day_trading",
     "symbols": ["NQ"], "status": "gauntlet_pass", "strategy_version": "volbreak-fut-0.1",
     "notes": "VOLATILITY BREAKOUT, OUTRIGHT NQ FUTURES (isolated from the options book, user "
              "2026-07-08). Stop-entry at open ± 0.3x prior-day range, EOD flat, gap-aware fills "
              "(research/strat_daily.py). NQ +0.094R PF 1.53 17/17 YEARS OOS+ — the most robust "
              "underlying edge in the book. ~30% both-levels-hit days are path-assumed (bar-level "
              "check before sizing). CAVEAT: thin (~12 bps/trade) => trade as futures (low cost), "
              "NOT options. Ladder lineage: volbreak-fut-0.1",
     "approval_requirements": "full AITP ladder from research"},
    {"id": "equities_volbreak", "asset_class": "options", "style": "options_trading",
     "symbols": ["QQQ", "SPY"], "status": "gauntlet_pass", "strategy_version": "volbreak-0dte-0.1",
     "notes": "VOLATILITY BREAKOUT expressed as 0DTE NAKED OPTIONS (isolated from the futures "
              "book, user 2026-07-08). Same open ± 0.3x prior-day-range trigger; on a break, buy "
              "the 0DTE call/put (convex — the large fast move pays for the gamma). Cross-test "
              "2026-07-06: QQQ +1.01 ret/premium PF 3.30 9/9 yrs OOS +1.11 · SPY +0.63 PF 2.51 9/9 "
              "(debit/credit fail — naked only). Underlying QQQ +0.103R PF 1.69, SPY +0.086R PF "
              "1.55, both 9/9. Ladder lineage: volbreak-0dte-0.1",
     "approval_requirements": "full AITP ladder from research"},
    {"id": "equities_overnight", "asset_class": "equities", "style": "swing_trading",
     "symbols": ["QQQ", "SPY"], "status": "gauntlet_pass", "strategy_version": "overnight-1d-0.1",
     "notes": "OVERNIGHT DRIFT (research/overnight_drift.py + overnight_hardening.py, 2026-07-08): buy "
              "MOC / sell next MOO — the night effect (Lou-Polk-Skouras, JFE 2019). QQQ +0.034R PF 1.14 "
              "8/9 · SPY +0.032R PF 1.12 8/9, BOTH survive 2x cost AND the 2022-26 regime; the intraday "
              "(O->C) leg FAILS, confirming the effect is overnight. Concentrates AFTER a down close "
              "(QQQ 9/9 yrs) — the wired conditioning. VEHICLE: SHARES only (options frictions exceed "
              "the ~0.03%/night edge). Isolated from volbreak so the two never share a book. Ladder "
              "lineage: overnight-1d-0.1",
     "approval_requirements": "full AITP ladder from research"},
    {"id": "futures_tsmom", "asset_class": "futures", "style": "swing_trading",
     "symbols": ["NQ"], "status": "gauntlet_pass", "strategy_version": "tsmom-fut-0.1",
     "notes": "TIME-SERIES MOMENTUM (Moskowitz-Ooi-Pedersen, JFE 2012; research/tsmom.py, 2026-07-09): "
              "sign of the trailing 12-mo (skip last mo) return -> position for the next month. "
              "LONG-ONLY on NQ (the short side loses on secularly-rising indices, which broke the "
              "2-sided gauntlet). Long NQ 12mo: expR +0.81, PF 1.58, 81% of years+, OOS +1.11%, CI+. "
              "OUTRIGHT futures (shares book); a slow trend overlay complementing the intraday/vol "
              "strategies as ORB fades. Ladder lineage: tsmom-fut-0.1",
     "approval_requirements": "full AITP ladder from research"},
    # ── BOSS WORKERS (docs/BOSS_WORKERS_PLAN.md, discovery rounds F80 2026-07-06) — the
    # high-WR per-symbol specs (band: WR 75-85 · PF >= 1.7 · DD <= 10R OOS) under the Main Boss ──
    {"id": "worker_q_qqq", "asset_class": "equities", "style": "day_trading",
     "symbols": ["QQQ"], "status": "research_candidate", "strategy_version": "worker-q-0.1",
     "notes": "HIGH-WR worker: 07.7 stack · target 0.40x stop · slope-STRONG tier. OOS IN BAND "
              "(WR 82.6 PF 1.79 DD -3.0) but IS PF 1.21 and OOS n=23 — needs more data/holdout "
              "before freeze; the pooled loser-veto HURT it (cut winners) and is NOT deployed. "
              "Boss contract: bot/boss.py worker-q",
     "approval_requirements": "full AITP ladder from research"},
    {"id": "worker_s_spy", "asset_class": "equities", "style": "day_trading",
     "symbols": ["SPY"], "status": "research_candidate", "strategy_version": "worker-s-0.1",
     "notes": "HIGH-WR worker: 07.7 stack · target 0.33x stop (no tier survived both halves — "
              "slope/wide-OR were era artifacts). OOS WR 82.7 PF 1.43; needs the veto or more "
              "data to close the PF gap. Boss contract: worker-s",
     "approval_requirements": "full AITP ladder from research"},
    {"id": "worker_n_nq", "asset_class": "futures", "style": "day_trading",
     "symbols": ["NQ", "MNQ"], "status": "research_candidate", "strategy_version": "worker-n-0.1",
     "notes": "HIGH-WR worker: 07.7 stack · target 0.30x stop · EARLY-ONLY tier (<12:00 ET — "
              "improves BOTH halves: OOS PF 1.16->1.34, DD -13.8->-7.5, n343). IS era still "
              "PF 0.82 — regime question open. Boss contract: worker-n",
     "approval_requirements": "full AITP ladder from research"},
    {"id": "worker_e_es", "asset_class": "futures", "style": "day_trading",
     "symbols": ["ES", "MES"], "status": "obsolete", "strategy_version": "worker-e-0.1",
     "notes": "OBSOLETE 2026-07-06 (worker_specs + worker_cohorts F80): PF < 1 at EVERY "
              "tight-target cell and tier (best OOS 0.93 late-only), DD -23..-31R, on top of the "
              "standing 2x-slip fragility. High-WR ES worker does not exist under current costs. "
              "Revival requires a fresh full gauntlet on NEW data. ES stays a SIGNALS-ONLY "
              "worker for the Boss's market read",
     "approval_requirements": "fresh full gauntlet on new data, then the ladder from research"},
    {"id": "worker_g_gc", "asset_class": "futures", "style": "day_trading",
     "symbols": ["GC", "MGC"], "status": "obsolete", "strategy_version": "worker-g-0.1",
     "notes": "OBSOLETE 2026-07-06 (F80): IS PF 0.07-0.25 at every cell; best combo "
              "(slope+early) OOS PF 0.46 — the F30 edge stays non-reproducible. Per user rule G "
              "still LADDERS TO PAPER as SIGNALS-ONLY (paper evidence may promote or bury it "
              "for good). Boss refuses to arm it",
     "approval_requirements": "paper signals-only; revival = fresh full gauntlet on new data"},
    {"id": "equities_trail_exit", "asset_class": "equities", "style": "day_trading",
     "symbols": ["QQQ", "SPY"], "status": "gauntlet_pass", "strategy_version": "trail-eq-0.1",
     "notes": "FULL 7/7 GAUNTLET PASS x2 (gauntlet_trail_hg.py 2026-07-07, F84): the canonical "
              "07.7 entries with a CHANDELIER-TRAIL exit instead of the 4R cap — the "
              "expectancy-first profile found in F82. QQQ exp +0.305R CI-lo +0.16 OOS +0.539 "
              "PF 1.70 2x-frictions +0.278 · SPY +0.223 CI-lo +0.067 OOS +0.403 PF 1.51 2x "
              "+0.194 — both 7/9 years positive. ~50% WR: EXCEEDS the goal's PF leg, not the "
              "WR band — runs as its own lineage, judged on expectancy. Ladder: trail-eq-0.1",
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
