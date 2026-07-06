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

# RESTART RECOVERY (AITP phase 7, pulled forward 2026-07-05): safety toggles + paper dedup keys
# survive a server restart — a kill-switch must NOT silently reset to off, and a restart must not
# re-place paper orders already sent this session. Mode is NOT restored (live requires its double
# gate every boot by design).
_RUNTIME_STATE = Path(__file__).resolve().parents[2] / "data" / "runtime_state.json"


def _persist_runtime():
    try:
        _RUNTIME_STATE.parent.mkdir(parents=True, exist_ok=True)
        _RUNTIME_STATE.write_text(json.dumps(
            {"kill_switch": _state.get("kill_switch", False),
             "paper_autotrade": _state.get("paper_autotrade", False),
             "paper_placed": sorted(_paper["placed"])[-500:],
             "saved_at": _now()}), encoding="utf-8")
    except Exception:
        pass


def _restore_runtime():
    try:
        if not _RUNTIME_STATE.exists():
            return
        st = json.loads(_RUNTIME_STATE.read_text(encoding="utf-8"))
        _state["kill_switch"] = bool(st.get("kill_switch", False))
        _state["paper_autotrade"] = bool(st.get("paper_autotrade", False))
        _paper["placed"].update(st.get("paper_placed") or [])
    except Exception:
        pass


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
    # APPROVAL GATE (AITP): the strategy version must carry a MANUAL 'paper' approval to trade
    # paper. Re-checked every cycle so a revoke takes effect immediately.
    try:
        from bot.approval import paper_approved
        from bot.strategy.orb_candidates import STRATEGY_VERSION
        if not paper_approved(STRATEGY_VERSION):
            _state["paper_autotrade"] = False
            _paper["log"].append({"ts": _now(), "error": f"paper approval missing for {STRATEGY_VERSION} — autotrade disarmed"})
            return
    except Exception:
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
            _persist_runtime()              # restart must not re-place this order
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
                             "grade": s.get("grade"), "generated_at": c.get("generated_at"),
                             # POST-TRADE LEARNING QUEUE (AITP §18): the PIT snapshot rides with the
                             # decision so resolved outcomes become training rows (bot.ml.live_labels)
                             "pit_features": s.get("pit_features"),
                             "slope_grade": s.get("slope_grade"),
                             # OPTIONS-LEG SHADOW RECORD (audit gap 2026-07-05): the translated
                             # option structure (strikes/expiry/type/est. cost) rides with every
                             # tracked signal — the data the standalone options strategy needs,
                             # collected through paper before any options module goes live.
                             "options": s.get("options"),
                             "ai_decision": s.get("ai_decision")}, taken=True, auto=True)
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
                # bars_back=12 (1 hour): the autotracker dedups per bar, so a wider window costs
                # nothing but makes signal capture survive server restarts — with 4 (20 min) the
                # NQ B-long on 2026-07-06 fired during a reload storm and was never recorded
                _latest["signals"] = scan_watchlist(_WATCH, bars_back=12, persist=False)
                _latest["ts"] = _now(); _latest["error"] = None
                _autotrack_acceptable()          # shadow-track ACCEPTABLE signals -> Candidates/Performance/scorecard update
                _paper_autotrade()               # STUDY: place paper orders when the toggle is on
                track_outcomes()                 # resolve first-touch outcomes of tracked signals each cycle
                try:                             # persist flow scores each cycle (data-first — future feature backfill)
                    from bot.orderflow.persist import snapshot as _of_snap
                    _of_snap(list(dict.fromkeys(s.get("symbol") for s in (_latest.get("signals") or [])
                                                if s.get("symbol"))) or ["SPY", "QQQ"])
                except Exception:
                    pass
                if _mkt_tick["n"] % 10 == 0:      # market context every ~10 cycles (slow daily data)
                    _latest["market"] = market_context()
                    # PERIODIC RECONCILE (phase-7 pulled forward): compare tracked open decisions
                    # vs the paper broker's positions every ~10 min while autotrade is armed
                    if _state.get("paper_autotrade"):
                        try:
                            from bot.reconcile import reconcile_once
                            _latest["reconcile"] = reconcile_once(_paper_broker())
                        except Exception as e:
                            _latest["reconcile"] = {"error": str(e)[:120]}
                    # STRATEGY DUEL (user 2026-07-06): approved module lineages shadow-trade
                    # their daily rules head-to-head; idempotent per completed trading day
                    try:
                        from bot.strategy.duel import run_duel_once
                        _latest["duel_tick"] = run_duel_once()
                    except Exception as e:
                        _latest["duel_tick"] = {"error": str(e)[:120]}
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


_DIR_BARS_CACHE: dict = {}                                # symbol -> (ts, bars_1m)


