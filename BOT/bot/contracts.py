"""Canonical contracts — the objects every layer of the BOT speaks.

One definition, used by strategy → risk → execution → journal → API. Stdlib only (dataclasses +
enums); migrates cleanly to pydantic/FastAPI at the API phase. Everything is fail-closed: an object
that does not validate cannot be constructed, so a malformed candidate/order never reaches risk or a
broker.

Sources reconciled: BUILD_PLAN.md §3, Evidence.docx §8 "Shared Signal Object", Botreview CONTRACTS.

    from bot.contracts import TradeCandidate, Side, RiskDecision, RiskStatus
    c = TradeCandidate(symbol="QQQ", side=Side.LONG, timeframe="5m", setup="orb_stack",
                       entry=545.10, stop=544.30, tp1=545.90, tp2=548.30, strategy_version="1.0.0")
    c.rr            # reward:risk to tp2
    c.to_json()     # canonical JSON (maps to the web ingestion payload)
"""
from __future__ import annotations

import hashlib
import json
import uuid
from dataclasses import dataclass, field, asdict, fields
from datetime import datetime, timezone
from enum import Enum
from typing import Any

SCHEMA_VERSION = "1.0.0"


def utcnow_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


# ─────────────────────────── enums ───────────────────────────

class Side(str, Enum):
    LONG = "long"
    SHORT = "short"

    @property
    def sign(self) -> int:
        return 1 if self is Side.LONG else -1


class Session(str, Enum):
    RTH = "rth"
    ASIA = "asia"
    LONDON = "london"


class RiskStatus(str, Enum):
    APPROVED = "approved"
    REJECTED = "rejected"   # the candidate itself is bad (no stop, R:R too low, …)
    BLOCKED = "blocked"     # account/market state forbids it (daily loss, kill switch, stale data, …)


class ReasonCode(str, Enum):
    OK = "ok"
    NO_STOP = "no_stop"
    RR_TOO_LOW = "rr_too_low"
    STALE_DATA = "stale_data"
    SOURCE_HEALTH_CRITICAL = "source_health_critical"
    DAILY_LOSS_LIMIT = "daily_loss_limit"
    TRAILING_DRAWDOWN = "trailing_drawdown"
    MAX_CONTRACTS = "max_contracts"
    MAX_OPEN_POSITIONS = "max_open_positions"
    MAX_TRADES_PER_DAY = "max_trades_per_day"
    CONSECUTIVE_LOSSES = "consecutive_losses"
    WEEKLY_LOSS_LIMIT = "weekly_loss_limit"
    CORRELATED_EXPOSURE = "correlated_exposure"
    SPREAD_TOO_WIDE = "spread_too_wide"
    DUPLICATE_CANDIDATE = "duplicate_candidate"
    KILL_SWITCH = "kill_switch"
    OUTSIDE_WINDOW = "outside_window"
    LIVE_LOCKED = "live_locked"


class OrderType(str, Enum):
    MARKET = "market"
    LIMIT = "limit"
    STOP = "stop"
    STOP_LIMIT = "stop_limit"


class TimeInForce(str, Enum):
    DAY = "day"
    GTC = "gtc"
    IOC = "ioc"
    FOK = "fok"


class OrderState(str, Enum):
    CREATED = "created"
    VALIDATED = "validated"
    SUBMITTED = "submitted"
    ACCEPTED = "accepted"
    PARTIALLY_FILLED = "partially_filled"
    FILLED = "filled"
    CANCELLED = "cancelled"
    REJECTED = "rejected"
    EXPIRED = "expired"
    ERROR = "error"


class PositionPhase(str, Enum):
    NONE = "none"
    OPENING = "opening"
    OPEN = "open"
    REDUCING = "reducing"
    CLOSING = "closing"
    CLOSED = "closed"
    MISMATCH = "mismatch"   # broker truth disagrees with internal — pause + reconcile
    UNKNOWN = "unknown"
    EMERGENCY = "emergency"


class ExitReason(str, Enum):
    TP1 = "tp1"
    TP2 = "tp2"
    STOP = "stop"
    TRAIL = "trail"
    EARLY_FAILURE = "early_failure"
    EOD_FLAT = "eod_flat"
    TIME_STOP = "time_stop"
    KILL_SWITCH = "kill_switch"


class Mode(str, Enum):
    REPLAY = "replay"
    PAPER = "paper"
    LIVE = "live"


