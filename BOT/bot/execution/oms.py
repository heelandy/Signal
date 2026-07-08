"""Order Manager & Position Synchronization (OMS-001, PME-001).

Tracks every order through its state machine, handles partial fills, OCO bracket exits (one fill
cancels the sibling), order timeouts/replacement, and reconciles internal positions against broker
truth (the `mismatch`/`emergency` states). Broker-agnostic: it consumes fill/position events from
any adapter and emits the canonical OrderEvent / PositionState transitions.

    oms = OMS()
    oms.register_bracket(entry, stop_order, tp_order)
    oms.on_fill(order_id, qty, price)      # partial or full
    oms.reconcile(broker_positions)        # broker truth wins
    oms.check_timeouts(now)
"""
from __future__ import annotations

from dataclasses import dataclass, field

from bot.contracts import (OrderRequest, OrderEvent, OrderState, PositionState, PositionPhase,
                           Side, can_transition, ORDER_TRANSITIONS, utcnow_iso)


@dataclass
class _Tracked:
    order: OrderRequest
    state: OrderState = OrderState.SUBMITTED
    filled: int = 0
    avg_price: float = 0.0
    sibling: str | None = None         # OCO partner order_id
    submitted_at: str = field(default_factory=utcnow_iso)


@dataclass
class OMS:
    orders: dict[str, _Tracked] = field(default_factory=dict)
    positions: dict[str, PositionState] = field(default_factory=dict)
    events: list[OrderEvent] = field(default_factory=list)
    timeout_sec: float = 30.0

    # ---- order lifecycle --------------------------------------------------
    def submit(self, order: OrderRequest, sibling: str | None = None) -> None:
        self.orders[order.order_id] = _Tracked(order=order, sibling=sibling)
        self._emit(order.order_id, OrderState.SUBMITTED)

    def register_bracket(self, stop: OrderRequest, target: OrderRequest) -> None:
        """OCO: stop and target are siblings — a fill on one cancels the other."""
        self.submit(stop, sibling=target.order_id)
        self.submit(target, sibling=stop.order_id)

    def _emit(self, oid: str, state: OrderState, **kw) -> OrderEvent:
        t = self.orders.get(oid)
        if t and not can_transition(ORDER_TRANSITIONS, t.state, state) and t.state != state:
            ev = OrderEvent(order_id=oid, state=OrderState.ERROR,
                            message=f"illegal {t.state.value}->{state.value}")
            self.events.append(ev)
            return ev
        if t:
            t.state = state
        ev = OrderEvent(order_id=oid, state=state, **kw)
        self.events.append(ev)
        return ev

    def on_accept(self, oid: str) -> None:
        self._emit(oid, OrderState.ACCEPTED)

    def on_fill(self, oid: str, qty: int, price: float) -> OrderEvent:
        """Partial or full fill. On full fill, OCO-cancel the sibling and update the position.
        Fail-closed guards (review 2026-07): non-positive qty is rejected; a fill on an already
        FILLED/CANCELLED order (duplicate broker event) is rejected; an overfill beyond the order
        qty is clamped to the remaining quantity so the internal position can't exceed the order."""
        t = self.orders.get(oid)
        if t is None:
            return OrderEvent(order_id=oid, state=OrderState.ERROR, message="unknown order")
        if qty <= 0:
            return OrderEvent(order_id=oid, state=OrderState.ERROR, message=f"bad fill qty {qty}")
        if t.state in (OrderState.FILLED, OrderState.CANCELLED, OrderState.REJECTED,
                       OrderState.EXPIRED, OrderState.ERROR):
            ev = OrderEvent(order_id=oid, state=OrderState.ERROR,
                            message=f"duplicate/late fill ignored (order already {t.state.value})")
            self.events.append(ev)
            return ev
        qty = min(qty, t.order.qty - t.filled)      # overfill clamp
        if qty <= 0:
            return OrderEvent(order_id=oid, state=OrderState.ERROR, message="overfill ignored")
        t.avg_price = (t.avg_price * t.filled + price * qty) / (t.filled + qty)
        t.filled += qty
        full = t.filled >= t.order.qty
        ev = self._emit(oid, OrderState.FILLED if full else OrderState.PARTIALLY_FILLED,
                        filled_qty=t.filled, avg_fill_price=round(t.avg_price, 4))
        self._apply_to_position(t, qty, price)
        if full and t.sibling and t.sibling in self.orders:        # OCO
            if self.orders[t.sibling].state not in (OrderState.FILLED, OrderState.CANCELLED):
                self._emit(t.sibling, OrderState.CANCELLED, message="OCO sibling filled")
        return ev

    def cancel(self, oid: str) -> None:
        self._emit(oid, OrderState.CANCELLED)

    def check_timeouts(self, now_epoch: float, submitted_epochs: dict[str, float]) -> list[str]:
        """Cancel orders still unaccepted past timeout_sec (caller supplies submit epochs)."""
        expired = []
        for oid, t in self.orders.items():
            if t.state in (OrderState.SUBMITTED,) and oid in submitted_epochs:
                if now_epoch - submitted_epochs[oid] > self.timeout_sec:
                    self._emit(oid, OrderState.EXPIRED, message="timeout")
                    expired.append(oid)
        return expired

    # ---- position sync ----------------------------------------------------
    def _apply_to_position(self, t: _Tracked, qty: int, price: float) -> None:
        sym = t.order.symbol
        pos = self.positions.get(sym) or PositionState(symbol=sym, phase=PositionPhase.NONE)
        signed = qty if t.order.side is Side.LONG else -qty
        cur = (pos.qty if pos.side is Side.LONG else -pos.qty) if pos.side else 0
        new = cur + signed
        if cur == 0 and new != 0:
            pos = PositionState(symbol=sym, phase=PositionPhase.OPEN, qty=abs(new),
                                side=Side.LONG if new > 0 else Side.SHORT, avg_price=price)
        elif new == 0:
            pos.phase = PositionPhase.CLOSED if pos.phase != PositionPhase.NONE else PositionPhase.NONE
            pos.qty = 0
        else:
            pos.qty = abs(new)
            pos.side = Side.LONG if new > 0 else Side.SHORT
        pos.ts = utcnow_iso()
        self.positions[sym] = pos

    def reconcile(self, broker_positions: list[PositionState]) -> dict[str, str]:
        """Broker truth wins. Flag any symbol where internal != broker -> mismatch (pause)."""
        bmap = {p.symbol: p for p in broker_positions}
        result = {}
        for sym in set(self.positions) | set(bmap):
            internal = self.positions.get(sym)
            broker = bmap.get(sym)
            iq = (internal.qty * (1 if internal.side is Side.LONG else -1)) if internal and internal.side else 0
            bq = (broker.qty * (1 if broker.side is Side.LONG else -1)) if broker and broker.side else 0
            if iq != bq:
                self.positions[sym] = broker or PositionState(symbol=sym, phase=PositionPhase.MISMATCH)
                if self.positions[sym].phase not in (PositionPhase.NONE, PositionPhase.CLOSED):
                    self.positions[sym].phase = PositionPhase.MISMATCH
                result[sym] = f"MISMATCH internal={iq} broker={bq} (broker wins)"
            else:
                result[sym] = "ok"
        return result


