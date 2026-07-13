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
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from pydantic import BaseModel

from bot.config import settings
from bot.journal import Journal
from bot.contracts import TradeCandidate, OrderRequest, OrderType, Mode
from bot.risk import decide, Account
from bot import performance as perf


def _json_safe(o):
    """Recursively replace NaN/±inf floats with None (bug hunt W6): FastAPI serializes with
    allow_nan=False, so ONE NaN in a payload (a degenerate ratio, a missing live-data float)
    500s the whole endpoint. A null is a clean, parseable stand-in the console can render."""
    if isinstance(o, float):
        return None if (o != o or o == float("inf") or o == float("-inf")) else o
    if isinstance(o, dict):
        return {k: _json_safe(v) for k, v in o.items()}
    if isinstance(o, (list, tuple)):
        return [_json_safe(v) for v in o]
    return o


class SafeJSONResponse(JSONResponse):
    """App-wide NaN/inf-safe JSON: no endpoint can crash (or emit invalid JSON) on a stray NaN."""
    def render(self, content) -> bytes:
        return super().render(_json_safe(content))


app = FastAPI(title="HIGHSTRIKE BOT", version="0.1.0", default_response_class=SafeJSONResponse)
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
        from bot.config import write_json                      # ATOMIC (tmp+replace, Phase 7):
        write_json(_RUNTIME_STATE, {                           # a power cut can't half-write the
            "kill_switch": _state.get("kill_switch", False),   # safety state
            "paper_autotrade": _state.get("paper_autotrade", False),
            "paper_placed": sorted(_paper["placed"])[-500:],
            "last_scan_at": _latest.get("ts"),   # phase-7 health-heartbeat check reads this
            "saved_at": _now()})
    except Exception:
        pass


def _restore_runtime():
    """FAIL-CLOSED (remediation Phase 7, 2026-07-11): a missing file is a clean first boot; a
    file that EXISTS but cannot be parsed is corrupt safety state — boot with the kill switch ON
    and page the operator. The audited defect silently restored kill_switch=false."""
    if not _RUNTIME_STATE.exists():
        return
    try:
        st = json.loads(_RUNTIME_STATE.read_text(encoding="utf-8"))
    except Exception as e:
        _state["kill_switch"] = True
        try:
            from bot.alerts import alert
            alert(f"runtime_state.json CORRUPT ({str(e)[:80]}) — booting with the KILL SWITCH ON; "
                  f"inspect and disarm manually", level="critical", source="boot")
        except Exception:
            pass
        return
    _state["kill_switch"] = bool(st.get("kill_switch", False))
    _state["paper_autotrade"] = bool(st.get("paper_autotrade", False))
    _paper["placed"].update(st.get("paper_placed") or [])


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
# DECOUPLED RELOAD (user 2026-07-08): the scan/training run in a persistent WORKER; the API can
# reload freely (uvicorn --reload) WITHOUT restarting them. Shared state = the journal DB (already
# file-backed) + this transient scan snapshot, which the worker writes and the reloadable API reads.
_LATEST_SNAP = Path(__file__).resolve().parents[2] / "data" / "latest_scan.json"
_SNAP_KEYS = ("signals", "ts", "market", "scanning", "error")


def _snapshot_latest():
    try:
        tmp = _LATEST_SNAP.with_suffix(".tmp")
        tmp.write_text(json.dumps({k: _latest.get(k) for k in _SNAP_KEYS}, default=str),
                       encoding="utf-8")
        tmp.replace(_LATEST_SNAP)
    except Exception:
        pass


def _latest_reader():
    """API-only mode (BOT_AUTOSCAN=0): poll the worker's scan snapshot into _latest so the endpoints
    serve live signals without running the scan loop in this (reloadable) process."""
    import time as _t
    while True:
        try:
            if _LATEST_SNAP.exists():
                d = json.loads(_LATEST_SNAP.read_text(encoding="utf-8"))
                for k in _SNAP_KEYS:
                    if k in d:
                        _latest[k] = d[k]
        except Exception:
            pass
        _t.sleep(5)


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


def _sync_controls():
    """CROSS-PROCESS CONTROLS (2026-07-11, forward-gate boot finding): the API and the WORKER
    are different processes — a toggle POSTed to the API must reach the worker's scan loop, and
    the worker's own persist beat must never overwrite it back. exec_flags (SQLite WAL) is the
    single writer-safe channel: control POSTs write ctl_*, every process syncs from them."""
    try:
        svc = _exec_service()
        for k, key in (("kill_switch", "ctl_kill_switch"),
                       ("paper_autotrade", "ctl_paper_autotrade")):
            v = svc._flag(key)
            if v is not None:
                _state[k] = (v == "1")
    except Exception:
        pass


def _set_control(name: str, on: bool) -> None:
    try:
        _exec_service()._set_flag(f"ctl_{name}", "1" if on else "0")
    except Exception:
        pass


def _exec_service():
    """THE one execution path (remediation Phase 5): every order source — autotrade, manual,
    webhook — submits through this service (risk on real account state → persistent OMS →
    broker → fills → reconciliation). There is no other door to a broker."""
    if "exec" not in _broker_cache:
        from bot.execution.service import ExecutionService
        _broker_cache["exec"] = ExecutionService(_paper_broker())
    return _broker_cache["exec"]


def _paper_autotrade():
    """When the toggle is ON: for EVERY NEW breakout signal (grade B → A → A+), submit a
    grade-sized bracket through the EXECUTION SERVICE (remediation Phase 5) — risk on real
    account state → persistent OMS → broker → fills → reconciliation. This function only picks
    WHICH signals to trade (strategy-level selection); everything execution-shaped (approval,
    idempotency, account truth, sizing authority, dedup, journaling) lives in the service.
    Equities only (Alpaca can't trade futures). PAPER only — for study/data collection."""
    if not _state.get("paper_autotrade") or not settings.alpaca_paper:
        return
    from bot.contracts import TradeCandidate
    from bot.live import GRADE_MULT
    from bot.strategy.orb_candidates import STRATEGY_VERSION
    try:
        svc = _exec_service()
        mkt_open = _paper_broker().is_market_open()
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
        if str(s.get("boss", "")).startswith("stand_down"):       # BOSS one-macro-bet rule (review fix
            continue                                              # 2026-07-07): correlated same-direction
                                                                  # fires — only the bucket LEAD places
        if s.get("signal_state") == "invalid":    # ZONE GATE: structure already broke against the signal
            continue
        try:
            _cid = {}                              # P1.1 linkage: keep the SIGNAL's id so a fill
            sid = s.get("candidate_id") or s.get("id")   # can upgrade its tracker row's state
            if sid:
                _cid["candidate_id"] = str(sid)
            c = TradeCandidate(symbol=s["symbol"], side=s["side"], timeframe=s.get("tf", "5m"),
                               setup=str(s.get("family", "orb")), entry=float(s["entry"]),
                               stop=float(s["stop"]), tp2=float(s["tp2"]),
                               strategy_version=STRATEGY_VERSION, **_cid)
        except (KeyError, TypeError, ValueError) as e:            # broken geometry never leaves here
            _paper["log"].append({"ts": _now(), "symbol": s.get("symbol"), "error": f"bad geometry: {e}"})
            continue
        try:
            res = svc.submit(c, "autotrade", session=str(s.get("session") or ""),
                             feed_healthy=s.get("source_healthy"),   # not-proven -> service refuses
                             kill_switch=_state.get("kill_switch", False),
                             qty_mult=GRADE_MULT.get(grade, 0.4), grade=str(grade))
            if res.action == "rejected" and "no paper approval" in res.reason:
                _state["paper_autotrade"] = False                 # revoke disarms on the next cycle
                _paper["log"].append({"ts": _now(), "error": res.reason + " — autotrade disarmed"})
                return
            if res.action != "duplicate":                         # duplicates are steady-state noise
                _paper["log"].append({"ts": _now(), "symbol": s["symbol"], "side": s["side"],
                                      "grade": grade, "entry": s["entry"], "stop": s["stop"],
                                      "tp2": s["tp2"], "action": res.action, "qty": res.qty,
                                      "corr": res.correlation_id, "reason": res.reason[:160],
                                      "order": res.broker_order_id or ""})
            _paper["log"] = _paper["log"][-200:]
        except Exception as e:
            _paper["log"].append({"ts": _now(), "symbol": s.get("symbol"), "error": str(e)[:120]})


def _worker_shadow_study():
    """BOSS WORKERS paper study (user 2026-07-07: approve workers -> they paper trade). Each
    PAPER-APPROVED worker records its OWN tight-target what-if trades (tagged family=worker id),
    resolved by track_outcomes and scored per worker (Boss conformance / phase78). Real Alpaca
    brackets stay on the core system — one paper account nets a single position per symbol, so
    five workers on two symbols can only run as parallel shadow studies, which is exactly what
    judges them for promotion. No broker call here; nothing is placed."""
    try:
        from bot.boss import shadow_decisions
        from bot.tracker import record_decision
        for dec in shadow_decisions(_latest.get("signals") or []):
            try:
                record_decision(dec, taken=True, auto=True)
            except Exception:
                pass
    except Exception:
        pass


def _capture_15m_journal():
    """15m LIVE PASS (user 2026-07-07: pursue the 15m lineage + 5m, feed live data into the
    training lab). A second scan at 15m for the two live-entitled equities; its acceptable signals
    are journaled tagged tf=15m so build_live_labels/attach_live_journal grow the 15m lineage's
    training corpus. No orders — journal only. Approval-independent (learning, not trading)."""
    try:
        from bot.live import scan_watchlist
        sigs = scan_watchlist(["QQQ", "SPY"], bars_back=12, persist=False,
                              with_options=False, tf="15m")
        _autotrack_acceptable(sigs)
    except Exception as e:
        _latest["journal15m_err"] = str(e)[:120]


def _trail_shadow_study():
    """TRAIL-EQ paper shadow (user 2026-07-07: the graduated trail must paper-trade like the
    workers). When trail-eq-0.1 carries a paper approval, every acceptable QQQ/SPY core 5m
    signal ALSO journals a trail twin: same canonical entry/stop, NO fixed TP — exit_mode=trail
    resolves via the chandelier walk (tracker._walk_trail). family='trail-eq' keeps it SEALED
    out of core analytics/datasets; it is judged on its own stream like every lineage."""
    try:
        from bot.approval import paper_approved
        if not paper_approved("trail-eq-0.1"):
            return
        from bot.tracker import record_decision
        for s in (_latest.get("signals") or []):
            if s.get("symbol") not in ("QQQ", "SPY") or not s.get("tradeable"):
                continue
            if s.get("grade") not in ("A+", "A", "B") or s.get("signal_state") == "invalid":
                continue
            if (s.get("bars_ago") or 0) < 1 or (s.get("timeframe") or "5m") != "5m":
                continue
            c = s.get("candidate") or {}
            if not c.get("generated_at"):
                continue
            key = f"trail-eq:{s.get('session')}:{s['side']}:{c.get('generated_at')}"
            try:
                record_decision({"candidate_id": key, "symbol": s["symbol"], "side": s["side"],
                                 "family": "trail-eq", "session": s.get("session"),
                                 "entry": s["entry"], "stop": s["stop"], "tp1": None, "tp2": None,
                                 "grade": s.get("grade"), "generated_at": c.get("generated_at"),
                                 "tf": "5m", "exit_mode": "trail", "trail_atr": 2.0,
                                 "pit_features": s.get("pit_features")}, taken=True, auto=True)
            except Exception:
                pass
    except Exception:
        pass


def _on_repo_data():
    from bot.config import BOT_ROOT
    return BOT_ROOT.parent / "data"