@app.get("/api/direction")
def direction(symbol: str = "QQQ"):
    """Multi-TF ROLLING direction (research 2026-07-02) for a 10-15s dashboard poll: every chart
    TF re-scored from the SAME 1m array; the 2-bar IMMEDIATE read is refreshed with the live last
    trade on EVERY call, so 'now' moves between minute closes. The 1m frame itself is cached ~45s
    (a new completed bar only arrives once a minute). Detection layer only — never gates trades."""
    sym = symbol.upper()
    from bot.market_data.providers import get_bars, latest_price
    from bot.strategy.direction_engine import update_all_directions, confirmed_states
    hit = _DIR_BARS_CACHE.get(sym)
    b1 = hit[1] if (hit and _time.time() - hit[0] < 45) else None
    if b1 is None:
        try:
            b1 = get_bars(sym, "1m", period="2d")
            _DIR_BARS_CACHE[sym] = (_time.time(), b1)
        except Exception as e:
            return {"symbol": sym, "error": str(e)[:120]}
    try:
        lp = latest_price(sym)
        live = lp.get("price")
    except Exception:
        live = None
    rolling = update_all_directions(b1, live_price=live)
    return {"symbol": sym, "rolling": rolling, "confirmed": confirmed_states(b1),
            "bars": int(len(b1)) if b1 is not None else 0,
            "cached_bars": bool(hit and _time.time() - hit[0] < 45)}


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
    _restore_runtime()                      # kill-switch/paper toggles + dedup keys survive restarts
    if os.environ.get("BOT_AUTOSCAN", "1") != "0":
        _threading.Thread(target=_scan_loop, daemon=True).start()
    # AUTO-ARM continuous training on boot (opt-in): set BOT_CONT_TRAINING=1 (+ optional
    # BOT_CONT_INTERVAL_MIN). Pairs with run_server.bat's --reload so new code always runs.
    if os.environ.get("BOT_CONT_TRAINING", "0") == "1" and not _cont["on"]:
        _cont["interval_min"] = max(30, int(os.environ.get("BOT_CONT_INTERVAL_MIN", "360")))
        _cont["on"] = True
        _threading.Thread(target=_cont_loop, daemon=True).start()
    # report retention (ENGINEERING_AUDIT): timestamped training reports older than 90 days go;
    # un-timestamped study reports (gauntlet/sweep/geometry/...) are latest-only and always kept
    try:
        from bot.config import BOT_ROOT
        import re as _re2, time as _t2
        cutoff = _t2.time() - 90 * 86400
        for f in (BOT_ROOT / "data" / "ml" / "reports").glob("*_*T*.json"):
            if _re2.search(r"_\d{8}T\d{6}\.json$", f.name) and f.stat().st_mtime < cutoff:
                f.unlink()
    except Exception:
        pass


@app.get("/api/health")
def health():
    broker = "n/a"
    try:
        from bot.strategy.orb_candidates import STRATEGY_VERSION as _sv
    except Exception:
        _sv = "?"
    return {"mode": _state["mode"], "kill_switch": _state["kill_switch"],
            "live_allowed": settings.live_allowed, "alpaca_paper": settings.alpaca_paper,
            "source_healthy": True, "broker": broker, "healthy": not _state["kill_switch"],
            "uptime_sec": int(_time.time() - _START), "scanning": _latest["scanning"],
            "paper_autotrade": _state.get("paper_autotrade", False),
            "strategy_version": _sv,           # stale-server tell: compare with the CHANGELOG
            "continuous_training": _cont["on"]}


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
    _persist_runtime()                      # survives a restart (phase-7 recovery)
    from bot.audit import log as _audit
    _audit("kill_switch", on=bool(on))
    return {"kill_switch": _state["kill_switch"]}


@app.post("/api/control/paper_autotrade")
def paper_autotrade_toggle(on: int = 0, _=Depends(auth)):
    """STUDY toggle: when ON, the bot auto-places PAPER bracket orders on Alpaca for A+/A equity
    signals (grade-sized). PAPER ACCOUNT ONLY (hardcoded paper=True) — it can NEVER place a live trade.
    Requires Alpaca keys + market hours + the AITP 'paper' approval for the current strategy version."""
    if on and not settings.alpaca_paper:
        return {"error": "Alpaca is not in paper mode (set ALPACA_PAPER=true + keys)", "paper_autotrade": False}
    if on:
        from bot.approval import paper_approved
        from bot.strategy.orb_candidates import STRATEGY_VERSION
        if not paper_approved(STRATEGY_VERSION):
            return {"error": f"BLOCKED: strategy {STRATEGY_VERSION} has no 'paper' approval — "
                             f"approve research → replay → paper on /training first",
                    "paper_autotrade": False}
    _state["paper_autotrade"] = bool(on)
    _persist_runtime()                      # survives a restart (phase-7 recovery)
    from bot.audit import log as _audit
    _audit("paper_autotrade", on=bool(on))
    return {"paper_autotrade": _state["paper_autotrade"], "placed": len(_paper["placed"])}


@app.get("/api/paper_log")
def paper_log():
    """Study log — what the paper-autotrade placed (and any errors), PLUS the exact blocker when
    it is not trading (user 2026-07-05: 'paper account is set up but I don't see where this is
    doing') — every gate in _paper_autotrade's order, diagnosed."""
    why = "trading — orders appear below as breakout signals fire"
    if not settings.alpaca_paper:
        why = "Alpaca keys not in paper mode — set ALPACA_PAPER=true + API keys, restart"
    elif not _state.get("paper_autotrade"):
        why = "toggle is OFF — flip 'Paper autotrade' on this dashboard"
    else:
        try:
            from bot.approval import paper_approved
            from bot.strategy.orb_candidates import STRATEGY_VERSION
            if not paper_approved(STRATEGY_VERSION):
                why = (f"strategy {STRATEGY_VERSION} has NO 'paper' approval — the rule version "
                       "moved (each bump needs a fresh research→replay→paper approval on /training)")
            else:
                try:
                    if not _paper_broker().is_market_open():
                        why = "market closed — arms itself at the next session"
                except Exception as e:
                    why = "broker unreachable: " + str(e)[:100]
        except Exception as e:
            why = "approval check failed: " + str(e)[:100]
    return {"on": _state.get("paper_autotrade", False), "alpaca_paper": settings.alpaca_paper,
            "why": why, "placed": len(_paper["placed"]), "log": _paper["log"][-40:]}


