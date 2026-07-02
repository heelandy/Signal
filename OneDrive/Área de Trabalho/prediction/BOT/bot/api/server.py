"""FastAPI backend (API-001 / APIREF-001) — REST + WebSocket over the bot's state.

Read-mostly: the UI observes; the only mutating endpoints are the safety controls (kill switch /
mode / flatten), each routed through the orchestrator + risk gate, never placing a trade directly.

    uvicorn bot.api.server:app --reload      # then open http://127.0.0.1:8000
Endpoints: /api/health /api/journal/metrics /api/performance /api/attribution /api/candidates
           /api/positions  POST /api/control/kill  POST /api/control/mode  + WS /ws/tape  + / (dashboard)
"""
from __future__ import annotations

import asyncio
import json
import os
import random
from pathlib import Path

from fastapi import FastAPI, WebSocket, WebSocketDisconnect, Request, Header, HTTPException, Depends
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles

from pydantic import BaseModel

from bot.config import settings
from bot.journal import Journal
from bot.contracts import TradeCandidate, OrderRequest, OrderType, Mode
from bot.risk import decide, Account
from bot import performance as perf

app = FastAPI(title="HIGHSTRIKE BOT", version="0.1.0")
_journal = Journal()
_state = {"mode": settings.mode, "kill_switch": False}
_broker_cache = {}
STATIC = Path(__file__).parent / "static"
STATIC.mkdir(exist_ok=True)


_REQUIRE_AUTH = os.environ.get("API_REQUIRE_AUTH", "").lower() in ("1", "true", "yes")


def auth(x_api_token: str | None = Header(default=None)):
    """Optional token guard on order-placing + control endpoints. Off by default (server is
    localhost-bound); set API_REQUIRE_AUTH=true to enforce — header X-API-Token: <WEBHOOK_TOKEN>."""
    from bot.security import verify_token
    if _REQUIRE_AUTH and not verify_token(x_api_token):
        raise HTTPException(status_code=401, detail="bad or missing X-API-Token")


# DUPLICATE-ORDER GUARD (review 2026-07): one submission per idempotency key per process, and the
# key rides to the broker as client_order_id so Alpaca dedupes across retries/restarts too.
_SUBMITTED_KEYS: set[str] = set()


def _already_submitted(key: str | None) -> bool:
    if not key:
        return False
    if key in _SUBMITTED_KEYS:
        return True
    _SUBMITTED_KEYS.add(key)
    if len(_SUBMITTED_KEYS) > 5000:                 # bound memory; oldest keys age out wholesale
        _SUBMITTED_KEYS.clear(); _SUBMITTED_KEYS.add(key)
    return False


def _broker():
    """Lazy Alpaca broker for paper/live modes (cached). None in replay/shadow."""
    if _state["mode"] not in (Mode.PAPER.value, Mode.LIVE.value):
        return None
    if "b" not in _broker_cache:
        from bot.brokers.alpaca_broker import AlpacaBroker
        _broker_cache["b"] = AlpacaBroker()
    return _broker_cache["b"]


# ── continuous auto-scan: the engine ALWAYS looks for signals (3 futures sessions + equities) ──
import threading as _threading
import time as _time
from bot.contracts import utcnow_iso as _now
_START = _time.time()                          # process start — for the status-bar uptime
_WATCH = ["SPY", "QQQ", "NQ", "GC"]
_latest = {"signals": [], "ts": None, "error": None, "scanning": False, "market": {}}
_mkt_tick = {"n": 0}


# ── PAPER auto-trade (STUDY MODE) — opt-in toggle; places bracket orders on the ALPACA PAPER account
#    only (hardcoded paper=True → can NEVER go live). Collects real fills to compare vs the backtest. ──
_state["paper_autotrade"] = False
_paper = {"placed": set(), "log": [], "last_err": None}   # dedup keys + study log + last broker error (throttle)


def _paper_broker():
    """Alpaca broker FORCED to paper (paper=True) — independent of the run mode, never touches live."""
    if "pb" not in _broker_cache:
        from bot.brokers.alpaca_broker import AlpacaBroker
        _broker_cache["pb"] = AlpacaBroker(paper=True)
    return _broker_cache["pb"]