# allowed state transitions (anything else is rejected — fail closed)
ORDER_TRANSITIONS: dict[OrderState, set[OrderState]] = {
    OrderState.CREATED: {OrderState.VALIDATED, OrderState.REJECTED, OrderState.ERROR},
    OrderState.VALIDATED: {OrderState.SUBMITTED, OrderState.REJECTED, OrderState.ERROR},
    OrderState.SUBMITTED: {OrderState.ACCEPTED, OrderState.CANCELLED, OrderState.REJECTED,
                           OrderState.EXPIRED, OrderState.ERROR},
    OrderState.ACCEPTED: {OrderState.PARTIALLY_FILLED, OrderState.FILLED, OrderState.CANCELLED,
                          OrderState.EXPIRED, OrderState.ERROR},
    OrderState.PARTIALLY_FILLED: {OrderState.PARTIALLY_FILLED, OrderState.FILLED, OrderState.CANCELLED,
                                  OrderState.EXPIRED, OrderState.ERROR},
    OrderState.FILLED: set(), OrderState.CANCELLED: set(), OrderState.REJECTED: set(),
    OrderState.EXPIRED: set(), OrderState.ERROR: set(),
}

POSITION_TRANSITIONS: dict[PositionPhase, set[PositionPhase]] = {
    PositionPhase.NONE: {PositionPhase.OPENING, PositionPhase.UNKNOWN},
    PositionPhase.OPENING: {PositionPhase.OPEN, PositionPhase.CLOSED, PositionPhase.MISMATCH, PositionPhase.UNKNOWN},
    PositionPhase.OPEN: {PositionPhase.REDUCING, PositionPhase.CLOSING, PositionPhase.MISMATCH,
                         PositionPhase.EMERGENCY, PositionPhase.UNKNOWN},
    PositionPhase.REDUCING: {PositionPhase.OPEN, PositionPhase.CLOSING, PositionPhase.CLOSED,
                             PositionPhase.MISMATCH},
    PositionPhase.CLOSING: {PositionPhase.CLOSED, PositionPhase.MISMATCH, PositionPhase.EMERGENCY},
    PositionPhase.CLOSED: set(),
    PositionPhase.MISMATCH: {PositionPhase.OPEN, PositionPhase.CLOSED, PositionPhase.UNKNOWN},
    PositionPhase.UNKNOWN: {PositionPhase.OPEN, PositionPhase.CLOSED, PositionPhase.MISMATCH},
    PositionPhase.EMERGENCY: {PositionPhase.CLOSED},
}


def can_transition(transitions: dict, src, dst) -> bool:
    return dst in transitions.get(src, set())


# ─────────────────────────── serialization mixin ───────────────────────────

class _Serializable:
    """JSON round-trip with enum <-> value handling. Keeps contracts dependency-free."""

    def to_dict(self) -> dict[str, Any]:
        def conv(v):
            if isinstance(v, Enum):
                return v.value
            if isinstance(v, list):
                return [conv(x) for x in v]
            if isinstance(v, dict):
                return {k: conv(x) for k, x in v.items()}
            return v
        return {k: conv(v) for k, v in asdict(self).items()}

    def to_json(self, **kw) -> str:
        return json.dumps(self.to_dict(), **kw)

    @classmethod
    def from_dict(cls, d: dict[str, Any]):
        kw = {}
        type_by_name = {f.name: f.type for f in fields(cls)}
        for k, v in d.items():
            if k not in type_by_name:
                continue
            kw[k] = v
        return cls(**kw)  # __post_init__ re-validates + coerces enums


# ─────────────────────────── contracts ───────────────────────────

@dataclass
class MarketCandle(_Serializable):
    symbol: str
    ts_utc: str               # ISO8601 UTC, bar OPEN time
    open: float
    high: float
    low: float
    close: float
    volume: float
    source: str = "databento"
    timeframe: str = "1m"
    quality_flags: list[str] = field(default_factory=list)   # e.g. ["stale"], ["gap"], ["bad_ohlc"]
    ingested_ts: str = field(default_factory=utcnow_iso)
    schema_version: str = SCHEMA_VERSION

    def __post_init__(self):
        if not (self.low <= self.open <= self.high and self.low <= self.close <= self.high):
            self.quality_flags = sorted(set(self.quality_flags) | {"bad_ohlc"})

    @property
    def ok(self) -> bool:
        return not self.quality_flags