def _on_day_book(date: str):
    """Full-session 0DTE book {(cp,strike,hm):(bid,ask,mid)} + strike arrays from the compact OPRA
    parquet for `date`, or (None, None). Real chain only — forward dates absent from the parquet
    return None (the study is then inert; a BS proxy is validated-insufficient, F86)."""
    import numpy as np
    import duckdb
    parq = _on_repo_data() / "opra_qqq_cbbo.parquet"
    if not parq.exists():
        return None, None
    con = duckdb.connect()
    try:
        con.execute("SET memory_limit='512MB'; SET threads=1")
        df = con.execute(
            "SELECT cp, strike, "
            "(extract('hour' FROM minute) * 60 + extract('minute' FROM minute)) AS hm, "
            f"bid, ask, mid FROM read_parquet('{parq.as_posix()}') "
            f"WHERE session = DATE '{date}' AND dte = 0").df()
    finally:
        con.close()
    if df.empty:
        return None, None
    book = {(t.cp, float(t.strike), int(t.hm)): (float(t.bid), float(t.ask), float(t.mid))
            for t in df.itertuples()}
    strikes = {cp: np.array(sorted(df[df["cp"] == cp]["strike"].unique())) for cp in ("C", "P")}
    return book, strikes


def _on_qqq_ref(date: str):
    """{open, spot:{600,780}, close} for QQQ on `date` from the 1m bar store, or None."""
    import pandas as pd
    parq = _on_repo_data() / "qqq_continuous_1m.parquet"
    if not parq.exists():
        return None
    df = pd.read_parquet(parq, columns=["ts_et", "open", "close", "session"])
    et = pd.to_datetime(df["ts_et"]).dt.tz_convert("America/New_York")
    day = df[(et.dt.date.astype(str) == date) & (df["session"] == "RTH")].copy()
    if day.empty:
        return None
    hm = (pd.to_datetime(day["ts_et"]).dt.tz_convert("America/New_York").dt.hour * 60
          + pd.to_datetime(day["ts_et"]).dt.tz_convert("America/New_York").dt.minute)
    day = day.assign(hm=hm.values)
    op, cl = day[day["hm"] == 570], day[day["hm"].between(950, 959)]

    def spot_at(h):
        r = day[day["hm"] == h]
        return float(r["close"].iloc[0]) if len(r) else None
    return {"open": float(op["open"].iloc[0]) if len(op) else None,
            "spot": {600: spot_at(600), 780: spot_at(780)},
            "close": float(cl["close"].iloc[-1]) if len(cl) else None}


def _options_native_study():
    """OPTIONS-NATIVE (F86) paper study: when options-native-0.1 is approved, journal the 0DTE VRP
    condor / directional-spread signals to its SEALED store from the REAL OPRA chain, resolved at
    settle. Backfills every chain-covered session (idempotent, a few per tick) and extends forward
    as the chain grows. Inert without a real chain — a BS proxy is validated-insufficient (F86), so
    nothing misleading is ever written."""
    try:
        from bot.approval import paper_approved
        from bot.options import native
        if not paper_approved(native.LINEAGE):
            return
        import duckdb
        parq = _on_repo_data() / "opra_qqq_cbbo.parquet"
        if not parq.exists():
            return
        con = duckdb.connect()
        try:
            con.execute("SET memory_limit='512MB'; SET threads=1")
            dates = [str(d[0]) for d in con.execute(
                f"SELECT DISTINCT session FROM read_parquet('{parq.as_posix()}') ORDER BY 1").fetchall()]
        finally:
            con.close()
        done = {(r["date"], r["slot"]) for r in native.load_journal()}
        pending = [d for d in dates if (d, "am") not in done or (d, "pm") not in done]
        for date in pending[:3]:                     # a few sessions per tick; fully idempotent
            ref = _on_qqq_ref(date)
            book, strikes = _on_day_book(date)
            if ref and book:
                native.record_session(date, book, strikes, ref)
    except Exception:
        pass


def _options_native_live():
    """LIVE PER-TICK MANAGEMENT (user 2026-07-08): enter the managed credit spread at the windows,
    MARK every open position on the live Alpaca chain each scan tick, and take profit (+tp*credit) /
    stop / settle. This is what turns hold-to-settle (loses) into managed (F88). Runs in the
    persistent worker so it survives API reloads. Gated on paper_approved; real Alpaca chain only —
    nothing is journalled off a BS estimate."""
    try:
        from bot.approval import paper_approved
        from bot.options import native
        if not paper_approved(native.LINEAGE):
            return
        import pandas as pd
        from bot.market_data.options_data import alpaca_chain_0dte
        from bot.market_data.providers import latest_price   # was NameError -> loop never entered/managed (fix 2026-07-09)
        now = pd.Timestamp.now(tz="America/New_York")
        if now.dayofweek >= 5:
            return
        hm = now.hour * 60 + now.minute
        date = now.strftime("%Y-%m-%d")
        spot = (latest_price("QQQ") or {}).get("price")
        # 1) ENTRY at 10:00 / 13:00 ET — the managed 0DTE credit spread + ONE 7DTE condor (F89).
        # BROKER 0DTE OPEN CUTOFF (user-verified 2026-07-10): Webull blocks NEW same-day-expiry
        # opens after 15:00 ET; Robinhood after 15:30 AND auto-closes at-risk expiring positions
        # FROM 15:30 (hold-to-settle rows get force-closed early there). Current slots comply;
        # this hard gate keeps any FUTURE slot from silently violating manual-broker reality.
        zdte_cut = int(os.environ.get("ZERO_DTE_OPEN_CUTOFF_HM", "900"))     # 900 = 15:00 ET (Webull, strictest)
        if spot:
            for slot, ehm in (("am", 600), ("pm", 780)):
                if ehm <= hm <= ehm + 3 and hm <= zdte_cut:
                    sig = native.live_signal_from_alpaca("QQQ", spot=float(spot),
                                                         structure="credit_spread")
                    if not sig.get("error") and sig.get("priced_from") == "alpaca_live":
                        native.open_position(sig, date, slot, "credit_spread")
            if 600 <= hm <= 603:                      # O11: enter one 7DTE condor/session (backtest cadence)
                s7 = native.live_signal_from_alpaca("QQQ", spot=float(spot),
                                                    structure="condor_7dte", dte=7)
                if not s7.get("error") and s7.get("priced_from") == "alpaca_live":
                    native.open_position(s7, date, "7d", "condor_7dte")
        # 2) MANAGE every open position on the chain that MATCHES ITS EXPIRY (O11): a 7DTE condor
        # must be marked on the 7-day chain, not the 0DTE one; settle only at the stored expiry (O7).
        opens = native.load_open()
        if opens:
            import datetime as _dt
            from bot.market_data.options_data import alpaca_chain_dte
            et_today = _dt.date.fromisoformat(date)
            books = {}                                # expiry -> book (only if the chain's expiry matches)
            for r in opens:
                exp = r.get("expiry") or date
                if exp in books:
                    continue
                rem = (_dt.date.fromisoformat(exp) - et_today).days
                ch = (alpaca_chain_0dte("QQQ", spot=float(spot) if spot else None) if rem <= 0
                      else alpaca_chain_dte("QQQ", target_dte=rem, spot=float(spot) if spot else None))
                books[exp] = ch.get("book") if (ch.get("ok") and ch.get("expiry") == exp) else None

            def mark_cost(r):                         # cost to close: buy back shorts, sell wings
                book = books.get(r.get("expiry") or date)
                if not book:
                    return None
                cost = 0.0
                for ks, kl, cp in ((r.get("ksc"), r.get("klc"), "C"), (r.get("ksp"), r.get("klp"), "P")):
                    if ks is None:
                        continue
                    qs, ql = book.get((cp, float(ks))), book.get((cp, float(kl)))
                    if qs is None or ql is None:
                        return None
                    cost += qs[1] - ql[0]
                return cost

            def settle_close(d):                      # underlying close (available after 15:55)
                ref = _on_qqq_ref(d)
                return ref.get("close") if ref else None
            native.manage_open(mark_cost, settle_close, now_hm=hm)
    except Exception:
        pass


