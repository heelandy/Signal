"""Capital Preservation + Prop-Firm engine (CPE-001 / PFR-001 / RRL-001).

Evaluates an account against a funded/prop ruleset: profit target, daily-loss limit, (trailing or
static) max drawdown, min trading days, consistency, and previous-green-day protection. Returns the
eval STATE (active / passed / failed), room to each limit, and whether a NEW trade is allowed — a
fail-closed gate the risk layer / dashboard consult. (Signal engine: advisory; you place the trade.)
"""
from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class PropProfile:
    name: str
    account_size: float
    profit_target: float        # $ to pass
    daily_loss: float           # $ max loss in a day
    max_drawdown: float         # $ drawdown allowance
    trailing: bool = True       # trailing (from peak) vs static (from start)
    max_contracts: int = 10
    min_days: int = 1
    consistency_pct: float = 0.40   # no single day > 40% of total profit
    halt_buffer: float = 0.0    # stop trading this buffer $ BEFORE a hard limit
    protect_green_pct: float = 0.50  # CPE: keep this share of a green day (don't give it all back)


# common funded-eval shapes (the bot's documented defaults: target/daily/trailing)
PROFILES = {
    "50k":  PropProfile("50k Eval",  50_000, 3_000, 1_100, 2_000, True, max_contracts=5,  halt_buffer=200),
    "100k": PropProfile("100k Eval", 100_000, 6_000, 2_200, 3_000, True, max_contracts=10, halt_buffer=300),
    "150k": PropProfile("150k Eval", 150_000, 9_000, 3_300, 4_500, True, max_contracts=15, halt_buffer=400),
}


def evaluate(p: PropProfile, equity: float, peak_equity: float | None = None,
             day_pnl: float = 0.0, days_traded: int = 0, best_day_profit: float = 0.0,
             yesterday_green: float = 0.0) -> dict:
    """Eval verdict + room. yesterday_green = yesterday's realised profit (for green-day protection)."""
    peak_equity = peak_equity or max(equity, p.account_size)
    total_profit = equity - p.account_size
    dd_floor = (peak_equity - p.max_drawdown) if p.trailing else (p.account_size - p.max_drawdown)
    # hard limits (with halt buffer applied early)
    daily_floor = -(p.daily_loss - p.halt_buffer)
    daily_loss_hit = day_pnl <= daily_floor
    dd_hit = equity <= dd_floor + p.halt_buffer
    target_hit = total_profit >= p.profit_target
    consistency_ok = (best_day_profit <= p.consistency_pct * total_profit) if total_profit > 0 else True
    # CPE previous-green-day protection: don't give back more than (1-protect) of yesterday's green today
    green_protect_floor = -(1 - p.protect_green_pct) * yesterday_green if yesterday_green > 0 else None
    green_breach = green_protect_floor is not None and day_pnl <= green_protect_floor

    if daily_loss_hit or dd_hit:
        status = "failed"
    elif target_hit and days_traded >= p.min_days and consistency_ok:
        status = "passed"
    else:
        status = "active"
    can_trade = status == "active" and not daily_loss_hit and not dd_hit and not green_breach
    return {
        "profile": p.name, "status": status, "can_trade": can_trade,
        "equity": round(equity, 2), "total_profit": round(total_profit, 2),
        "room_to_target": round(p.profit_target - total_profit, 2),
        "room_to_daily_loss": round(day_pnl - daily_floor, 2),
        "room_to_drawdown": round(equity - (dd_floor + p.halt_buffer), 2),
        "drawdown_floor": round(dd_floor, 2), "consistency_ok": consistency_ok,
        "green_day_protected": bool(green_breach),
        "block_reason": ("daily_loss" if daily_loss_hit else "max_drawdown" if dd_hit
                         else "green_day_protection" if green_breach else None),
    }


if __name__ == "__main__":
    p = PROFILES["100k"]
    print("100k eval, fresh:", evaluate(p, 100_000)["status"], "| can_trade", evaluate(p, 100_000)["can_trade"])
    print("up $4k:", {k: evaluate(p, 104_000, 104_000)[k] for k in ("status", "room_to_target", "room_to_drawdown")})
    print("passed (+$6.2k, 2 days):", evaluate(p, 106_200, 106_200, days_traded=2, best_day_profit=2000)["status"])
    print("daily-loss breach:", evaluate(p, 98_000, 100_000, day_pnl=-2000)["block_reason"])
    print("trailing-DD breach:", evaluate(p, 100_500, 104_000, day_pnl=-200)["block_reason"])
    g = evaluate(p, 100_500, 101_000, day_pnl=-600, yesterday_green=1000)
    print("green-day protection:", g["block_reason"], "| can_trade", g["can_trade"])
    print("prop engine OK")