def _paper_autotrade():
    """When the toggle is ON: for EVERY NEW breakout signal (grade B → A → A+), place a grade-sized
    bracket order on the PAPER account, simultaneously as the scan detects them. Study ALL grades (incl.
    B) to confirm the live exp-by-grade — B is kept a small NON-zero size so it collects data. Equities
    only (Alpaca can't trade futures). Dedup'd. PAPER only — for study/data collection."""
    if not _state.get("paper_autotrade") or not settings.alpaca_paper:
        return
    from bot.contracts import OrderRequest, OrderType, Side, TimeInForce
    from bot.live import GRADE_MULT
    try:
        b = _paper_broker()
        mkt_open = b.is_market_open()
        _paper["last_err"] = None                 # broker reachable — clear any prior error state
    except Exception as e:
        msg = "broker: " + str(e)[:100]
        if msg != _paper.get("last_err"):         # throttle: log a transient blip ONCE, not every 60s cycle
            _paper["log"].append({"ts": _now(), "error": msg}); _paper["last_err"] = msg
        return
    if not mkt_open:
        return
    for s in (_latest.get("signals") or []):
        if s.get("symbol") not in ("QQQ", "SPY"):                 # Alpaca-tradeable equities only
            continue
        grade = s.get("grade")
        if not s.get("tradeable") or grade not in ("A+", "A", "B"):   # B → A+ (skip C = info-only/unverified)
            continue
        if s.get("source_healthy") is False:      # STALE-DATA GATE: never place an order off a stale/dirty feed
            continue
        if s.get("signal_state") == "invalid":    # ZONE GATE: structure already broke against the signal
            continue
        # STUDY size = grade-weighted (A+ 1.5x / A 1.0x / B 0.4x); B kept ≥1 (don't skip) to collect its live data
        qty = max(1, round(int(s.get("suggested_qty") or 1) * GRADE_MULT.get(grade, 0.4)))
        key = f"{s['symbol']}:{s['side']}:{s['entry']}:{s.get('session')}"
        if key in _paper["placed"]:
            continue
        try:
            order = OrderRequest(candidate_id=key, symbol=s["symbol"],
                                 side=Side.LONG if s["side"] == "long" else Side.SHORT, qty=qty,
                                 order_type=OrderType.MARKET, stop_price=s["stop"], take_profit=s["tp2"],
                                 tif=TimeInForce.DAY, idempotency_key=key)
            ev = b.submit(order)
            _paper["placed"].add(key)
            _paper["log"].append({"ts": _now(), "symbol": s["symbol"], "side": s["side"], "qty": qty,
                                  "grade": s["grade"], "entry": s["entry"], "stop": s["stop"], "tp2": s["tp2"],
                                  "order": str(getattr(ev, "broker_order_id", "") or getattr(ev, "status", "submitted"))})
            _paper["log"] = _paper["log"][-200:]
        except Exception as e:
            _paper["log"].append({"ts": _now(), "symbol": s.get("symbol"), "error": str(e)[:120]})


def _autotrack_acceptable():
    """Shadow-track every ACCEPTABLE live signal (tradeable + grade A+/A/B) as a what-if decision, so the
    Recent-Candidates / Performance / Live-vs-Backtest panels update from the engine's own signal flow —
    no manual Take needed and no order placed. Dedup'd by a stable per-bar key; never clobbers a manual
    decision. track_outcomes() then walks bars to resolve stop/TP1/TP2 first-touch."""
    from bot.tracker import record_decision
    for s in (_latest.get("signals") or []):
        if not s.get("tradeable") or s.get("grade") not in ("A+", "A", "B"):
            continue
        if s.get("signal_state") == "invalid":      # ZONE GATE: don't shadow-track a structurally dead signal
            continue
        if (s.get("bars_ago") or 0) < 1:            # BUGFIX: only CONFIRMED bars — never the forming bar whose
            continue                                # close (=entry) drifts each scan and repaints the signal
        c = s.get("candidate") or {}
        # dedup by BAR (generated_at), NOT the entry price — one tracked signal per bar/side/session, not one
        # per price tick. (The old key put s['entry'] in it, so a drifting live close made 6 rows for 1 breakout.)
        key = f"{s['symbol']}:{s.get('family')}:{s.get('session')}:{s['side']}:{c.get('generated_at') or ''}"
        try:
            record_decision({"candidate_id": key, "symbol": s["symbol"], "side": s["side"],
                             "family": s.get("family"), "session": s.get("session"), "entry": s["entry"],
                             "stop": s["stop"], "tp1": s.get("tp1"), "tp2": s.get("tp2"),
                             "grade": s.get("grade"), "generated_at": c.get("generated_at")}, taken=True, auto=True)
        except Exception:
            pass


def _scan_loop():
    from bot.live import scan_watchlist
    from bot.tracker import track_outcomes
    from bot.market_intel import market_context
    period = int(os.environ.get("BOT_SCAN_SEC", "60"))
    while True:
        if not _state["kill_switch"]:
            _latest["scanning"] = True
            try:
                _latest["signals"] = scan_watchlist(_WATCH, bars_back=4, persist=False)
                _latest["ts"] = _now(); _latest["error"] = None
                _autotrack_acceptable()          # shadow-track ACCEPTABLE signals -> Candidates/Performance/scorecard update
                _paper_autotrade()               # STUDY: place paper orders when the toggle is on
                track_outcomes()                 # resolve first-touch outcomes of tracked signals each cycle
                if _mkt_tick["n"] % 10 == 0:      # market context every ~10 cycles (slow daily data)
                    _latest["market"] = market_context()
                _mkt_tick["n"] += 1
            except Exception as e:
                _latest["error"] = str(e)
            _latest["scanning"] = False
        _time.sleep(period)