@app.post("/api/control/mode")
def set_mode(mode: str, _=Depends(auth)):
    if mode == "live":
        # DOUBLE GATE (AITP phase 8): the readiness lock file AND the approval ladder's 'live'
        # stage — either missing blocks live. Paper results must earn this stage first.
        if not settings.live_allowed:
            return {"error": "live blocked: needs LIVE_APPROVED.lock", "mode": _state["mode"]}
        from bot.approval import status as _appr_status
        from bot.strategy.orb_candidates import STRATEGY_VERSION
        if not _appr_status(STRATEGY_VERSION)["stages"].get("live"):
            return {"error": f"live blocked: strategy {STRATEGY_VERSION} has no 'live' approval "
                             f"(earn it with a green paper scorecard first)", "mode": _state["mode"]}
    _state["mode"] = mode
    _broker_cache.clear()                       # rebuild broker for the new mode
    from bot.audit import log as _audit
    _audit("mode_change", mode=mode)
    return {"mode": _state["mode"]}


@app.get("/api/audit")
def audit_tail(n: int = 60, event: str | None = None):
    """Unified audit trail (AITP §8.10) — newest-first governance/state events."""
    from bot.audit import tail
    return {"records": tail(min(n, 500), event)}


@app.get("/api/strategy/modules")
def strategy_modules(status: str | None = None):
    """The AITP strategy-module registry (asset class x style, full module contract)."""
    from bot.strategy.modules import modules
    return {"modules": modules(status)}


@app.get("/api/training/live_labels")
def training_live_labels():
    """Post-trade learning queue status: resolved live outcomes -> training rows."""
    from bot.ml.live_labels import summary
    return summary()


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
    from bot.options.exit_plan import STRUCTURE_GATES
    try:
        c = TradeCandidate(symbol=o.symbol.upper(), side=o.side, timeframe="manual", setup="manual",
                           entry=o.entry, stop=o.stop, tp1=o.tp1, tp2=o.tp2, strategy_version="ui")
    except ValueError as e:
        return {"error": str(e)}
    out = options_for_candidate(c, iv=o.iv, dte=o.dte, sel_n=o.sel_n)
    if isinstance(out, dict):
        out["gates"] = STRUCTURE_GATES          # every UI shows the gate each structure passed
        out["recommended"] = "naked"
    return out


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


# ── ML/NN TRAINING DASHBOARD (offline research visualization — /training) ─────────────────────
# Read-mostly endpoints over the saved training reports/registry/A-B results + one runner that
# launches a training subprocess (research tooling; nothing here places trades).
import subprocess as _subprocess
import sys as _sys

_train_state = {"proc": None, "kind": None, "sym": None, "started": None, "rc": None, "log": []}


def _train_reader(proc):
    try:
        for line in iter(proc.stdout.readline, ""):
            if not line:
                break
            _train_state["log"].append(line.rstrip()[:300])
            _train_state["log"] = _train_state["log"][-80:]
    finally:
        _train_state["rc"] = proc.wait()
        _train_state["proc"] = None


import re as _re


def _safe_args(args: str) -> list[str]:
    """Whitelist-sanitize extra CLI tokens from the dashboard (params like --tf=15m, --retest=0.25)."""
    out = []
    for tok in (args or "").split():
        if _re.fullmatch(r"[A-Za-z0-9@._=\-]+", tok):
            out.append(tok)
    return out


def _train_cmds(kind: str, sym: str, promote: bool = True, extra: list[str] | None = None):
    from bot.config import BOT_ROOT
    root = BOT_ROOT.parent
    flag = ([] if promote else ["--no-promote"]) + (extra or [])
    cmds = {"dataset": ([_sys.executable, "-m", "bot.ml.dataset", sym] + (extra or []), BOT_ROOT),
            "rejects": ([_sys.executable, "-c",
                         "import sys\n"
                         "from bot.ml.dataset import build_rejects\n"
                         "s = sys.argv[1]\n"
                         "df = build_rejects(s)\n"
                         "print(s, len(df), 'rejected setups',\n"
                         "      dict(df['block_reason'].value_counts()) if len(df) else {})",
                         sym], BOT_ROOT),
            "ml": ([_sys.executable, "-m", "bot.ml.pipeline", sym] + flag, BOT_ROOT),
            "nn": ([_sys.executable, "-m", "bot.nn.train", sym] + flag, BOT_ROOT),
            "dataqa": ([_sys.executable, str(root / "pipeline" / "hs_data_qa.py"),
                        "QQQ", "SPY", "NQ", "ES", "GC"], root),
            "ab": ([_sys.executable, str(root / "research" / "ab_entry_standard.py"),
                    "QQQ", "SPY", "NQ", "ES"], root),
            "sweep": ([_sys.executable, str(root / "research" / "sweep_entry_params.py")]
                      + (["QQQ", "SPY", "NQ", "ES"] if sym == "ALL" else [sym])
                      + (extra or []), root),
            "nqwr": ([_sys.executable, str(root / "research" / "nq_winrate.py")]
                     + (["NQ", "ES"] if sym == "ALL" else [sym]), root),
            "heads": ([_sys.executable, "-m", "bot.ml.heads", sym] + flag, BOT_ROOT),
            "similarity": ([_sys.executable, "-m", "bot.nn.similarity", sym], BOT_ROOT),
            "l2sync": ([_sys.executable, "-m", "bot.ml.l2_features", "sync", sym], BOT_ROOT),
            "report": ([_sys.executable, str(root / "research" / "backtest_report.py")]
                       + (["QQQ", "SPY", "NQ", "ES"] if sym == "ALL" else [sym]), root),
            "parity": ([_sys.executable, str(root / "research" / "replay_parity.py")]
                       + (["QQQ", "SPY"] if sym == "ALL" else [sym]), root),
            "gauntlet": ([_sys.executable, str(root / "research" / "gauntlet.py"), sym]
                         + (extra or []), root),
            "threshold": ([_sys.executable, str(root / "research" / "threshold_study.py"), sym], root),
            "geometry": ([_sys.executable, str(root / "research" / "target_geometry.py")]
                         + (["QQQ", "SPY", "NQ", "ES"] if sym == "ALL" else [sym]), root),
            "pairs": ([_sys.executable, str(root / "research" / "dirfast_pairs.py")]
                      + (["QQQ", "SPY", "NQ", "ES"] if sym == "ALL" else [sym]), root)}
    return cmds.get(kind)


