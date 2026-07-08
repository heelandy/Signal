"""Performance Intelligence (PFI-001) — attribution + benchmarking from the journal.

Breaks realised PnL down by strategy / symbol / side / exit-reason, builds the equity curve and
drawdown, and compares the strategy's return stream to a buy-and-hold benchmark (alpha + correlation).
"""
from __future__ import annotations

from collections import defaultdict

import numpy as np

from bot.ml.validation import sharpe


def _bucket(rows: list[dict], key: str) -> dict:
    agg = defaultdict(list)
    for r in rows:
        if r.get("net_r") is not None:
            agg[r.get(key, "?")].append(r["net_r"])
    return {k: {"trades": len(v), "exp_R": round(float(np.mean(v)), 3), "total_R": round(float(np.sum(v)), 1),
                "win_pct": round(float(100 * np.mean(np.array(v) > 0)), 1)} for k, v in agg.items()}


def attribution(journal) -> dict:
    rows = journal.read("JournalEntry")
    return {dim: _bucket(rows, key) for dim, key in
            [("by_strategy", "strategy_version"), ("by_symbol", "symbol"),
             ("by_side", "side"), ("by_exit", "exit_reason")]}


def equity_curve(journal, risk_dollars: float = 100.0, start_equity: float = 25_000.0) -> np.ndarray:
    rs = [r["net_r"] for r in journal.read("JournalEntry") if r.get("net_r") is not None]
    return start_equity + np.cumsum(np.array(rs) * risk_dollars) if rs else np.array([start_equity])


def max_drawdown(curve: np.ndarray) -> dict:
    peak = np.maximum.accumulate(curve)
    dd = (curve - peak) / peak
    i = int(dd.argmin())
    return {"max_dd_pct": round(100 * float(dd.min()), 2), "trough_idx": i,
            "peak": round(float(peak[i]), 0), "trough": round(float(curve[i]), 0)}


def summary(journal, risk_dollars: float = 100.0) -> dict:
    rs = np.array([r["net_r"] for r in journal.read("JournalEntry") if r.get("net_r") is not None])
    if not len(rs):
        return {"trades": 0}
    curve = equity_curve(journal, risk_dollars)
    gw = rs[rs > 0].sum(); gl = -rs[rs <= 0].sum()
    return {"trades": len(rs), "exp_R": round(float(rs.mean()), 3), "total_R": round(float(rs.sum()), 1),
            "win_pct": round(100 * float((rs > 0).mean()), 1),
            "profit_factor": round(float(gw / gl), 2) if gl else float("inf"),
            "sharpe_per_trade": round(sharpe(rs, periods=len(rs)), 2),
            **max_drawdown(curve)}


def benchmark_compare(strategy_R: np.ndarray, benchmark_R: np.ndarray) -> dict:
    """Alpha (mean excess) + correlation vs a buy-and-hold benchmark return stream (aligned, same n)."""
    s = np.asarray(strategy_R, float); b = np.asarray(benchmark_R, float)
    n = min(len(s), len(b))
    if n < 3:
        return {"alpha": float("nan"), "correlation": float("nan")}
    s, b = s[:n], b[:n]
    corr = float(np.corrcoef(s, b)[0, 1]) if s.std() and b.std() else 0.0
    return {"alpha": round(float(s.mean() - b.mean()), 4), "correlation": round(corr, 3),
            "strat_sharpe": round(sharpe(s, n), 2), "bench_sharpe": round(sharpe(b, n), 2)}


if __name__ == "__main__":
    import tempfile
    from pathlib import Path
    from bot.journal import Journal
    from bot.contracts import JournalEntry, Mode, ExitReason
    j = Journal(Path(tempfile.mkdtemp()) / "perf.jsonl")
    rng = np.random.default_rng(3)
    for i in range(60):
        r = 4.0 if rng.random() < 0.42 else -1.0
        j.record(JournalEntry(candidate_id=str(i), symbol="QQQ" if i % 2 else "SPY", side="long",
                              mode=Mode.REPLAY, net_r=r, strategy_version="orb_stack",
                              exit_reason=ExitReason.TP2 if r > 0 else ExitReason.STOP))
    s = summary(j)
    assert s["trades"] == 60
    print("summary:", s)
    print("attribution by_symbol:", attribution(j)["by_symbol"])
    bc = benchmark_compare(rng.normal(0.1, 1, 50), rng.normal(0.03, 1, 50))
    print("benchmark compare:", bc)
    print("performance intelligence OK")
