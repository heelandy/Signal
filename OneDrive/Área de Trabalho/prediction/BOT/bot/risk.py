"""Risk gate v1 — the highest authority. No trade moves without an APPROVED RiskDecision.

Pure decision service: `decide(candidate, account, limits) -> RiskDecision`. No broker calls, no
hidden writes. Fail-closed and ordered — the first failing rule wins, with a reason code. Defaults
are the Evidence.docx "first-live" day-trade settings.

    from bot.risk import decide, Account
    rd = decide(candidate, Account(equity=25_000))
    if rd.approved: ... qty = rd.max_qty
"""
from __future__ import annotations

from dataclasses import dataclass, field

from bot.config import settings
from bot.contracts import RiskDecision, RiskStatus, ReasonCode, TradeCandidate, Mode

# per-point $ value for sizing (equities/ETFs trade in $/share = 1.0)
POINT_VALUE = {"NQ": 20.0, "MNQ": 2.0, "ES": 50.0, "MES": 5.0, "GC": 100.0, "MGC": 10.0}


@dataclass
class RiskLimits:
    risk_per_trade: float = 0.0025      # 0.25% of equity (Evidence 0.20–0.35%)
    max_daily_loss: float = 0.0075      # 0.75% (Evidence 0.75–1.0%)
    max_trailing_dd: float = 0.03       # 3% peak-to-now stand-down
    max_trades_per_day: int = 3
    max_consecutive_losses: int = 2
    max_open_positions: int = 1         # one position at a time (Evidence: one strategy at a time)
    min_rr: float = 1.5                 # reward-to-first-target floor
    max_contracts: int = 50             # absolute cap for FUTURES contracts
    max_notional_mult: float = 4.0      # equity/ETF: position notional <= this × equity (sizing safety)


@dataclass
class Account:
    equity: float
    peak_equity: float | None = None
    daily_pnl: float = 0.0              # today's realized PnL ($); negative = down
    open_positions: int = 0
    trades_today: int = 0
    consecutive_losses: int = 0
    kill_switch: bool = False
    source_healthy: bool = True
    mode: Mode = Mode.REPLAY
    point_value: dict[str, float] = field(default_factory=lambda: dict(POINT_VALUE))

    def __post_init__(self):
        self.mode = Mode(self.mode)
        if self.peak_equity is None:
            self.peak_equity = self.equity


def _block(cid, code, notes=""):
    return RiskDecision(candidate_id=cid, status=RiskStatus.BLOCKED, reason_code=code, notes=notes)


def _reject(cid, code, notes=""):
    return RiskDecision(candidate_id=cid, status=RiskStatus.REJECTED, reason_code=code, notes=notes)