@app.post("/api/training/run")
def training_run(kind: str = "ml", sym: str = "QQQ", args: str = "", _=Depends(auth)):
    """Launch one offline training/research job as a subprocess:
    kind = dataset | rejects | ml | nn | heads | similarity | dataqa | ab | sweep | report |
    parity | l2sync | gauntlet. `args` = sanitized extra CLI tokens (e.g. --tf=15m,
    gauntlet params --ctx=1 --cooldown=0 ...). One at a time; watch /api/training/status."""
    if _train_state["proc"] is not None:
        return {"error": f"a {_train_state['kind']} run is already in progress", "running": True}
    sym = sym.upper()
    if not _re.fullmatch(r"[A-Z0-9@._\-]{1,12}", sym):     # sym feeds argv — whitelist it
        return {"error": f"bad symbol '{sym}'"}
    hit = _train_cmds(kind, sym, extra=_safe_args(args))
    if hit is None:
        known = ["dataset", "rejects", "ml", "nn", "dataqa", "ab", "sweep", "heads", "similarity",
                 "l2sync", "report", "parity", "gauntlet", "threshold", "geometry", "nqwr", "pairs"]
        return {"error": f"unknown kind {kind}" + (
                    " — this kind EXISTS in the current code: the SERVER IS RUNNING OLD CODE, "
                    "restart it (run_server.bat)" if kind in known else ""),
                "kinds": known}
    cmd, cwd = hit
    proc = _subprocess.Popen(cmd, cwd=str(cwd), stdout=_subprocess.PIPE,
                             stderr=_subprocess.STDOUT, text=True, encoding="utf-8", errors="replace")
    _train_state.update(proc=proc, kind=kind, sym=sym.upper(), started=_now(), rc=None, log=[])
    _threading.Thread(target=_train_reader, args=(proc,), daemon=True).start()
    from bot.audit import log as _audit
    _audit("training_run", kind=kind, sym=sym.upper(), by="dashboard")
    return {"started": kind, "sym": sym.upper()}


# ── CONTINUOUS TRAINING (AITP §19 — controlled, logged, validated; promotion stays MANUAL) ──
# A background worker cycles dataset -> ML -> NN per symbol (subprocesses, sequential) on an
# interval. Runs train CHALLENGERS with --no-promote: a gate-passing model is registered as
# PENDING and waits for the user's Approve click on the Training Lab. Web-controllable.
_cont = {"on": False, "interval_min": 360, "syms": ["QQQ", "SPY", "NQ", "ES", "ALL"],
         "cycle": 0, "last_start": None, "last_end": None, "current": None, "history": []}


def _cont_run(kind: str, sym: str) -> int:
    hit = _train_cmds(kind, sym, promote=False)
    if hit is None:
        return -1
    cmd, cwd = hit
    _cont["current"] = f"{kind} {sym}"
    p = _subprocess.run(cmd, cwd=str(cwd), stdout=_subprocess.PIPE, stderr=_subprocess.STDOUT,
                        text=True, encoding="utf-8", errors="replace", timeout=3600)
    tail = (p.stdout or "").strip().splitlines()[-3:]
    _cont["history"].append({"ts": _now(), "job": f"{kind} {sym}", "rc": p.returncode,
                             "tail": tail})
    _cont["history"] = _cont["history"][-60:]
    return p.returncode