@app.get("/api/prop")
def prop_eval(profile: str = "100k", equity: float = 0.0, day_pnl: float = 0.0, peak: float = 0.0,
              days: int = 0, best_day: float = 0.0, yesterday_green: float = 0.0,
              risk_per_r: float = 0.0, from_trades: int = 0):
    """Prop-firm / capital-preservation eval: room to target / daily-loss / trailing-DD + can_trade.
    from_trades=1 estimates equity from your TAKEN closed trades (tracker R × risk_per_r)."""
    from bot.prop import PROFILES, evaluate
    p = PROFILES.get(profile, PROFILES["100k"])
    eq = equity or p.account_size
    if from_trades and risk_per_r > 0:
        from bot.tracker import summary
        eq = p.account_size + (summary().get("total_R", 0.0) or 0.0) * risk_per_r
    res = evaluate(p, eq, peak or None, day_pnl, days, best_day, yesterday_green)
    return {**res, "account_size": p.account_size, "profit_target": p.profit_target,
            "daily_loss": p.daily_loss, "max_drawdown": p.max_drawdown,
            "trailing": p.trailing, "max_contracts": p.max_contracts, "profiles": list(PROFILES)}


@app.get("/api/market")
def market():
    from bot.market_intel import market_context
    return _latest.get("market") or market_context()


_QUOTE_GROUPS = {
    "indices": [("SPY", "SPY"), ("QQQ", "QQQ"), ("DIA", "DIA"), ("IWM", "IWM"), ("VIX", "^VIX")],
    "futures": [("ES", "ES=F"), ("NQ", "NQ=F"), ("YM", "YM=F"), ("RTY", "RTY=F"), ("GC", "GC=F"), ("CL", "CL=F")],
    "forex":   [("EURUSD", "EURUSD=X"), ("GBPUSD", "GBPUSD=X"), ("USDJPY", "JPY=X"), ("DXY", "DX-Y.NYB")],
    "crypto":  [("BTC", "BTC-USD"), ("ETH", "ETH-USD"), ("SOL", "SOL-USD"), ("XRP", "XRP-USD")],
}
_QUOTE_CACHE: dict = {}                                   # group -> (ts, quotes)


@app.get("/api/quotes")
def quotes(group: str = "indices"):
    """Live Market tabs — last price + intraday change for a group of REAL securities (yfinance).
    Cached ~30s so tab-switching is instant."""
    group = group.lower()
    if group not in _QUOTE_GROUPS:
        return {"group": group, "quotes": [], "error": "unknown group"}
    hit = _QUOTE_CACHE.get(group)
    if hit and _time.time() - hit[0] < 30:
        return {"group": group, "quotes": hit[1], "cached": True}
    import yfinance as yf
    labels = {sym: lab for lab, sym in _QUOTE_GROUPS[group]}
    out = []
    try:
        df = yf.download(list(labels), period="2d", interval="1d", progress=False, group_by="ticker", threads=True)
        for sym, lab in ((s, l) for l, s in _QUOTE_GROUPS[group]):
            try:
                closes = df[sym]["Close"].dropna() if sym in df.columns.get_level_values(0) else df["Close"].dropna()
                if len(closes) < 1:
                    continue
                last = float(closes.iloc[-1]); prev = float(closes.iloc[-2]) if len(closes) > 1 else last
                chg = last - prev; pct = 100 * chg / prev if prev else 0.0
                out.append({"symbol": lab, "price": round(last, 2), "change": round(chg, 2), "pct": round(pct, 2)})
            except Exception:
                pass
    except Exception as e:
        return {"group": group, "quotes": [], "error": str(e)[:80]}
    _QUOTE_CACHE[group] = (_time.time(), out)
    return {"group": group, "quotes": out}


@app.get("/api/system")
def system():
    from bot.platform import registry
    from bot.security import keys_status
    return {"capabilities": registry.health(), "keys": keys_status()}


@app.get("/api/datasources")
def datasources(probe: int = 0):
    """Readiness of every data provider (configured / SDK / auth) + the active priority order.
    ?probe=1 actively hits Webull so you SEE it authenticate the moment you paste production keys."""
    from bot.market_data.providers import provider_status
    return provider_status(probe=bool(probe))


@app.on_event("startup")
def _startup():
    if os.environ.get("BOT_AUTOSCAN", "1") != "0":
        _threading.Thread(target=_scan_loop, daemon=True).start()


