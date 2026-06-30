"""Portfolio Intelligence (PIE-001) — cross-position risk on top of the per-trade Risk gate.

The Risk gate (`risk.py`) sizes ONE trade; the Portfolio layer governs the BOOK: gross/net exposure,
portfolio heat (total open risk), single-name concentration, correlated-cluster exposure, and max
concurrent positions. It vetoes a new (already risk-approved) candidate that would breach a book limit,
and provides inverse-volatility weights for the long-term ETF rebalancer (Evidence §Portfolio).

    pf = Portfolio(equity=100_000)
    pf.add("QQQ", qty=100, price=545, risk_dollars=250, side="long")
    pf.check_add(cand, risk_dollars, corr={("QQQ","SPY"):0.9})   # -> (ok, reason)
"""
from __future__ import annotations

from dataclasses import dataclass, field

from bot.contracts import Side


@dataclass
class _Holding:
    symbol: str
    qty: int
    price: float
    risk_dollars: float
    side: Side


@dataclass
class PortfolioLimits:
    max_gross_mult: float = 4.0       # gross notional <= 4x equity
    max_heat: float = 0.02            # total open risk <= 2% equity
    max_name_weight: float = 0.25     # one symbol <= 25% gross
    max_cluster_risk: float = 0.012   # correlated-cluster open risk <= 1.2% equity
    max_positions: int = 5
    corr_threshold: float = 0.7       # |corr| above this => same cluster


@dataclass
class Portfolio:
    equity: float
    holdings: dict[str, _Holding] = field(default_factory=dict)
    limits: PortfolioLimits = field(default_factory=PortfolioLimits)

    def add(self, symbol: str, qty: int, price: float, risk_dollars: float, side) -> None:
        self.holdings[symbol] = _Holding(symbol, qty, price, risk_dollars, Side(side))

    def remove(self, symbol: str) -> None:
        self.holdings.pop(symbol, None)

    # ---- book metrics -----------------------------------------------------
    def gross_notional(self) -> float:
        return sum(h.qty * h.price for h in self.holdings.values())

    def net_notional(self) -> float:
        return sum(h.qty * h.price * h.side.sign for h in self.holdings.values())

    def heat(self) -> float:
        return sum(h.risk_dollars for h in self.holdings.values()) / self.equity if self.equity else 0.0

    def concentration(self) -> float:
        g = self.gross_notional()
        return max((h.qty * h.price / g for h in self.holdings.values()), default=0.0) if g else 0.0

    def snapshot(self) -> dict:
        return {"positions": len(self.holdings), "gross_pct": round(self.gross_notional() / self.equity, 2),
                "net_pct": round(self.net_notional() / self.equity, 2), "heat_pct": round(100 * self.heat(), 2),
                "concentration_pct": round(100 * self.concentration(), 1)}

    # ---- admission control ------------------------------------------------
    def check_add(self, symbol: str, qty: int, price: float, risk_dollars: float, side,
                  corr: dict[tuple[str, str], float] | None = None) -> tuple[bool, str]:
        L = self.limits
        if len(self.holdings) >= L.max_positions:
            return False, f"max_positions {L.max_positions} reached"
        new_gross = self.gross_notional() + qty * price
        if new_gross > L.max_gross_mult * self.equity:
            return False, f"gross {new_gross/self.equity:.1f}x > {L.max_gross_mult}x"
        if (self.heat() + risk_dollars / self.equity) > L.max_heat:
            return False, f"portfolio heat would exceed {L.max_heat:.1%}"
        if (qty * price / max(new_gross, 1)) > L.max_name_weight:
            return False, f"{symbol} weight > {L.max_name_weight:.0%}"
        # correlated-cluster open risk (incl. the new one)
        corr = corr or {}
        cluster_risk = risk_dollars
        for h in self.holdings.values():
            c = corr.get((symbol, h.symbol), corr.get((h.symbol, symbol), 0.0))
            if abs(c) >= L.corr_threshold:
                cluster_risk += h.risk_dollars
        if cluster_risk / self.equity > L.max_cluster_risk:
            return False, f"correlated-cluster risk {cluster_risk/self.equity:.2%} > {L.max_cluster_risk:.2%}"
        return True, "ok"


def inverse_vol_weights(vols: dict[str, float], max_weight: float = 0.25) -> dict[str, float]:
    """Risk-parity-lite weights for the ETF rebalancer (Evidence Step 5): w_i ∝ 1/vol_i, capped."""
    raw = {s: 1.0 / v for s, v in vols.items() if v > 0}
    tot = sum(raw.values()) or 1.0
    w = {s: r / tot for s, r in raw.items()}
    # cap + renormalise once
    w = {s: min(x, max_weight) for s, x in w.items()}
    tot2 = sum(w.values()) or 1.0
    return {s: round(x / tot2, 4) for s, x in w.items()}


if __name__ == "__main__":   # self-test
    pf = Portfolio(equity=100_000)
    pf.add("QQQ", 100, 545, risk_dollars=250, side="long")
    print("snapshot:", pf.snapshot())
    ok, why = pf.check_add("AAPL", 50, 200, 200, "long")
    assert ok, why
    # correlated cluster: small SPY position (passes weight + heat) but corr 0.95 with QQQ -> cluster veto
    ok2, why2 = pf.check_add("SPY", 20, 600, 1000, "long", corr={("SPY", "QQQ"): 0.95})
    assert not ok2 and "cluster" in why2, why2
    print("cluster veto:", why2)
    # heat veto (risk too large for the book; checked before name-weight here)
    ok3, why3 = pf.check_add("TSLA", 10, 250, 2500, "long")
    assert not ok3 and "heat" in why3, why3
    print("heat veto:", why3)
    w = inverse_vol_weights({"SPY": 0.10, "TLT": 0.08, "GLD": 0.12, "QQQ": 0.15})
    assert abs(sum(w.values()) - 1.0) < 1e-6, w
    print("inverse-vol weights:", w)
    print("portfolio OK")