def _autotrack_acceptable(signals=None):
    """Shadow-track every ACCEPTABLE live signal (tradeable + grade A+/A/B) as a what-if decision, so the
    Recent-Candidates / Performance / Live-vs-Backtest panels update from the engine's own signal flow —
    no manual Take needed and no order placed. Dedup'd by a stable per-bar key; never clobbers a manual
    decision. track_outcomes() then walks bars to resolve stop/TP1/TP2 first-touch. `signals` defaults
    to the latest 5m scan; the 15m pass passes its own list (tf tag differentiates the journal rows)."""
    from bot.tracker import record_decision
    for s in (signals if signals is not None else (_latest.get("signals") or [])):
        if not s.get("tradeable") or s.get("grade") not in ("A+", "A", "B"):
            continue
        if s.get("signal_state") == "invalid":      # ZONE GATE: don't shadow-track a structurally dead signal
            continue
        if (s.get("bars_ago") or 0) < 1:            # BUGFIX: only CONFIRMED bars — never the forming bar whose
            continue                                # close (=entry) drifts each scan and repaints the signal
        c = s.get("candidate") or {}
        _tf = s.get("timeframe") or "5m"
        # dedup by BAR (generated_at) + TF, NOT the entry price — one tracked signal per bar/side/session/tf
        key = f"{s['symbol']}:{s.get('family')}:{s.get('session')}:{s['side']}:{_tf}:{c.get('generated_at') or ''}"
        try:
            record_decision({"candidate_id": key, "symbol": s["symbol"], "side": s["side"],
                             "family": s.get("family"), "session": s.get("session"), "entry": s["entry"],
                             "stop": s["stop"], "tp1": s.get("tp1"), "tp2": s.get("tp2"),
                             "grade": s.get("grade"), "generated_at": c.get("generated_at"),
                             "tf": s.get("timeframe") or "5m",   # journal->training-lab tf tag (5m default; 15m pass tags 15m)
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


_beats: dict = {}    # SUBSYSTEM HEARTBEATS (D5 lesson: the resolver was dead 19h, silently)


def _beat(name, fn):
    """SILENT-FAILURE KILLER: run one scan-loop step ISOLATED — one failing step no longer skips
    every step after it — and record the outcome so /api/health + the dashboard surface a dead
    subsystem within one cycle instead of never."""
    try:
        fn()
        _beats[name] = {"ok": True, "ts": _now(), "error": None}
    except Exception as e:
        _beats[name] = {"ok": False, "ts": _now(), "error": f"{type(e).__name__}: {str(e)[:120]}"}


def _beat_val(name, fn):
    """_beat for steps whose RESULT is kept (market context, duel tick, phase78...): returns the
    value on success, an {'error': ...} stub on failure — and always records the heartbeat."""
    try:
        v = fn()
        _beats[name] = {"ok": True, "ts": _now(), "error": None}
        return v
    except Exception as e:
        _beats[name] = {"ok": False, "ts": _now(), "error": f"{type(e).__name__}: {str(e)[:120]}"}
        return {"error": str(e)[:120]}


def _scan_loop():
    from bot.live import scan_watchlist
    from bot.tracker import track_outcomes
    from bot.market_intel import market_context
    period = int(os.environ.get("BOT_SCAN_SEC", "60"))
    while True:
        _sync_controls()                       # API-set toggles reach THIS process every cycle
        if not _state["kill_switch"]:
            _latest["scanning"] = True
            try:
                # bars_back=12 (1 hour): the autotracker dedups per bar, so a wider window costs
                # nothing but makes signal capture survive server restarts — with 4 (20 min) the
                # NQ B-long on 2026-07-06 fired during a reload storm and was never recorded
                _sigs = scan_watchlist(_WATCH, bars_back=12, persist=False)
                try:                             # BOSS correlation buckets (BOSS_WORKERS_PLAN §4):
                    from bot.boss import allocate  # same-direction fires on correlated symbols
                    allocate(_sigs)                # are ONE macro bet — annotates lead/stand_down
                except Exception:
                    pass
                _latest["signals"] = _sigs       # publish AFTER allocate's in-place sort (review
                _latest["ts"] = _now(); _latest["error"] = None   # fix: no mid-sort reads)
                # EVERY step below runs ISOLATED with a heartbeat (D5 lesson): before, one raise
                # here skipped every later step — track_outcomes died silently for 19 hours.
                _beat("snapshot", _snapshot_latest)        # share signals with the reloadable API process
                _beat("autotrack", _autotrack_acceptable)  # shadow-track ACCEPTABLE 5m signals -> journal
                if _mkt_tick["n"] % 3 == 0:                # 15m LINEAGE live journal (every ~3 min)
                    _beat("journal_15m", _capture_15m_journal)
                _beat("workers", _worker_shadow_study)     # BOSS WORKERS: tight-target what-if study
                _beat("trail", _trail_shadow_study)        # TRAIL-EQ (F84): chandelier-exit twin
                _beat("options_study", _options_native_study)  # OPTIONS-NATIVE (F86): 0DTE VRP journal
                _beat("options_live", _options_native_live)    # LIVE per-tick: enter + mark + settle (F88)
                _beat("paper_autotrade", _paper_autotrade)     # STUDY: paper orders when armed
                def _run_outcomes():                           # resolve + SURFACE the outcomes
                    upd = track_outcomes()
                    if upd:                                    # awareness (user 2026-07-10): a TP2/stop
                        for u in upd:                          # resolution must announce itself, not
                            u["ts"] = _now()                   # sit silently in the journal
                        buf = _latest.setdefault("resolutions", [])
                        buf.extend(upd); del buf[:-30]
                _beat("track_outcomes", _run_outcomes)
                def _weekend_fade_tick():                      # F97b weekend fade (Sun 18:05 in,
                    from bot.strategy.asia_fade import tick    # 0.5x stop live, Mon 03:05 out) —
                    tick()                                     # approval-gated shadow
                _beat("weekend_fade", _weekend_fade_tick)
                def _nq_composite_tick():                      # F104 confluence composite (votes
                    from bot.strategy.nq_composite import tick  # @10:35, exit 16:00) — approval-
                    tick()                                     # gated shadow
                _beat("nq_composite", _nq_composite_tick)
                def _eq_calendar_tick():                       # F108 QQQ confluence@open + SPY
                    from bot.strategy.eq_calendar import tick  # monday (EQ shares book) —
                    tick()                                     # approval-gated shadow
                _beat("eq_calendar", _eq_calendar_tick)
                _beat("persist", _persist_runtime)             # heartbeat for the phase-7 health check
                def _tickwatch_check():                        # F102: the 3s poll thread must stay fresh
                    from bot.market_data import tickwatch
                    st = tickwatch.status()
                    if st["on"] and (st["age_sec"] is None or st["age_sec"] > 90):
                        raise RuntimeError(f"tick poll stale {st['age_sec']}s")
                _beat("tickwatch", _tickwatch_check)
                try:                             # persist flow scores each cycle (data-first — future feature backfill)
                    from bot.orderflow.persist import snapshot as _of_snap
                    _of_snap(list(dict.fromkeys(s.get("symbol") for s in (_latest.get("signals") or [])
                                                if s.get("symbol"))) or ["SPY", "QQQ"])
                except Exception:
                    pass
                if _mkt_tick["n"] % 10 == 0:      # market context every ~10 cycles (slow daily data)
                    # TRAINING-LAB-PLANE HEARTBEATS (user 2026-07-10 "same test for the training
                    # lab"): the slow-cadence steps recorded errors into _latest but nothing
                    # SURFACED them — a dead duel/phase78 hid exactly like the dead resolver (D5)
                    _latest["market"] = _beat_val("market_context", market_context)
                    if settings.alpaca_paper:
                        # EXECUTION SERVICE beats (Phase 5): broker-truth fills, reconciliation
                        # with teeth (mismatch -> halt_submissions), stale-order sweep. Runs
                        # whenever the paper broker is configured — open orders need tracking
                        # even after the autotrade toggle goes off.
                        _beat("exec_fills", lambda: _exec_service().poll_fills())
                        _latest["reconcile"] = _beat_val("reconcile",
                                                         lambda: _exec_service().reconcile())
                        _beat("exec_stale", lambda: _exec_service().staleness_sweep())
                    from bot.strategy.duel import run_duel_once
                    _latest["duel_tick"] = _beat_val("duel", run_duel_once)
                if _mkt_tick["n"] % 60 == 0:      # AITP PHASE 7-8 AUTO-ADVANCE (user 2026-07-06):
                    # NIGHTLY RESEARCH BATTERY (F98 — pattern discovery): launch ~02:00 ET once
                    # a day; surface verdict CHANGES (new edges / decay) as research alerts.
                    def _battery_tick():
                        import json as _json
                        import pandas as _pd
                        from bot.config import BOT_ROOT
                        rep_p = BOT_ROOT / "data" / "ml" / "reports" / "nightly_research.json"
                        now_et = _pd.Timestamp.now(tz="America/New_York")
                        today = now_et.strftime("%Y-%m-%d")
                        rep = {}
                        if rep_p.exists():
                            try:
                                rep = _json.loads(rep_p.read_text(encoding="utf-8"))
                            except Exception:
                                rep = {}
                        if now_et.hour == 2 and str(rep.get("generated_at", ""))[:10] != today \
                                and _train_state["proc"] is None:
                            log = open(rep_p.parent / "nightly_research.log", "a", encoding="utf-8")
                            _subprocess.Popen([_sys.executable,
                                               str(BOT_ROOT.parent / "research" / "nightly_battery.py")],
                                              cwd=str(BOT_ROOT.parent), stdout=log,
                                              stderr=_subprocess.STDOUT)
                        # surface a fresh report's changes exactly once
                        ts = rep.get("generated_at")
                        if ts and ts != _latest.get("battery_seen"):
                            _latest["battery_seen"] = ts
                            _latest["research_alerts"] = (rep.get("changes") or [])[:12]
                    _beat("battery", _battery_tick)
                    def _daily_backup():          # Phase 7: one verified snapshot per UTC day
                        import time as _t
                        from bot import backup as _bk
                        today = _t.strftime("%Y%m%d", _t.gmtime())
                        if _state.get("_last_backup") == today:
                            return {"skipped": today}
                        r = _bk.backup()
                        v = _bk.verify(r["path"]) if r.get("ok") else {"ok": False}
                        _bk.prune()
                        _state["_last_backup"] = today
                        if not v.get("ok"):
                            from bot.alerts import alert
                            alert(f"daily backup FAILED verification: {r} / {v}", level="critical")
                        return {**r, "verified": v.get("ok")}
                    _beat("backup", _daily_backup)
                    def _daily_bar_persist():     # LIVE-BAR PERSISTER (user 2026-07-12): the
                        import datetime as _dt    # store's forward edge grows from the scan's
                        from zoneinfo import ZoneInfo as _ZI   # own delayed feeds — QA freshness
                        now_et = _dt.datetime.now(_ZI("America/New_York"))   # clears on its own
                        if now_et.weekday() >= 5 or (now_et.hour, now_et.minute) < (16, 10):
                            return {"skipped": "before 16:10 ET / weekend"}
                        key = now_et.strftime("%Y%m%d")
                        if _state.get("_last_bar_persist") == key:
                            return {"skipped": key}
                        from bot.market_data.live_persist import persist_day
                        r = persist_day()
                        _state["_last_bar_persist"] = key
                        return r
                    _beat("bar_persist", _daily_bar_persist)
                    from bot.phase78 import evaluate as _p78       # paper study self-eval, hourly
                    _latest["phase78"] = _beat_val("phase78", _p78)
                    from bot.boss import evaluate as _boss         # BOSS conformance watch
                    _latest["boss"] = _beat_val("boss", _boss)
                    try:                          # JOURNAL INTEGRITY watch (hourly): corruption
                        from bot.tracker import integrity as _integ   # never sits unnoticed
                        _latest["journal_integrity"] = _beat_val("journal_integrity", _integ)
                        if not _latest["journal_integrity"].get("ok", True):   # error stub = no alert (beat shows it)
                            from bot.alerts import alert as _alert
                            ji = _latest["journal_integrity"]
                            _alert(f"journal integrity: {len(ji['dupes'])} dupes, "
                                   f"{len(ji['bad_levels'])} bad levels, "
                                   f"{len(ji['missing_bar_identity'])} without bar id",
                                   level="critical", source="journal")
                    except Exception as e:
                        _latest["journal_integrity"] = {"error": str(e)[:120]}
                    try:                          # HEALTH pushes (phase-7 alerting channel):
                        from bot.alerts import alert as _alert       # scan errors + worker
                        if _latest.get("error"):                     # band-passes leave the app
                            _alert(f"scan error: {_latest['error']}", "warn", "scan")
                        for _wid, _w in (_latest.get("boss", {}).get("workers") or {}).items():
                            if (_w.get("conformance") or {}).get("band_pass") and not _w.get("paper_approved"):
                                _alert(f"{_wid} PASSES ITS BAND — approve for paper on the dashboard",
                                       "info", "boss")
                        p78 = _latest.get("phase78") or {}
                        if p78.get("auto_advanced"):
                            _alert("PHASE 8: 'live' stage AUTO-ADVANCED (lock file still manual)",
                                   "critical", "phase78")
                    except Exception:
                        pass
                    try:                          # EVOLUTION nightly — TIME-based (review fix:
                        from bot.evolve import REPORT as _erep   # the old %1440 cycle counter
                        import os as _os          # reset on every reload, so the nightly could
                        _age = _time.time() - (_os.path.getmtime(_erep) if _erep.exists() else 0)
                        if _age > 24 * 3600:      # never fire; report mtime is restart-proof
                            _spawn_evolve_deep()  # subprocess — never inside the live server
                    except Exception as e:
                        _latest["evolve"] = {"error": str(e)[:120]}
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
    """Market context with SELF-HEALING cache (D4 2026-07-09): a failed context ('unknown') got
    cached at the 16:00 yahoo rate-limit and was served frozen for hours — the header sat on
    'market: unknown' with a dead feed dot. Recompute when the cache is a failure or >15 min old."""
    from bot.market_intel import market_context
    m = _latest.get("market")
    stale = True
    if m and m.get("regime") != "unknown":
        try:
            import pandas as _pd
            age = (_pd.Timestamp.now(tz="America/New_York") - _pd.Timestamp(m["ts"])).total_seconds()
            stale = age > 900
        except Exception:
            pass
    if stale:
        m = market_context()
        _latest["market"] = m
    return m


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


_tw_cache = {"t": 0.0, "syms": [], "rows": []}


def _tick_symbols() -> list:
    """ACTIVE set for the tick watcher (30s-cached): open tracked positions + the weekend-fade
    hold + currently-firing tradeable signals. Small on purpose — rate-limit friendly."""
    import time as _t
    if _t.time() - _tw_cache["t"] < 30:
        return _tw_cache["syms"]
    syms, rows = [], []
    try:
        from bot.tracker import list_decisions
        for x in list_decisions(200):
            if x.get("taken") and x.get("outcome") in ("open", "tp1_open"):
                syms.append(x["symbol"])
                rows.append({"id": x["id"], "symbol": x["symbol"], "side": x["side"],
                             "stop": x.get("stop"), "tp1": x.get("tp1"), "tp2": x.get("tp2")})
    except Exception:
        pass
    try:
        from bot.strategy.asia_fade import open_position
        if open_position():
            syms.append("NQ")
    except Exception:
        pass
    syms += [s.get("symbol") for s in (_latest.get("signals") or []) if s.get("tradeable")]
    syms += list(_WATCH)                    # F103: tick-direction rings for the whole watchlist
    _tw_cache.update(t=_t.time(), syms=[s for s in dict.fromkeys(syms) if s], rows=rows)
    return _tw_cache["syms"]


_tw_touched: set = set()


def _tick_touch(sym: str, ts: float, px: float) -> None:
    """Intrabar TOUCH detection (F102): a tracked position's stop/TP crossed between bar closes
    fires an alert IMMEDIATELY (the walk still books the official outcome — no double-booking)."""
    for r in _tw_cache["rows"]:
        if r["symbol"] != sym:
            continue
        sgn = 1 if r["side"] == "long" else -1
        for level, val in (("stop", r.get("stop")), ("tp1", r.get("tp1")), ("tp2", r.get("tp2"))):
            if val is None:
                continue
            crossed = (px - float(val)) * sgn <= 0 if level == "stop" else (px - float(val)) * sgn >= 0
            key = f"{r['id']}|{level}"
            if crossed and key not in _tw_touched:
                _tw_touched.add(key)
                buf = _latest.setdefault("intrabar", [])
                buf.append({"symbol": sym, "level": level, "px": round(px, 2),
                            "side": r["side"], "ts": _now()})
                del buf[:-20]


@app.on_event("startup")   # NOTE: on_event is deprecated in FastAPI; migration to lifespan is
def _startup():            # queued — it touches the thread-startup path, so it gets its own
                           # change + verification pass rather than riding a warning sweep.
    _restore_runtime()                      # kill-switch/paper toggles + dedup keys survive restarts
    if os.environ.get("BOT_AUTOSCAN", "1") != "0":
        _threading.Thread(target=_scan_loop, daemon=True).start()
    else:                                   # API-ONLY (reloadable): the worker scans; we just read
        _threading.Thread(target=_latest_reader, daemon=True).start()
    # TICK WATCHER (F102): 3s snapshot poll for the ACTIVE set only — open tracked positions,
    # session holds, firing signals. Serves intrabar TOUCH alerts + the forward tick archive;
    # entries stay on validated 5m closes.
    try:
        from bot.market_data import tickwatch
        tickwatch.start(_tick_symbols, on_tick=_tick_touch)
    except Exception:
        pass
    # EXECUTION-SERVICE RECOVERY on boot (Phase 5): converge order rows to broker truth —
    # crash-before-submit -> FAILED; timeout-but-accepted -> adopted; then reconcile positions.
    if settings.alpaca_paper:
        try:
            _exec_service().recover()
        except Exception:
            pass
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


_CORE_BEATS = ("snapshot", "autotrack", "track_outcomes", "persist", "exec_fills", "reconcile")


def _semantic_health(now: float | None = None) -> dict:
    """SEMANTIC health (remediation Phase 7, 2026-07-11): 'the server responds' is not 'safe to
    trade'. source_healthy = the scan heartbeat is FRESH (< 3x the scan cadence); healthy = kill
    switch off AND heartbeat fresh AND no CORE subsystem beat failing. The audited endpoint
    hardcoded source_healthy=true and derived healthy from the kill switch alone."""
    from datetime import datetime as _dt
    now = now if now is not None else _time.time()
    scan_sec = max(int(os.environ.get("BOT_SCAN_SEC", "30") or 30), 30)
    age = None
    ts = _latest.get("ts")
    if not ts and os.environ.get("BOT_AUTOSCAN") != "1":
        # API role (reloadable process): the WORKER's persisted heartbeat is the cross-process
        # truth — a dead worker behind a live API must read UNHEALTHY, and a live worker behind
        # a freshly-reloaded API must read healthy (Phase 7 split-brain visibility).
        try:
            ts = json.loads(_RUNTIME_STATE.read_text(encoding="utf-8")).get("last_scan_at")
        except Exception:
            ts = None
    if ts:
        try:
            age = now - _dt.fromisoformat(str(ts).replace("Z", "+00:00")).timestamp()
        except Exception:
            age = None
    scan_fresh = age is not None and age < 3 * scan_sec
    fails = sorted(k for k, v in _beats.items() if not v.get("ok"))
    core_fails = [k for k in fails if k in _CORE_BEATS]
    broker = "n/a"
    if settings.alpaca_paper:
        try:
            _paper_broker().is_market_open()
            broker = "ok"
        except Exception as e:
            broker = f"down: {str(e)[:60]}"
    healthy = (not _state["kill_switch"]) and scan_fresh and not core_fails \
        and not str(broker).startswith("down")
    return {"healthy": healthy, "source_healthy": bool(scan_fresh),
            "scan_age_sec": round(age, 1) if age is not None else None,
            "scan_budget_sec": 3 * scan_sec, "broker": broker,
            "kill_switch": _state["kill_switch"],
            "beats_failing": fails, "core_beats_failing": core_fails,
            # PROCESS IDENTITY (split-brain visibility): which process produced this answer,
            # and how old the snapshot it serves is
            "pid": os.getpid(), "role": "scanner" if os.environ.get("BOT_AUTOSCAN") == "1" else "api",
            "started_at": _START, "uptime_sec": int(now - _START)}


@app.get("/api/health")
def health():
    try:
        from bot.strategy.orb_candidates import STRATEGY_VERSION as _sv
    except Exception:
        _sv = "?"
    sem = _semantic_health()
    return {"mode": _state["mode"], "live_allowed": settings.live_allowed,
            "alpaca_paper": settings.alpaca_paper,
            **sem,
            "scanning": _latest["scanning"],
            "paper_autotrade": _state.get("paper_autotrade", False),
            "strategy_version": _sv,           # stale-server tell: compare with the CHANGELOG
            "continuous_training": _cont["on"],
            # SUBSYSTEM HEARTBEATS (D5 prevention): each scan-loop step's last outcome — a step
            # that is failing or hasn't succeeded recently shows RED on the dashboard
            "beats": _beats}


@app.get("/api/live")
def liveness():
    """The WATCHDOG's endpoint (Phase 7): HTTP 200 alone means nothing — the watchdog reads
    `healthy` and restarts on false/stale, not merely on connection failure."""
    return _semantic_health()


@app.get("/api/entry_matrix")
def entry_matrix(evidence: str = "", floor: int = 30):
    """ENTRY PROFITABILITY MATRIX (Phase E — the Profitability Lab's source). `evidence` is
    REQUIRED and singular: backtest | shadow | paper | live — mixing is refused (rule 3).
    Under-sample cells say INSUFFICIENT SAMPLE, never 0.00R (rule 6)."""
    from bot.ml.entry_matrix import matrix
    try:
        return matrix(evidence, floor=max(int(floor), 1))
    except ValueError as e:
        return {"error": str(e)}


@app.get("/api/entry_matrix/nominations")
def entry_matrix_nominations(evidence: str = "backtest"):
    """Removal NOMINATIONS (Phase E.3): negative-expectancy cells with sample — each still needs
    the cohort test before any removal is adopted. The matrix nominates; it never auto-blocks."""
    from bot.ml.entry_matrix import nominations
    try:
        return {"evidence": evidence, "nominations": nominations(evidence)}
    except ValueError as e:
        return {"error": str(e)}


@app.get("/api/contract")
def contract(symbol: str, spot: float, side: str = "long", iv: float | None = None, dte: int = 0,
             otm: float = 0.0, tp1: float = 0.0, tp2: float = 0.0, stop: float = 0.0):
    """Greeks + bid/mid/ask for the ATM(-ish) option a signal would use, PLUS what the contract is worth
    if the underlying reaches TP1 / TP2 / stop (Black-Scholes repriced at each level, same IV) — powers the
    Selected Contract panel. bid/ask from a ~4% spread estimate (Pine/BOT have no live chain).
    iv defaults to the OPRA-calibrated ATM term structure (F85) when the caller doesn't supply one."""
    from bot.options import pricing as P
    iv = P.default_iv(dte) if iv is None else float(iv)
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


@app.get("/api/alerts")
def alerts_feed(n: int = 30):
    """The health-alert feed (phase-7 channel): file-backed, webhook-pushed when
    ALERT_WEBHOOK_URL is set in .env (Discord/Slack/ntfy auto-detected — env-ready)."""
    from bot.alerts import recent
    from bot.config import _get
    return {"alerts": recent(n),
            "webhook_configured": bool((_get("ALERT_WEBHOOK_URL") or "").strip())}


@app.get("/api/options_strategies")
def options_strategies_list():
    """The APPROVED options lineages to list on the Selected-Contract dropdown (user 2026-07-08),
    each keyed by its category id + paper-approval state so the dropdown is data-driven."""
    from bot.options import native
    return {"strategies": native.approved_options_lineages()}


@app.get("/api/options_native")
def options_native_feed(structure: str = "long_single", lineage: str = "", underlying: str = ""):
    """Any approved OPTIONS lineage's live 0DTE contract + its PER-LINEAGE journal scorecard
    (user 2026-07-08). `lineage` defaults to options-native (VRP); naked lineages (volbreak-0dte /
    options-0.1) force the long_single structure and price their own underlying. Real-premium rows
    accrue as each lineage trades; until then the backtest headline stands in."""
    from bot.options import native
    from bot.approval import paper_approved
    from bot.market_data.providers import latest_price   # was NameError here -> spot None -> "chain closed" always (fix 2026-07-09)
    lin = lineage or native.LINEAGE
    meta = native.OPTIONS_LINEAGES.get(lin, {})
    if meta.get("kind") == "naked":                       # naked-only lineages have one structure
        structure = "long_single"
    unders = meta.get("underlyings") or ["QQQ"]
    und = underlying if underlying in unders else unders[0]
    dte = 7 if structure == "condor_7dte" else meta.get("dte", 0)   # 7DTE condor / 21DTE swing / else 0DTE
    spot, live = None, None
    try:
        spot = (latest_price(und) or {}).get("price")
        if not spot:                                      # after hours: last bar close so it still prices
            try:
                import pandas as _pd
                _b = _pd.read_parquet(_on_repo_data() / f"{und.lower()}_continuous_1m.parquet", columns=["close"])
                spot = float(_b["close"].iloc[-1])
            except Exception:
                spot = None
        live = native.live_signal_from_alpaca(und, spot=float(spot) if spot else None,
                                              structure=structure, dte=dte)
        if live.get("error"):
            live = None
    except Exception:
        live = None
    # BS FALLBACK (user 2026-07-09: "we have the data live already"): if the live Alpaca chain is
    # unavailable (after hours / no entitlement) but we have the underlying spot, price an ESTIMATED
    # contract off Black-Scholes + the F85-calibrated IV so the panel POPULATES instead of "chain
    # closed". Advisory only — flagged priced_from='bs_estimate', never journaled (BS can't price
    # 0DTE skew, O2). Real Alpaca rows still win when the chain is live.
    if live is None and spot:
        try:
            from bot.options.pricing import default_iv
            mins = native._mins_to_close() if dte == 0 else dte * 390.0
            q = native.bs_quote(float(spot), mins, default_iv(dte))
            pos = native.build(float(spot), float(spot), q, native.strikes_around(float(spot)),
                               spec=dict(native.SPEC, structure=structure))
            if pos:
                est = native.describe(pos, float(spot), mins_to_close=mins)
                est.update({"priced_from": "bs_estimate", "lineage": lin, "underlying": und,
                            "is_0dte": dte == 0, "spot": round(float(spot), 2)})
                live = est
        except Exception:
            live = None
    if live:
        live["underlying"] = und          # label the PICKED underlying (describe/build default to QQQ)
    return {"lineage": lin, "label": meta.get("label", lin), "approved": paper_approved(lin),
            "structure": structure, "underlying": und,
            "underlyings": unders, "structures": list(meta.get("structures", native.STRUCTURES)),
            "headline": meta.get("headline", ""),
            "target": {"win_pct": [75, 85], "pf": [1.6, 1.8], "maxDD_pct": 11, "signals_per_session": [1, 2]},
            "summary": native.journal_summary(lin),
            "signal": live,                               # REAL Alpaca only; None -> panel shows EMPTY
            "live_chain": bool(live),
            "performance": native.performance_by_structure(lin),   # which structure is working, per entry
            "rows": sorted(native.load_journal(lin), key=lambda r: (r.get("date"), r.get("slot")))[-60:]}


@app.get("/api/journal/integrity")
def journal_integrity():
    """Journal integrity audit (user 2026-07-07: same-bar entry/TP/stop corruption watch):
    same-lineage duplicates, impossible level geometry, rows without bar identity. Also runs
    hourly in the scan loop and rides the journal_feed panel."""
    from bot.tracker import integrity
    return integrity()


@app.get("/api/study")
def study():
    """First-touch study: what hit first (stop vs TP) + MFE/MAE + tuning hints for stop/target accuracy."""
    from bot.tracker import study as _study
    return _study()


def _tracked_closed():
    """The tracked live record (same closed-decision population as /api/performance) — the
    attribution/equity panels were reading the REPLAY journal, which live/paper never writes
    (scan persist=False), so they sat empty next to a Performance panel showing 30 trades."""
    from bot.tracker import list_decisions
    return [x for x in list_decisions(3000)
            if x["taken"] and x.get("result_r") is not None and x["outcome"] != "open"]


@app.get("/api/attribution")
def attribution():
    d = _tracked_closed()
    if d:
        from bot.performance import _bucket
        rows = [{"net_r": float(x["result_r"]), "strategy_version": x.get("family") or "?",
                 "symbol": x["symbol"], "side": x["side"], "exit_reason": x.get("outcome") or "?"}
                for x in d]
        return {dim: _bucket(rows, key) for dim, key in
                [("by_strategy", "strategy_version"), ("by_symbol", "symbol"),
                 ("by_side", "side"), ("by_exit", "exit_reason")]}
    return perf.attribution(_journal)


@app.get("/api/equity")
def equity():
    d = sorted(_tracked_closed(), key=lambda x: x.get("decided_at") or "")
    if d:
        import numpy as np
        cum = 25_000.0 + np.cumsum([float(x["result_r"]) * 100.0 for x in d])
        return {"curve": [25000.0] + [round(float(v), 2) for v in cum]}
    return {"curve": [round(float(x), 2) for x in perf.equity_curve(_journal).tolist()]}


@app.get("/api/strategy_perf")
def strategy_perf():
    """LIVE STRATEGY PERFORMANCE — every active strategy stream ranked by its OWN record (user
    2026-07-09: 'performance for live strategies... so we can make the signal prioritisation per
    performance'). One board, three record sources:
      tracker  — intraday lineages (ORB core, workers, trail), taken+resolved shadow/live rows
      duel     — the daily lineages head-to-head (volbreak/swing/overnight/tsmom), shadow-daily
      options  — per-lineage×structure journals (backtest until live fills accrue; source shown)
    rank: avg R desc among RANKABLE rows (n >= MIN_SAMPLE); thin samples sit below, accruing.
    band = the goal (WR 75-85 · PF >= 1.7). This board is the substrate for signal prioritisation."""
    import numpy as np
    from collections import defaultdict
    from bot.tracker import MIN_SAMPLE
    rows = []
    # tracker families -> their lineage + book (so the APPROVAL LADDER can show each version's
    # live record, and eq/ft/op stay visibly separated — user 2026-07-10)
    _fam_lineage = {"trail-eq": "trail-eq-0.1"}
    _fam_book = {}
    try:
        from bot.boss import WORKERS
        for wid, w in WORKERS.items():
            _fam_lineage[wid] = w["lineage"]
            _fam_book[wid] = "eq" if w["symbol"] in ("QQQ", "SPY") else "ft"
    except Exception:
        pass
    try:
        from bot.strategy.orb_candidates import STRATEGY_VERSION as _sv
        _fam_lineage["breakout"] = _sv
    except Exception:
        pass
    g = defaultdict(list)
    for x in _tracked_closed():
        g[x.get("family") or "?"].append(float(x["result_r"]))
    for fam, rs in g.items():
        rs = np.array(rs); w = float(rs[rs > 0].sum()); l = float(-rs[rs <= 0].sum())
        rows.append({"strategy": fam, "source": "tracker · intraday", "n": int(len(rs)),
                     "win_pct": round(100 * float((rs > 0).mean()), 1),
                     "avg_r": round(float(rs.mean()), 3), "total_r": round(float(rs.sum()), 1),
                     "pf": round(w / l, 2) if l > 0 else None, "record": "live-shadow",
                     "lineage": _fam_lineage.get(fam), "book": _fam_book.get(fam)})
    try:
        from bot.strategy.duel import leaderboard
        lb = leaderboard()
        stage = lb.get("stage") or {}
        lins, books = lb.get("lineage") or {}, lb.get("books") or {}
        for m, r in (lb.get("results") or {}).items():
            rows.append({"strategy": m, "source": "duel · daily", "n": r["n"], "win_pct": r["win_pct"],
                         "avg_r": r["avg_r"], "total_r": r["total_r"], "pf": r.get("pf"),
                         "record": f"shadow · {stage.get(m, 'research')}",
                         "lineage": lins.get(m), "book": books.get(m)})
    except Exception:
        pass
    try:
        from bot.options import native
        for lin in native.OPTIONS_LINEAGES:
            for struct, p in (native.performance_by_structure(lin) or {}).items():
                if not p.get("n"):
                    continue
                rows.append({"strategy": f"{lin} · {struct}", "source": "options journal",
                             "n": p["n"], "win_pct": p.get("win_pct"), "avg_r": p.get("avg_ret"),
                             "total_r": round((p.get("avg_ret") or 0) * p["n"], 1), "pf": p.get("pf"),
                             "record": p.get("source", "backtest") + (f" · live {p['live_n']}" if p.get("live_n") else ""),
                             "lineage": lin, "book": "op"})
    except Exception:
        pass
    try:                                             # F97b weekend-fade (session shadow, FT book)
        from bot.strategy.asia_fade import perf as _af_perf, LINEAGE as _AF_LIN
        p = _af_perf()
        if p.get("n"):
            rows.append({"strategy": "weekend_fade", "source": "session · shadow", "n": p["n"],
                         "win_pct": p["win_pct"], "avg_r": p["avg_r"], "total_r": p["total_r"],
                         "pf": p.get("pf"), "record": "live-shadow", "lineage": _AF_LIN, "book": "ft"})
    except Exception:
        pass
    try:                                             # F104 confluence composite (FT book)
        from bot.strategy.nq_composite import perf as _nc_perf, LINEAGE as _NC_LIN
        p = _nc_perf()
        if p.get("n"):
            rows.append({"strategy": "nq_composite", "source": "session · shadow", "n": p["n"],
                         "win_pct": p["win_pct"], "avg_r": p["avg_r"], "total_r": p["total_r"],
                         "pf": p.get("pf"), "record": "live-shadow", "lineage": _NC_LIN, "book": "ft"})
    except Exception:
        pass
    try:                                             # F108 equity calendar rules (EQ shares book)
        from bot.strategy.eq_calendar import perf as _ec_perf, RULES as _EC_RULES
        for key, cfg in _EC_RULES.items():
            p = _ec_perf(key)
            if p.get("n"):
                rows.append({"strategy": key, "source": "session · shadow", "n": p["n"],
                             "win_pct": p["win_pct"], "avg_r": p["avg_r"], "total_r": p["total_r"],
                             "pf": p.get("pf"), "record": "live-shadow",
                             "lineage": cfg["lineage"], "book": "eq"})
    except Exception:
        pass
    for r in rows:
        r["rankable"] = r["n"] >= MIN_SAMPLE
        wp, pf = r.get("win_pct"), r.get("pf")
        r["band_pass"] = bool(wp is not None and pf is not None and 75 <= wp <= 85 and pf >= 1.7)
    rows.sort(key=lambda r: (not r["rankable"], -(r.get("avg_r") if r.get("avg_r") is not None else -9)))
    return {"strategies": rows, "min_sample": MIN_SAMPLE,
            "band": "WR 75-85 · PF ≥ 1.7", "generated_at": _now()}


_bias_cache: dict = {}    # per-symbol 60s cache — the panel polls but bars only change per bar


@app.get("/api/bias")
def daily_bias(symbol: str = "SPY"):
    """DAILY BIAS for the Underlying-Signals panel (user 2026-07-09): six causal reads off the
    bars answering "which way does TODAY lean?" — gap (open vs prior close), since-open control,
    position vs the prior day's range (PDH/PDL), the classic floor pivot, session-VWAP side, and
    the daily EMA20/50 stack. Each votes -1/0/+1; the composite labels the day."""
    import time as _t
    hit = _bias_cache.get(symbol)
    if hit and _t.time() - hit[0] < 60:
        return hit[1]
    import pandas as pd
    from bot.market_data.providers import get_bars
    try:
        b = get_bars(symbol, tf="5m", period="5d")
    except Exception as e:
        return {"error": f"bars unavailable: {e}"}
    if b is None or not len(b):
        return {"error": "no bars"}
    b = b.copy()
    tcol = "ts_et" if "ts_et" in b.columns else "ts"
    b["date"] = pd.to_datetime(b[tcol]).dt.strftime("%Y-%m-%d")
    days = sorted(b["date"].unique())
    if len(days) < 2:
        return {"error": "need 2 sessions of bars"}
    T, P = b[b["date"] == days[-1]], b[b["date"] == days[-2]]
    px, opn = float(T["close"].iloc[-1]), float(T["open"].iloc[0])
    pdh, pdl, pdc = float(P["high"].max()), float(P["low"].min()), float(P["close"].iloc[-1])
    piv = (pdh + pdl + pdc) / 3.0
    vol = T["volume"].astype(float).clip(lower=0) if "volume" in T.columns else None
    vwap = None
    if vol is not None and float(vol.sum()) > 0:
        tp = (T["high"].astype(float) + T["low"].astype(float) + T["close"].astype(float)) / 3.0
        vwap = float((tp * vol).sum() / vol.sum())
    sgn = lambda x, eps=0.0: 1 if x > eps else (-1 if x < -eps else 0)
    gap = 100 * (opn - pdc) / pdc
    since_open = 100 * (px - opn) / opn
    f = {"gap": {"read": sgn(gap, 0.10), "detail": f"open {gap:+.2f}% vs prior close"},
         "since_open": {"read": sgn(since_open, 0.05), "detail": f"{since_open:+.2f}% since the open"},
         "prior_range": {"read": 1 if px > pdh else (-1 if px < pdl else 0),
                         "detail": f"vs PDH {pdh:.2f} / PDL {pdl:.2f}"},
         "pivot": {"read": sgn(px - piv), "detail": f"P {piv:.2f} (H+L+C)/3"}}
    if vwap:
        f["vwap"] = {"read": sgn(px - vwap), "detail": f"session VWAP {vwap:.2f}"}
    try:                                             # daily structural trend (EMA20/50 stack)
        dd = get_bars(symbol, tf="1d", period="6mo")
        c = dd["close"].astype(float)
        e20 = float(c.ewm(span=20, adjust=False).mean().iloc[-1])
        e50 = float(c.ewm(span=50, adjust=False).mean().iloc[-1])
        last = float(c.iloc[-1])
        f["daily_trend"] = {"read": 1 if last > e20 > e50 else (-1 if last < e20 < e50 else 0),
                            "detail": f"close vs EMA20 {e20:.2f} / EMA50 {e50:.2f}"}
    except Exception:
        pass
    score = sum(v["read"] for v in f.values())
    out = {"symbol": symbol, "factors": f, "score": score,
           "bias": "bullish" if score >= 2 else "bearish" if score <= -2 else "neutral",
           "price": round(px, 2), "open": round(opn, 2), "pdh": round(pdh, 2),
           "pdl": round(pdl, 2), "pdc": round(pdc, 2), "pivot": round(piv, 2),
           "vwap": round(vwap, 2) if vwap else None, "session_date": days[-1], "ts": _now()}
    _bias_cache[symbol] = (_t.time(), out)
    return out


_so_cache = {"t": 0.0, "data": []}


def _session_opens() -> list:
    """Open positions of the session shadow strategies (30s cache): module, side, entry, levels."""
    import time as _t
    if _t.time() - _so_cache["t"] < 30:
        return _so_cache["data"]
    out = []
    try:
        from bot.strategy.asia_fade import open_position as _wf_open
        p = _wf_open()
        if p:
            out.append({"module": "weekend_fade", "book": "ft", "symbol": "NQ", "side": "long",
                        "entry": p.get("entry"), "stop": p.get("stop"), "opened": p.get("date"),
                        "note": f"risk unit {p.get('risk')} pts · exit Mon 03:00"})
    except Exception:
        pass
    try:
        from bot.strategy.nq_composite import open_position as _nc_open
        p = _nc_open()
        if p:
            out.append({"module": "nq_composite", "book": "ft", "symbol": "NQ",
                        "side": p.get("side"), "entry": p.get("entry"), "stop": p.get("stop"),
                        "opened": p.get("date"),
                        "note": f"votes {p.get('votes')} {p.get('detail')} · exit 16:00 close"})
    except Exception:
        pass
    try:                                             # F108 equity calendar opens (EQ shares)
        from bot.strategy.eq_calendar import open_positions as _ec_open
        out += _ec_open()
    except Exception:
        pass
    _so_cache.update(t=_t.time(), data=out)
    return out


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
            "error": _latest["error"], "watchlist": _WATCH,
            # RESOLUTION FEED (user 2026-07-10 awareness): last ~30 first-touch outcomes so the
            # dashboard can announce a TP2/stop the cycle it books, not when you dig for it
            "resolutions": _latest.get("resolutions") or [],
            # RESEARCH FEED (F98): verdict changes from the latest nightly battery run
            "research_alerts": _latest.get("research_alerts") or [],
            # INTRABAR TOUCHES (F102): stop/TP levels crossed between bar closes (tick watcher)
            "intrabar": _latest.get("intrabar") or [],
            # SESSION-STRATEGY OPENS (user 2026-07-10 "do I have to look for the confluence
            # myself?" — NO): weekend-fade + nq-composite entries surface + alert automatically
            "session_opens": _session_opens()}


@app.get("/api/patterns")
def patterns(sym: str = ""):
    """PATTERN ADVISORY (read-only, docs/PATTERN_RECOGNITION_V1.md §13) — re-presents the LIVE scan
    snapshot as the pattern panel per symbol, with the confluence/pass summary. Advisory ONLY: it
    creates no orders and the certified path is untouched. Evidence chip (PR1): QQQ/SPY=CERTIFIED
    (can PASS the gate); NQ=CONTEXT, ES=UNPROVEN, GC=UNVERIFIED (never pass). Fast: reads the
    already-computed snapshot, no re-scan."""
    from bot.strategy.pattern_advisory import watchlist_advisory
    syms = [sym.upper()] if sym else list(_WATCH)
    return watchlist_advisory(_latest.get("signals") or [], syms, "5m")


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
    from bot.options.pricing import calibrate_realized_iv as _cal, default_iv as _div
    iv = _cal(float(np.std(ret) * (252 * 78) ** 0.5), dte=0) if len(ret) > 5 else _div(0)  # F85
    risk = 1.5 * atr
    return {"symbol": sym, "side": "long", "entry": round(px, 2), "stop": round(px - risk, 2),
            "tp1": round(px + 1.5 * risk, 2), "tp2": round(px + 4 * risk, 2), "iv_est": iv,
            "source": "current price + ATR default (no live signal — adjust side/levels as needed)"}


class DecisionReq(BaseModel):
    signal: dict
    taken: bool


@app.post("/api/signal/decision")
def signal_decision(d: DecisionReq, _=Depends(auth)):      # P1.4: journal mutation -> token guard
    """User marks a signal Taken or Skipped; the system then tracks where it goes (stop/TP1/TP2 first)."""
    from bot.tracker import record_decision
    return record_decision(d.signal, d.taken)


@app.get("/api/decisions")
def decisions():
    """The journal of taken/skipped signals + their tracked outcomes (real performance of the engine).
    READ-ONLY (lock fix 2026-07-10): this poll ran track_outcomes on every 12s dashboard refresh,
    racing the scan loop's own run — concurrent writers held the SQLite lock past busy_timeout and
    resolutions failed ('positions still open'). The scan cycle owns resolution; polls just read."""
    from bot.tracker import list_decisions, summary
    return {"decisions": list_decisions(50), "summary": summary()}


@app.get("/api/scorecard")
def scorecard():
    """LIVE-vs-BACKTEST gate: do taken signals realise the backtested edge (by grade)? The check that
    must pass before sizing up — proves the edge survives live fills, not just the backtest.
    READ-ONLY — the scan cycle owns track_outcomes (see /api/decisions)."""
    from bot.tracker import scorecard as _sc
    return _sc()


@app.get("/api/boss")
def boss_status():
    """THE MAIN BOSS (BOSS_WORKERS_PLAN §4): worker contracts + rolling conformance + armed
    states. Gating scope is the WORKER lineages (worker-*): the classic orb-standard paper
    study is outside Boss scope and keeps trading under its own approval."""
    from bot.boss import evaluate
    return evaluate()


@app.post("/api/boss/arm")
def boss_arm(worker: str, on: bool = True, _=Depends(auth)):
    """Manually arm/disarm a worker. OBSOLETE workers refuse to arm (fresh gauntlet required)."""
    from bot.boss import arm
    return arm(worker, on)


@app.post("/api/boss/park")
def boss_park(worker: str, on: bool = True, _=Depends(auth)):
    """PARK/RESUME a worker (user 2026-07-10): parked = shadow study paused, NO new journal rows,
    history + approvals intact. Not a merge, not a delete — the garage."""
    from bot.boss import park
    return park(worker, on)


_dp_cache = {"t": 0.0, "data": None}


@app.get("/api/duel_preview")
def duel_preview():
    """PRE-CLOSE PREVIEW of the daily book (user 2026-07-10): what each approved daily module
    WOULD enter if today's forming bar closed now — so manual brokers without MOC (Webull,
    Robinhood) get their order in 15:50-15:59, not as a next-day pending order. 120s cache."""
    import time as _t
    if _dp_cache["data"] is not None and _t.time() - _dp_cache["t"] < 120:
        return _dp_cache["data"]
    from bot.strategy.duel import preview_today
    try:
        out = {"entries": preview_today(), "ts": _now(),
               "note": "advisory — official shadow entry books on the completed bar (~17:10)"}
    except Exception as e:
        out = {"entries": [], "error": str(e)[:120]}
    _dp_cache["t"] = _t.time(); _dp_cache["data"] = out
    return out


_jf_cache = {"t": 0.0, "data": None}


@app.get("/api/training/journal_feed")
def training_journal_feed():
    """THE JOURNAL IS THE TRAINING LAB (user 2026-07-07). Shows the live trade journal that feeds
    continuous learning — per symbol × timeframe: how many resolved rows carry PIT features (the
    trainable ones) and how they fold into each lineage's dataset. This growth needs NO paper
    approval: journaling (shadow-track) and continuous training both run independent of it; the
    ONLY persisted substrate is the journal (live bars are transient — the scan is persist=False).
    30s cache (review fix): the scan cycle is 60s, so per-poll table rebuilds bought nothing."""
    if _jf_cache["data"] is not None and _time.time() - _jf_cache["t"] < 30:
        return _jf_cache["data"]
    from bot.ml.live_labels import build_live_labels
    lj = build_live_labels(save=False)
    from bot.ml.features_pit import FEATURE_COLUMNS
    feat0 = FEATURE_COLUMNS[0]
    out = {"total_rows": int(len(lj)), "by_symbol_tf": {},
           "approval_required": False,
           "note": "learning runs without paper approval; only the journal is saved"}
    out["by_strategy"] = {}
    out["by_category"] = {}
    out["recent"] = []
    if len(lj):
        lj = lj.copy()
        lj["tf"] = lj.get("tf", "5m")
        lj["family"] = lj.get("family", "?").fillna("?")
        from bot.tracker import is_core_family
        from bot.strategy.asset_config import (asset_category, CATEGORY_ORDER, CATEGORY_ID,
                                               CATEGORY_LABEL)
        _core = lj["family"].map(is_core_family)
        # 3-category tag (user 2026-07-08): each row is eq / ft / op — one shared journal, sliced
        lj["cat"] = [asset_category(s, f) for s, f in zip(lj["symbol"], lj["family"])]
        for (sym, tf), g in lj.groupby(["symbol", "tf"]):
            taken = g[g["taken"] == 1]
            # trainable = what actually feeds THIS lineage's dataset = CORE rows only (review fix:
            # worker rows inflated the count while attach_live_journal excludes them)
            trainable = taken[taken[feat0].notna() & _core.loc[taken.index]]
            out["by_symbol_tf"][f"{sym}@{tf}"] = {
                "rows": int(len(g)), "taken": int(len(taken)),
                "trainable_with_features": int(len(trainable)),
                "win_rate": round(float((trainable["net_r"] > 0).mean()), 3) if len(trainable) else None}
        # WHICH STRATEGY made the trade (user 2026-07-07): break the journal down by family/lineage
        for fam, g in lj.groupby("family"):
            tk = g[g["taken"] == 1]
            out["by_strategy"][str(fam)] = {
                "rows": int(len(g)), "taken": int(len(tk)),
                "win_rate": round(float((tk["net_r"] > 0).mean()), 3) if len(tk) else None,
                "avg_r": round(float(tk["net_r"].mean()), 3) if len(tk) else None}
        # THE 3 CATEGORIES (user 2026-07-08), in canonical eq -> ft -> op order — the shared journal
        # split by id-eq / id-ft / id-op so training can slice by category on the same store
        for cat in CATEGORY_ORDER:
            g = lj[lj["cat"] == cat]
            if not len(g):
                continue
            tk = g[g["taken"] == 1]
            out["by_category"][CATEGORY_ID[cat]] = {
                "label": CATEGORY_LABEL[cat], "rows": int(len(g)), "taken": int(len(tk)),
                "symbols": sorted(set(g["symbol"].astype(str))),
                "win_rate": round(float((tk["net_r"] > 0).mean()), 3) if len(tk) else None,
                "avg_r": round(float(tk["net_r"].mean()), 3) if len(tk) else None}
        # recent journal rows WITH their strategy + category (newest first)
        for _, r in lj.sort_values("ts").tail(40).iloc[::-1].iterrows():
            nr = r.get("net_r")
            out["recent"].append({
                "ts": str(r["ts"])[:16], "strategy": str(r.get("family", "?")),
                "cat_id": CATEGORY_ID.get(r.get("cat"), "id-eq"),
                "symbol": r["symbol"], "tf": r["tf"], "side": r["side"],
                "outcome": r.get("outcome"),
                "net_r": (round(float(nr), 2) if nr == nr else None)})
    out["continuous_syms"] = _cont["syms"]
    out["continuous_on"] = _cont["on"]
    try:                                           # integrity rides the panel (cached with it)
        from bot.tracker import integrity
        integ = integrity()
        out["integrity"] = {"ok": integ["ok"], "dupes": len(integ["dupes"]),
                            "bad_levels": len(integ["bad_levels"]),
                            "missing_bar_identity": len(integ["missing_bar_identity"])}
    except Exception:
        pass
    _jf_cache["t"], _jf_cache["data"] = _time.time(), out
    return out


_evolve_proc = {"p": None}


def _spawn_evolve_deep():
    """Run the deep evolution pass in its OWN process (review fix 2026-07-07: the exit/TP miner
    imports research modules that os.chdir and run backtests — isolating protects the always-on
    server's cwd and memory). Results land in the saved report the endpoint serves."""
    if _evolve_proc["p"] is not None and _evolve_proc["p"].poll() is None:
        return False                                # one at a time
    from bot.config import BOT_ROOT
    _evolve_proc["p"] = _subprocess.Popen([_sys.executable, "-m", "bot.evolve", "--deep"],
                                          cwd=str(BOT_ROOT), stdout=_subprocess.DEVNULL,
                                          stderr=_subprocess.DEVNULL)
    return True


@app.get("/api/evolve")
def evolve_report():
    """EVOLUTION ENGINE (BOSS_WORKERS_PLAN §4b): the SAVED mining report + emergent drafts.
    READ-ONLY (Phase 6 GET-mutation audit): the old ?deep=true spawned the miner from a GET —
    a dashboard poll could launch a full table scan. Deep runs are POST /api/evolve/run."""
    try:
        from bot.config import read_json
        from bot.evolve import _load_drafts, REPORT
        rep = read_json(REPORT, default={"note": "no mining run saved yet — click Mine now or "
                                                 "wait for the nightly tick"})
        out = dict(rep)
        out["mining"] = (_evolve_proc["p"] is not None and _evolve_proc["p"].poll() is None)
        out["drafts"] = _load_drafts()
        return out
    except Exception as e:                        # surface the cause instead of a bare 500
        import traceback
        return {"error": f"{type(e).__name__}: {e}", "trace": traceback.format_exc()[-400:]}


@app.post("/api/evolve/run")
def evolve_run(_=Depends(auth)):
    """Spawn the full miner (was GET ?deep=true — moved to POST+auth, Phase 6)."""
    return {"deep_started": _spawn_evolve_deep()}


@app.get("/api/phase78")
def phase78():
    """AITP phase 7-8 readiness — READ-ONLY evaluation (Phase 6 GET-mutation audit: the old
    default advance=true meant a BROWSER REFRESH or monitoring probe could advance the 'live'
    approval stage — the audited governance-via-GET defect). The hourly scan-loop tick still
    auto-advances when everything is green; a manual advance is POST /api/phase78/advance."""
    from bot.phase78 import evaluate
    return evaluate(auto_advance=False)


@app.post("/api/phase78/advance")
def phase78_advance(_=Depends(auth)):
    """Evaluate AND auto-advance the live stage when all green (POST+auth, Phase 6)."""
    from bot.phase78 import evaluate
    return evaluate(auto_advance=True)


@app.get("/api/candidates")
def candidates(limit: int = 50):
    """Recent ACCEPTABLE signals the engine tracked (auto-shadow + manual), newest first, with the
    resolved first-touch outcome. Updates live off the same tracker the scorecard/Performance use."""
    from bot.tracker import list_decisions
    out = []
    for x in list_decisions(limit):
        risk = abs((x.get("entry") or 0) - (x.get("stop") or 0))
        tp2 = x.get("tp2")   # single-target lineages (worker/trail) have tp2=None -> R:R is n/a, not entry/risk
        rr = round(abs(tp2 - x["entry"]) / risk, 1) if (risk and tp2 is not None and x.get("entry")) else None
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
    _set_control("kill_switch", bool(on))   # cross-process: the WORKER syncs this each cycle
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
    _set_control("paper_autotrade", bool(on))  # cross-process (worker scan loop syncs)
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
    # 2+3) ONE EXECUTION PATH (remediation Phase 5): approval + dated idempotency + account
    # truth + risk + persistent OMS + broker all live in the service — the hand-rolled Account
    # (equity-only, empty P&L/positions) and per-endpoint dedup keys are gone.
    b = _broker()
    if b is None or _state["mode"] not in ("paper", "live"):
        return {"action": "shadow", "note": "logged, NOT transmitted (mode=" + _state["mode"] + ")",
                "rr": round(c.rr, 2)}
    res = _exec_service().submit(c, "manual", session="manual", feed_healthy=True,
                                 kill_switch=_state["kill_switch"],
                                 qty_cap=t.qty or None)
    return res.to_dict()


class OptionReq(BaseModel):
    symbol: str
    side: str
    entry: float
    stop: float
    tp1: float | None = None
    tp2: float
    iv: float | None = None          # None -> OPRA-calibrated default_iv(dte) at the endpoint (F85)
    dte: int = 0
    sel_n: int = 1


@app.post("/api/options")
def options(o: OptionReq):
    """Compute the naked/debit/credit call-and-put plays for a signal (Python, not Pine)."""
    from bot.options.translate import options_for_candidate
    from bot.options.exit_plan import STRUCTURE_GATES
    from bot.options.pricing import default_iv
    try:
        c = TradeCandidate(symbol=o.symbol.upper(), side=o.side, timeframe="manual", setup="manual",
                           entry=o.entry, stop=o.stop, tp1=o.tp1, tp2=o.tp2, strategy_version="ui")
    except ValueError as e:
        return {"error": str(e)}
    out = options_for_candidate(c, iv=o.iv if o.iv is not None else default_iv(o.dte),
                                dte=o.dte, sel_n=o.sel_n)
    if isinstance(out, dict):
        out["gates"] = STRUCTURE_GATES          # every UI shows the gate each structure passed
        out["recommended"] = "naked"
    return out


@app.post("/api/exit_plan")
def exit_plan(o: OptionReq):
    """WHERE to take TP1(1.5R)/TP2(4R) + which option structure exits where + the recommendation (F64)."""
    from bot.options.exit_plan import options_exit_plan
    from bot.options.pricing import default_iv
    # exit_plan derives TP1/TP2 from entry/stop itself; tp2 just needs to be a valid placeholder
    try:
        c = TradeCandidate(symbol=o.symbol.upper(), side=o.side, timeframe="manual", setup="manual",
                           entry=o.entry, stop=o.stop, tp2=o.tp2, regime=None, strategy_version="ui")
    except ValueError as e:
        return {"error": str(e)}
    return options_exit_plan(c, iv=o.iv if o.iv is not None else default_iv(o.dte),
                             dte=o.dte, sel_n=o.sel_n)


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
    _journal.record(c)
    # ONE EXECUTION PATH (remediation Phase 5): the service owns the dated idempotency key (TV
    # retries resolve to 'duplicate'), submit-time approval, account truth, sizing authority and
    # the persistent OMS. Every response carries a correlation id + final action.
    if b is None or _state["mode"] not in ("paper", "live"):
        return {"action": "shadow", "ticker": sym,
                "note": f"logged, not transmitted (mode={_state['mode']})"}
    res = _exec_service().submit(c, "webhook", session="tv", feed_healthy=True,
                                 kill_switch=_state["kill_switch"],
                                 qty_cap=int(p.get("quantity") or 0) or None)
    return {"ticker": sym, **res.to_dict()}


@app.post("/api/order/cancel")
def cancel_order(order_id: str, _=Depends(auth)):          # P1.4: broker mutation -> token guard
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
                      + (["QQQ", "SPY", "NQ", "ES"] if sym == "ALL" else [sym]), root),
            "battery": ([_sys.executable, str(root / "research" / "nightly_battery.py")], root)}
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
                 "l2sync", "report", "parity", "gauntlet", "threshold", "geometry", "nqwr", "pairs",
                 "battery"]
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
# QQQ@15m / SPY@15m = the 15m LINEAGE (user 2026-07-07: pursue 15m + 5m, fed by the live journal).
# The dataset build unions the growing live journal, so these retrain as live QQQ/SPY trades accrue.
_cont = {"on": False, "interval_min": 360,
         "syms": ["QQQ", "SPY", "NQ", "ES", "QQQ@15m", "SPY@15m", "ALL"],
         "cycle": 0, "last_start": None, "last_end": None, "current": None, "history": []}