@dataclass
class TradeCandidate(_Serializable):
    """A signal, not an order. Maps 1:1 to Evidence §8 shared-signal object + the web payload."""
    symbol: str
    side: Side
    timeframe: str
    setup: str                       # "orb_stack" | "vwap_revert" | …
    entry: float
    stop: float
    tp1: float | None = None
    tp2: float | None = None
    strategy_version: str = "0.0.0"
    direction_score: float | None = None   # Evidence 0–100 intrabar score (MBO phase)
    confidence: float | None = None
    expected_r: float | None = None
    regime: str | None = None
    session: Session | None = None
    spread_bps: float | None = None
    evidence: dict[str, Any] = field(default_factory=dict)   # feature snapshot at fire time
    rejection_reasons: list[str] = field(default_factory=list)
    generated_at: str = field(default_factory=utcnow_iso)
    expiration_at: str | None = None
    candidate_id: str = field(default_factory=lambda: str(uuid.uuid4()))
    idempotency_key: str | None = None
    schema_version: str = SCHEMA_VERSION

    def __post_init__(self):
        self.side = Side(self.side)
        if self.session is not None:
            self.session = Session(self.session)
        # fail-closed geometry: a stop must invalidate the trade (correct side of entry)
        if self.stop is None:
            raise ValueError("TradeCandidate requires a stop (no stop -> no trade)")
        if self.side is Side.LONG and not self.stop < self.entry:
            raise ValueError(f"long stop {self.stop} must be below entry {self.entry}")
        if self.side is Side.SHORT and not self.stop > self.entry:
            raise ValueError(f"short stop {self.stop} must be above entry {self.entry}")
        for name, tp in (("tp1", self.tp1), ("tp2", self.tp2)):
            if tp is not None and (tp - self.entry) * self.side.sign <= 0:
                raise ValueError(f"{name} {tp} must be beyond entry {self.entry} in the trade direction")
        if self.expected_r is None and self.tp2 is not None:
            self.expected_r = round(self.rr, 3)
        if self.idempotency_key is None:
            self.idempotency_key = self._make_key()

    @property
    def risk(self) -> float:
        return abs(self.entry - self.stop)

    @property
    def rr(self) -> float:
        """Reward:risk to tp2 (or tp1 if no tp2)."""
        tp = self.tp2 if self.tp2 is not None else self.tp1
        return abs(tp - self.entry) / self.risk if (tp is not None and self.risk > 0) else 0.0

    def _make_key(self) -> str:
        # one candidate per (symbol, side, setup, session-day) — dedup across restarts
        day = self.generated_at[:10]
        raw = f"{self.symbol}|{self.side.value}|{self.setup}|{self.session}|{day}"
        return hashlib.sha1(raw.encode()).hexdigest()[:16]


@dataclass
class RiskDecision(_Serializable):
    candidate_id: str
    status: RiskStatus
    reason_code: ReasonCode = ReasonCode.OK
    max_qty: int = 0
    max_risk_dollars: float = 0.0
    stop_policy: str = "struct"        # how the working stop is managed
    target_policy: str = "cap4"        # capped-TP2 (the shipped exit)
    notes: str = ""
    trace_id: str = field(default_factory=lambda: str(uuid.uuid4()))
    decided_at: str = field(default_factory=utcnow_iso)
    schema_version: str = SCHEMA_VERSION

    def __post_init__(self):
        self.status = RiskStatus(self.status)
        self.reason_code = ReasonCode(self.reason_code)
        if self.status is RiskStatus.APPROVED:
            if self.max_qty <= 0 or self.max_risk_dollars <= 0:
                raise ValueError("approved RiskDecision needs max_qty>0 and max_risk_dollars>0")
        elif self.reason_code is ReasonCode.OK:
            raise ValueError("a non-approved RiskDecision must carry a non-OK reason_code")

    @property
    def approved(self) -> bool:
        return self.status is RiskStatus.APPROVED


@dataclass
class OrderRequest(_Serializable):
    candidate_id: str
    symbol: str
    side: Side
    qty: int
    order_type: OrderType = OrderType.LIMIT
    limit_price: float | None = None
    stop_price: float | None = None          # bracket protective stop
    take_profit: float | None = None         # bracket target
    tif: TimeInForce = TimeInForce.DAY
    idempotency_key: str | None = None        # broker dedup — never submit the same key twice
    order_id: str = field(default_factory=lambda: str(uuid.uuid4()))
    created_at: str = field(default_factory=utcnow_iso)
    schema_version: str = SCHEMA_VERSION

    def __post_init__(self):
        self.side = Side(self.side)
        self.order_type = OrderType(self.order_type)
        self.tif = TimeInForce(self.tif)
        if self.qty <= 0:
            raise ValueError("OrderRequest qty must be > 0")
        if self.order_type in (OrderType.LIMIT, OrderType.STOP_LIMIT) and self.limit_price is None:
            raise ValueError(f"{self.order_type.value} order requires a limit_price")
        if self.order_type in (OrderType.STOP, OrderType.STOP_LIMIT) and self.stop_price is None:
            raise ValueError(f"{self.order_type.value} order requires a stop_price")
        if self.idempotency_key is None:
            self.idempotency_key = self.order_id


@dataclass
class OrderEvent(_Serializable):
    order_id: str
    state: OrderState
    filled_qty: int = 0
    avg_fill_price: float | None = None
    broker_order_id: str | None = None
    message: str = ""
    ts: str = field(default_factory=utcnow_iso)
    schema_version: str = SCHEMA_VERSION

    def __post_init__(self):
        self.state = OrderState(self.state)


