"""Persist live order-flow pressure scores (audit gap 2026-07-05: "live tape scores not
persisted for training").

DATA-FIRST: the volume-weighted flow score (bot.api.server._flow_score — same formula here) is
appended once per scan cycle per symbol to data/orderflow_scores.csv (minute-deduped). It cannot
join the 59-column training schema yet — there is no HISTORICAL backfill for it, so a schema
column would be 100% NaN for every training row. Once months of live rows exist, add an
`of_score` feature + schema bump and the stored file becomes its backfill (same pattern as the
options-leg recording: collect during paper, model later).
"""
from __future__ import annotations

import pandas as pd

from bot.config import BOT_ROOT

PATH = BOT_ROOT / "data" / "orderflow_scores.csv"
_last: dict = {}                       # (symbol -> last minute written) — in-process dedup


def flow_score(bars: pd.DataFrame, n: int = 20) -> float:
    """Net volume-weighted direction of the last n bars -> 0-100 (50 = balanced)."""
    import numpy as np
    try:
        t = bars.tail(n)
        delta = (t["close"].astype(float) - t["open"].astype(float)).to_numpy()
        vol = t["volume"].astype(float).clip(lower=1.0).to_numpy()
        total = float(vol.sum())
        if total <= 0:
            return 50.0
        return round(max(0.0, min(100.0, 50.0 + 50.0 * float((np.sign(delta) * vol).sum()) / total)), 1)
    except Exception:
        return 50.0


def record(symbol: str, score: float) -> None:
    """Append one (minute, symbol, score) row; minute-deduped so a 60s loop writes each once."""
    minute = pd.Timestamp.now("UTC").floor("min").isoformat()
    if _last.get(symbol) == minute:
        return
    _last[symbol] = minute
    PATH.parent.mkdir(parents=True, exist_ok=True)
    new = not PATH.exists()
    with open(PATH, "a", encoding="utf-8") as f:
        if new:
            f.write("minute,symbol,of_score\n")
        f.write(f"{minute},{symbol},{score}\n")


def snapshot(symbols: list[str]) -> int:
    """Score + persist each symbol from the provider chain; returns rows written."""
    from bot.market_data.providers import get_bars
    n = 0
    for sym in symbols:
        try:
            record(sym, flow_score(get_bars(sym, "5m", "1d")))
            n += 1
        except Exception:
            continue
    return n


if __name__ == "__main__":
    import numpy as np
    b = pd.DataFrame({"open": np.linspace(100, 101, 30), "close": np.linspace(100.1, 101.2, 30),
                      "volume": np.full(30, 1000.0)})
    s = flow_score(b)
    assert s > 50.0, s                      # all up-bars -> buy pressure
    record("TEST", s)
    record("TEST", s)                       # dedup: second write same minute is a no-op
    df = pd.read_csv(PATH)
    assert (df["symbol"] == "TEST").sum() >= 1
    print(f"orderflow persist OK — score {s}, file {PATH.name}, rows {len(df)}")
