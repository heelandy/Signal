"""Broker interface — every adapter (replay / Alpaca paper / live / futures) implements this.

Keeps strategy/risk/runtime decoupled from any specific broker. The replay broker implements the
same surface for backtests; the Alpaca adapter for paper/live; a futures adapter later.
"""
from __future__ import annotations

import abc
from dataclasses import dataclass

from bot.contracts import OrderRequest, OrderEvent, PositionState


@dataclass
class AccountInfo:
    equity: float
    buying_power: float
    cash: float
    open_position_count: int
    is_paper: bool
    detail: str = ""


class Broker(abc.ABC):
    """Minimal order/account surface. Bracket (stop+target) is carried on the OrderRequest."""

    name: str = "broker"
    is_paper: bool = True

    @abc.abstractmethod
    def account(self) -> AccountInfo: ...

    @abc.abstractmethod
    def positions(self) -> list[PositionState]: ...

    @abc.abstractmethod
    def submit(self, order: OrderRequest) -> OrderEvent: ...

    @abc.abstractmethod
    def cancel(self, order_id: str) -> OrderEvent: ...

    def is_market_open(self) -> bool:   # optional; default unknown -> closed (fail-closed)
        return False