@app.get("/api/health")
def health():
    broker = "n/a"
    return {"mode": _state["mode"], "kill_switch": _state["kill_switch"],
            "live_allowed": settings.live_allowed, "alpaca_paper": settings.alpaca_paper,
            "source_healthy": True, "broker": broker, "healthy": not _state["kill_switch"],
            "uptime_sec": int(_time.time() - _START), "scanning": _latest["scanning"],
            "paper_autotrade": _state.get("paper_autotrade", False)}


@app.get("/api/contract")
def contract(symbol: str, spot: float, side: str = "long", iv: float = 0.20, dte: int = 0, otm: float = 0.0,
             tp1: float = 0.0, tp2: float = 0.0, stop: float = 0.0):
    """Greeks + bid/mid/ask for the ATM(-ish) option a signal would use, PLUS what the contract is worth
    if the underlying reaches TP1 / TP2 / stop (Black-Scholes repriced at each level, same IV) — powers the
    Selected Contract panel. bid/ask from a ~4% spread estimate (Pine/BOT have no live chain)."""
    from bot.options import pricing as P
    right = "C" if side.lower() in ("long", "call", "c") else "P"
    S = float(spot)
    K = round(S * (1 + (otm / 100.0) * (1 if right == "C" else -1)))
    T = P.year_frac(max(int(dte), 0) * 390 + 195)          # 0DTE ~ half a session of clock left
    g = P.greeks(S, K, T, 0.045, float(iv), right)
    mid = g.price
    spread = max(0.02, round(mid * 0.04, 2))

    def proj(level):                                        # option value if the underlying reaches `level`
        if not level or mid <= 0:
            return None
        v = P.price(float(level), K, T, 0.045, float(iv), right)
        return {"px": round(v, 2), "pct": round(100 * (v - mid) / mid, 0)}

    return {"symbol": symbol.upper(), "right": right, "strike": K, "dte": int(dte), "iv": round(float(iv), 3),
            "bid": round(mid - spread / 2, 2), "mid": round(mid, 2), "ask": round(mid + spread / 2, 2),
            "delta": g.delta, "gamma": g.gamma, "theta": g.theta, "vega": g.vega,
            "implied_move_pct": round(100 * float(iv) * (T ** 0.5), 2),
            "at_tp1": proj(tp1), "at_tp2": proj(tp2), "at_stop": proj(stop)}


@app.get("/api/orb_levels")
def orb_levels(symbol: str = "SPY"):
    """Per-session opening-range hi/lo + live clock status for the ORB Manager panel. One 5m fetch,
    sliced by ET time into the NY / Asia / London OR windows + the prior-day RTH OR."""
    from bot.market_data.providers import get_bars
    import pandas as pd
    sym = symbol.upper()
    try:
        b = get_bars(sym, "5m", period="5d")
    except Exception as e:
        return {"symbol": sym, "sessions": [], "error": str(e)[:100]}
    if b is None or not len(b):
        return {"symbol": sym, "sessions": [], "error": "no bars"}
    b = b.copy()
    et = pd.to_datetime(b["ts_et"])                           # provider returns bars already in ET
    if getattr(et.dt, "tz", None) is not None:
        et = et.dt.tz_convert("America/New_York")
    b["d"] = et.dt.date; b["hm"] = (et.dt.hour * 60 + et.dt.minute)
    now = pd.Timestamp.now(tz="America/New_York"); now_hm = now.hour * 60 + now.minute

    def orng(lo, hi, back=0):
        w = b[(b["hm"] >= lo) & (b["hm"] < hi)]
        days = sorted(w["d"].unique())
        if len(days) <= back:
            return None
        ww = w[w["d"] == days[-1 - back]]
        return {"high": round(float(ww["high"].max()), 2), "low": round(float(ww["low"].min()), 2)}

    # (name, label, or_lo_min, or_hi_min, trade_end_min, back)
    specs = [("NY ORB", "09:30-10:00", 570, 600, 900, 0),
             ("Asia ORB", "19:00-19:30", 1140, 1170, 210, 0),
             ("London ORB", "03:00-03:30", 180, 210, 480, 0),
             ("Prev Day ORB", "09:30-10:00", 570, 600, 900, 1)]
    def _in(a, b):                                            # now_hm in [a,b), wrap-aware (Asia/London cross midnight)
        return (a <= now_hm < b) if a <= b else (now_hm >= a or now_hm < b)
    out = []
    for name, lab, olo, ohi, tend, back in specs:
        lv = orng(olo, ohi, back)
        if back:                                              # prior day = reference only
            st = "REF"
        elif _in(olo, ohi):
            st = "BUILDING"
        elif _in(ohi, tend):
            st = "ACTIVE"
        else:
            st = "CLOSED"
        out.append({"session": name, "time": lab, "high": lv["high"] if lv else None,
                    "low": lv["low"] if lv else None, "status": st})
    return {"symbol": sym, "sessions": out, "now_et": now.strftime("%H:%M")}


