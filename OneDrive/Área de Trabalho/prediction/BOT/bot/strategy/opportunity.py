"""Strategy-decision completions: Market Opportunity Queue (MOQ-001), Exit Intelligence (XIE-001),
and Decision Explainability (DIE-001).

- OpportunityQueue ranks candidates from ALL strategies by expected value and picks the best when
  several fire at once (one position at a time per the risk layer).
- ExitPolicy describes how a live trade is managed (cap4 / trail / scale) + an order-flow early-exit.
- explain() turns a candidate + its risk decision into a plain-text rationale for the UI / journal.
"""
from __future__ import annotations

from dataclasses import dataclass

from bot.contracts import TradeCandidate, RiskDecision, ExitReason

# how much a regime grade scales expected value (A best)
_REGIME_W = {"A": 1.0, "B": 0.7, "C": 0.5, "D": 0.0}


def expected_value(c: TradeCandidate) -> float:
    """EV in R: P(win)·reward − P(loss)·1, using confidence if present else a grade/RR heuristic."""
    reward = c.rr or 1.0
    p = c.confidence if c.confidence is not None else 0.40   # ORB base hit-rate ~40%
    ev = p * reward - (1 - p) * 1.0
    return ev * _REGIME_W.get((c.regime or "B"), 0.6)


@dataclass
class OpportunityQueue:
    candidates: list[TradeCandidate] = None

    def __post_init__(self):
        self.candidates = self.candidates or []

    def add(self, c: TradeCandidate) -> None:
        self.candidates.append(c)

    def ranked(self) -> list[tuple[TradeCandidate, float]]:
        return sorted(((c, expected_value(c)) for c in self.candidates), key=lambda x: x[1], reverse=True)

    def best(self) -> TradeCandidate | None:
        r = self.ranked()
        return r[0][0] if r and r[0][1] > 0 else None

    def best_per_symbol(self) -> dict[str, TradeCandidate]:
        out: dict[str, tuple[TradeCandidate, float]] = {}
        for c, ev in self.ranked():
            if c.symbol not in out:               # ranked() is already best-first
                out[c.symbol] = (c, ev)
        return {s: cv[0] for s, cv in out.items()}


@dataclass
class ExitPolicy:
    mode: str = "cap4"                 # cap4 (full->4R) | trail | scale
    tp1_rr: float = 1.0
    tp2_rr: float = 4.0
    trail_atr: float = 2.5
    early_exit_score: float = 80.0     # opposite order-flow score that triggers an early bail

    def early_exit(self, opposite_flow_score: float) -> bool:
        """Evidence early-failure: a hard opposite order-flow flip exits before the structural stop."""
        return opposite_flow_score >= self.early_exit_score

    def describe(self) -> str:
        return {"cap4": f"full position to {self.tp2_rr}R cap on the structure stop",
                "trail": f"{self.trail_atr}-ATR chandelier trail",
                "scale": f"50% at {self.tp1_rr}R then runner to {self.tp2_rr}R (BE after TP1)"}.get(self.mode, self.mode)


def explain(c: TradeCandidate, rd: RiskDecision | None = None) -> str:
    """Human-readable rationale (DIE): setup, direction, levels, R:R, EV, regime, gates."""
    parts = [
        f"{c.side.value.upper()} {c.symbol} {c.timeframe} via {c.setup}",
        f"entry {c.entry} / stop {c.stop} / tp2 {c.tp2} (R:R {c.rr:.1f}, risk {c.risk:.2f})",
        f"regime {c.regime or '?'}, session {(c.session.value if c.session else '?')}, EV {expected_value(c):+.2f}R",
    ]
    if c.direction_score is not None:
        parts.append(f"order-flow score {c.direction_score:.0f}/100")
    if c.evidence:
        parts.append("evidence " + ", ".join(f"{k}={v}" for k, v in list(c.evidence.items())[:4]))
    if rd is not None:
        parts.append(f"RISK: {rd.status.value} ({rd.reason_code.value})"
                     + (f" qty {rd.max_qty} risk ${rd.max_risk_dollars}" if rd.approved else ""))
    if "UNVALIDATED" in c.strategy_version:
        parts.append("⚠ strategy not yet validated — gated off for live")
    return " | ".join(parts)


if __name__ == "__main__":
    def c(setup, rr_tp, regime="A", conf=None):
        return TradeCandidate(symbol="QQQ", side="long", timeframe="5m", setup=setup,
                              entry=100, stop=99, tp2=99 + rr_tp, strategy_version=setup, regime=regime, confidence=conf)
    q = OpportunityQueue()
    q.add(c("orb_stack", 5, "A"))            # EV high
    q.add(c("vwap_revert", 1.6, "C"))        # EV low
    q.add(c("trend_pullback", 3, "B"))
    r = q.ranked()
    assert r[0][0].setup == "orb_stack", r
    print("ranked:", [(x[0].setup, round(x[1], 2)) for x in r])
    print("best:", q.best().setup)

    ep = ExitPolicy(mode="cap4")
    assert ep.early_exit(85) and not ep.early_exit(50)
    print("exit policy:", ep.describe(), "| early-exit@85:", ep.early_exit(85))
    print("explain:", explain(c("orb_stack", 5, "A")))
    print("opportunity/exit/explain OK")
