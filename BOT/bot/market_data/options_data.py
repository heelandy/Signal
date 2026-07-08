"""LIVE OPTIONS-DATA providers — Alpaca vs Webull, with a STABILITY TEST (user 2026-07-08).

The options-native strategy (F86) and the Selected-Contract panel need a REAL options feed (a BS
proxy is validated-insufficient). Two candidates:

  • ALPACA  — https://docs.alpaca.markets/us/docs/historical-option-data — OPRA snapshots/quotes via
              alpaca-py's OptionHistoricalDataClient. Uses the SAME keys as trading (env-ready).
  • WEBULL  — options chain via the Webull OpenAPI DataClient (settings.require_webull).

`stability_test()` calls each provider repeatedly and reports success rate, latency, and quote
coverage so the more stable one can be chosen. Env-ready: no keys -> that provider reports
"unavailable" (which is itself the stability signal), never a crash.

    python -m bot.market_data.options_data QQQ         # run the head-to-head stability test
Report -> BOT/data/ml/reports/options_data_stability.json
"""
from __future__ import annotations

import json
import time
from pathlib import Path

from bot.config import BOT_ROOT, settings

REPORT = BOT_ROOT / "data" / "ml" / "reports" / "options_data_stability.json"


def alpaca_snapshot(underlying: str = "QQQ") -> dict:
    """Latest ATM-ish option quotes for `underlying` from Alpaca OPRA. Returns
    {ok, latency_ms, n_quotes, two_sided_pct, sample, error}."""
    t0 = time.time()
    try:
        key, secret = settings.require_alpaca()
    except Exception as e:
        return {"ok": False, "error": f"alpaca keys unset: {str(e)[:80]}", "latency_ms": 0}
    try:
        from alpaca.data.historical.option import OptionHistoricalDataClient
        from alpaca.data.requests import OptionChainRequest
        cli = OptionHistoricalDataClient(key, secret)
        chain = cli.get_option_chain(OptionChainRequest(underlying_symbol=underlying))
        lat = int((time.time() - t0) * 1000)
        rows = list(chain.values()) if hasattr(chain, "values") else list(chain)
        n = len(rows)
        two = 0
        sample = None
        for r in rows:
            q = getattr(r, "latest_quote", None)
            if q and getattr(q, "bid_price", 0) and getattr(q, "ask_price", 0):
                two += 1
                if sample is None:
                    sample = {"bid": float(q.bid_price), "ask": float(q.ask_price)}
        return {"ok": n > 0, "latency_ms": lat, "n_quotes": n,
                "two_sided_pct": round(100 * two / n, 1) if n else 0.0, "sample": sample}
    except Exception as e:
        return {"ok": False, "error": f"{type(e).__name__}: {str(e)[:120]}",
                "latency_ms": int((time.time() - t0) * 1000)}


def webull_snapshot(underlying: str = "QQQ") -> dict:
    """Latest option chain for `underlying` from the Webull OpenAPI DataClient."""
    t0 = time.time()
    try:
        settings.require_webull()
    except Exception as e:
        return {"ok": False, "error": f"webull keys unset: {str(e)[:80]}", "latency_ms": 0}
    try:
        from webull.data.data_client import DataClient  # noqa: F401
        from bot.market_data.providers import _webull_client
        cli = _webull_client()
        fn = None
        for name in ("get_option_chain", "get_options", "option_chain", "get_option"):
            fn = getattr(cli, name, None)
            if fn:
                break
        if fn is None:
            return {"ok": False, "error": "webull DataClient exposes no option-chain method",
                    "latency_ms": int((time.time() - t0) * 1000)}
        res = fn(underlying)
        lat = int((time.time() - t0) * 1000)
        from bot.market_data.providers import _webull_rows
        rows = _webull_rows(res) or []
        return {"ok": bool(rows), "latency_ms": lat, "n_quotes": len(rows), "two_sided_pct": None,
                "sample": str(rows[0])[:120] if rows else None}
    except Exception as e:
        return {"ok": False, "error": f"{type(e).__name__}: {str(e)[:120]}",
                "latency_ms": int((time.time() - t0) * 1000)}


