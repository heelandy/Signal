"""NQ PATTERN COMPOSITE shadow study (F104, gauntlet-passed 2026-07-10 ALL-7, lineage
nq-composite-0.1, FT book).

The census pass-cells as VOTES at ~10:30 ET; trade only on CONFLUENCE (|sum| >= 2):
  +1 long if MONDAY · +sign(first hour) if |FH| >= FH_BIG · -sign(yesterday's RTH) ·
  +1 long if overnight gap up.  Enter 10:35-11:00 at the live price, exit at the 16:00 close.
Record: n=1320 +6.3bps net WR 57 PF 1.22 CI_lo +2.2 15/17 YEARS OOS +9.5 2x-slip +4.4.
Vol overlay (F99[7], V2): high-vol days carry ~4x the edge — sizing input, not wired yet.

FH_BIG is the trailing-252d tercile of |first-hour move|, refreshed by the nightly battery era —
a reviewed CONSTANT here (0.476%) so the live rule stays causal and auditable.
"""
from __future__ import annotations

import json

import pandas as pd

from bot.config import BOT_ROOT

LINEAGE = "nq-composite-0.1"
STATE = BOT_ROOT / "data" / "nq_composite.json"
SYMBOL = "NQ"
MIN_VOTES = 2
FH_BIG = 0.00476                       # trailing-252d tercile @ 2026-07-10 (battery reviews it)
STOP_MULT = 0.25                       # x prior-day RTH range — F107: the stop IMPROVES the rule
                                       # (+6.2bps keeps 124%, PF 1.29, OOS +15.0, worst -1.59%)


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


def _bars():
    from bot.market_data.providers import get_bars
    b = get_bars(SYMBOL, tf="5m", period="5d")
    tcol = "ts_et" if "ts_et" in b.columns else "ts"
    et = pd.to_datetime(b[tcol])
    return b.assign(_hm=et.dt.hour * 60 + et.dt.minute, _day=et.dt.strftime("%Y-%m-%d"))


def compute_votes(b, today: str, dow: int):
    """The four pre-registered votes off completed bars; None when inputs are missing."""
    days = sorted(set(b["_day"]))
    if today not in days or days.index(today) < 1:
        return None
    prev = days[days.index(today) - 1]
    rth_prev = b[(b["_day"] == prev) & (b["_hm"].between(570, 959))]
    fh = b[(b["_day"] == today) & (b["_hm"].between(570, 629))]
    op = b[(b["_day"] == today) & (b["_hm"] >= 570)]
    if len(rth_prev) < 30 or len(fh) < 4 or not len(op):
        return None
    prev_ret = float(rth_prev["close"].iloc[-1]) / float(rth_prev["open"].iloc[0]) - 1
    prev_rng = float(rth_prev["high"].max()) - float(rth_prev["low"].min())
    fh_ret = float(fh["close"].iloc[-1]) / float(fh["open"].iloc[0]) - 1
    gap = float(op["open"].iloc[0]) / float(rth_prev["close"].iloc[-1]) - 1
    v = 0
    detail = {}
    if dow == 0:
        v += 1; detail["monday"] = +1
    if abs(fh_ret) >= FH_BIG:
        s = 1 if fh_ret > 0 else -1
        v += s; detail["first_hour"] = s
    s = -1 if prev_ret > 0 else (1 if prev_ret < 0 else 0)
    v += s; detail["fade_yesterday"] = s
    if gap > 0:
        v += 1; detail["gap_up"] = +1
    return {"votes": v, "detail": detail, "fh_ret": round(fh_ret, 5), "gap": round(gap, 5),
            "prev_rng": round(prev_rng, 2)}


def tick(now=None) -> None:
    if not _approved():
        return
    now = now or pd.Timestamp.now(tz="America/New_York")
    hm = now.hour * 60 + now.minute
    dow = now.dayofweek
    today = now.strftime("%Y-%m-%d")
    st = _load()
    pos = st.get("open")
    # ── LIVE STOP (F107): 0.25x prior-day range — first touch books it, gap-honest at the price seen
    if pos and pos.get("stop") and hm < 16 * 60 + 1:
        try:
            from bot.market_data.providers import latest_price
            px = (latest_price(SYMBOL) or {}).get("price")
        except Exception:
            px = None
        if px:
            sgn = 1 if pos["side"] == "long" else -1
            if (float(px) - pos["stop"]) * sgn <= 0:
                ret = sgn * (float(px) - pos["entry"]) / pos["entry"]
                st["journal"].append({"lineage": LINEAGE, "symbol": SYMBOL, "date": pos["date"],
                                      "side": pos["side"], "votes": pos["votes"], "how": "stop",
                                      "entry": pos["entry"], "exit": round(float(px), 2),
                                      "ret_pct": round(100 * ret, 4), "net_r": round(ret * 100, 3),
                                      "detail": pos.get("detail")})
                st["journal"] = st["journal"][-2000:]
                st["open"] = None
                _save(st)
                return
    # ── EXIT: 16:01-16:30, book at the last RTH close
    if pos and hm >= 16 * 60 + 1:
        b = _bars()
        rth = b[(b["_day"] == pos["date"]) & (b["_hm"].between(570, 959))]
        if len(rth):
            x = float(rth["close"].iloc[-1])
            sgn = 1 if pos["side"] == "long" else -1
            ret = sgn * (x - pos["entry"]) / pos["entry"]
            st["journal"].append({"lineage": LINEAGE, "symbol": SYMBOL, "date": pos["date"],
                                  "side": pos["side"], "votes": pos["votes"],
                                  "entry": pos["entry"], "exit": round(x, 2),
                                  "ret_pct": round(100 * ret, 4), "net_r": round(ret * 100, 3),
                                  "detail": pos.get("detail")})
            st["journal"] = st["journal"][-2000:]
            st["open"] = None
            _save(st)
        return
    # ── ENTRY: weekdays 10:35-11:00 on confluence
    if pos is None and dow <= 4 and 10 * 60 + 35 <= hm < 11 * 60:
        b = _bars()
        sig = compute_votes(b, today, dow)
        if not sig or abs(sig["votes"]) < MIN_VOTES:
            return
        try:
            from bot.market_data.providers import latest_price
            px = (latest_price(SYMBOL) or {}).get("price")
        except Exception:
            px = None
        if not px:
            return
        side = "long" if sig["votes"] > 0 else "short"
        sgn = 1 if side == "long" else -1
        st["open"] = {"date": today, "side": side,
                      "votes": sig["votes"], "detail": sig["detail"],
                      "entry": round(float(px), 2),
                      "risk": sig.get("prev_rng"),
                      "stop": round(float(px) - sgn * STOP_MULT * sig["prev_rng"], 2)
                              if sig.get("prev_rng") else None,
                      "entered_at": str(now)[:16]}
        _save(st)


def perf() -> dict:
    j = [x for x in _load()["journal"] if x.get("ret_pct") is not None]
    if not j:
        return {"n": 0}
    import numpy as np
    rs = np.array([x["ret_pct"] for x in j], float)      # % units; board shows avg per trade
    w, l = float(rs[rs > 0].sum()), float(-rs[rs <= 0].sum())
    return {"n": int(len(rs)), "win_pct": round(100 * float((rs > 0).mean()), 1),
            "avg_r": round(float(rs.mean()), 3), "total_r": round(float(rs.sum()), 2),
            "pf": round(w / l, 2) if l > 0 else None}


def open_position() -> dict | None:
    return _load().get("open")


if __name__ == "__main__":
    print("state:", json.dumps(_load(), indent=1)[:300])
    print("perf:", perf())
    print("nq-composite module OK")