def _cont_loop():
    sig: dict = {}          # sym -> dataset-build tail (row count + span = content signature)
    while _cont["on"]:
        _cont["last_start"] = _now()
        _cont["cycle"] += 1
        changed = False
        try:
            for sym in list(_cont["syms"]):
                if not _cont["on"]:
                    break
                if _train_state["proc"] is not None:      # never fight a manual run
                    _time.sleep(30)
                    continue
                if sym != "ALL":
                    rc = _cont_run("dataset", sym)
                    tail = _cont["history"][-1]["tail"] if _cont["history"] else None
                    # signature = dataset tail (rows/span) + the l2 feature-store mtimes — an L2
                    # sync changes column VALUES without changing row counts, so the tail alone
                    # would wrongly skip the retrain that the sync exists to trigger
                    try:
                        from bot.config import BOT_ROOT as _BR
                        l2sig = ",".join(f"{f.name}:{int(f.stat().st_mtime)}" for f in
                                         sorted((_BR / "data" / "ml" / "features").glob(f"l2feat_{sym}*")))
                    except Exception:
                        l2sig = ""
                    key = (tuple(tail) if tail else None, l2sig)
                    if rc == 0 and tail and key == sig.get(sym):
                        _cont["history"].append({"ts": _now(), "job": f"skip {sym}", "rc": 0,
                                                 "tail": ["dataset unchanged — ml/nn skipped"]})
                        continue
                    sig[sym] = key
                elif not changed and sig.get("ALL_ran"):   # pooled inputs unchanged too
                    _cont["history"].append({"ts": _now(), "job": "skip ALL", "rc": 0,
                                             "tail": ["no per-symbol dataset changed"]})
                    continue
                changed = changed or sym != "ALL"
                sig["ALL_ran"] = sig.get("ALL_ran") or sym == "ALL"
                _cont_run("ml", sym)
                _cont_run("nn", sym)
        except Exception as e:
            _cont["history"].append({"ts": _now(), "job": "cycle", "rc": -1, "tail": [str(e)[:200]]})
        _cont["last_end"] = _now()
        _cont["current"] = None
        for _ in range(int(_cont["interval_min"] * 60 / 5)):
            if not _cont["on"]:
                break
            _time.sleep(5)


@app.post("/api/training/continuous")
def training_continuous(on: int = 1, interval_min: int = 0, syms: str = "", _=Depends(auth)):
    """Start/stop the continuous training worker (web control). syms = comma list; may include
    ALL (pooled). Challengers train with --no-promote — promotion is your click, never automatic."""
    if interval_min > 0:
        _cont["interval_min"] = max(30, int(interval_min))
    if syms:
        _cont["syms"] = [s.strip().upper() for s in syms.split(",") if s.strip()]
    from bot.audit import log as _audit
    if on and not _cont["on"]:
        _cont["on"] = True
        _threading.Thread(target=_cont_loop, daemon=True).start()
        _audit("continuous_training", state="started", interval_min=_cont["interval_min"],
               syms=_cont["syms"])
    elif not on:
        _cont["on"] = False
        _cont["current"] = None
        _audit("continuous_training", state="stopped")
    return {k: v for k, v in _cont.items() if k != "history"}


@app.get("/api/training/status")
def training_status():
    return {"running": _train_state["proc"] is not None, "kind": _train_state["kind"],
            "sym": _train_state["sym"], "started": _train_state["started"],
            "rc": _train_state["rc"], "log": _train_state["log"][-25:],
            "continuous": {**{k: v for k, v in _cont.items() if k != "history"},
                           "history": _cont["history"][-10:]}}


@app.post("/api/training/approve_model")
def training_approve_model(name: str, version: str, _=Depends(auth)):
    """MANUAL model promotion (AITP §19): make a gate-passing PENDING model the live champion."""
    from bot.ml.registry import ModelRegistry
    ok = ModelRegistry().promote(name, version)
    return {"promoted": ok, "name": name, "version": version}


# ── STRATEGY APPROVAL WORKFLOW (AITP — paper trading stays blocked until manually approved) ──

def _approval_versions() -> dict:
    """Every approvable strategy LINEAGE: the ORB entry standard + each gauntlet-passed module
    (swing/volbreak/connors… — user 2026-07-05: modules get their OWN ladder from research)."""
    from bot.strategy.orb_candidates import STRATEGY_VERSION
    from bot.strategy.modules import STRATEGY_MODULES
    out = {STRATEGY_VERSION: {"what_it_is": "ORB day-trading entry standard (the core system)",
                              "evidence": "A/B + gauntlet + parity reports on this page"}}
    for m in STRATEGY_MODULES:
        v = m.get("strategy_version")
        if v and v != STRATEGY_VERSION and m.get("status") == "gauntlet_pass":
            out[v] = {"what_it_is": f"{m['id']} — {m.get('notes', '')[:220]}",
                      "evidence": "swing_gauntlet.json / strat_daily run (research reports)"}
    return out


@app.get("/api/approval/versions")
def approval_versions():
    return {"versions": _approval_versions()}