def decide(c: TradeCandidate, acct: Account, limits: RiskLimits | None = None) -> RiskDecision:
    L = limits or RiskLimits()
    cid = c.candidate_id

    # --- account/market state blocks (fail-closed, checked first) ---
    if acct.kill_switch:
        return _block(cid, ReasonCode.KILL_SWITCH, "manual kill switch active")
    if not acct.source_healthy:
        return _block(cid, ReasonCode.SOURCE_HEALTH_CRITICAL, "market data not certified")
    if acct.mode is Mode.LIVE and not settings.live_allowed:
        return _block(cid, ReasonCode.LIVE_LOCKED, "live mode requires the readiness lock")
    if acct.daily_pnl <= -L.max_daily_loss * acct.equity:
        return _block(cid, ReasonCode.DAILY_LOSS_LIMIT,
                      f"daily PnL {acct.daily_pnl:.0f} <= -{L.max_daily_loss:.2%} equity")
    if acct.peak_equity and (acct.peak_equity - acct.equity) >= L.max_trailing_dd * acct.peak_equity:
        return _block(cid, ReasonCode.TRAILING_DRAWDOWN, "trailing drawdown limit hit")
    if acct.trades_today >= L.max_trades_per_day:
        return _block(cid, ReasonCode.MAX_TRADES_PER_DAY, f"{acct.trades_today} trades today")
    if acct.consecutive_losses >= L.max_consecutive_losses:
        return _block(cid, ReasonCode.CONSECUTIVE_LOSSES, f"{acct.consecutive_losses} losses in a row")
    if acct.open_positions >= L.max_open_positions:
        return _block(cid, ReasonCode.MAX_OPEN_POSITIONS, f"{acct.open_positions} already open")

    # --- candidate-quality rejects ---
    if c.risk <= 0:
        return _reject(cid, ReasonCode.NO_STOP, "non-positive stop distance")
    if c.rr < L.min_rr:
        return _reject(cid, ReasonCode.RR_TOO_LOW, f"R:R {c.rr:.2f} < {L.min_rr}")

    # --- sizing ---
    risk_dollars = acct.equity * L.risk_per_trade
    pv = acct.point_value.get(c.symbol.upper(), 1.0)
    risk_per_unit = c.risk * pv
    qty = int(risk_dollars // risk_per_unit) if risk_per_unit > 0 else 0
    if qty < 1:
        return _reject(cid, ReasonCode.MAX_CONTRACTS,
                       f"risk/unit ${risk_per_unit:.2f} > budget ${risk_dollars:.2f} (account too small)")
    cap = L.max_contracts if pv != 1.0 else int(L.max_notional_mult * acct.equity / c.entry)  # futures vs equity
    qty = min(qty, max(cap, 1))
    return RiskDecision(candidate_id=cid, status=RiskStatus.APPROVED, reason_code=ReasonCode.OK,
                        max_qty=qty, max_risk_dollars=round(qty * risk_per_unit, 2),
                        stop_policy="struct", target_policy="cap4",
                        notes=f"risk ${risk_dollars:.0f} @ ${risk_per_unit:.2f}/unit")


if __name__ == "__main__":   # self-test: one approve + each block/reject path
    def cand(entry=100.0, stop=99.0, tp2=104.0, sym="QQQ"):
        return TradeCandidate(symbol=sym, side="long", timeframe="5m", setup="orb_stack",
                              entry=entry, stop=stop, tp2=tp2, strategy_version="t")
    base = Account(equity=25_000)
    ok = decide(cand(), base)   # $1 stop, $62.5 budget -> 62 shares (well under the notional cap)
    assert ok.approved and ok.max_qty == 62, ok.to_json()
    print("approve:", ok.status.value, "qty", ok.max_qty, "risk$", ok.max_risk_dollars, "|", ok.notes)

    checks = [
        ("kill",      Account(equity=25_000, kill_switch=True),            ReasonCode.KILL_SWITCH),
        ("stale",     Account(equity=25_000, source_healthy=False),        ReasonCode.SOURCE_HEALTH_CRITICAL),
        ("dailyloss", Account(equity=25_000, daily_pnl=-200),              ReasonCode.DAILY_LOSS_LIMIT),
        ("maxtrades", Account(equity=25_000, trades_today=3),              ReasonCode.MAX_TRADES_PER_DAY),
        ("losses",    Account(equity=25_000, consecutive_losses=2),        ReasonCode.CONSECUTIVE_LOSSES),
        ("openpos",   Account(equity=25_000, open_positions=1),            ReasonCode.MAX_OPEN_POSITIONS),
    ]
    for name, acct, code in checks:
        d = decide(cand(), acct)
        assert d.reason_code is code and not d.approved, (name, d.to_json())
        print(f"block {name:9}: {d.status.value:8} {d.reason_code.value}")

    rr = decide(cand(tp2=101.0), base)   # only 1R reward
    assert rr.reason_code is ReasonCode.RR_TOO_LOW, rr.to_json()
    print("reject rr_too_low:", rr.notes)

    small = decide(cand(sym="NQ", entry=20000, stop=19970, tp2=20120), Account(equity=2_000))
    assert small.reason_code is ReasonCode.MAX_CONTRACTS, small.to_json()
    print("reject sizing:", small.notes)
    print("\nrisk gate OK")
