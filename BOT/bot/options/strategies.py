"""Options strategy translation (the Python computation the Pine cannot do).

Turns an ORB signal (side + entry/stop/tp) into the three structures the OPTIONS spec defines:
  • NAKED BUY  — long call (long bias) / long put (short bias), BUY ONLY.
  • DEBIT  vertical — long the chosen strike, short the strike at TP1 (caps cost + payoff).
  • CREDIT vertical — defined-risk on the OTHER side, short strike at the STRUCTURE STOP.
Each comes with real premium/Greeks/max-P/L/breakeven/R:R (BS by default; pass a chain-backed
price_fn for the real OPRA mid). 0DTE entry, ≤4-DTE hold. The user picks one at their discretion.
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field

from bot.options.pricing import price as bs_price, greeks as bs_greeks


# strike `n` steps ITM(n>0)/OTM(n<0)/ATM(0) vs entry, side-aware (matches the Pine f_strike_n)
def strike_n(entry: float, is_call: bool, n: int, inc: float = 1.0) -> float:
    f_floor = lambda p: math.floor(p / inc) * inc
    f_ceil = lambda p: math.ceil(p / inc) * inc
    if n == 0:
        return round(entry / inc) * inc
    if n > 0:                                   # ITM
        return f_floor(entry) - (n - 1) * inc if is_call else f_ceil(entry) + (n - 1) * inc
    return f_ceil(entry) + (-n - 1) * inc if is_call else f_floor(entry) - (-n - 1) * inc


@dataclass
class Leg:
    right: str          # "C" | "P"
    strike: float
    side: str           # "long" | "short"
    price: float        # per share
    delta: float


@dataclass
class OptionPlay:
    name: str
    legs: list[Leg]
    net: float                      # per-share debit(+)/credit(-) ; *100*contracts = $
    cost_or_credit_usd: float       # $ paid (debit) or received (credit)
    max_profit_usd: float
    max_loss_usd: float
    breakeven: float
    net_delta: float
    target_value_usd: float         # value if the underlying reaches TP2 (estimate)
    rr: float
    note: str = ""


def _mk(name, legs, mult, target_per_share, note=""):
    net = sum((l.price if l.side == "long" else -l.price) for l in legs)   # +debit / -credit
    net_d = sum((l.delta if l.side == "long" else -l.delta) for l in legs)
    cost_usd = net * mult
    tgt_usd = target_per_share * mult
    return net, cost_usd, tgt_usd, OptionPlay(name, legs, round(net, 4), 0, 0, 0, 0,
                                              round(net_d, 4), round(tgt_usd, 2), 0, note)


def signal_to_options(side: str, entry: float, stop: float, tp1: float, tp2: float,
                      S: float, iv: float, T: float, r: float = 0.04, inc: float = 1.0,
                      sel_n: int = 1, contracts: int = 1, price_fn=None) -> dict[str, OptionPlay]:
    """Return {naked, debit, credit} plays for the signal. price_fn(K,right)->per-share premium;
    defaults to Black-Scholes at (S, T, r, iv)."""
    px = price_fn or (lambda K, right: bs_price(S, K, T, r, iv, right))
    dlt = lambda K, right: bs_greeks(S, K, T, r, iv, right).delta
    mult = 100 * contracts
    is_long = side == "long"
    oc = "C" if is_long else "P"          # naked/debit side
    cc = "P" if is_long else "C"          # credit = the other side
    sgn = 1 if is_long else -1
    out: dict[str, OptionPlay] = {}

    # ---- NAKED BUY (long call / long put) ----
    k = strike_n(entry, is_long, sel_n, inc)
    prem = px(k, oc)
    tgt = bs_price(tp2, k, T, r, iv, oc)                       # value if underlying hits TP2
    p = OptionPlay("naked_buy", [Leg(oc, k, "long", round(prem, 4), dlt(k, oc))],
                   round(prem, 4), round(prem * mult, 2), float("inf"), round(prem * mult, 2),
                   round(k + sgn * prem, 2), round(dlt(k, oc), 4), round(tgt * mult, 2),
                   round((tgt - prem) / prem, 2) if prem > 0 else 0.0,
                   "buy-only; max loss = premium; convex, theta-decays (prefer 0DTE)")
    out["naked"] = p

    # ---- DEBIT vertical (long k, short at TP1) ----
    ks = round(tp1 / inc) * inc
    long_p, short_p = px(k, oc), px(ks, oc)
    net = long_p - short_p
    width = abs(ks - k)
    tgt_d = bs_price(tp2, k, T, r, iv, oc) - bs_price(tp2, ks, T, r, iv, oc)
    out["debit"] = OptionPlay(
        "debit_spread", [Leg(oc, k, "long", round(long_p, 4), dlt(k, oc)),
                         Leg(oc, ks, "short", round(short_p, 4), dlt(ks, oc))],
        round(net, 4), round(net * mult, 2), round((width - net) * mult, 2), round(net * mult, 2),
        round(k + sgn * net, 2), round(dlt(k, oc) - dlt(ks, oc), 4), round(tgt_d * mult, 2),
        round((width - net) / net, 2) if net > 0 else 0.0,
        f"capped at TP1 ${ks:g}; cheaper than naked, defined payoff")

    # ---- CREDIT vertical (short at structure stop, other side, defined risk) ----
    k_short = round(stop / inc) * inc
    k_long = k_short - inc if is_long else k_short + inc          # one strike further OTM = protection
    short_c, long_c = px(k_short, cc), px(k_long, cc)
    credit = short_c - long_c
    width_c = abs(k_short - k_long)
    out["credit"] = OptionPlay(
        "credit_spread", [Leg(cc, k_short, "short", round(short_c, 4), dlt(k_short, cc)),
                          Leg(cc, k_long, "long", round(long_c, 4), dlt(k_long, cc))],
        round(-credit, 4), round(credit * mult, 2), round(credit * mult, 2),
        round((width_c - credit) * mult, 2),
        round(k_short - sgn * credit, 2), round(dlt(k_long, cc) - dlt(k_short, cc), 4),
        round(credit * mult, 2),                                 # at TP2 the short side expires worthless
        round(credit / (width_c - credit), 2) if (width_c - credit) > 0 else 0.0,
        f"defined-risk {'bull put' if is_long else 'bear call'}; short @ stop ${k_short:g}, profits on theta/move")
    return out


if __name__ == "__main__":   # self-test on a QQQ-like long signal
    plays = signal_to_options("long", entry=545.0, stop=543.0, tp1=547.0, tp2=553.0,
                              S=545.0, iv=0.20, T=4 / 365, sel_n=1, contracts=1)
    for kind, p in plays.items():
        legs = " / ".join(f"{l.side} {l.right}{l.strike:g}@{l.price}" for l in p.legs)
        print(f"{kind:7} [{p.name}] {legs}")
        print(f"        cost/credit ${p.cost_or_credit_usd}  maxP ${p.max_profit_usd}  maxL ${p.max_loss_usd}  "
              f"BE {p.breakeven}  Δ {p.net_delta}  R:R {p.rr}  | {p.note}")
    assert plays["naked"].legs[0].right == "C" and plays["credit"].legs[0].right == "P"
    assert plays["debit"].max_loss_usd > 0 and plays["credit"].max_loss_usd > 0
    print("\noptions strategies OK")