def _cont_run(kind: str, sym: str) -> int:
    base, _, tf = sym.partition("@")            # "QQQ@15m" -> base QQQ + --tf=15m (5m default = no suffix)
    hit = _train_cmds(kind, base, promote=False, extra=([f"--tf={tf}"] if tf else None))
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
                           "history": _cont["history"][-10:]},
            # SUBSYSTEM HEARTBEATS on the LAB page too (user 2026-07-10): a failing scan-loop /
            # governance step (duel, phase78, boss, resolver...) shows red in the lab status bar
            "beats_failing": sorted(k for k, v in _beats.items() if not v.get("ok")),
            "beats_errors": {k: v.get("error") for k, v in _beats.items() if not v.get("ok")}}


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
        if not v or v == STRATEGY_VERSION:
            continue
        st = m.get("status")
        # gauntlet-passed modules AND the BOSS WORKERS (research_candidate / obsolete signals-only)
        # get their own ladder — a worker must be paper-approvable so its live study can begin,
        # and obsolete workers still ladder to paper as SIGNALS-ONLY (user gold rule 2026-07-06)
        is_worker = str(v).startswith("worker-")
        if st == "gauntlet_pass" or is_worker:
            tag = ("BOSS WORKER" if is_worker else "module")
            if st == "obsolete":
                tag = "BOSS WORKER — OBSOLETE (paper = signals-only; Boss won't arm)"
            elif is_worker:
                tag = "BOSS WORKER — research_candidate (paper study opens the band judgment)"
            out[v] = {"what_it_is": f"[{tag}] {m['id']} — {m.get('notes', '')[:200]}",
                      "evidence": ("worker_specs / worker_cohorts / worker_veto reports"
                                   if is_worker else
                                   "swing_gauntlet.json / strat_daily run (research reports)"),
                      "status": st}
    # EMERGENT LINEAGES (review gap 2026-07-07): a draft the evolution engine produced becomes
    # approvable the moment its gauntlet passes — set the draft's status to "gauntlet_pass" in
    # data/evolve_drafts.json (the gauntlet runner's job) and it appears here with its own
    # ladder. Plain drafts stay OUT of the dropdown (the engine proposes, the gauntlet judges).
    try:
        from bot.evolve import _load_drafts
        for dft in _load_drafts():
            if dft.get("status") == "gauntlet_pass" and dft.get("id"):
                out[dft["id"]] = {"what_it_is": f"[EMERGENT — gauntlet PASSED] {dft.get('spec', '')[:200]}",
                                  "evidence": "evolve_drafts.json + its gauntlet report",
                                  "status": "gauntlet_pass"}
    except Exception:
        pass
    # OPTIONS-NATIVE lineage (F86) — a PURE options signal (0DTE VRP condor + directional fallback),
    # not a translation of any underlying trade. Approvable so its paper study can begin; it journals
    # to a SEALED family. Honest caveat: real-premium result WR 80/PF 1.69 needs a REAL options feed —
    # a Black-Scholes proxy misprices 0DTE skew (PF collapses to ~1.1), so BS-priced rows are advisory.
    try:
        from bot.options.native import LINEAGE as _ON
        out[_ON] = {"what_it_is": f"[OPTIONS-NATIVE] {_ON} — 0DTE VRP iron condor + trend-day "
                    "directional spread (F86). WR 80 · PF 1.69 · DD 1.2% in-sample on real OPRA "
                    "(22 sessions). NEEDS a real options feed; BS-priced fills are advisory-only.",
                    "evidence": "opra_condor.json + F86 (RESEARCH_NOTES)", "status": "gauntlet_pass"}
    except Exception:
        pass
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
def data_register(path: str, symbol: str | None = None, _=Depends(auth)):
    """Register an on-disk L2/L3 file (external drive fine — nothing is copied). AUTO-LABEL
    (2026-07-06): the file's own `symbol` column decides the label (multi-symbol files split
    into one source per symbol); pass `symbol` only as the fallback for files without one.
    Then run kind=l2sync with sym=<source id> to synthesize its features."""
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
async def data_synthesize_upload(request: Request, symbol: str | None = None, _=Depends(auth)):
    """Drag-and-drop path: the dragged file streams here, features are synthesized IN MEMORY and
    only the per-minute l2_* parquet persists — the raw upload is never written to disk.
    AUTO-DETECT (user 2026-07-07: "remove user selection — the system detects the symbol so the
    wrong name never mixes with the data"): the file's own `symbol` column decides; multi-symbol
    files synthesize once PER symbol found. A file WITHOUT a symbol column is refused unless the
    optional fallback `symbol` is given explicitly."""
    import io
    import pandas as pd
    from bot.ml.l2_features import synthesize_frame
    # P1.4: enforce the size limit BEFORE reading (the audited path read the whole body
    # into memory first — a large upload could OOM the API while "checking" its size)
    cl = request.headers.get("content-length")
    if cl and cl.isdigit() and int(cl) > 800_000_000:
        return {"error": "file > 800MB — register its PATH instead (reads in place, no copy)"}
    body = await request.body()
    if len(body) > 800_000_000:                     # chunked uploads without a length header
        return {"error": "file > 800MB — register its PATH instead (reads in place, no copy)"}
    name = (request.headers.get("x-filename") or "upload.csv").lower()
    try:
        if name.endswith(".parquet"):
            df = pd.read_parquet(io.BytesIO(body))
        else:
            df = pd.read_csv(io.BytesIO(body))
    except Exception as e:
        return {"error": f"could not parse upload: {str(e)[:120]}"}
    df.columns = [str(c).lower() for c in df.columns]
    if "symbol" in df.columns:
        syms = sorted(str(s).upper() for s in df["symbol"].dropna().unique()[:20])
    elif symbol:
        syms = [symbol.upper()]                     # explicit fallback for column-less files
    else:
        return {"error": "no `symbol` column in the file — cannot auto-detect. Re-export with "
                         "the symbol column, or register the PATH with an explicit fallback."}
    out = []
    for s in syms:
        res = synthesize_frame(df, s)               # synthesize_frame filters rows to `s` itself
        res["symbol"] = s
        out.append(res)
        if "error" not in res:
            from bot.audit import log as _audit
            _audit("l2_upload_synthesized", symbol=s, rows=res.get("feature_rows"),
                   filename=name, label_source="auto")
    return out[0] if len(out) == 1 else {"detected_symbols": syms, "results": out}


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


