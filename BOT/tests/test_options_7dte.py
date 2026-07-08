"""Regression tests for the 7DTE managed condor wiring + the audit fixes (F89, audit 2026-07-08).

Pins the bug classes found while wiring `condor_7dte`:
  E8  — routing: condor_7dte must build a CONDOR with its OWN geometry (not silently drift)
  O11 — a multi-day position settles ONLY at its stored expiry, and manage marks it (no false hold)
  O12 — manage_open uses the PER-STRUCTURE spec (7DTE tp=0.6), not one global spec
  O13 — the live signal carries the raw strikes so the manager can re-price it (no instant false TP)

None of these touch the real journal/open store — they monkeypatch the paths to a tmp dir.
"""
from __future__ import annotations

import numpy as np
import pytest

from bot.options import native as N
from bot.market_data import options_data as OD


def _decaying_book(spot=720.0, lo=690, hi=752):
    """A realistic chain: price decays with distance from spot, so OTM shorts collect real credit."""
    strikes = {"C": np.arange(lo, hi, 1.0), "P": np.arange(lo, hi, 1.0)}

    def q(cp, K):
        if K is None:
            return None
        d = abs(K - spot)
        mid = max(0.05, 3.0 * np.exp(-d / 6.0))
        return (round(mid * 0.97, 2), round(mid * 1.03, 2), round(mid, 2))
    return q, strikes


@pytest.fixture
def tmp_store(tmp_path, monkeypatch):
    """Point the sealed journal + open store at a tmp dir so tests never pollute the real one."""
    monkeypatch.setattr(N, "journal_path", lambda: tmp_path / "j.jsonl")
    monkeypatch.setattr(N, "open_path", lambda: tmp_path / "open.jsonl")
    return tmp_path


# --- E8: routing + spec decoupling ------------------------------------------------------------
def test_condor_7dte_routes_to_condor():
    q, strikes = _decaying_book()
    pos = N.build(720.0, 718.0, q, strikes, spec=N.spec_for("condor_7dte"), directional=False)
    assert pos is not None and pos["kind"] == "condor"      # not a one-sided spread, not None
    assert pos["wing"] == 5.0                                # SPEC_7DTE wing, not the 0DTE 6
    assert pos["ksc"] is not None and pos["ksp"] is not None  # both sides -> a real condor


def test_spec_7dte_decoupled_from_0dte_spec():
    assert N.spec_for("condor_7dte")["em_mult"] == 1.0 and N.spec_for("condor_7dte")["wing"] == 5
    assert N.SPEC["em_mult"] == 1.1 and N.SPEC["wing"] == 6   # tuning 7DTE never moved the 0DTE spec


# --- O13: the live signal carries the raw strikes (no instant false TP) -----------------------
def test_live_signal_carries_strikes(monkeypatch):
    q, strikes = _decaying_book()
    book = {(cp, float(K)): q(cp, K) for cp in ("C", "P") for K in strikes[cp]}
    monkeypatch.setattr(OD, "alpaca_chain_dte", lambda *a, **k: {
        "ok": True, "expiry": "2026-07-15", "dte": 7, "book": book, "strikes": strikes, "n": len(book)})
    sig = N.live_signal_from_alpaca("QQQ", spot=720.0, structure="condor_7dte", dte=7)
    assert not sig.get("error")
    # the four strikes MUST survive describe() (which only emits `legs`) for the manager to work
    for k in ("ksc", "klc", "ksp", "klp"):
        assert sig.get(k) is not None, f"{k} dropped -> manager would mark None legs -> false TP"


# --- O12 / O13: management reconstructs the position and uses the 7DTE tp --------------------
def _open_condor_7dte(tmp_store):
    q, strikes = _decaying_book()
    pos = N.build(720.0, 718.0, q, strikes, spec=N.spec_for("condor_7dte"), directional=False)
    sig = dict(pos, priced_from="alpaca_live", expiry="2026-07-15", structure="condor_7dte")
    row = N.open_position(sig, "2026-07-08", "7d", "condor_7dte")
    assert row is not None
    return pos["credit"]


def test_manage_no_false_tp_when_no_profit(tmp_store):
    credit = _open_condor_7dte(tmp_store)
    closed = N.manage_open(lambda r: credit, lambda d: None, now_hm=700)   # cost==credit -> pnl 0
    assert closed == [] and len(N.load_open()) == 1        # stays open, NOT a false TP


def test_manage_tp_at_7dte_spec(tmp_store):
    credit = _open_condor_7dte(tmp_store)
    # cost leaves pnl_now = 0.6*credit exactly -> TP must fire at the 7DTE spec's tp (0.6)
    closed = N.manage_open(lambda r: credit * 0.4, lambda d: None, now_hm=700)
    assert len(closed) == 1 and closed[0]["exit"] == "tp"
    assert closed[0]["ret"] == pytest.approx(0.6 * credit / closed[0]["max_loss"], abs=2e-3)


def test_manage_tp_override_ignores_global_spec(tmp_store):
    credit = _open_condor_7dte(tmp_store)
    # pass a global spec with tp=0.9; the 7DTE position must STILL tp at its own 0.6 (per-structure)
    closed = N.manage_open(lambda r: credit * 0.4, lambda d: None,
                           spec=dict(N.SPEC, tp=0.9), now_hm=700)
    assert len(closed) == 1 and closed[0]["exit"] == "tp"   # 0.6 hit even though global tp=0.9


# --- O11: a 7DTE position settles ONLY at its stored expiry ----------------------------------
def test_manage_holds_until_stored_expiry(tmp_store):
    _open_condor_7dte(tmp_store)
    # end-of-day, but the expiry (2026-07-15) is in the future -> settle_close returns None -> hold
    closed = N.manage_open(lambda r: None, lambda d: None, now_hm=960)
    assert closed == [] and len(N.load_open()) == 1        # future expiry must NOT settle early (O7/O11)


# --- D2: the DTE gate uses the ET market date and honours the tolerance ----------------------
def test_chain_book_dte_gate_and_tolerance():
    rows = [{"expiry": e, "cp": cp, "strike": float(k), "bid": 1.0, "ask": 1.1, "mid": 1.05}
            for e in ("2026-07-08", "2026-07-15", "2026-07-22")
            for cp in ("C", "P") for k in range(715, 726)]
    g = OD._chain_book_dte(rows, 7, spot=720.0, today="2026-07-08")
    assert g["ok"] and g["expiry"] == "2026-07-15" and g["dte"] == 7
    bad = OD._chain_book_dte(rows, 30, today="2026-07-08")   # nothing within tol of 30d
    assert not bad["ok"] and "no expiry near" in bad["error"]