@app.get("/api/journal/metrics")
def journal_metrics():
    return _journal.metrics()


@app.get("/api/performance")
def performance():
    """Live tracked record (auto-shadow + manual taken signals, first-touch R). Falls back to the
    replay journal if nothing is tracked yet."""
    from bot.tracker import perf_summary
    p = perf_summary()
    return p if p.get("trades") else perf.summary(_journal)


@app.get("/api/study")
def study():
    """First-touch study: what hit first (stop vs TP) + MFE/MAE + tuning hints for stop/target accuracy."""
    from bot.tracker import study as _study
    return _study()


@app.get("/api/attribution")
def attribution():
    return perf.attribution(_journal)


@app.get("/api/equity")
def equity():
    return {"curve": [round(float(x), 2) for x in perf.equity_curve(_journal).tolist()]}


@app.get("/api/signals")
def signals(force: int = 0):
    """LIVE SIGNALS (the product) — served from the CONTINUOUS auto-scanner (always looking, 3 futures
    sessions + equities). Each carries entry/stop/TP1/TP2, P(win), order-flow, the options play, family
    + asset validation. ?force=1 triggers a fresh scan. No trades."""
    if force or _latest["ts"] is None:
        from bot.live import scan_watchlist
        try:
            _latest["signals"] = scan_watchlist(_WATCH, bars_back=4, persist=False); _latest["ts"] = _now()
        except Exception as e:
            _latest["error"] = str(e)
    return {"signals": _latest["signals"], "ts": _latest["ts"], "scanning": _latest["scanning"],
            "error": _latest["error"], "watchlist": _WATCH}


@app.get("/api/asset_levels")
def asset_levels(symbol: str):
    """Levels to auto-fill the options calculator for a SELECTED asset (even when no signal is firing):
    a live signal's levels if one exists, else current price + an ATR-based default setup."""
    sym = symbol.upper()
    for s in (_latest.get("signals") or []):                 # 1) a live signal for this asset?
        if s.get("symbol") == sym and s.get("side"):
            return {"symbol": sym, "side": s["side"], "entry": s["entry"], "stop": s["stop"],
                    "tp1": s.get("tp1"), "tp2": s["tp2"], "iv_est": s.get("iv_est"), "source": "live signal"}
    import numpy as np                                        # 2) current price + ATR default
    from bot.market_data.providers import get_bars, latest_price
    try:
        bars = get_bars(sym, "5m", period="3d")
    except Exception as e:
        return {"error": f"{sym}: {e}"}
    if not len(bars):
        return {"error": f"no data for {sym}"}
    px = latest_price(sym).get("price") or round(float(bars["close"].iloc[-1]), 2)
    hi, lo, cl = (bars[c].to_numpy(float) for c in ("high", "low", "close"))
    atr = float(np.nanmean((hi - lo)[-50:])) or px * 0.002
    ret = np.diff(np.log(cl[-120:]))
    iv = round(float(np.clip(np.std(ret) * (252 * 78) ** 0.5, 0.10, 0.80)), 3) if len(ret) > 5 else 0.20
    risk = 1.5 * atr
    return {"symbol": sym, "side": "long", "entry": round(px, 2), "stop": round(px - risk, 2),
            "tp1": round(px + 1.5 * risk, 2), "tp2": round(px + 4 * risk, 2), "iv_est": iv,
            "source": "current price + ATR default (no live signal — adjust side/levels as needed)"}


class DecisionReq(BaseModel):
    signal: dict
    taken: bool


@app.post("/api/signal/decision")
def signal_decision(d: DecisionReq):
    """User marks a signal Taken or Skipped; the system then tracks where it goes (stop/TP1/TP2 first)."""
    from bot.tracker import record_decision
    return record_decision(d.signal, d.taken)


@app.get("/api/decisions")
def decisions():
    """The journal of taken/skipped signals + their tracked outcomes (real performance of the engine)."""
    from bot.tracker import list_decisions, track_outcomes, summary
    try:
        track_outcomes()
    except Exception:
        pass
    return {"decisions": list_decisions(50), "summary": summary()}


@app.get("/api/scorecard")
def scorecard():
    """LIVE-vs-BACKTEST gate: do taken signals realise the backtested edge (by grade)? The check that
    must pass before sizing up — proves the edge survives live fills, not just the backtest."""
    from bot.tracker import scorecard as _sc, track_outcomes
    try:
        track_outcomes()
    except Exception:
        pass
    return _sc()


