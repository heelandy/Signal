"""PATTERN ADVISORY tests — the honesty gate (advisory-only, corrected evidence).

The advisory re-presents live scan proposals as the pattern panel. These tests pin the invariants
that keep it SAFE: NQ can never read ACTION (CONTEXT/UNPROVEN), QQQ/SPY read CERTIFIED, the form is
per-asset, ML always ABSTAINs, and a missing/unhealthy read degrades to UNKNOWN/WAIT — never green.
"""
from __future__ import annotations

import pytest

from bot.strategy import pattern_advisory as PA


def _prop(sym, side="long", state="active", grade="A", tradeable=True, **kw):
    p = {"symbol": sym, "side": side, "signal_state": state, "grade": grade, "tradeable": tradeable,
         "entry": 100.0, "stop": 99.0, "tp1": 101.5, "tp2": 104.0, "or_high": 100.0, "or_low": 98.0,
         "slope_S": 0.35, "clean_air": True, "air_atr": 2.8, "struct_aligned": True,
         "slope_grade": "A", "source_healthy": True, "session": "rth", "vol_expansion": False}
    p.update(kw)
    return p


def test_nq_is_context_never_action():
    adv = PA.advisory_from_proposals("NQ", [_prop("NQ", state="active", grade="A")], "5m")
    assert adv["header"]["evidence"] == "CONTEXT" and adv["header"]["actionable"] is False
    panel = adv["panels"][0]
    assert "CONTEXT" in panel["evidence"] and "WATCH ONLY" in panel["action"], panel
    assert "ENTER" not in panel["action"].upper(), "NQ (CONTEXT) must NEVER surface an ENTER prompt"
    assert panel["pattern"].startswith("ORB-C+RT"), panel["pattern"]      # NQ = retest form
    assert panel["ml"] == "ABSTAIN"


def test_qqq_is_certified_and_can_enter():
    adv = PA.advisory_from_proposals("QQQ", [_prop("QQQ", state="active", grade="A+")], "5m")
    assert adv["header"]["evidence"] == "CERTIFIED" and adv["header"]["actionable"] is True
    panel = adv["panels"][0]
    assert "CERTIFIED" in panel["evidence"]
    assert panel["pattern"].startswith("ORB-C ")                          # equity = continuation form
    assert "enter" in panel["action"].lower() or "READY" in panel["action"], panel
    assert panel["ml"] == "ABSTAIN", "even a certified asset abstains until pattern-specific ML exists"


def test_gc_unverified_es_unproven_never_action():
    for sym, ev in (("GC", "UNVERIFIED"), ("ES", "UNPROVEN")):
        adv = PA.advisory_from_proposals(sym, [_prop(sym, state="active", grade="A")], "15m")
        assert adv["header"]["evidence"] == ev
        assert "WATCH ONLY" in adv["panels"][0]["action"], sym


def test_removed_group_is_blocked_even_if_certified():
    adv = PA.advisory_from_proposals("QQQ", [_prop("QQQ", removed={"reason": "cohort loss"})], "5m")
    p = adv["panels"][0]
    assert "BLOCKED" in p["state"] and "BLOCKED" in p["action"], p


def test_day_type_from_slope_and_expansion():
    assert PA._day_type(_prop("NQ", slope_S=0.35)) == "TREND UP (strong)"
    assert PA._day_type(_prop("NQ", slope_S=-0.15)) == "TREND DOWN"
    assert PA._day_type(_prop("NQ", slope_S=0.02)) == "RANGE / BALANCE"
    assert PA._day_type(_prop("NQ", vol_expansion=True)) == "VOLATILITY EXPANSION"
    assert PA._day_type(_prop("NQ", source_healthy=False)).startswith("UNKNOWN")
    assert PA._day_type({"slope_S": None}) == "UNKNOWN"                   # missing data -> UNKNOWN, never green


def test_no_proposal_degrades_to_wait_not_green():
    adv = PA.advisory_from_proposals("NQ", [], "5m")
    p = adv["panels"][0]
    assert p["state"] == "WAIT" and adv["header"]["day_type"] == "UNKNOWN"
    assert "ENTER" not in p.get("action", "").upper()


def test_wall_overhead_shows_in_location_and_confluence():
    adv = PA.advisory_from_proposals("QQQ", [_prop("QQQ", clean_air=False, air_atr=1.1)], "5m")
    p = adv["panels"][0]
    assert "WALL" in p["location"] and "WALL overhead" in p["confluence"]


def test_render_is_stringy_and_marks_advisory():
    adv = PA.advisory_from_proposals("NQ", [_prop("NQ")], "5m")
    txt = PA.render(adv)
    assert "advisory only" in txt and "ML: ABSTAIN" in txt and "CONTEXT" in txt


def test_passes_gate_only_certified_actionable():
    qqq = PA.advisory_from_proposals("QQQ", [_prop("QQQ", state="active", tradeable=True)], "5m")
    assert qqq["panels"][0]["passes"] is True, "certified + active + tradeable must PASS"
    nq = PA.advisory_from_proposals("NQ", [_prop("NQ", state="active", tradeable=True)], "5m")
    assert nq["panels"][0]["passes"] is False, "NQ (CONTEXT) can NEVER pass"
    skip = PA.advisory_from_proposals("QQQ", [_prop("QQQ", state="active", skip_reco=True)], "5m")
    assert skip["panels"][0]["passes"] is False, "a skip-reco (grade C / wall) must not pass"


def test_has_confluence_flag():
    with_c = PA.advisory_from_proposals("QQQ", [_prop("QQQ", struct_aligned=True, clean_air=True)], "5m")
    assert with_c["panels"][0]["has_confluence"] is True
    bare = PA.advisory_from_proposals("QQQ", [_prop("QQQ", struct_aligned=False, clean_air=None,
                                                     slope_grade=None, vol_expansion=False, tranche="full")], "5m")
    assert bare["panels"][0]["has_confluence"] is False


def test_watchlist_summary_counts_confluence_and_pass():
    props = [_prop("QQQ", state="active", grade="A", tradeable=True, struct_aligned=True),  # passes + confluence
             _prop("SPY", state="watch", grade="B", tradeable=True, clean_air=None,
                   struct_aligned=False, slope_grade=None, vol_expansion=False, tranche="full"),  # passes, no confluence
             _prop("NQ", state="active", grade="A", tradeable=True, struct_aligned=True)]        # confluence, never passes
    wl = PA.watchlist_advisory(props, ("QQQ", "SPY", "NQ"), "5m")
    s = wl["summary"]
    assert s["advisories"] == 3, s
    assert s["with_confluence"] == 2, s           # QQQ + NQ show confluence
    assert s["passing"] == 2, s                   # QQQ + SPY pass; NQ (CONTEXT) never does


def test_watchlist_wait_symbols_do_not_count():
    wl = PA.watchlist_advisory([], ("QQQ", "NQ"), "5m")   # no proposals -> all WAIT placeholders
    assert wl["summary"] == {"advisories": 0, "with_confluence": 0, "passing": 0}