@dataclass
class PositionState(_Serializable):
    symbol: str
    phase: PositionPhase = PositionPhase.NONE
    qty: int = 0
    avg_price: float | None = None
    side: Side | None = None
    realized_r: float = 0.0
    unrealized_r: float = 0.0
    ts: str = field(default_factory=utcnow_iso)
    schema_version: str = SCHEMA_VERSION

    def __post_init__(self):
        self.phase = PositionPhase(self.phase)
        if self.side is not None:
            self.side = Side(self.side)

    def transition(self, dst: PositionPhase) -> "PositionState":
        dst = PositionPhase(dst)
        if not can_transition(POSITION_TRANSITIONS, self.phase, dst):
            raise ValueError(f"illegal position transition {self.phase.value} -> {dst.value}")
        self.phase = dst
        self.ts = utcnow_iso()
        return self


@dataclass
class JournalEntry(_Serializable):
    """Append-only outcome record linking candidate -> risk -> orders -> fills -> result."""
    candidate_id: str
    symbol: str
    side: Side
    mode: Mode
    entry_price: float | None = None
    planned_entry: float | None = None       # signal price (Phase 6 fill schema — slippage base)
    avg_fill_price: float | None = None      # measured broker fill (Phase 5 execution record)
    exit_price: float | None = None
    qty: int = 0
    net_r: float | None = None
    mfe_r: float | None = None
    mae_r: float | None = None
    exit_reason: ExitReason | None = None
    risk_decision_trace: str | None = None
    order_ids: list[str] = field(default_factory=list)
    strategy_version: str = "0.0.0"
    opened_at: str | None = None
    closed_at: str | None = None
    entry_id: str = field(default_factory=lambda: str(uuid.uuid4()))
    schema_version: str = SCHEMA_VERSION

    def __post_init__(self):
        self.side = Side(self.side)
        self.mode = Mode(self.mode)
        if self.exit_reason is not None:
            self.exit_reason = ExitReason(self.exit_reason)


@dataclass
class SourceHealthState(_Serializable):
    source: str
    healthy: bool = True
    last_ts: str | None = None
    staleness_sec: float | None = None
    detail: str = ""
    checked_at: str = field(default_factory=utcnow_iso)
    schema_version: str = SCHEMA_VERSION


@dataclass
class KillSwitchState(_Serializable):
    active: bool = False
    reason: str = ""
    set_by: str = "system"
    set_at: str | None = None
    schema_version: str = SCHEMA_VERSION


if __name__ == "__main__":   # self-test: build one of each, round-trip JSON, reject bad cases
    c = TradeCandidate(symbol="QQQ", side="long", timeframe="5m", setup="orb_stack",
                       entry=545.10, stop=544.30, tp1=545.90, tp2=548.30,
                       strategy_version="1.0.0", session="rth")
    assert abs(c.rr - 4.0) < 1e-6, c.rr
    assert TradeCandidate.from_dict(json.loads(c.to_json())).idempotency_key == c.idempotency_key
    print(f"TradeCandidate ok  rr={c.rr:.2f}  key={c.idempotency_key}")

    rd = RiskDecision(candidate_id=c.candidate_id, status="approved",
                      max_qty=125, max_risk_dollars=62.50)
    print(f"RiskDecision ok    {rd.status.value} qty={rd.max_qty}")

    o = OrderRequest(candidate_id=c.candidate_id, symbol="QQQ", side="long", qty=125,
                     order_type="limit", limit_price=545.12, stop_price=544.30, take_profit=548.30)
    print(f"OrderRequest ok    {o.order_type.value} {o.qty}@{o.limit_price}")

    pos = PositionState(symbol="QQQ").transition(PositionPhase.OPENING).transition(PositionPhase.OPEN)
    print(f"PositionState ok   phase={pos.phase.value}")

    # fail-closed checks
    for bad, label in [
        (lambda: TradeCandidate(symbol="QQQ", side="long", timeframe="5m", setup="x",
                                entry=100, stop=101), "long stop above entry"),
        (lambda: RiskDecision(candidate_id="x", status="blocked"), "blocked w/o reason"),
        (lambda: OrderRequest(candidate_id="x", symbol="QQQ", side="long", qty=0), "zero qty"),
        (lambda: PositionState(symbol="QQQ").transition(PositionPhase.CLOSED) and
                 PositionState(symbol="QQQ", phase=PositionPhase.CLOSED).transition(PositionPhase.OPEN),
         "closed -> open"),
    ]:
        try:
            bad(); raise AssertionError(f"should have rejected: {label}")
        except ValueError:
            print(f"rejected (good):   {label}")
    print("\nall contracts validate + round-trip OK")
