"""Orchestrator — the live/paper decision loop that ties the pieces together with hard mode gating.

Per candidate:  market-truth (upstream) → risk.decide → [shadow: log only | paper/live: broker.submit]
→ journal everything. Mode is fail-closed: LIVE requires `settings.live_allowed`; SHADOW builds the
order but never transmits (Evidence stage-4 shadow mode); PAPER/LIVE submit through the broker.

    from bot.orchestrator import Orchestrator
    orc = Orchestrator(broker, account, journal, mode=Mode.SHADOW)
    orc.process(candidate)
    orc.health()
"""
from __future__ import annotations

from dataclasses import dataclass

from bot.config import settings
from bot.contracts import (Mode, OrderRequest, OrderType, RiskStatus, utcnow_iso)
from bot.risk import decide, Account, RiskLimits
from bot.journal import Journal


# extend the contract Mode with SHADOW at the orchestration layer (replay/paper/shadow/live)
SHADOW = "shadow"


@dataclass
class Orchestrator:
    broker: object | None
    account: Account
    journal: Journal
    mode: str = Mode.REPLAY.value
    limits: RiskLimits = None
    kill_switch: bool = False

    def __post_init__(self):
        self.limits = self.limits or RiskLimits()
        if self.mode == Mode.LIVE.value and not settings.live_allowed:
            raise RuntimeError("LIVE blocked: BOT_MODE=live + config/LIVE_APPROVED.lock required.")

    # ---- health (fail-closed) --------------------------------------------
    def health(self) -> dict:
        broker_ok, broker_detail = True, "n/a"
        if self.broker is not None and self.mode in (Mode.PAPER.value, Mode.LIVE.value):
            try:
                a = self.broker.account()
                broker_ok, broker_detail = True, f"equity ${a.equity:,.0f} paper={a.is_paper}"
            except Exception as e:
                broker_ok, broker_detail = False, str(e)
        healthy = self.account.source_healthy and not self.kill_switch and broker_ok
        return {"ts": utcnow_iso(), "mode": self.mode, "healthy": healthy,
                "source_healthy": self.account.source_healthy, "kill_switch": self.kill_switch,
                "broker_ok": broker_ok, "broker": broker_detail,
                "equity": round(self.account.equity, 2), "open_positions": self.account.open_positions}

    # ---- per-candidate decision loop -------------------------------------
    def process(self, candidate) -> dict:
        self.account.kill_switch = self.kill_switch
        self.journal.record(candidate)
        rd = decide(candidate, self.account, self.limits)
        self.journal.record(rd)
        if rd.status is not RiskStatus.APPROVED:
            return {"action": "rejected", "reason": rd.reason_code.value, "candidate": candidate.candidate_id}

        order = OrderRequest(candidate_id=candidate.candidate_id, symbol=candidate.symbol,
                             side=candidate.side, qty=rd.max_qty, order_type=OrderType.LIMIT,
                             limit_price=candidate.entry, stop_price=candidate.stop,
                             take_profit=candidate.tp2)

        if self.mode == SHADOW or self.broker is None:        # build + log, DO NOT transmit
            return {"action": "shadow", "would_submit": order.to_dict(), "qty": rd.max_qty}
        if self.mode == Mode.REPLAY.value:
            _, jr = self.broker.execute(order, candidate, mode=Mode.REPLAY)
            self.journal.record(jr)
            return {"action": "replay_filled", "net_r": jr.net_r}
        ev = self.broker.submit(order)                        # PAPER / LIVE — real transmit
        self.journal.record(ev)
        return {"action": "submitted", "state": ev.state.value, "broker_order_id": ev.broker_order_id}


if __name__ == "__main__":   # self-test in SHADOW (no orders transmitted)
    import tempfile
    from pathlib import Path
    from bot.contracts import TradeCandidate
    j = Journal(Path(tempfile.mkdtemp()) / "orc.jsonl")
    orc = Orchestrator(broker=None, account=Account(equity=25_000), journal=j, mode=SHADOW)
    c = TradeCandidate(symbol="QQQ", side="long", timeframe="5m", setup="orb_stack",
                       entry=545.10, stop=544.30, tp2=548.30, strategy_version="t")
    r = orc.process(c)
    assert r["action"] == "shadow" and r["qty"] > 0, r
    print("shadow:", r["action"], "qty", r["qty"])
    print("health:", orc.health())
    # kill switch blocks
    orc.kill_switch = True
    assert orc.process(c)["action"] == "rejected"
    print("kill-switch -> rejected; journal rows:", len(j.read()))
    print("orchestrator OK")