# ═══════════════════════════════════════════════════════════════════════════════
# PHASE U — OPERATOR-CONSOLE ENDPOINTS (docs/UI_PLAN.md step 0; thin + read-only)
# ═══════════════════════════════════════════════════════════════════════════════

_ready_cache = {"ts": 0.0, "out": None}


@app.get("/api/readiness")
def readiness():
    """THE single readiness source (Phase U hard rule 4): server-computed gates with VERBATIM
    reasons — the UI renders this, never derives readiness client-side. UNKNOWN never reads as
    green: any blocking gate not True => overall BLOCKED."""
    import time as _t
    if _ready_cache["out"] and _t.time() - _ready_cache["ts"] < 20:
        return _ready_cache["out"]
    gates = []

    def g(name, ok, reason, blocking=True):
        gates.append({"name": name, "ok": (True if ok is True else (False if ok is False else None)),
                      "reason": str(reason)[:200], "blocking": blocking})

    sem = _semantic_health()
    g("system health", sem["healthy"],
      ("scan heartbeat fresh" if sem["source_healthy"]
       else f"scan heartbeat stale ({sem['scan_age_sec']}s / budget {sem['scan_budget_sec']}s)")
      + (f" · core beats failing: {sem['core_beats_failing']}" if sem["core_beats_failing"] else "")
      + (f" · broker {sem['broker']}" if str(sem["broker"]).startswith("down") else ""))
    g("kill switch", not _state["kill_switch"],
      "off" if not _state["kill_switch"] else "ARMED — all trading stopped")
    try:
        from bot.strategy.orb_candidates import STRATEGY_VERSION
        from bot import approval
        st = approval.status(STRATEGY_VERSION)
        ev = st["evidence"]
        g("data QA (traded book)", ev.get("data_qa_traded_ok"),
          ("QQQ+SPY green" + ("" if ev.get("data_qa_all_ok") else
                              " — futures stores stay red on LEGACY short days (visible, non-traded)"))
          if ev.get("data_qa_traded_ok")
          else "traded-book QA RED — QQQ/SPY stale or damaged (persister catches spans up EOD)")
        g("A/B version match", ev.get("ab_strategy_version_match"),
          f"A/B report matches {STRATEGY_VERSION}" if ev.get("ab_strategy_version_match")
          else "A/B report belongs to a DIFFERENT strategy version")
        note = " (LEGACY record — pre-predicate)" if st.get("legacy") else \
               (" (STALE — store fingerprint drifted)" if st.get("stale") else "")
        g("paper approval", st["paper_approved"], f"{STRATEGY_VERSION}{note}")
        from bot.phase78 import fills_scorecard, reconciliation_clean
        fs = fills_scorecard()
        n = fs["overall"].get("n", 0)
        g("phase-8 fills", n >= 60, f"{n}/60 measured broker fills", blocking=False)
        rc = reconciliation_clean()
        g("reconciliation", rc.get("ok"),
          (f"HALT: {rc.get('halt')}" if rc.get("halt")
           else (f"{rc.get('investigation_required', 0)} order(s) INVESTIGATION_REQUIRED"
                 if rc.get("investigation_required") else "clean")))
    except Exception as e:
        g("evidence", False, f"readiness computation failed: {str(e)[:140]}")
    g("live lock", None, "LIVE stays hard-locked by design (LIVE_APPROVED.lock)", blocking=False)
    blocked = [x["name"] for x in gates if x["blocking"] and x["ok"] is not True]
    # READINESS SPLIT (Signal-Certificate T3): paper / live / model must never be confused. `overall`
    # OK can hold at 0/60 fills because fills are non-blocking FOR PAPER — but that must not read as
    # live-ready. Each objective is computed from its own gate set.
    def _names_ok(names):
        hit = [x for x in gates if x["name"] in names]
        return (bool(hit) and all(x["ok"] is True for x in hit),
                [f"{x['name']}: {x['reason']}" for x in hit if x["ok"] is not True])
    paper_names = {"system health", "kill switch", "data QA (traded book)", "A/B version match",
                   "paper approval", "reconciliation"}
    p_ok, p_block = _names_ok(paper_names)
    fills_ok = any(x["name"] == "phase-8 fills" and x["ok"] is True for x in gates)
    live_block = list(p_block) + ([] if fills_ok else ["phase-8 fills: <60 measured broker fills"]) \
        + ["LIVE hard-locked by design (LIVE_APPROVED.lock)"]
    try:
        from bot.strategy.orb_candidates import STRATEGY_VERSION as _SV
        from bot.ml.registry import ModelRegistry
        champ = next((m for m in ModelRegistry().list() if getattr(m, "champion", False)), None)
        if champ and getattr(champ, "strategy_version", None) == _SV:
            m_ok, m_block = True, []
        elif champ:
            m_ok, m_block = False, [f"champion trained on {champ.strategy_version}, current is {_SV} — must abstain"]
        else:
            m_ok, m_block = False, ["no champion model — ML abstains"]
    except Exception as e:
        m_ok, m_block = False, [f"model registry unavailable: {str(e)[:80]}"]
    out = {"mode": _state["mode"], "kill_switch": _state["kill_switch"],
           "overall": "OK" if not blocked else "BLOCKED", "blocking": blocked,
           "objectives": {
               "paper_ready": {"ready": bool(p_ok), "blocking": p_block},
               "live_ready": {"ready": False, "blocking": live_block},   # hard-locked by design
               "model_ready": {"ready": bool(m_ok), "blocking": m_block}},
           "gates": gates, "generated_at": _now()}
    _ready_cache.update(ts=_t.time(), out=out)
    return out