@app.get("/api/candidates")
def candidates(limit: int = 50):
    """Recent ACCEPTABLE signals the engine tracked (auto-shadow + manual), newest first, with the
    resolved first-touch outcome. Updates live off the same tracker the scorecard/Performance use."""
    from bot.tracker import list_decisions
    out = []
    for x in list_decisions(limit):
        risk = abs((x.get("entry") or 0) - (x.get("stop") or 0))
        rr = round(abs((x.get("tp2") or 0) - (x.get("entry") or 0)) / risk, 1) if risk else None
        out.append({"symbol": x["symbol"], "side": x["side"], "setup": x.get("family"), "entry": x["entry"],
                    "expected_r": rr, "generated_at": x.get("signal_at") or x.get("decided_at"),
                    "outcome": x.get("outcome")})
    return {"candidates": out}


@app.get("/api/positions")
def positions():
    rows = _journal.read("JournalEntry")
    open_rows = [r for r in rows if r.get("closed_at") is None and r.get("net_r") is None]
    return {"open": open_rows, "recent_closed": rows[-20:]}


@app.post("/api/control/kill")
def kill(on: bool = True, x_api_token: str | None = Header(default=None)):
    """ACTIVATING the kill switch is always allowed (an emergency stop must never be locked out);
    DISARMING it goes through the token guard when API_REQUIRE_AUTH is on."""
    if not on:
        auth(x_api_token)
    _state["kill_switch"] = bool(on)        # consulted by the orchestrator before any submit
    return {"kill_switch": _state["kill_switch"]}


@app.post("/api/control/paper_autotrade")
def paper_autotrade_toggle(on: int = 0, _=Depends(auth)):
    """STUDY toggle: when ON, the bot auto-places PAPER bracket orders on Alpaca for A+/A equity
    signals (grade-sized). PAPER ACCOUNT ONLY (hardcoded paper=True) — it can NEVER place a live trade.
    Requires Alpaca keys + market hours. Data is for study/comparison vs the backtest."""
    if on and not settings.alpaca_paper:
        return {"error": "Alpaca is not in paper mode (set ALPACA_PAPER=true + keys)", "paper_autotrade": False}
    _state["paper_autotrade"] = bool(on)
    return {"paper_autotrade": _state["paper_autotrade"], "placed": len(_paper["placed"])}


@app.get("/api/paper_log")
def paper_log():
    """Study log — what the paper-autotrade placed (and any errors)."""
    return {"on": _state.get("paper_autotrade", False), "alpaca_paper": settings.alpaca_paper,
            "placed": len(_paper["placed"]), "log": _paper["log"][-40:]}


@app.post("/api/control/mode")
def set_mode(mode: str, _=Depends(auth)):
    if mode == "live" and not settings.live_allowed:
        return {"error": "live blocked: needs LIVE_APPROVED.lock", "mode": _state["mode"]}
    _state["mode"] = mode
    _broker_cache.clear()                       # rebuild broker for the new mode
    return {"mode": _state["mode"]}


# ── order placement (UI), still routed through risk gate + kill switch + mode gate ──
class OrderTicket(BaseModel):
    symbol: str
    side: str                                   # "long" | "short"
    entry: float
    stop: float
    tp2: float
    qty: int | None = None                      # optional; risk sizes if omitted


@app.get("/api/account")
def account():
    b = _broker()
    if b is None:
        return {"mode": _state["mode"], "broker": "none (replay/shadow)", "positions": [], "orders": []}
    try:
        a = b.account()
        return {"mode": _state["mode"], "equity": a.equity, "buying_power": a.buying_power,
                "is_paper": a.is_paper, "market_open": b.is_market_open(),
                "positions": [p.to_dict() for p in b.positions()], "orders": b.open_orders()}
    except Exception as e:
        return {"mode": _state["mode"], "error": str(e), "positions": [], "orders": []}