@app.get("/api/approval/status")
def approval_status(version: str = ""):
    """Approval ladder + WHAT IS BEING APPROVED (user 2026-07-05: 'I need to know what was used
    and how') — the strategy version, its rules, and the evidence reports behind each stage.
    version = any lineage from /api/approval/versions (default: the ORB entry standard)."""
    from bot.approval import status
    from bot.strategy.orb_candidates import STRATEGY_VERSION
    from bot.ml.registry import REPORTS_DIR
    versions = _approval_versions()
    ver = version if version in versions else STRATEGY_VERSION
    if ver != STRATEGY_VERSION:                     # module lineage: lighter about-block
        st = status(ver)
        st["about"] = {"strategy_version": ver, **versions[ver],
                       "stage_meaning": {"research": "you reviewed the module's gauntlet evidence",
                                         "replay": "you reviewed its rules vs the research replay",
                                         "paper": "you authorize paper execution for this module",
                                         "live": "real money — also needs LIVE_APPROVED.lock"}}
        st["available_versions"] = list(versions)
        return st
    st = status(STRATEGY_VERSION)
    st["available_versions"] = list(versions)
    about = {
        "strategy_version": STRATEGY_VERSION,
        "what_it_is": "ORB day-trading entry standard: ARMED (context) -> WATCH (close beyond OR "
                      "mid) -> FILL (strong body close beyond OR high/low + continuation + dir-seq), "
                      "pullback retest modes, cooldown 3 (SPY 0), stale 24 (SPY 12), retest 0.5 ATR "
                      "(SPY 0.25), struct stop, 4R cap, EOD flat. Symbols: QQQ SPY NQ MNQ ES (GC "
                      "unverified).",
        "stage_meaning": {
            "research": "you reviewed the data QA + backtest reports and accept the rule version "
                        "as the strategy-of-record",
            "replay": "you reviewed replay parity (contract candidates == engine trades) and the "
                      "A/B + gauntlet evidence",
            "paper": "you authorize AUTOMATIC paper orders on the Alpaca PAPER account "
                     "(grade-sized brackets, equities; futures via TV webhook in paper mode)",
            "live": "final gate for real money — ALSO requires the LIVE_APPROVED.lock file; "
                    "earned only by a green paper scorecard",
        },
    }
    # headline evidence pulled from the saved reports so the decision is informed, not blind
    try:
        m = json.loads((REPORTS_DIR / "backtest_matrix.json").read_text(encoding="utf-8"))["symbols"]
        about["backtest_overall"] = {s: v.get("overall") for s, v in m.items() if "overall" in v}
        about["cost_stress_warning"] = [s for s, v in m.items()
                                        if (v.get("cost_stress", {}).get("slip_x2", {}).get("avg_r") or 0) <= 0]
    except Exception:
        pass
    try:
        p = json.loads((REPORTS_DIR / "replay_parity.json").read_text(encoding="utf-8"))["symbols"]
        about["replay_parity"] = {s: v.get("match_pct") for s, v in p.items() if "match_pct" in v}
    except Exception:
        pass
    try:
        g = json.loads((REPORTS_DIR / "gauntlet.json").read_text(encoding="utf-8"))["runs"]
        about["gauntlet_runs"] = {k: v.get("verdict") for k, v in g.items()}
    except Exception:
        pass
    st["about"] = about
    return st


@app.post("/api/approval/approve")
def approval_approve(stage: str, notes: str = "", approved_by: str = "user", version: str = "",
                     _=Depends(auth)):
    from bot.approval import approve, status
    from bot.strategy.orb_candidates import STRATEGY_VERSION
    versions = _approval_versions()
    ver = version if version in versions else STRATEGY_VERSION   # whitelist — no junk keys
    try:
        approve(ver, stage, approved_by=approved_by, notes=notes)
    except ValueError as e:
        return {"error": str(e), **status(ver)}
    return status(ver)


@app.post("/api/approval/revoke")
def approval_revoke(stage: str, version: str = "", _=Depends(auth)):
    from bot.approval import revoke, status
    from bot.strategy.orb_candidates import STRATEGY_VERSION
    versions = _approval_versions()
    ver = version if version in versions else STRATEGY_VERSION
    revoke(ver, stage)
    return status(ver)


@app.get("/api/training/report_matrix")
def training_report_matrix():
    """Backtest report matrix + cost stress (research/backtest_report.py; run kind=report)."""
    from bot.ml.registry import REPORTS_DIR
    p = REPORTS_DIR / "backtest_matrix.json"
    if not p.exists():
        return {"error": "no report matrix yet — run kind=report"}
    return json.loads(p.read_text(encoding="utf-8"))


@app.get("/api/training/parity")
def training_parity():
    """Replay-parity report (research/replay_parity.py; run kind=parity)."""
    from bot.ml.registry import REPORTS_DIR
    p = REPORTS_DIR / "replay_parity.json"
    if not p.exists():
        return {"error": "no parity report yet — run kind=parity"}
    return json.loads(p.read_text(encoding="utf-8"))


@app.get("/api/training/sweep")
def training_sweep():
    """The saved entry-parameter sweep (research/sweep_entry_params.py; run kind=sweep)."""
    from bot.ml.registry import REPORTS_DIR
    p = REPORTS_DIR / "sweep_entry_params.json"
    if not p.exists():
        return {"error": "no sweep report yet — run kind=sweep"}
    return json.loads(p.read_text(encoding="utf-8"))


@app.get("/api/training/threshold")
def training_threshold():
    """Threshold-usage study (research/threshold_study.py; run kind=threshold)."""
    from bot.ml.registry import REPORTS_DIR
    p = REPORTS_DIR / "threshold_study.json"
    if not p.exists():
        return {"error": "no threshold study yet — run kind=threshold"}
    return json.loads(p.read_text(encoding="utf-8"))


@app.get("/api/training/gauntlet")
def training_gauntlet():
    """Saved gauntlet runs (research/gauntlet.py; run kind=gauntlet with candidate params)."""
    from bot.ml.registry import REPORTS_DIR
    p = REPORTS_DIR / "gauntlet.json"
    if not p.exists():
        return {"error": "no gauntlet runs yet — pick a sweep candidate and run the gauntlet"}
    return json.loads(p.read_text(encoding="utf-8"))


