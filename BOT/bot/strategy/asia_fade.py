"""WEEKEND-FADE shadow study (F96->F97b respec 2026-07-10, lineage weekend-fade-0.1, FT book).

Rule (the REAL edge after cohort decomposition — the weekday 18:00->03:00 fade is DEAD OOS):
  FRIDAY's RTH closes in the BOTTOM THIRD of its range
    -> LONG NQ at the SUNDAY 18:00 ET reopen
    -> STOP at entry - 0.5 x the risk unit (Friday's RTH range) — gauntlet-IMPROVING (F97b:
       +8.5bps vs +7.9 no-stop, PF 1.50, OOS +22.5, worst capped -2.35%, ALL 7 PASS)
    -> else exit at the Monday 03:00 Asia close.
Shadow only — no orders; requires a research approval on the ladder (lineage weekend-fade-0.1).

State: data/weekend_fade.json  {"open": {...}|null, "journal": [...]}
Called from the scan loop via _beat("weekend_fade", tick):
  Sunday 18:05-19:00 enter · any tick Sun evening: stop check · Monday >=03:05 time exit.
"""
from __future__ import annotations

import json

import pandas as pd

from bot.config import BOT_ROOT

LINEAGE = "weekend-fade-0.1"
STATE = BOT_ROOT / "data" / "weekend_fade.json"
SYMBOL = "NQ"
STOP_MULT = 0.5                      # x the risk unit (Friday RTH range) — F97b's best cell


def _load() -> dict:
    if STATE.exists():
        try:
            return json.loads(STATE.read_text(encoding="utf-8"))
        except Exception:
            pass
    return {"open": None, "journal": []}


def _save(d: dict) -> None:
    STATE.parent.mkdir(parents=True, exist_ok=True)
    STATE.write_text(json.dumps(d, indent=1), encoding="utf-8")


def _approved() -> bool:
    from bot.approval import status
    return bool(status(LINEAGE)["stages"].get("research"))


def _bars(period="5d"):
    from bot.market_data.providers import get_bars
    b = get_bars(SYMBOL, tf="5m", period=period)
    tcol = "ts_et" if "ts_et" in b.columns else "ts"
    et = pd.to_datetime(b[tcol])
    return b.assign(_hm=et.dt.hour * 60 + et.dt.minute,
                    _day=et.dt.strftime("%Y-%m-%d"), _dow=et.dt.dayofweek)


def _book(st, pos, x, how, today):
    ret = (x - pos["entry"]) / pos["entry"]
    r = (x - pos["entry"]) / pos["risk"] if pos.get("risk") else None
    st["journal"].append({"lineage": LINEAGE, "symbol": SYMBOL, "side": "long",
                          "entered": pos["date"], "exited": today, "how": how,
                          "entry": pos["entry"], "exit": round(float(x), 2),
                          "ret_pct": round(100 * ret, 4),
                          "net_r": round(r, 3) if r is not None else None,
                          "risk_unit": pos.get("risk"), "stop": pos.get("stop")})
    st["journal"] = st["journal"][-2000:]
    st["open"] = None
    _save(st)


def tick(now=None) -> None:
    """One scan-cycle step: Sunday-evening entry off Friday's weak close, live stop, Monday exit."""
    if not _approved():
        return
    now = now or pd.Timestamp.now(tz="America/New_York")
    hm = now.hour * 60 + now.minute
    dow = now.dayofweek                              # Mon=0 .. Sun=6
    today = now.strftime("%Y-%m-%d")
    st = _load()
    pos = st.get("open")
    # ── STOP CHECK: while the position is on (Sun evening through Mon 03:00), first touch books it
    if pos and pos.get("stop"):
        try:
            from bot.market_data.providers import latest_price
            px = (latest_price(SYMBOL) or {}).get("price")
        except Exception:
            px = None
        if px and float(px) <= pos["stop"]:
            _book(st, pos, max(float(px), 0.0), "stop", today)
            return
    # ── TIME EXIT: Monday 03:05-09:30, at the last bar <= 03:00
    if pos and dow == 0 and 3 * 60 + 5 <= hm < 9 * 60 + 30:
        b = _bars("2d")
        seg = b[(b["_day"] == today) & (b["_hm"] < 3 * 60)]
        if len(seg):
            _book(st, pos, float(seg["close"].iloc[-1]), "time_0300", today)
        return
    # ── ENTRY: Sunday 18:05-19:00, keyed off FRIDAY's completed RTH
    if pos is None and dow == 6 and 18 * 60 + 5 <= hm < 19 * 60:
        b = _bars("5d")
        fridays = sorted(set(b.loc[b["_dow"] == 4, "_day"]))
        if not fridays:
            return
        fri = fridays[-1]
        rth = b[(b["_day"] == fri) & (b["_hm"].between(9 * 60 + 30, 15 * 60 + 59))]
        if len(rth) < 30:
            return
        h, l, c = float(rth["high"].max()), float(rth["low"].min()), float(rth["close"].iloc[-1])
        rng = h - l
        if rng <= 0 or (c - l) / rng > 1 / 3:        # Friday didn't close weak -> no trade
            return
        post = b[(b["_day"] == today) & (b["_hm"] >= 18 * 60)]
        if not len(post):
            return
        e = float(post["open"].iloc[0])              # the Sunday reopen
        st["open"] = {"date": today, "friday": fri, "entry": round(e, 2),
                      "risk": round(rng, 2), "stop": round(e - STOP_MULT * rng, 2),
                      "fri_close_loc": round((c - l) / rng, 3), "entered_at": str(now)[:16]}
        _save(st)


def perf() -> dict:
    """Live shadow record for the performance board (net_r normalized by the risk unit)."""
    j = [x for x in _load()["journal"] if x.get("net_r") is not None]
    if not j:
        return {"n": 0}
    import numpy as np
    rs = np.array([x["net_r"] for x in j], float)
    w, l = float(rs[rs > 0].sum()), float(-rs[rs <= 0].sum())
    return {"n": int(len(rs)), "win_pct": round(100 * float((rs > 0).mean()), 1),
            "avg_r": round(float(rs.mean()), 3), "total_r": round(float(rs.sum()), 1),
            "pf": round(w / l, 2) if l > 0 else None}


def open_position() -> dict | None:
    return _load().get("open")


if __name__ == "__main__":
    print("state:", json.dumps(_load(), indent=1)[:300])
    print("perf:", perf())
    print("weekend-fade module OK")