if __name__ == "__main__":   # self-test: bracket OCO, partial fills, reconcile mismatch
    from bot.contracts import OrderType
    oms = OMS()
    entry = OrderRequest(candidate_id="c", symbol="QQQ", side="long", qty=100,
                         order_type=OrderType.LIMIT, limit_price=545.0, stop_price=544.0, take_profit=548.0)
    oms.submit(entry); oms.on_accept(entry.order_id)
    oms.on_fill(entry.order_id, 40, 545.0)               # partial
    assert oms.orders[entry.order_id].state is OrderState.PARTIALLY_FILLED
    oms.on_fill(entry.order_id, 60, 545.1)               # complete
    assert oms.orders[entry.order_id].state is OrderState.FILLED
    assert oms.positions["QQQ"].qty == 100 and oms.positions["QQQ"].side is Side.LONG
    print("partial->full fill OK; position", oms.positions["QQQ"].qty, oms.positions["QQQ"].side.value)

    stop = OrderRequest(candidate_id="c", symbol="QQQ", side="short", qty=100, order_type=OrderType.STOP, stop_price=544.0)
    tp = OrderRequest(candidate_id="c", symbol="QQQ", side="short", qty=100, order_type=OrderType.LIMIT, limit_price=548.0)
    oms.register_bracket(stop, tp)
    oms.on_fill(tp.order_id, 100, 548.0)                 # TP fills -> stop OCO-cancelled
    assert oms.orders[stop.order_id].state is OrderState.CANCELLED
    assert oms.positions["QQQ"].qty == 0
    print("OCO bracket OK; position flat after TP")

    # reconcile: broker says we still hold 50 -> mismatch
    rec = oms.reconcile([PositionState(symbol="QQQ", phase=PositionPhase.OPEN, qty=50, side=Side.LONG)])
    assert "MISMATCH" in rec["QQQ"] and oms.positions["QQQ"].phase is PositionPhase.MISMATCH
    print("reconcile:", rec["QQQ"])
    print("OMS OK")
