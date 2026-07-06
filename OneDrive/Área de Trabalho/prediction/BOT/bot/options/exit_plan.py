"""Options exit plan — WHERE TP1/TP2 sit and which option structure exits where (F64).

Research (F64): TP2 = 4R is the validated knee (cap-4, plateau 4-6R, best OOS); TP1 = 1.5R is the
best scale/debit-cap point; medMFE ~1R means MOST trades only run ~1R (4R is a fat-tail target). So:

  • DEBIT vertical  — long@entry-strike, SHORT@TP1(1.5R). The WORKHORSE: most trades reach ~1R, the
                      spread caps at TP1, defined cost. Take it as the default.
  • NAKED long      — runs to TP2(4R). The convex TAIL-CAPTURE for clean trend days; cheap, theta-decays.
                      Scale: sell half at TP1, let half run to TP2.
  • CREDIT vertical — short@structure-stop, defined risk. Theta/range income; close at ~50% credit or
                      TP2, stop if the underlying tags the structure stop.

    from bot.options.exit_plan import options_exit_plan
    plan = options_exit_plan(candidate)      # levels + 3 structures w/ exits + recommendation
"""
from __future__ import annotations

from bot.contracts import TradeCandidate
from bot.options.pricing import year_frac
from bot.options.strategies import signal_to_options

TP1_RR, TP2_RR = 1.5, 4.0      # F64: TP1 = debit cap / scale point; TP2 = naked target / final cap

# GATE VERDICTS per structure on ORB signals (payoff replay 2026-07-06, research/options_replay.py
# + options_cross.py) — the single source every UI shows (user: "show the information according
# to the gate they pass").
STRUCTURE_GATES = {"naked": "PASS (QQQ PF 2.05 / SPY 1.5, 9/9 yrs)",
                   "debit": "FAIL on ORB (passes only on swing QQQ @21DTE)",
                   "credit": "FAIL (all streams)"}


def options_exit_plan(c: TradeCandidate, iv: float = 0.20, dte: int = 0, sel_n: int = 1,
                      contracts: int = 1) -> dict:
    sign = c.side.sign
    risk = c.risk
    tp1 = round(c.entry + sign * TP1_RR * risk, 2)
    tp2 = round(c.entry + sign * TP2_RR * risk, 2)
    T = year_frac(60) + dte / 365.0
    plays = signal_to_options(c.side.value, c.entry, c.stop, tp1, tp2, c.entry, iv, T,
                              sel_n=sel_n, contracts=contracts)

    exits = {
        "naked": {"target": f"TP2 {tp2} ({TP2_RR}R)", "scale": f"sell half at TP1 {tp1}, run half to TP2 {tp2}",
                  "stop": f"underlying tags structure stop {c.stop}",
                  "when": "THE VALIDATED PLAY — the ORB's low-WR/big-winner profile needs convexity"},
        "debit": {"target": f"TP1 {tp1} ({TP1_RR}R) — short leg caps it here",
                  "manage": "close near the short strike; defined cost", "stop": f"underlying stop {c.stop}",
                  "when": "REJECTED for ORB signals — capping the 4R tail kills the edge"},
        "credit": {"target": f"close ~50% of credit, or by TP2 {tp2} / expiry", "manage": "theta works for you",
                   "stop": f"underlying tags the short strike near the structure stop {c.stop}",
                   "when": "REJECTED — selling the predicted direction fails every stream"},
    }
    gates = STRUCTURE_GATES
    out = {"underlying": {"symbol": c.symbol, "side": c.side.value, "entry": c.entry, "stop": c.stop,
                          "tp1": tp1, "tp2": tp2, "tp1_rr": TP1_RR, "tp2_rr": TP2_RR, "risk": round(risk, 2)},
           "recommended": "naked",
           "rationale": "payoff replay verdict (2026-07-06): NAKED is the only structure that "
                        "passes on ORB signals — the 4R tail pays; spreads cap or sell it. "
                        "Debit/credit shown for reference with their FAIL gates.",
           "structures": {}}
    for k, p in plays.items():
        out["structures"][k] = {"legs": [f"{l.side} {l.right}{l.strike:g}@{l.price}" for l in p.legs],
                                "gate": gates.get(k, "untested"),
                                "cost_or_credit_usd": p.cost_or_credit_usd, "max_loss_usd": p.max_loss_usd,
                                "max_profit_usd": ("unlimited" if p.max_profit_usd == float("inf") else p.max_profit_usd),
                                "breakeven": p.breakeven, "rr": p.rr, "exit": exits[k]}
    return out


if __name__ == "__main__":
    import json
    for reg in ("A", "C"):
        c = TradeCandidate(symbol="QQQ", side="long", timeframe="5m", setup="breakout",
                           entry=722.0, stop=720.0, tp2=730, regime=reg, strategy_version="t",
                           generated_at="2026-06-29T14:30:00+00:00")
        plan = options_exit_plan(c)
        u = plan["underlying"]
        print(f"\nregime {reg}: entry {u['entry']} stop {u['stop']} -> TP1 {u['tp1']}(1.5R) TP2 {u['tp2']}(4R) "
              f"| RECOMMEND: {plan['recommended'].upper()}")
        for k, s in plan["structures"].items():
            mark = " <<" if k == plan["recommended"] else ""
            print(f"   {k:7} {' / '.join(s['legs'])}  cost ${s['cost_or_credit_usd']} maxL ${s['max_loss_usd']} "
                  f"R:R {s['rr']} | exit: {s['exit']['target']}{mark}")
    print("\noptions exit plan OK")
