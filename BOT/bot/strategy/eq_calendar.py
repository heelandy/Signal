"""EQUITY CALENDAR shadow studies (F108, gauntlet-passed 2026-07-10 after the equity cost-model
fix — both ALL-7):

  qqq-composite-0.1  QQQ CONFLUENCE at the 9:30 OPEN: Monday(+1) + fade-yesterday votes, |v|>=2
                     == LONG on a MONDAY AFTER A DOWN FRIDAY, exit the 16:00 close.
                     n=172 +19.6bps WR 61 PF 1.57 CI_lo +5.5 7/9yrs OOS +24.0 2x +18.9.
                     (The equities twin of the NQ weekend complex. On QQQ the 9:30 open BEATS
                     the 10:35 entry — each symbol has its own best clock.)
  spy-monday-0.1     SPY LONG every Monday open -> close (single census cell; confluence needs
                     >=2 votes and SPY only has one). n=382 +9.0bps PF 1.40 7/9 OOS +11.9.

Book: EQ shares (overnight precedent — option theta/spread eats a one-day ~10-20bps edge).
Stops: NOT yet gauntleted for these (queued in the battery) — shadow runs time-exit as validated.
"""
from __future__ import annotations

import json

import pandas as pd

from bot.config import BOT_ROOT

RULES = {
    "qqq_composite": {"lineage": "qqq-composite-0.1", "symbol": "QQQ", "kind": "monday_after_down_friday"},
    "spy_monday": {"lineage": "spy-monday-0.1", "symbol": "SPY", "kind": "every_monday"},
}
STATE = BOT_ROOT / "data" / "eq_calendar.json"


def _load() -> dict:
    if STATE.exists():
        try:
            return json.loads(STATE.read_text(encoding="utf-8"))
        except Exception:
            pass
    return {"open": {}, "journal": []}


def _save(d: dict) -> None:
    STATE.parent.mkdir(parents=True, exist_ok=True)
    STATE.write_text(json.dumps(d, indent=1), encoding="utf-8")


def _approved(lineage: str) -> bool:
    from bot.approval import status
    return bool(status(lineage)["stages"].get("research"))


def _bars(sym):
    from bot.market_data.providers import get_bars
    b = get_bars(sym, tf="5m", period="5d")
    tcol = "ts_et" if "ts_et" in b.columns else "ts"
    et = pd.to_datetime(b[tcol])
    return b.assign(_hm=et.dt.hour * 60 + et.dt.minute, _day=et.dt.strftime("%Y-%m-%d"))


def _fires(rule_key: str, b, today: str) -> bool:
    """Entry condition on completed prior bars (evaluated Monday 9:31-9:50)."""
    days = sorted(set(b["_day"]))
    if today not in days or days.index(today) < 1:
        return False
    if RULES[rule_key]["kind"] == "every_monday":
        return True
    prev = days[days.index(today) - 1]                # the prior trading day (Friday)
    rth = b[(b["_day"] == prev) & (b["_hm"].between(570, 959))]
    if len(rth) < 30:
        return False
    return float(rth["close"].iloc[-1]) < float(rth["open"].iloc[0])   # down Friday -> long Monday


def tick(now=None) -> None:
    now = now or pd.Timestamp.now(tz="America/New_York")
    hm = now.hour * 60 + now.minute
    today = now.strftime("%Y-%m-%d")
    st = _load()
    for key, cfg in RULES.items():
        if not _approved(cfg["lineage"]):
            continue
        pos = st["open"].get(key)
        # EXIT: book at the RTH close
        if pos and hm >= 16 * 60 + 1:
            b = _bars(cfg["symbol"])
            rth = b[(b["_day"] == pos["date"]) & (b["_hm"].between(570, 959))]
            if len(rth):
                x = float(rth["close"].iloc[-1])
                ret = (x - pos["entry"]) / pos["entry"]
                st["journal"].append({"lineage": cfg["lineage"], "symbol": cfg["symbol"],
                                      "date": pos["date"], "side": "long",
                                      "entry": pos["entry"], "exit": round(x, 2),
                                      "ret_pct": round(100 * ret, 4)})
                st["journal"] = st["journal"][-2000:]
                st["open"][key] = None
                _save(st)
            continue
        # ENTRY: Monday 9:31-9:50
        if pos is None and now.dayofweek == 0 and 9 * 60 + 31 <= hm < 9 * 60 + 50:
            b = _bars(cfg["symbol"])
            if not _fires(key, b, today):
                continue
            try:
                from bot.market_data.providers import latest_price
                px = (latest_price(cfg["symbol"]) or {}).get("price")
            except Exception:
                px = None
            if px:
                st["open"][key] = {"date": today, "entry": round(float(px), 2),
                                   "entered_at": str(now)[:16]}
                _save(st)


def perf(rule_key: str) -> dict:
    lin = RULES[rule_key]["lineage"]
    j = [x for x in _load()["journal"] if x.get("lineage") == lin and x.get("ret_pct") is not None]
    if not j:
        return {"n": 0}
    import numpy as np
    rs = np.array([x["ret_pct"] for x in j], float)
    w, l = float(rs[rs > 0].sum()), float(-rs[rs <= 0].sum())
    return {"n": int(len(rs)), "win_pct": round(100 * float((rs > 0).mean()), 1),
            "avg_r": round(float(rs.mean()), 3), "total_r": round(float(rs.sum()), 2),
            "pf": round(w / l, 2) if l > 0 else None}


def open_positions() -> list:
    st = _load()
    out = []
    for key, pos in (st.get("open") or {}).items():
        if pos:
            cfg = RULES[key]
            out.append({"module": key, "book": "eq", "symbol": cfg["symbol"], "side": "long",
                        "entry": pos["entry"], "opened": pos["date"],
                        "note": "exit at the 16:00 close (stop grid queued)"})
    return out


if __name__ == "__main__":
    print("state:", json.dumps(_load(), indent=1)[:250])
    for k in RULES:
        print(k, perf(k))
    print("eq-calendar module OK")
