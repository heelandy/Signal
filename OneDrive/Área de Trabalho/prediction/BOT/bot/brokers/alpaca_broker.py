"""Alpaca adapter — equity (and later options) paper/live execution.

Paper-first: constructed from BOT/config/.env (ALPACA_*). Going live requires ALPACA_PAPER=false
AND the bot's own live readiness lock — this adapter refuses live unless `settings.live_allowed`.

Order submission is bracketed (entry + protective stop + take-profit) so the broker holds the
exit even if the bot disconnects. submit() is the ONLY method that mutates the account; the rest
are read-only.

    from bot.brokers.alpaca_broker import AlpacaBroker
    b = AlpacaBroker()           # paper
    b.account()                  # read-only connectivity check
"""
from __future__ import annotations

from bot.config import settings
from bot.contracts import (OrderRequest, OrderEvent, OrderState, OrderType, Side,
                           TimeInForce, PositionState, PositionPhase, Mode)
from bot.brokers.base import Broker, AccountInfo


class AlpacaBroker(Broker):
    name = "alpaca"

    def __init__(self, paper: bool | None = None):
        key, secret = settings.require_alpaca()
        self.is_paper = settings.alpaca_paper if paper is None else paper
        if not self.is_paper and not settings.live_allowed:
            raise RuntimeError("Alpaca LIVE blocked: set BOT_MODE=live + create config/LIVE_APPROVED.lock first.")
        try:
            from alpaca.trading.client import TradingClient
        except ImportError as e:
            raise RuntimeError("alpaca-py not installed: pip install alpaca-py") from e
        self._client = TradingClient(key, secret, paper=self.is_paper)

    # --- read-only ---------------------------------------------------------
    def account(self) -> AccountInfo:
        a = self._client.get_account()
        pos = self._client.get_all_positions()
        return AccountInfo(equity=float(a.equity), buying_power=float(a.buying_power),
                           cash=float(a.cash), open_position_count=len(pos),
                           is_paper=self.is_paper, detail=f"status={a.status}")

    def positions(self) -> list[PositionState]:
        out = []
        for p in self._client.get_all_positions():
            qty = int(float(p.qty))
            out.append(PositionState(
                symbol=p.symbol, phase=PositionPhase.OPEN if qty else PositionPhase.NONE,
                qty=abs(qty), avg_price=float(p.avg_entry_price),
                side=Side.LONG if qty > 0 else Side.SHORT,
                unrealized_r=float(getattr(p, "unrealized_plpc", 0.0) or 0.0)))
        return out

    def is_market_open(self) -> bool:
        return bool(self._client.get_clock().is_open)

    # --- mutating ----------------------------------------------------------
    def submit(self, order: OrderRequest) -> OrderEvent:
        from alpaca.trading.requests import (MarketOrderRequest, LimitOrderRequest,
                                             TakeProfitRequest, StopLossRequest)
        from alpaca.trading.enums import OrderSide, TimeInForce as ATIF, OrderClass
        side = OrderSide.BUY if order.side is Side.LONG else OrderSide.SELL
        tif = {TimeInForce.DAY: ATIF.DAY, TimeInForce.GTC: ATIF.GTC,
               TimeInForce.IOC: ATIF.IOC, TimeInForce.FOK: ATIF.FOK}[order.tif]
        bracket = {}
        if order.take_profit is not None and order.stop_price is not None:
            bracket = dict(order_class=OrderClass.BRACKET,
                           take_profit=TakeProfitRequest(limit_price=round(order.take_profit, 2)),
                           stop_loss=StopLossRequest(stop_price=round(order.stop_price, 2)))
        common = dict(symbol=order.symbol, qty=order.qty, side=side, time_in_force=tif,
                      client_order_id=order.idempotency_key, **bracket)
        req = (LimitOrderRequest(limit_price=round(order.limit_price, 2), **common)
               if order.order_type in (OrderType.LIMIT, OrderType.STOP_LIMIT)
               else MarketOrderRequest(**common))
        try:
            r = self._client.submit_order(req)
            return OrderEvent(order_id=order.order_id, state=OrderState.SUBMITTED,
                              broker_order_id=str(r.id), message=f"alpaca {r.status}")
        except Exception as e:                       # fail closed — surface the broker error
            return OrderEvent(order_id=order.order_id, state=OrderState.ERROR, message=str(e))

    def cancel(self, order_id: str) -> OrderEvent:
        try:
            self._client.cancel_order_by_id(order_id)
            return OrderEvent(order_id=order_id, state=OrderState.CANCELLED)
        except Exception as e:
            return OrderEvent(order_id=order_id, state=OrderState.ERROR, message=str(e))

    def open_orders(self) -> list[dict]:
        from alpaca.trading.requests import GetOrdersRequest
        from alpaca.trading.enums import QueryOrderStatus
        try:
            ords = self._client.get_orders(GetOrdersRequest(status=QueryOrderStatus.OPEN))
            return [{"id": str(o.id), "symbol": o.symbol, "side": str(o.side).split(".")[-1],
                     "qty": o.qty, "type": str(o.order_type).split(".")[-1],
                     "limit": o.limit_price, "status": str(o.status).split(".")[-1]} for o in ords]
        except Exception:
            return []

    def flatten(self) -> dict:
        """Close ALL positions + cancel open orders (the UI 'Flatten All' button)."""
        try:
            self._client.close_all_positions(cancel_orders=True)
            return {"flattened": True}
        except Exception as e:
            return {"flattened": False, "error": str(e)}

    # --- options (OCC symbols + single/multi-leg) --------------------------
    def submit_option_play(self, play, root: str, expiry: str, contracts: int = 1,
                           transmit: bool = False) -> dict:
        """Submit one of the options plays from bot.options (naked = 1 leg, debit/credit = 2-leg MLEG).
        `expiry` = 'YYYY-MM-DD'. transmit=False (default) DRY-RUNS: returns the order it WOULD send
        (so nothing fires without an explicit transmit=True + an options-enabled account)."""
        from alpaca.trading.requests import LimitOrderRequest, OptionLegRequest
        from alpaca.trading.enums import OrderSide, TimeInForce as ATIF, OrderClass
        legs_occ = [(occ_symbol(root, expiry, l.right, l.strike), l.side, l.price) for l in play.legs]
        net = round(abs(play.net), 2)
        if len(legs_occ) == 1:                                  # naked single-leg buy
            occ, side, px = legs_occ[0]
            req = LimitOrderRequest(symbol=occ, qty=contracts, side=OrderSide.BUY,
                                    limit_price=net, time_in_force=ATIF.DAY)
            desc = {"type": "single", "symbol": occ, "side": "buy", "limit": net, "qty": contracts}
        else:                                                   # vertical = 2-leg MLEG
            mleg = [OptionLegRequest(symbol=o, ratio_qty=1,
                                     side=OrderSide.BUY if s == "long" else OrderSide.SELL)
                    for o, s, _ in legs_occ]
            req = LimitOrderRequest(qty=contracts, limit_price=net, order_class=OrderClass.MLEG,
                                    legs=mleg, time_in_force=ATIF.DAY)
            desc = {"type": "mleg", "legs": [(o, s) for o, s, _ in legs_occ], "limit": net, "qty": contracts}
        if not transmit:
            return {"dry_run": True, "would_submit": desc, "play": play.name}
        try:
            r = self._client.submit_order(req)
            return {"submitted": True, "broker_order_id": str(r.id), "status": str(r.status), "play": play.name}
        except Exception as e:
            return {"submitted": False, "error": str(e), "play": play.name,
                    "hint": "needs options trading enabled on the account (level 2/3 for spreads)"}


def occ_symbol(root: str, expiry: str, right: str, strike: float) -> str:
    """OSI/OCC option symbol: ROOT + YYMMDD + C/P + strike*1000 (8 digits). e.g. QQQ260717C00545000."""
    yymmdd = expiry.replace("-", "")[2:]
    return f"{root.upper()}{yymmdd}{right.upper()}{int(round(strike * 1000)):08d}"


if __name__ == "__main__":   # READ-ONLY connectivity check (no orders submitted)
    b = AlpacaBroker()
    a = b.account()
    print(f"Alpaca {'PAPER' if a.is_paper else 'LIVE'} connected: equity ${a.equity:,.2f} "
          f"buying_power ${a.buying_power:,.2f} positions {a.open_position_count} ({a.detail})")
    print("market open:", b.is_market_open())