@app.post("/api/approval/approve_paper_all")
def approval_approve_paper_all(notes: str = "", approved_by: str = "user", version: str = "",
                               _=Depends(auth)):
    """ONE-CLICK strategy approval (user request 2026-07-04, extended 2026-07-06): walk the
    whole ladder — research -> replay -> paper — for the given lineage AND arm the learning
    loop: continuous training starts (challengers retrain on every data change, --no-promote)
    and the approved module joins the STRATEGY DUEL (daily shadow head-to-head)."""
    from bot.approval import approve, status
    from bot.strategy.orb_candidates import STRATEGY_VERSION
    versions = _approval_versions()
    ver = version if version in versions else STRATEGY_VERSION
    st = status(ver)
    for stage in ("research", "replay", "paper"):
        if not st["stages"].get(stage):
            approve(ver, stage, approved_by=approved_by,
                    notes=notes or "one-click approval from Training Lab")
            st = status(ver)
    # LEARNING LOOP (user 2026-07-06: "continuous train and learning from the approval, one
    # click"): arm the continuous-training worker if it isn't running yet
    started_training = False
    if not _cont["on"]:
        _cont["on"] = True
        _threading.Thread(target=_cont_loop, daemon=True).start()
        started_training = True
        from bot.audit import log as _audit
        _audit("continuous_training", state="started", via="one_click_approval",
               interval_min=_cont["interval_min"], syms=_cont["syms"])
    st["continuous_training"] = "started" if started_training else "already running"
    st["duel"] = "this lineage now shadow-trades daily in the strategy duel (/api/duel)"
    return st


@app.get("/api/duel")
def duel_leaderboard():
    """STRATEGY DUEL leaderboard — approved lineages' daily shadow results head-to-head
    (bot/strategy/duel.py; a module joins after its lineage's research approval)."""
    from bot.strategy.duel import leaderboard, run_duel_once
    try:
        run_duel_once()                      # idempotent catch-up (no-op if today already ran)
    except Exception:
        pass
    return leaderboard()


@app.get("/api/training/dataqa")
def training_dataqa():
    """The saved historical data-QA report (pipeline/hs_data_qa.py; run kind=dataqa to refresh)."""
    from bot.ml.registry import REPORTS_DIR
    p = REPORTS_DIR / "dataqa.json"
    if not p.exists():
        return {"error": "no data-QA report yet — run kind=dataqa"}
    return json.loads(p.read_text(encoding="utf-8"))


# ── L2/L3 EXTERNAL DATA (register a path on ANY disk — read in place, only features persist) ──

@app.get("/api/data/sources")
def data_sources():
    from bot.ml.l2_features import sources
    return {"sources": sources()}


@app.post("/api/data/register")
def data_register(path: str, symbol: str = "NQ", _=Depends(auth)):
    """Register an on-disk L2/L3 file (external drive fine — nothing is copied). Then run
    kind=l2sync with sym=<source id> to synthesize its features."""
    from bot.ml.l2_features import register
    return register(path, symbol)


_l2sync = {"on": False, "current": None, "done": 0, "total": 0, "errors": [], "training": None}


def _post_sync_train(symbols: list[str]):
    """AUTO-PIPELINE after a sync (user 2026-07-05: 'after synchronise, does the dataset and
    test run automatically?' — now YES): rebuild the dataset then retrain ml+nn for every symbol
    whose depth features changed. --no-promote as always; progress rides /api/data/sync_status."""
    for sym in symbols:
        for kind in ("dataset", "ml", "nn"):
            while _train_state["proc"] is not None:   # never fight a manual run
                _time.sleep(15)
            _l2sync["training"] = f"{kind} {sym}"
            try:
                _cont_run(kind, sym)
            except Exception as e:
                _l2sync["errors"].append(f"train {kind} {sym}: {str(e)[:120]}")
    _l2sync["training"] = "done — check Pending models / reports"


def _sync_all_worker():
    from bot.ml.l2_features import sources, synthesize
    todo = [s for s in sources() if s.get("status") == "registered"]
    _l2sync.update(on=True, done=0, total=len(todo), errors=[], training=None)
    for s in todo:
        _l2sync["current"] = f"{s['symbol']} {s['path'].split(chr(92))[-1]} ({s['size_mb']} MB)"
        try:
            r = synthesize(s["id"])
            if "error" in r:
                _l2sync["errors"].append(f"{s['id']}: {r['error']}")
        except Exception as e:
            _l2sync["errors"].append(f"{s['id']}: {str(e)[:120]}")
        _l2sync["done"] += 1
    _l2sync.update(on=False, current=None)
    synced_syms = sorted({s["symbol"] for s in todo})
    if synced_syms and _l2sync["done"] > len(_l2sync["errors"]):
        _post_sync_train(synced_syms)             # datasets + ml + nn fire automatically


@app.post("/api/data/retrain_synced")
def data_retrain_synced(syms: str = "", _=Depends(auth)):
    """Manual trigger for the post-sync pipeline (the automatic run also uses this path).
    syms = comma list; empty = every symbol that has synthesized depth features."""
    from bot.ml.l2_features import sources
    symbols = ([x.strip().upper() for x in syms.split(",") if x.strip()] or
               sorted({s["symbol"] for s in sources() if s.get("status") == "synthesized"}))
    if not symbols:
        return {"error": "no synthesized sources — sync first"}
    _threading.Thread(target=_post_sync_train, args=(symbols,), daemon=True).start()
    return {"started": True, "symbols": symbols, "steps": ["dataset", "ml", "nn"]}


