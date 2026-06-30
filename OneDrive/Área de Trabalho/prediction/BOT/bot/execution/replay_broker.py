"""ReplayBroker — deterministic bracket execution over historical bars.

Same interface a paper/live adapter will implement (`execute(order, candidate) -> (events, journal)`),
but fills are simulated from the bar path: entry at the plan price, then the bracket walks forward
within the session — protective stop, TP2 cap, or EOD-flat — exactly the engine's tp2_full model, so
the journal's R reconciles with the validated backtest. Deterministic: same bars + order → same result.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from bot.contracts import (OrderRequest, OrderEvent, OrderState, JournalEntry,
                           Side, Mode, ExitReason)

ET = "America/New_York"


class ReplayBroker:
    def __init__(self, d: pd.DataFrame, eod_min: int = 958):
        self.eod_min = eod_min
        ts = pd.to_datetime(d["ts"], utc=True)
        self.o = d["open"].to_numpy(float); self.h = d["high"].to_numpy(float)
        self.l = d["low"].to_numpy(float); self.c = d["close"].to_numpy(float)
        et = ts.dt.tz_convert(ET)
        self.daykey = (et.dt.year * 10000 + et.dt.month * 100 + et.dt.day).to_numpy()
        self.tod = (et.dt.hour * 60 + et.dt.minute).to_numpy()
        self.n = len(d)
        self._ix = {t.value: i for i, t in enumerate(ts)}   # ns timestamp -> row index

    def execute(self, order: OrderRequest, candidate, mode: Mode = Mode.REPLAY):
        entry = float(order.limit_price); stop = float(order.stop_price); tp = float(order.take_profit)
        sign = 1 if order.side is Side.LONG else -1
        risk = abs(entry - stop)
        key = pd.Timestamp(candidate.generated_at).tz_convert("UTC").value
        i0 = self._ix.get(key)
        evs = [OrderEvent(order.order_id, OrderState.CREATED),
               OrderEvent(order.order_id, OrderState.VALIDATED),
               OrderEvent(order.order_id, OrderState.SUBMITTED),
               OrderEvent(order.order_id, OrderState.ACCEPTED),
               OrderEvent(order.order_id, OrderState.FILLED, filled_qty=order.qty, avg_fill_price=entry)]

        exit_px, reason, mfe, mae = None, None, 0.0, 0.0
        if i0 is not None and risk > 0:
            for j in range(i0 + 1, self.n):
                # order mirrors engine tp2_full exactly: track MFE/MAE, then stop, then TP, then EOD
                mfe = max(mfe, sign * (self.h[j] - entry) / risk)
                mae = min(mae, sign * (self.l[j] - entry) / risk)
                hit_stop = (self.l[j] <= stop) if sign == 1 else (self.h[j] >= stop)
                hit_tp = (self.h[j] >= tp) if sign == 1 else (self.l[j] <= tp)
                if hit_stop:                                   # stop checked first (engine order)
                    exit_px, reason = stop, ExitReason.STOP; break
                if hit_tp:
                    exit_px, reason = tp, ExitReason.TP2; break
                if self.daykey[j] != self.daykey[i0] or self.tod[j] >= self.eod_min:   # session end -> flat
                    exit_px, reason = self.c[j], ExitReason.EOD_FLAT; break
        if exit_px is None:                                    # ran out of bars
            exit_px, reason = (self.c[-1] if i0 is not None else entry), ExitReason.EOD_FLAT
        net_r = sign * (exit_px - entry) / risk if risk > 0 else 0.0

        jrnl = JournalEntry(
            candidate_id=candidate.candidate_id, symbol=order.symbol, side=order.side, mode=mode,
            entry_price=round(entry, 2), exit_price=round(float(exit_px), 2), qty=order.qty,
            net_r=round(net_r, 4), mfe_r=round(mfe, 3), mae_r=round(mae, 3),
            exit_reason=reason, order_ids=[order.order_id],
            strategy_version=candidate.strategy_version,
            opened_at=candidate.generated_at)
        return evs, jrnl
