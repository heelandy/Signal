"""BUG HUNT — pattern advisory subsystem (module + /api/patterns + summary).

Adversarial probes on the NEW advisory layer, same discipline as the main hunt:
  ADV1  the evidence gate can NEVER be bypassed — a non-actionable symbol must not PASS even if
        its evidence chip is (mis)marked CERTIFIED (defense against the EVIDENCE/ACTIONABLE lists
        drifting apart).
  ADV2  a malformed scan snapshot (non-dict entries, missing fields) must not crash the advisory.
  ADV3  NaN/inf / hostile fields in the snapshot must yield a valid, non-crashing endpoint response.
  ADV4  an adversarial ?sym= must return a clean empty advisory, never a 500.
"""
from __future__ import annotations

import json

import pytest

from bot.strategy import pattern_advisory as PA


def _prop(sym, side="long", state="active", grade="A", tradeable=True, **kw):
    p = {"symbol": sym, "side": side, "signal_state": state, "grade": grade, "tradeable": tradeable,
         "entry": 100.0, "stop": 99.0, "tp1": 101.5, "tp2": 104.0, "or_high": 100.0, "or_low": 98.0,
         "slope_S": 0.35, "clean_air": True, "air_atr": 2.8, "struct_aligned": True,
         "slope_grade": "A", "source_healthy": True, "session": "rth", "vol_expansion": False}
    p.update(kw)
    return p


def test_adv1_passes_implies_actionable_even_if_mismarked_certified(monkeypatch):
    """The pass gate must be robust to the EVIDENCE and ACTIONABLE lists diverging: a symbol NOT in
    ACTIONABLE must never PASS, even if someone marks its evidence CERTIFIED."""
    monkeypatch.setitem(PA.EVIDENCE, "TSLA", "CERTIFIED")     # rogue: certified but not actionable
    adv = PA.advisory_from_proposals("TSLA", [_prop("TSLA", state="active", tradeable=True)], "5m")
    assert adv["panels"][0]["passes"] is False, (
        "a non-ACTIONABLE symbol must NEVER pass the gate, even mismarked CERTIFIED")


@pytest.mark.parametrize("sym", ["NQ", "ES", "GC", "TSLA", "MNQ", ""])
def test_adv1b_non_certified_never_passes(sym):
    adv = PA.advisory_from_proposals(sym or "X", [_prop(sym or "X", state="active", tradeable=True)], "5m")
    assert adv["panels"][0]["passes"] is False, f"{sym!r} must never pass"


def test_adv2_malformed_proposals_do_not_crash():
    """A malformed scan snapshot (None / str / int entries, missing fields) must not crash the
    advisory — filter to real proposals and carry on."""
    props = [None, "garbage", 42, [], {"no_symbol": True},
             _prop("QQQ", state="active"), {"symbol": "QQQ"}]   # last: a dict missing most fields
    adv = PA.advisory_from_proposals("QQQ", props, "5m")        # must not raise
    assert any(p.get("symbol") == "QQQ" for p in adv["panels"])
    wl = PA.watchlist_advisory(props, ("QQQ", "NQ"), "5m")      # must not raise
    assert set(wl["summary"]) == {"advisories", "with_confluence", "passing"}


def test_adv2b_panel_survives_a_near_empty_proposal():
    adv = PA.advisory_from_proposals("QQQ", [{"symbol": "QQQ"}], "5m")   # only the symbol
    p = adv["panels"][0]
    assert p["symbol"] == "QQQ" and p["ml"] == "ABSTAIN"       # no crash; honesty fields intact
    assert p["passes"] in (True, False)


def test_adv3_endpoint_survives_nan_and_malformed_snapshot():
    from fastapi.testclient import TestClient
    import bot.api.server as srv
    srv._latest["signals"] = [None, "x", 7,
        _prop("QQQ", entry=float("nan"), stop=float("inf"), slope_S=float("-inf"), note="<script>x</script>")]
    c = TestClient(srv.app, raise_server_exceptions=False)
    r = c.get("/api/patterns")
    assert r.status_code == 200, r.status_code
    body = json.loads(r.text)                                  # STRICT parse: fails on bare NaN/inf
    assert "summary" in body and "symbols" in body


def test_adv4_endpoint_adversarial_sym_is_clean():
    from fastapi.testclient import TestClient
    import bot.api.server as srv
    srv._latest["signals"] = []
    c = TestClient(srv.app, raise_server_exceptions=False)
    for evil in ("../../x", "<script>", "'; DROP TABLE", "%00", "A" * 500):
        r = c.get("/api/patterns", params={"sym": evil})
        assert r.status_code == 200, (evil, r.status_code)
        body = json.loads(r.text)
        assert body["summary"]["passing"] == 0                 # an unknown symbol never passes