@app.post("/api/order")
def place_order(t: OrderTicket, _=Depends(auth)):
    if _state["kill_switch"]:
        return {"action": "blocked", "reason": "kill_switch active"}
    # 1) build + validate the candidate (fail-closed geometry)
    try:
        c = TradeCandidate(symbol=t.symbol.upper(), side=t.side, timeframe="manual", setup="manual",
                           entry=t.entry, stop=t.stop, tp2=t.tp2, strategy_version="ui-manual")
    except ValueError as e:
        return {"action": "rejected", "reason": f"bad order geometry: {e}"}
    _journal.record(c)
    # 2) risk gate (sized off the live account when paper/live)
    b = _broker()
    equity = 100_000.0
    if b is not None:
        try:
            equity = b.account().equity
        except Exception:
            pass
    acct = Account(equity=equity, mode=Mode(_state["mode"]) if _state["mode"] in
                   ("replay", "paper", "live") else Mode.PAPER, kill_switch=_state["kill_switch"])
    rd = decide(c, acct)
    _journal.record(rd)
    if not rd.approved:
        return {"action": "rejected", "reason": rd.reason_code.value, "notes": rd.notes}
    qty = min(t.qty, rd.max_qty) if t.qty else rd.max_qty
    # DUPLICATE-ORDER GUARD: a double-clicked ticket / retried POST must not stack orders.
    # Manual tickets are keyed by the full geometry (symbol|side|entry|stop|qty|day) so an
    # intentionally different second trade on the same symbol still goes through.
    import hashlib as _hl
    ticket_key = _hl.sha1(f"manual|{c.symbol}|{c.side.value}|{c.entry}|{c.stop}|{qty}|"
                          f"{c.generated_at[:10]}".encode()).hexdigest()[:16]
    if _already_submitted(ticket_key):
        return {"action": "duplicate", "idempotency_key": ticket_key,
                "note": "identical ticket already submitted today — no new order"}
    order = OrderRequest(candidate_id=c.candidate_id, symbol=c.symbol, side=c.side, qty=qty,
                         order_type=OrderType.LIMIT, limit_price=c.entry,
                         stop_price=c.stop, take_profit=c.tp2, idempotency_key=ticket_key)
    # 3) transmit (paper/live) or shadow-log (replay/shadow)
    if b is None:
        return {"action": "shadow", "qty": qty, "note": "logged, NOT transmitted (mode=" + _state["mode"] + ")",
                "rr": round(c.rr, 2)}
    ev = b.submit(order)
    _journal.record(ev)
    return {"action": "submitted", "state": ev.state.value, "qty": qty,
            "broker_order_id": ev.broker_order_id, "msg": ev.message}


class OptionReq(BaseModel):
    symbol: str
    side: str
    entry: float
    stop: float
    tp1: float | None = None
    tp2: float
    iv: float = 0.20
    dte: int = 0
    sel_n: int = 1


@app.post("/api/options")
def options(o: OptionReq):
    """Compute the naked/debit/credit call-and-put plays for a signal (Python, not Pine)."""
    from bot.options.translate import options_for_candidate
    try:
        c = TradeCandidate(symbol=o.symbol.upper(), side=o.side, timeframe="manual", setup="manual",
                           entry=o.entry, stop=o.stop, tp1=o.tp1, tp2=o.tp2, strategy_version="ui")
    except ValueError as e:
        return {"error": str(e)}
    return options_for_candidate(c, iv=o.iv, dte=o.dte, sel_n=o.sel_n)


@app.post("/api/exit_plan")
def exit_plan(o: OptionReq):
    """WHERE to take TP1(1.5R)/TP2(4R) + which option structure exits where + the recommendation (F64)."""
    from bot.options.exit_plan import options_exit_plan
    # exit_plan derives TP1/TP2 from entry/stop itself; tp2 just needs to be a valid placeholder
    try:
        c = TradeCandidate(symbol=o.symbol.upper(), side=o.side, timeframe="manual", setup="manual",
                           entry=o.entry, stop=o.stop, tp2=o.tp2, regime=None, strategy_version="ui")
    except ValueError as e:
        return {"error": str(e)}
    return options_exit_plan(c, iv=o.iv, dte=o.dte, sel_n=o.sel_n)


