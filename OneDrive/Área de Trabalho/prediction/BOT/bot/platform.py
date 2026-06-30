"""Platform core (TOS-001 / EVT-001 / RCR-001) — a light event bus + capability registry.

EventBus: in-process pub/sub so modules emit/consume events (signal.generated, decision.recorded,
outcome.tracked, …) without direct coupling. CapabilityRegistry: every module registers with a health
check; `health()` is the system's status map (used by the dashboard / readiness gate).
"""
from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass, field
from typing import Callable

from bot.contracts import utcnow_iso


class EventBus:
    def __init__(self):
        self._subs: dict[str, list[Callable]] = defaultdict(list)
        self.log: list[dict] = []

    def subscribe(self, topic: str, cb: Callable) -> None:
        self._subs[topic].append(cb)

    def publish(self, topic: str, data: dict) -> int:
        self.log.append({"topic": topic, "ts": utcnow_iso(), "data": data})
        del self.log[:-500]                       # keep the last 500 events
        n = 0
        for cb in self._subs.get(topic, []):
            try:
                cb(data); n += 1
            except Exception:
                pass
        return n


@dataclass
class Capability:
    name: str
    version: str = "1.0"
    status: str = "active"        # active | degraded | down
    health_fn: Callable | None = None


@dataclass
class CapabilityRegistry:
    modules: dict[str, Capability] = field(default_factory=dict)

    def register(self, name, version="1.0", status="active", health_fn=None) -> None:
        self.modules[name] = Capability(name, version, status, health_fn)

    def health(self) -> dict:
        out = {}
        for n, c in self.modules.items():
            healthy = True
            try:
                healthy = bool(c.health_fn()) if c.health_fn else (c.status == "active")
            except Exception:
                healthy = False
            out[n] = {"version": c.version, "status": c.status, "healthy": healthy}
        return out


# singletons + the bot's standing capabilities
bus = EventBus()
registry = CapabilityRegistry()
for _m in ["market_data", "market_truth", "feature_engine", "market_intel", "opening_range_matrix",
           "strategy_families", "risk", "prop", "portfolio", "options", "orderflow", "ml_pipeline",
           "journal", "store", "tracker", "api"]:
    registry.register(_m)


if __name__ == "__main__":
    got = []
    bus.subscribe("signal.generated", lambda d: got.append(d["symbol"]))
    assert bus.publish("signal.generated", {"symbol": "QQQ"}) == 1 and got == ["QQQ"]
    print("event bus: published -> delivered to", len(got), "subscriber(s)")
    h = registry.health()
    print(f"capability registry: {len(h)} modules,", sum(1 for v in h.values() if v['healthy']), "healthy")
    print("platform OK")