@app.get("/api/exec/orders")
def exec_orders(limit: int = 100):
    """Orders & Fills + Reconciliation Center source: every order with its full lifecycle
    timeline, fills, and the requested/filled/remaining/cancelled/PROTECTED breakdown."""
    svc = _exec_service()
    cols = ("order_id", "correlation_id", "source", "symbol", "side", "qty", "planned_entry",
            "stop", "tp", "strategy_version", "state", "broker_order_id", "reason",
            "created_at", "updated_at", "session", "family", "grade", "candidate_id")
    rows = svc.db.execute(
        "SELECT " + ",".join(cols) + " FROM exec_orders ORDER BY created_at DESC LIMIT ?",
        (max(int(limit), 1),)).fetchall()
    out = []
    for r in rows:
        o = dict(zip(cols, r))
        o["timeline"] = [{"state": s, "message": m, "at": a} for s, m, a in svc.db.execute(
            "SELECT state, message, at FROM exec_events WHERE order_id=? ORDER BY seq",
            (o["order_id"],))]
        fl = svc.db.execute("SELECT qty, price, at FROM exec_fills WHERE order_id=? ORDER BY at",
                            (o["order_id"],)).fetchall()
        o["fills"] = [{"qty": q, "price": p, "at": a} for q, p, a in fl]
        filled = int(sum(q for q, _, _ in fl))
        bracket_missing = any(t["state"] == "BRACKET_MISSING" for t in o["timeline"])
        o["qty_breakdown"] = {
            "requested": o["qty"] or 0, "filled": filled,
            "remaining": max((o["qty"] or 0) - filled, 0),
            "cancelled": max((o["qty"] or 0) - filled, 0) if o["state"] == "CANCELLED" else 0,
            "protected": 0 if bracket_missing else filled}
        out.append(o)
    return {"halt": svc.halted(), "orders": out}