def alpaca_chain_0dte(underlying: str = "QQQ", spot: float | None = None,
                      spot_pct: float = 0.08, require_0dte: bool = True) -> dict:
    """LIVE 0DTE chain from Alpaca for `underlying`: returns {ok, expiry, book, strikes, error}
    where book={(cp,strike):(bid,ask,mid)} and strikes={'C':[...],'P':[...]} — the exact shape
    bot.options.native.build expects. This is the real options feed the options-native strategy
    (F86) needs. 0DTE = the nearest expiry present; strikes within +-spot_pct of `spot` (the REAL
    underlying price; falls back to the chain center only if spot is None)."""
    import re
    try:
        key, secret = settings.require_alpaca()
        from alpaca.data.historical.option import OptionHistoricalDataClient
        from alpaca.data.requests import OptionChainRequest
        cli = OptionHistoricalDataClient(key, secret)
        chain = cli.get_option_chain(OptionChainRequest(underlying_symbol=underlying))
    except Exception as e:
        return {"ok": False, "error": f"{type(e).__name__}: {str(e)[:120]}"}
    # parse OSI right-anchored (Alpaca roots are NOT space-padded): ...YYMMDD C/P STRIKE(8 millis)
    rows = []
    occ = re.compile(r"(\d{6})([CP])(\d{8})$")
    for osi, snap in (chain.items() if hasattr(chain, "items") else []):
        m = occ.search(str(osi))
        q = getattr(snap, "latest_quote", None)
        if not m or not q or not getattr(q, "bid_price", 0) or not getattr(q, "ask_price", 0):
            continue
        yy, mm, dd = m.group(1)[:2], m.group(1)[2:4], m.group(1)[4:6]
        rows.append({"expiry": f"20{yy}-{mm}-{dd}", "cp": m.group(2),
                     "strike": int(m.group(3)) / 1000.0,
                     "bid": float(q.bid_price), "ask": float(q.ask_price),
                     "mid": (float(q.bid_price) + float(q.ask_price)) / 2.0})
    return _chain_book(rows, spot=spot, spot_pct=spot_pct, require_0dte=require_0dte)


def _et_today() -> str:
    """Today's date in US/Eastern (the market tz), NOT the server's local wall clock — so the
    0DTE/DTE gate can't pick an expiry a day off near local midnight (D2 timezone class)."""
    try:
        from datetime import datetime
        from zoneinfo import ZoneInfo
        return datetime.now(ZoneInfo("America/New_York")).strftime("%Y-%m-%d")
    except Exception:
        from datetime import date
        return str(date.today())


def alpaca_chain_dte(underlying: str = "QQQ", target_dte: int = 7, spot: float | None = None,
                     spot_pct: float = 0.12, tol_days: int = 3) -> dict:
    """LIVE chain for the expiry nearest `target_dte` calendar days out (the F89 7DTE condor feed).
    Same {ok, expiry, dte, book, strikes, n} shape as alpaca_chain_0dte, but gated to an expiry
    within `tol_days` of the target rather than 0DTE. `spot_pct` is wider (0.12) because a multi-day
    expected move is larger than 0DTE — the condor's short strikes sit further out."""
    import re
    try:
        key, secret = settings.require_alpaca()
        from alpaca.data.historical.option import OptionHistoricalDataClient
        from alpaca.data.requests import OptionChainRequest
        cli = OptionHistoricalDataClient(key, secret)
        chain = cli.get_option_chain(OptionChainRequest(underlying_symbol=underlying))
    except Exception as e:
        return {"ok": False, "error": f"{type(e).__name__}: {str(e)[:120]}"}
    rows = []
    occ = re.compile(r"(\d{6})([CP])(\d{8})$")
    for osi, snap in (chain.items() if hasattr(chain, "items") else []):
        m = occ.search(str(osi))
        q = getattr(snap, "latest_quote", None)
        if not m or not q or not getattr(q, "bid_price", 0) or not getattr(q, "ask_price", 0):
            continue
        yy, mm, dd = m.group(1)[:2], m.group(1)[2:4], m.group(1)[4:6]
        rows.append({"expiry": f"20{yy}-{mm}-{dd}", "cp": m.group(2),
                     "strike": int(m.group(3)) / 1000.0,
                     "bid": float(q.bid_price), "ask": float(q.ask_price),
                     "mid": (float(q.bid_price) + float(q.ask_price)) / 2.0})
    return _chain_book_dte(rows, target_dte, spot=spot, spot_pct=spot_pct, tol_days=tol_days)