@app.post("/api/data/sync_all")
def data_sync_all(_=Depends(auth)):
    """Synthesize EVERY registered-but-unsynced L2/L3 source sequentially in the background
    (user 2026-07-05: ~10 MBO files per folder — one click instead of ten)."""
    if _l2sync["on"]:
        return {"error": "sync-all already running", **{k: _l2sync[k] for k in ("done", "total", "current")}}
    _threading.Thread(target=_sync_all_worker, daemon=True).start()
    from bot.audit import log as _audit
    _audit("l2_sync_all_started")
    return {"started": True}


@app.get("/api/data/sync_status")
def data_sync_status():
    return _l2sync


@app.post("/api/data/synthesize_upload")
async def data_synthesize_upload(request: Request, symbol: str = "NQ", _=Depends(auth)):
    """Drag-and-drop path: the dragged file streams here, features are synthesized IN MEMORY and
    only the per-minute l2_* parquet persists — the raw upload is never written to disk.
    Accepts csv or parquet bodies (browser drop zone posts the raw file)."""
    import io
    import pandas as pd
    from bot.ml.l2_features import synthesize_frame
    body = await request.body()
    if len(body) > 800_000_000:
        return {"error": "file > 800MB — register its PATH instead (reads in place, no copy)"}
    name = (request.headers.get("x-filename") or "upload.csv").lower()
    try:
        if name.endswith(".parquet"):
            df = pd.read_parquet(io.BytesIO(body))
        else:
            df = pd.read_csv(io.BytesIO(body))
    except Exception as e:
        return {"error": f"could not parse upload: {str(e)[:120]}"}
    res = synthesize_frame(df, symbol)
    if "error" not in res:
        from bot.audit import log as _audit
        _audit("l2_upload_synthesized", symbol=symbol.upper(), rows=res.get("feature_rows"),
               filename=name)
    return res


@app.get("/api/training/reports")
def training_reports():
    from bot.ml.registry import list_reports
    return {"reports": list_reports()[:40]}


@app.get("/api/training/report")
def training_report(name: str):
    from bot.ml.registry import load_report
    r = load_report(name)
    return r if r is not None else {"error": "not found"}


@app.get("/api/training/registry")
def training_registry():
    """Model registry — every artifact with metrics, feature schema size, rule version, champion flag."""
    from bot.ml.registry import ModelRegistry
    out = []
    for m in ModelRegistry().list():
        out.append({"name": m.name, "version": m.version, "champion": m.champion,
                    "created_at": m.created_at, "metrics": m.metrics,
                    "n_features": len(m.features) if m.features else None,
                    "strategy_version": m.strategy_version})
    return {"models": sorted(out, key=lambda x: x["created_at"], reverse=True)}


@app.get("/api/training/dataset")
def training_dataset(sym: str = "QQQ"):
    """Headline stats of the CACHED labeled dataset (build via kind=dataset if missing)."""
    from bot.ml.registry import FeatureStore
    from bot.ml.features_pit import FEATURE_COLUMNS
    from bot.ml.dataset import DATASET_NAME, _version_slug
    import pandas as pd
    try:
        df = FeatureStore().load(f"{DATASET_NAME}_{sym.upper()}", _version_slug())
    except FileNotFoundError:
        return {"sym": sym.upper(), "error": "no cached dataset — run kind=dataset first"}
    yr = pd.to_datetime(df["ts"]).dt.year
    nan_share = df[FEATURE_COLUMNS].isna().mean().sort_values(ascending=False)
    return {"sym": sym.upper(), "rows": int(len(df)),
            "strategy_version": str(df["strategy_version"].iloc[0]) if len(df) else None,
            "span": [str(df['ts'].iloc[0])[:10], str(df['ts'].iloc[-1])[:10]] if len(df) else None,
            "win_rate": round(float(df["y_win"].mean()), 3),
            "tp2_rate": round(float(df["y_tp2"].mean()), 3),
            "stop_rate": round(float(df["y_stop"].mean()), 3),
            "avg_net_r": round(float(df["net_r"].mean()), 3),
            "by_year": {int(k): int(v) for k, v in yr.value_counts().sort_index().items()},
            "worst_nan": {k: round(float(v), 3) for k, v in nan_share.head(6).items() if v > 0},
            "n_features": len(FEATURE_COLUMNS)}


@app.get("/api/training/ab")
def training_ab():
    """The saved entry-standard A/B (research/ab_entry_standard.py) — variants x symbols."""
    from bot.ml.registry import REPORTS_DIR
    p = REPORTS_DIR / "ab_entry_standard.json"
    if not p.exists():
        return {"error": "no A/B report yet — run kind=ab"}
    return json.loads(p.read_text(encoding="utf-8"))


_NO_CACHE = {"Cache-Control": "no-store, must-revalidate", "Pragma": "no-cache"}
# ^ the pages are read fresh from disk per request, but BROWSERS were caching them — a fixed bug
#   kept "still showing" until a hard refresh (user screenshot 2026-07-05). Never cache the UI.


@app.get("/training", response_class=HTMLResponse)
def training_page():
    f = STATIC / "training.html"
    body = f.read_text(encoding="utf-8") if f.exists() else "<h1>training.html missing</h1>"
    return HTMLResponse(body, headers=_NO_CACHE)


@app.get("/", response_class=HTMLResponse)
def dashboard():
    f = STATIC / "dashboard.html"
    body = f.read_text(encoding="utf-8") if f.exists() else "<h1>HIGHSTRIKE BOT</h1><p>dashboard.html missing</p>"
    return HTMLResponse(body, headers=_NO_CACHE)


if (STATIC).exists():
    app.mount("/static", StaticFiles(directory=str(STATIC)), name="static")