@app.get("/api/exec/fills")
def exec_fills_api():
    """Every measured fill + the fills-derived open book and realized round trips."""
    svc = _exec_service()
    from bot.execution.service import ExecutionService
    book, realized = ExecutionService._replay_fills(svc)
    fills = [{"fill_id": f, "order_id": o, "symbol": s, "side": sd, "qty": q, "price": p, "at": a}
             for f, o, s, sd, q, p, a in svc.db.execute(
                 "SELECT fill_id, order_id, symbol, side, qty, price, at FROM exec_fills "
                 "ORDER BY at DESC LIMIT 200")]
    return {"fills": fills,
            "open_book": {k: v for k, v in book.items() if v.get("net")},
            "realized": [{"at": a, "pnl_usd": round(p, 2)} for a, p in realized[-100:]]}


@app.get("/api/risk/state")
def risk_state():
    """Risk cockpit source: the SAME account truth the risk gate trades on, with per-field
    provenance. Unprovable => a BLOCKED payload, never zeros (Phase U rules 2/5/6)."""
    from bot.risk import RiskLimits, CORRELATION_BUCKET
    L = RiskLimits()
    try:
        svc = _exec_service()
        a = svc.account_truth(feed_healthy=True, kill_switch=_state["kill_switch"])
    except Exception as e:
        return {"blocked": True, "reason": f"ACCOUNT_STATE_UNPROVEN: {str(e)[:160]}",
                "note": "an unprovable limit is a breached limit — submissions refuse (rule 5)"}

    def f(v, src):
        return {"value": v, "source": src}

    buckets = {}
    for s in a.open_symbols:
        buckets.setdefault(CORRELATION_BUCKET.get(str(s).upper(), "other"), []).append(s)
    return {"blocked": False, "as_of": _now(),
            "equity": f(round(a.equity, 2), "broker"),
            "peak_equity": f(round(a.peak_equity, 2), "flags high-water"),
            "daily_pnl": f(round(a.daily_pnl, 2), "fills replay"),
            "weekly_pnl": f(round(a.weekly_pnl, 2), "fills replay"),
            "trades_today": f(a.trades_today, "exec orders"),
            "consecutive_losses": f(a.consecutive_losses, "fills replay"),
            "open_positions": f(a.open_positions, "broker (reconciled)"),
            "correlation_buckets": buckets, "kill_switch": _state["kill_switch"],
            "limits": {"daily_loss_usd": round(L.max_daily_loss * a.equity, 2),
                       "weekly_loss_usd": round(L.max_weekly_loss * a.equity, 2),
                       "max_trades_per_day": L.max_trades_per_day,
                       "max_consecutive_losses": L.max_consecutive_losses,
                       "max_open_positions": L.max_open_positions,
                       "risk_per_trade_usd": round(L.risk_per_trade * a.equity, 2)}}


