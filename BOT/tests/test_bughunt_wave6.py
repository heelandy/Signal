"""BUG HUNT — Wave 6 (API/UI contract sweep).

W6.1  path-traversal on the report endpoint is refused (armor — load_report resolves + parent-checks).
W6.2  when API_REQUIRE_AUTH is on, a MUTATING endpoint without a token is 401 (Depends(auth) short-
      circuits BEFORE the body, so no side effect); arming the kill switch stays open (safety is
      always armable).
W6.3  the read-only console/dashboard GET endpoints return clean JSON and never leak a raw
      Python traceback into the response body.
"""
from __future__ import annotations

import pytest

pd = pytest.importorskip("pandas")

from fastapi.testclient import TestClient  # noqa: E402

import bot.api.server as srv  # noqa: E402


@pytest.fixture()
def client():
    srv._state["kill_switch"] = False
    srv._ready_cache.update(ts=0.0, out=None)
    yield TestClient(srv.app, raise_server_exceptions=False)
    srv._state["kill_switch"] = False
    srv._ready_cache.update(ts=0.0, out=None)


def test_w6_report_endpoint_refuses_path_traversal(client):
    for evil in ("../../../../etc/passwd", "..%2f..%2fsecret", "../config/server", "..\\..\\secret"):
        r = client.get("/api/training/report", params={"name": evil})
        assert r.status_code == 200, (evil, r.status_code)
        body = r.json()
        assert body == {"error": "not found"} or "error" in body, (
            f"path traversal must resolve to not-found, got {body!r} for {evil!r}")


def test_w6_auth_gate_blocks_mutations_but_leaves_safety_armable(client, monkeypatch):
    monkeypatch.setattr(srv, "_REQUIRE_AUTH", True)
    # a mutating endpoint without a token -> 401 (short-circuits before any broker/state write)
    assert client.post("/api/flatten").status_code == 401
    assert client.post("/api/control/paper_autotrade", params={"on": 1}).status_code == 401
    assert client.post("/api/control/kill", params={"on": 0}).status_code == 401, "DISARM needs a token"
    # arming the kill switch (turning SAFETY ON) must stay open even under auth
    assert client.post("/api/control/kill", params={"on": 1}).status_code == 200, "arming safety must never need a token"


import inspect  # noqa: E402


def _all_get_routes():
    """Every GET /api route + the safe query/path params for the few that require them."""
    defaults = {"symbol": "QQQ", "spot": "100", "name": "does-not-exist", "sym": "QQQ"}
    out = []
    for r in srv.app.routes:
        if "GET" not in (getattr(r, "methods", None) or set()):
            continue
        path = getattr(r, "path", "")
        if not path.startswith("/api"):
            continue
        params = {}
        fn = getattr(r, "endpoint", None)
        if fn:
            for n, p in inspect.signature(fn).parameters.items():
                if p.default is inspect._empty and n not in ("request",):
                    params[n] = defaults.get(n, "1")
        # fill path params like /api/foo/{name}
        for seg in path.split("/"):
            if seg.startswith("{") and seg.endswith("}"):
                key = seg[1:-1]
                path = path.replace(seg, defaults.get(key, "1"))
        out.append((path, params))
    return out


def test_w6_every_get_route_is_clean_no_traceback_bounded(client):
    """EXHAUSTIVE: hit ALL 62 GET /api routes. None may leak a raw Python traceback, none may
    return an unbounded payload, and none may 500 with a stack trace (a data-provider failure must
    be a clean error dict, not a crash)."""
    routes = _all_get_routes()
    assert len(routes) >= 60, f"route enumeration looks wrong: {len(routes)}"
    leaked, unbounded, crashed = [], [], []
    for path, params in routes:
        try:
            r = client.get(path, params=params)
        except Exception as e:                            # a GET must never raise out of the app
            crashed.append((path, f"raised {type(e).__name__}: {e}"))
            continue
        raw = r.text
        if "Traceback (most recent call last)" in raw:
            leaked.append(path)
        if len(raw) > 5_000_000:
            unbounded.append((path, len(raw)))
        if r.status_code >= 500 and "Traceback" in raw:
            crashed.append((path, r.status_code))
    assert not leaked, f"endpoints leaked a Python traceback: {leaked}"
    assert not unbounded, f"endpoints returned an unbounded payload: {unbounded}"
    assert not crashed, f"endpoints crashed with a stack trace: {crashed}"


# ── W6 adversarial render payloads (category 2) ──

def test_w6_adversarial_signal_payload_stays_valid_json(client, monkeypatch):
    """Inject NaN / inf / 1e308 / a 10KB string / RTL + zero-width unicode / an XSS attempt into a
    live signal and hit /api/signals. The response must be 200, STRICT-valid JSON (NaN/inf → null),
    and carry the hostile string safely encoded (JSON-escaped — the page's esc() finishes the job)."""
    import json
    hostile = {
        "symbol": "QQQ", "side": "long", "entry": float("nan"), "stop": float("inf"),
        "tp2": 1e308, "pwin": float("-inf"),
        "note": "‮RTL​zero-width " + "A" * 10_000,
        "reason": "<script>alert('xss')</script>",
    }
    srv._latest["signals"] = [hostile]
    srv._latest["ts"] = 1.0
    r = client.get("/api/signals")
    assert r.status_code == 200, r.status_code
    assert "application/json" in r.headers.get("content-type", "")
    body = json.loads(r.text)                              # strict parse: FAILS on bare NaN/Infinity
    sig = body["signals"][0]
    assert sig["entry"] is None and sig["stop"] is None and sig["pwin"] is None, sig
    # the hostile fields survive as JSON string VALUES (content-type is JSON, so never executable);
    # the client's esc() handles DOM insertion — verified separately by the headless-Edge drill
    assert sig["reason"] == "<script>alert('xss')</script>" and len(sig["note"]) > 10_000


def test_w6_json_safe_helper_replaces_non_finite():
    from bot.api.server import _json_safe
    out = _json_safe({"a": float("nan"), "b": [1.0, float("inf"), {"c": float("-inf")}], "d": "ok"})
    assert out == {"a": None, "b": [1.0, None, {"c": None}], "d": "ok"}