@app.post("/webhook/tradingview")
async def tv_webhook(req: Request):
    """Receive a TradingView alert (AUTO Pine 'Generic JSON') and route it through the risk gate.
    Auth: a 'token' field in the payload must match WEBHOOK_TOKEN (TV can't send custom headers).
    Body: {"event":"entry|exit|close","ticker","action":"buy|sell","quantity","entry","stopLoss","takeProfit","token"}"""
    import json as _json
    from bot.security import verify_token
    raw = await req.body()
    try:
        p = _json.loads(raw or b"{}")
    except Exception:
        return {"action": "rejected", "reason": "bad json"}
    if not settings.webhook_token or not verify_token(p.get("token")):   # constant-time compare
        return {"action": "rejected", "reason": "bad or missing token"}
    if _state["kill_switch"]:
        return {"action": "blocked", "reason": "kill_switch"}
    sym = (p.get("ticker") or p.get("symbol") or "").upper()
    event = (p.get("event") or "").lower()
    b = _broker()

    if event in ("exit", "close") or (p.get("action") or "").lower() in ("exit", "close"):
        if b is None:
            return {"action": "shadow_exit", "ticker": sym, "note": "logged (no live broker in this mode)"}
        return {"action": "exit", "ticker": sym, **b.flatten()}

    side = {"buy": "long", "sell": "short"}.get((p.get("action") or "").lower())
    if side is None:
        return {"action": "rejected", "reason": f"unknown action {p.get('action')}"}
    try:
        c = TradeCandidate(symbol=sym, side=side, timeframe="webhook", setup="orb_stack_auto",
                           entry=float(p["entry"]), stop=float(p["stopLoss"]), tp2=float(p["takeProfit"]),
                           strategy_version="tv-auto")
    except (KeyError, ValueError) as e:
        return {"action": "rejected", "reason": f"bad payload geometry: {e}"}
    # DUPLICATE-WEBHOOK GUARD: TradingView retries + repeated alerts must not stack live orders.
    # Key = payload signalId if the Pine sends one, else the candidate's deterministic
    # (symbol|side|setup|session-day) idempotency key.
    dedup_key = str(p.get("signalId") or p.get("signal_id") or c.idempotency_key)
    if _already_submitted(dedup_key):
        return {"action": "duplicate", "ticker": sym, "idempotency_key": dedup_key,
                "note": "already processed — no new order"}
    _journal.record(c)
    equity = 100_000.0
    if b is not None:
        try:
            equity = b.account().equity
        except Exception:
            pass
    acct = Account(equity=equity, mode=Mode(_state["mode"]) if _state["mode"] in ("replay", "paper", "live") else Mode.PAPER,
                   kill_switch=_state["kill_switch"])
    rd = decide(c, acct)
    _journal.record(rd)
    if not rd.approved:
        return {"action": "rejected", "reason": rd.reason_code.value, "ticker": sym}
    qty = int(p.get("quantity") or 0) or rd.max_qty
    qty = min(qty, rd.max_qty)
    order = OrderRequest(candidate_id=c.candidate_id, symbol=sym, side=side, qty=qty,
                         order_type=OrderType.LIMIT, limit_price=c.entry, stop_price=c.stop,
                         take_profit=c.tp2, idempotency_key=dedup_key)   # broker-side dedup (client_order_id)
    if b is None:
        return {"action": "shadow", "ticker": sym, "qty": qty, "note": f"logged, not transmitted (mode={_state['mode']})"}
    ev = b.submit(order)
    _journal.record(ev)
    return {"action": "submitted", "ticker": sym, "qty": qty, "state": ev.state.value,
            "broker_order_id": ev.broker_order_id}


@app.post("/api/order/cancel")
def cancel_order(order_id: str):
    b = _broker()
    if b is None:
        return {"error": "no live broker in this mode"}
    return {"cancelled": b.cancel(order_id).state.value}


@app.post("/api/flatten")
def flatten(_=Depends(auth)):
    b = _broker()
    if b is None:
        return {"error": "no live broker in this mode"}
    return b.flatten()


def _flow_score(b, n: int = 20) -> float:
    """REAL order-flow pressure from recent bars (Webull feed): net volume-weighted direction of the last
    n 5m bars → 0-100 (50 = balanced, >50 = net buying, <50 = net selling). Uptick/downtick volume proxy —
    a bar closing up counts its volume as buy pressure, down as sell. Not tick-level, but real, not random."""
    try:
        import numpy as np
        t = b.tail(n)
        delta = (t["close"].astype(float) - t["open"].astype(float)).to_numpy()
        vol = t["volume"].astype(float).clip(lower=1.0).to_numpy()
        total = float(vol.sum())
        if total <= 0:
            return 50.0
        signed = float((np.sign(delta) * vol).sum())          # net buy vs sell volume, in [-total, total]
        return round(max(0.0, min(100.0, 50.0 + 50.0 * signed / total)), 0)
    except Exception:
        return 50.0


@app.websocket("/ws/tape")
async def tape(ws: WebSocket):
    """LIVE order-flow pressure — volume-weighted directional flow from the latest Webull 5m SPY bars
    (falls back through the provider chain). Refetched ~8s off-thread; streamed every 2s."""
    await ws.accept()
    from bot.market_data.providers import get_bars
    loop = asyncio.get_event_loop()
    score, sym, last = 50.0, "SPY", 0.0
    try:
        while True:
            now = loop.time()
            if now - last > 8:                                 # refetch bars off the event loop
                last = now
                try:
                    b = await loop.run_in_executor(None, lambda: get_bars(sym, "5m", "1d"))
                    score = _flow_score(b)
                except Exception:
                    pass
            await ws.send_text(json.dumps({"score": score, "sym": sym, "live": True, "ts": now}))
            await asyncio.sleep(2)
    except WebSocketDisconnect:
        return


@app.get("/", response_class=HTMLResponse)
def dashboard():
    f = STATIC / "dashboard.html"
    return f.read_text(encoding="utf-8") if f.exists() else "<h1>HIGHSTRIKE BOT</h1><p>dashboard.html missing</p>"


if (STATIC).exists():
    app.mount("/static", StaticFiles(directory=str(STATIC)), name="static")