@app.get("/api/removals")
def removals_api():
    """Removed entry groups (evidence-linked) + the matrix's current nominations."""
    from bot.strategy.removals import active
    try:
        from bot.ml.entry_matrix import nominations
        noms = nominations("backtest")
    except Exception as e:
        noms = [{"error": str(e)[:120]}]
    return {"active": active(), "nominations": noms}


@app.get("/api/incidents")
def incidents_api():
    """Incidents view source: crash records, watchdog events, backups, log growth, gate-1 clock."""
    import datetime as _dt
    from bot.config import BOT_ROOT as _BR
    out = {}
    crashes = sorted((_BR / "data").glob("crash_*.txt"))
    out["crashes"] = [{"file": c.name,
                       "head": c.read_text(encoding="utf-8", errors="replace")[:300]}
                      for c in crashes[-5:]]
    wl = _BR / "config" / "watchdog.log"
    events = []
    if wl.exists():
        for ln in wl.read_text(encoding="utf-8", errors="replace").splitlines()[-60:]:
            if any(k in ln for k in ("DOWN", "UNHEALTHY", "relaunch", "DELIBERATE", "started")):
                events.append(ln[:200])
    out["watchdog"] = events[-12:]
    out["last_backup"] = None
    bdir = _BR / "data" / "backups"
    if bdir.exists():
        snaps = sorted(d for d in bdir.iterdir() if d.is_dir())
        if snaps:
            from bot import backup as _bk
            out["last_backup"] = {"snapshot": snaps[-1].name, "verify": _bk.verify(snaps[-1])}
    logs = {}
    for root in (_BR, _BR / "config"):
        if root.exists():
            for fl in root.glob("*.log"):
                logs[fl.name] = fl.stat().st_size
    out["log_bytes"] = logs
    t0 = _dt.datetime(2026, 7, 12, 3, 0, tzinfo=_dt.timezone.utc)   # gate-1 start (23:00 ET 7/11)
    out["gate1"] = {"day": round(max((_dt.datetime.now(_dt.timezone.utc) - t0).total_seconds()
                                     / 86400.0, 0), 1), "of": 7,
                    "crash_records": len(crashes),
                    "note": "a crash WITH a record is explained; silence + zero records = pass"}
    try:
        al = _BR / "data" / "alerts.jsonl"
        out["alerts_tail"] = al.read_text(encoding="utf-8").splitlines()[-5:] if al.exists() else []
    except Exception:
        out["alerts_tail"] = []
    return out
