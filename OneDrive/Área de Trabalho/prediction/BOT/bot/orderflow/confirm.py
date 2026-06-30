"""Order-flow confirmation for a signal — does the L3 book agree with the breakout direction?

Attaches a book-level read (aggressive-trade imbalance / cum-delta into the entry) to a candidate so
the user sees whether order flow CONFIRMS or DIVERGES from the proposed trade. Uses the local QQQ MBO
when the signal's date is in the data window; for current/live sessions it returns "no feed" (needs
Databento live MBO). Advisory only — F63 has not yet shown it's additive, so it never gates a signal.

    from bot.orderflow.confirm import orderflow_confirm
    info = orderflow_confirm(candidate)        # {feed, ati, confirms, direction_score, note}
"""
from __future__ import annotations

import pandas as pd

from bot.market_data import databento_local as L

_ARM = 0.20      # ATI arm threshold (Evidence)
_STRONG = 0.35


def orderflow_confirm(candidate, lookback_min: int = 5) -> dict:
    sym = candidate.symbol.upper()
    date = candidate.generated_at[:10]
    if sym != "QQQ" or date not in set(L.list_days("xnas")):
        return {"feed": False, "note": "no MBO for this symbol/date — live order flow needs the Databento live MBO feed"}
    ts = pd.Timestamp(candidate.generated_at).tz_convert("America/New_York")
    end = ts.strftime("%H:%M")
    start = (ts - pd.Timedelta(minutes=lookback_min)).strftime("%H:%M")
    if start >= end:
        return {"feed": True, "note": "window outside RTH"}
    tr = L.load_mbo_day(date, "QQQ", actions=("T",), hhmm=(start, end))
    if tr.empty:
        return {"feed": True, "note": "no trades in the pre-entry window"}
    buy = int(tr["size"].where(tr["side"] == "B", 0).sum())     # B = buy-aggressor (calibrated)
    sell = int(tr["size"].where(tr["side"] == "A", 0).sum())
    tot = buy + sell
    ati = (buy - sell) / tot if tot else 0.0                    # aggressive-trade imbalance [-1,1]
    sign = candidate.side.sign
    confirms = (ati * sign) > 0 and abs(ati) >= _ARM
    diverges = (ati * sign) < 0 and abs(ati) >= _ARM
    mag = min(abs(ati) / _STRONG, 1.0)
    score = round(50 + 50 * mag * (1 if (ati * sign) > 0 else -1), 0)   # 0..100, 50 = neutral
    verdict = "CONFIRMS" if confirms else ("DIVERGES from" if diverges else "is neutral on")
    return {"feed": True, "ati": round(ati, 3), "buy": buy, "sell": sell,
            "confirms": confirms, "diverges": diverges, "direction_score": score,
            "note": f"order flow {verdict} the {candidate.side.value} (ATI {ati:+.2f}, {lookback_min}m into entry)"}


if __name__ == "__main__":   # test on an in-window QQQ candidate (both a long and a short)
    from bot.contracts import TradeCandidate
    for side, gen in [("long", "2026-05-27T13:45:00+00:00"), ("short", "2026-05-27T18:30:00+00:00")]:
        c = TradeCandidate(symbol="QQQ", side=side, timeframe="5m", setup="breakout",
                           entry=720 if side == "long" else 722,
                           stop=717 if side == "long" else 725,
                           tp2=732 if side == "long" else 710, strategy_version="t", generated_at=gen)
        info = orderflow_confirm(c)
        print(f"{side:5} @ {gen[11:16]}Z: {info}")
    # live (today) -> no feed, fast
    c2 = TradeCandidate(symbol="SPY", side="long", timeframe="5m", setup="breakout",
                        entry=740, stop=737, tp2=752, strategy_version="t")
    print("SPY live:", orderflow_confirm(c2)["note"])
    print("order-flow confirm OK")