def _chain_book_dte(rows: list[dict], target_dte: int, spot: float | None = None,
                    spot_pct: float = 0.12, tol_days: int = 3, today: str | None = None) -> dict:
    """Gate parsed chain `rows` to the expiry nearest `target_dte` days out (within tol_days) and
    build the {ok, expiry, dte, book, strikes, n} shape build() expects. Split out so the DTE gate
    is unit-testable without a live feed. `today` defaults to date.today() (override in tests)."""
    from datetime import date
    import numpy as np
    today = today or _et_today()                             # D2: ET market date, not server local
    if not rows:
        return {"ok": False, "error": "no two-sided quotes in chain"}
    td = date.fromisoformat(today)
    exps = sorted({r["expiry"] for r in rows})
    def _dte(e: str) -> int:
        return (date.fromisoformat(e) - td).days
    exp = min(exps, key=lambda e: abs(_dte(e) - target_dte))
    if abs(_dte(exp) - target_dte) > tol_days:
        return {"ok": False, "error": f"no expiry near {target_dte}DTE (nearest {exp}, {_dte(exp)}d)",
                "is_0dte": False}
    day = [r for r in rows if r["expiry"] == exp]
    if spot is None:                                          # real spot preferred; center is a fallback
        strikes_all = sorted({r["strike"] for r in day})
        spot = strikes_all[len(strikes_all) // 2]
    lo, hi = spot * (1 - spot_pct), spot * (1 + spot_pct)
    day = [r for r in day if lo <= r["strike"] <= hi]
    book = {(r["cp"], r["strike"]): (r["bid"], r["ask"], r["mid"]) for r in day}
    strikes = {cp: np.array(sorted({r["strike"] for r in day if r["cp"] == cp})) for cp in ("C", "P")}
    return {"ok": True, "expiry": exp, "dte": _dte(exp), "is_0dte": _dte(exp) == 0,
            "book": book, "strikes": strikes, "n": len(day)}


def _chain_book(rows: list[dict], spot: float | None = None, spot_pct: float = 0.08,
                require_0dte: bool = True, today: str | None = None) -> dict:
    """Gate parsed chain `rows` to the nearest expiry and build the {ok, expiry, is_0dte, book,
    strikes, n} shape bot.options.native.build expects. Split out of alpaca_chain_0dte so the
    0-DAY gate is unit-testable without a live feed. `rows`: [{expiry 'YYYY-MM-DD', cp, strike,
    bid, ask, mid}, ...]. `today` defaults to the ET market date (override only in tests)."""
    today = today or _et_today()                             # D2: ET market date, not server local
    if not rows:
        return {"ok": False, "error": "no two-sided quotes in chain"}
    exp0 = min(r["expiry"] for r in rows)                     # nearest expiry
    # 0-DAY ERROR FIX (audit 2026-07-08): the strategy settles at TODAY's close, so it must only
    # trade a TRUE 0DTE (expiry == today). On a day with no same-day expiry the nearest is 1-2 DTE
    # and force-settling it at today's intrinsic is wrong — refuse rather than misprice.
    if require_0dte and exp0 != today:
        return {"ok": False, "error": f"no 0DTE expiry today (nearest {exp0})", "is_0dte": False}
    day = [r for r in rows if r["expiry"] == exp0]
    if spot is None:                                          # real spot preferred; center is a fallback
        strikes_all = sorted({r["strike"] for r in day})
        spot = strikes_all[len(strikes_all) // 2]
    lo, hi = spot * (1 - spot_pct), spot * (1 + spot_pct)
    day = [r for r in day if lo <= r["strike"] <= hi]
    book = {(r["cp"], r["strike"]): (r["bid"], r["ask"], r["mid"]) for r in day}
    import numpy as np
    strikes = {cp: np.array(sorted({r["strike"] for r in day if r["cp"] == cp})) for cp in ("C", "P")}
    return {"ok": True, "expiry": exp0, "is_0dte": exp0 == today,
            "book": book, "strikes": strikes, "n": len(day)}


def stability_test(underlying: str = "QQQ", n: int = 5, gap_s: float = 1.0) -> dict:
    """Call each provider n times; report success rate, median latency, coverage. More stable =
    higher success rate + lower latency variance + two-sided coverage."""
    import statistics as st
    out = {"underlying": underlying, "calls": n, "providers": {}}
    for name, fn in (("alpaca", alpaca_snapshot), ("webull", webull_snapshot)):
        runs = []
        for _ in range(n):
            runs.append(fn(underlying))
            time.sleep(gap_s)
        oks = [r for r in runs if r.get("ok")]
        lats = [r["latency_ms"] for r in runs if r.get("latency_ms")]
        out["providers"][name] = {
            "success_rate": round(len(oks) / n, 2),
            "median_latency_ms": int(st.median(lats)) if lats else None,
            "latency_stdev_ms": int(st.pstdev(lats)) if len(lats) > 1 else 0,
            "avg_quotes": round(sum(r.get("n_quotes", 0) for r in oks) / len(oks), 0) if oks else 0,
            "two_sided_pct": next((r.get("two_sided_pct") for r in oks if r.get("two_sided_pct")), None),
            "last_error": next((r.get("error") for r in runs if r.get("error")), None)}
    a, w = out["providers"]["alpaca"], out["providers"]["webull"]

    def score(p):                                   # success first, then latency, then coverage
        return (p["success_rate"], -(p["median_latency_ms"] or 9e9), p["avg_quotes"])
    if a["success_rate"] == 0 and w["success_rate"] == 0:
        out["recommendation"] = "NEITHER reachable — check entitlements/keys (errors above)"
    else:
        out["recommendation"] = "alpaca" if score(a) >= score(w) else "webull"
    return out


if __name__ == "__main__":
    import sys
    for s in (sys.stdout, sys.stderr):
        try:
            s.reconfigure(encoding="utf-8", errors="backslashreplace")
        except Exception:
            pass
    sym = sys.argv[1] if len(sys.argv) > 1 else "QQQ"
    rep = stability_test(sym, n=int(sys.argv[2]) if len(sys.argv) > 2 else 5)
    REPORT.parent.mkdir(parents=True, exist_ok=True)
    REPORT.write_text(json.dumps(rep, indent=2), encoding="utf-8")
    print(json.dumps(rep, indent=2))
    print("recommendation:", rep["recommendation"], "-> report", REPORT)
