"""TICK WATCHER (F102, user 2026-07-10: "fast watcher thread — 2-5s snapshot/tick poll, only for
symbols with open positions or armed setups, rate-limit friendly").

A daemon thread polls latest_price (Webull snapshot chain) every POLL_SEC for the ACTIVE symbol
set only (a callback the server provides: open tracked positions + firing signals + session
holds). Keeps an in-memory ring per symbol, flushes 1-minute snapshots to data/ticks/ (data-first
— the forward tick archive true-tick research needs), and reports touch events via on_tick.

Entries stay on validated 5m closes — this watcher serves EXIT honesty, touch alerts, and data
collection, never new entry logic (that would be an unvalidated strategy).
"""
from __future__ import annotations

import json
import threading
import time
from collections import deque

from bot.config import BOT_ROOT

POLL_SEC = 3.0
RING = 1200                              # ~1h of 3s polls per symbol
DIR = BOT_ROOT / "data" / "ticks"

_state = {"on": False, "last_poll": 0.0, "polled": 0, "errors": 0, "symbols": []}
_rings: dict[str, deque] = {}
_flush_at = {"t": 0.0}


def status() -> dict:
    return {**_state, "age_sec": round(time.time() - _state["last_poll"], 1) if _state["last_poll"] else None,
            "ring_sizes": {k: len(v) for k, v in _rings.items()}}


def latest(sym: str):
    r = _rings.get(sym)
    return r[-1] if r else None


def series(sym: str, n: int = 200) -> list:
    r = _rings.get(sym)
    return list(r)[-n:] if r else []


def _flush():
    """Once a minute: append each ring's new points to data/ticks/<date>/<sym>.jsonl (forward
    tick archive — the substrate for true intrabar research once enough accrues)."""
    now = time.time()
    if now - _flush_at["t"] < 60:
        return
    _flush_at["t"] = now
    day = time.strftime("%Y-%m-%d")
    d = DIR / day
    d.mkdir(parents=True, exist_ok=True)
    for sym, r in _rings.items():
        fresh = [p for p in r if p[0] > now - 70]
        if not fresh:
            continue
        with open(d / f"{sym}.jsonl", "a", encoding="utf-8") as f:
            for ts, px in fresh:
                f.write(json.dumps({"ts": round(ts, 1), "px": px}) + "\n")


def _loop(symbols_fn, on_tick):
    from bot.market_data.providers import latest_price
    while _state["on"]:
        try:
            syms = list(dict.fromkeys(symbols_fn() or []))[:8]    # rate-limit: cap the active set
            _state["symbols"] = syms
            for sym in syms:
                try:
                    px = (latest_price(sym) or {}).get("price")
                except Exception:
                    px = None
                if px is None:
                    continue
                ts = time.time()
                _rings.setdefault(sym, deque(maxlen=RING)).append((ts, float(px)))
                _state["polled"] += 1
                if on_tick:
                    try:
                        on_tick(sym, ts, float(px))
                    except Exception:
                        _state["errors"] += 1
            _state["last_poll"] = time.time()
            _flush()
        except Exception:
            _state["errors"] += 1
        time.sleep(POLL_SEC)


def direction(sym: str, window_s: float = 90.0) -> dict | None:
    """TICK-DERIVED DIRECTION (F103 — the old 'use ticks instead of the 1m feed' plan, user
    2026-07-10): least-squares slope + up-move persistence over the last ~90s of 3s polls.
    ADVISORY, grade-layer input only — entries stay on validated 5m closes. Returns None when
    the ring is thin or stale (research imports, closed market) so callers fall back to 1m."""
    r = _rings.get(sym)
    if not r or len(r) < 8:
        return None
    now = time.time()
    pts = [(t, p) for t, p in r if t >= now - window_s]
    if len(pts) < 8 or now - pts[-1][0] > 30:
        return None
    n = len(pts)
    xs = [t - pts[0][0] for t, _ in pts]
    ys = [p for _, p in pts]
    mx, my = sum(xs) / n, sum(ys) / n
    den = sum((x - mx) ** 2 for x in xs) or 1e-9
    slope = sum((x - mx) * (y - my) for x, y in zip(xs, ys)) / den      # px per second
    bps_min = slope * 60.0 / my * 1e4
    ups = sum(1 for i in range(1, n) if ys[i] > ys[i - 1])
    pers = ups / (n - 1)
    d = 1 if (bps_min > 0.5 and pers > 0.55) else (-1 if (bps_min < -0.5 and pers < 0.45) else 0)
    return {"dir": d, "slope_bps_min": round(bps_min, 2), "persistence": round(pers, 2),
            "n": n, "window_s": window_s}


def start(symbols_fn, on_tick=None) -> None:
    if _state["on"]:
        return
    _state["on"] = True
    threading.Thread(target=_loop, args=(symbols_fn, on_tick), daemon=True).start()


def stop() -> None:
    _state["on"] = False


if __name__ == "__main__":
    start(lambda: ["QQQ"], on_tick=lambda s, t, p: print(s, p))
    time.sleep(10)
    print("status:", status())
    stop()
    print("tickwatch OK")
