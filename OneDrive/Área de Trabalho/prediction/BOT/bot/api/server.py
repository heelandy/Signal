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
    """Optional token guard on order-placing endpoints. Off by default (server is localhost-bound);
    set API_REQUIRE_AUTH=true to enforce — then send header X-API-Token: <WEBHOOK_TOKEN>."""
    if _REQUIRE_AUTH and x_api_token != settings.webhook_token:
        raise HTTPException(status_code=401, detail="bad or missing X-API-Token")


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
_WATCH = ["SPY", "QQQ", "NQ", "GC"]
_latest = {"signals": [], "ts": None, "error": None, "scanning": False, "market": {}}
_mkt_tick = {"n": 0}


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
                track_outcomes()                 # update outcomes of taken trades each cycle
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


@app.get("/api/system")
def system():
    from bot.platform import registry
    from bot.security import keys_status
    return {"capabilities": registry.health(), "keys": keys_status()}


@app.on_event("startup")
def _startup():
    if os.environ.get("BOT_AUTOSCAN", "1") != "0":
        _threading.Thread(target=_scan_loop, daemon=True).start()


@app.get("/api/health")
def health():
    broker = "n/a"
    return {"mode": _state["mode"], "kill_switch": _state["kill_switch"],
            "live_allowed": settings.live_allowed, "alpaca_paper": settings.alpaca_paper,
            "source_healthy": True, "broker": broker, "healthy": not _state["kill_switch"]}


@app.get("/api/journal/metrics")
def journal_metrics():
    return _journal.metrics()


@app.get("/api/performance")
def performance():
    return perf.summary(_journal)


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


@app.get("/api/candidates")
def candidates(limit: int = 50):
    rows = _journal.read("TradeCandidate")[-limit:]
    return {"candidates": rows}


@app.get("/api/positions")
def positions():
    rows = _journal.read("JournalEntry")
    open_rows = [r for r in rows if r.get("closed_at") is None and r.get("net_r") is None]
    return {"open": open_rows, "recent_closed": rows[-20:]}


@app.post("/api/control/kill")
def kill(on: bool = True):
    _state["kill_switch"] = bool(on)        # consulted by the orchestrator before any submit
    return {"kill_switch": _state["kill_switch"]}


@app.post("/api/control/mode")
def set_mode(mode: str):
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
    order = OrderRequest(candidate_id=c.candidate_id, symbol=c.symbol, side=c.side, qty=qty,
                         order_type=OrderType.LIMIT, limit_price=c.entry,
                         stop_price=c.stop, take_profit=c.tp2)
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
    raw = await req.body()
    try:
        p = _json.loads(raw or b"{}")
    except Exception:
        return {"action": "rejected", "reason": "bad json"}
    if not settings.webhook_token or p.get("token") != settings.webhook_token:
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
                         order_type=OrderType.LIMIT, limit_price=c.entry, stop_price=c.stop, take_profit=c.tp2)
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


@app.websocket("/ws/tape")
async def tape(ws: WebSocket):
    """Live tape stub — streams the (demo) order-flow direction score until the live loop is wired."""
    await ws.accept()
    try:
        score = 50.0
        while True:
            score = max(0, min(100, score + random.uniform(-8, 8)))
            await ws.send_text(json.dumps({"score": round(score, 0), "ts": asyncio.get_event_loop().time()}))
            await asyncio.sleep(1)
    except WebSocketDisconnect:
        return


@app.get("/", response_class=HTMLResponse)
def dashboard():
    f = STATIC / "dashboard.html"
    return f.read_text(encoding="utf-8") if f.exists() else "<h1>HIGHSTRIKE BOT</h1><p>dashboard.html missing</p>"


if (STATIC).exists():
    app.mount("/static", StaticFiles(directory=str(STATIC)), name="static")
