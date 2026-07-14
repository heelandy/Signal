"""DECLINE/MASK OBSERVABILITY (F-NQ-ASIA-1 fix, 2026-07-14).

Three live events cost three forensic evenings because declined decisions were INVISIBLE:
the engine computes first-failing-gate reasons (collect_rejects) that no caller collected, and
the scan-level macro masks silenced raw fires with no trace. 'Evaluated and declined' must never
look like 'dead scanner'. Watch-only: declines inform, they never fire or trade."""
from __future__ import annotations

import numpy as np
import pytest

pd = pytest.importorskip("pandas")

from bot.strategy import families  # noqa: E402


def _frame(weak_break=True):
    """RTH day: OR spike high 20100, gentle sub-OR uptrend, then a crossing break whose body is
    deliberately WEAK (quality reject) — the engine must DECLINE it with a reason."""
    rows = []
    ts = pd.Timestamp("2026-07-14 09:30", tz="America/New_York")
    rows.append((ts, 20000.0, 20100.0, 19990.0, 20010.0, 1200.0)); ts += pd.Timedelta(minutes=5)
    px = 20010.0
    for _ in range(5):
        rows.append((ts, px, px + 8.0, px - 8.0, px + 2.0, 1000.0)); px += 2.0
        ts += pd.Timedelta(minutes=5)
    for i in range(32):
        o = px; c = px + 3.0; h = c + 3.0; l = o - 3.0
        if i % 10 == 9:
            c = o - 8.0; h = o + 1.0; l = c - 8.0
        rows.append((ts, o, h, l, c, 1000.0)); px = c; ts += pd.Timedelta(minutes=5)
    o = 20092.0; c = 20120.0
    frac = 0.10 if weak_break else 0.80                     # 10% body = wick_or_weak_body reject
    full = (c - o) / frac
    h = c + (full - (c - o)) * 0.4; l = o - (full - (c - o)) * 0.6
    rows.append((ts, o, max(h, c), min(l, o), c, 2000.0))
    df = pd.DataFrame(rows, columns=["ts_et", "open", "high", "low", "close", "volume"])
    df["ts_et"] = df["ts_et"].astype(str)
    return df


def test_engine_decline_is_captured_with_its_reason(monkeypatch):
    monkeypatch.setattr(families, "_macro_daily", lambda: None)     # permissive macro, no network
    declines: list = []
    families.scan(_frame(), "NQ", bars_back=6, declines_out=declines)
    eng = [d for d in declines if d["kind"] == "engine"]
    assert eng, f"a weak-body crossing break must surface an ENGINE decline (got {declines})"
    assert any("body" in d["reason"] or "wick" in d["reason"] for d in eng), eng
    assert all(d["symbol"] == "NQ" and d["side"] in ("long", "short") and d["ts"] for d in eng)


def test_mask_reasons_are_specific():
    assert "regime" in families._mask_reason(False, True, True, "long").lower()
    assert "chop" in families._mask_reason(True, False, True, "long").lower()
    assert "short" in families._mask_reason(True, True, False, "short").lower()


def test_signals_endpoint_serves_declines(monkeypatch):
    from fastapi.testclient import TestClient
    import bot.api.server as srv
    monkeypatch.setitem(srv._latest, "declines",
                        [{"symbol": "NQ", "side": "short", "ts": "2026-07-13 20:50",
                          "kind": "mask", "reason": "SPY-directional stand-down blocks shorts"}])
    r = TestClient(srv.app).get("/api/signals").json()
    assert r.get("declines"), "the console must SEE what was declined — never a dead-scanner look"
    assert r["declines"][0]["reason"].startswith("SPY-directional")
