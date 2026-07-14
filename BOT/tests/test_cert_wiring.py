"""CERTIFICATE WIRING (completion-order steps 8/9, 2026-07-14) — the integration gap closes.

The audit's central finding: certify_and_fire existed with ZERO production callers — the console
computed ACTION: ENTER client-side from `tradeable` alone. Now: the SCAN certifies every tradeable
signal (9 gates), the proposal carries the BACKEND action + certificate, paper autotrade requires
action == ENTER (the one door), and certificates persist/alert on VERDICT TRANSITIONS only."""
from __future__ import annotations

import sqlite3
from types import SimpleNamespace

import pytest

pd = pytest.importorskip("pandas")

from bot.contracts import RiskDecision, RiskStatus, ReasonCode, TradeCandidate  # noqa: E402
from bot import live as L  # noqa: E402
from bot import signal_certificate as SC  # noqa: E402


def _cand(sym="QQQ"):
    from bot.strategy.orb_candidates import STRATEGY_VERSION
    return TradeCandidate(symbol=sym, side="long", timeframe="5m", setup="orb_stack",
                          entry=100.0, stop=99.0, tp2=104.0, strategy_version=STRATEGY_VERSION,
                          candidate_id=f"C-{sym}")


def _rd():
    return RiskDecision(candidate_id="C-QQQ", status=RiskStatus.APPROVED, reason_code=ReasonCode.OK,
                        max_qty=10, max_risk_dollars=250.0)


def _sig(sym="QQQ", tradeable=True, state="active", bars_ago=1):
    return {"symbol": sym, "side": "long", "family": "breakout", "session": "rth", "tf": "5m",
            "tradeable": tradeable, "signal_state": state, "bars_ago": bars_ago,
            "pit_features": {"x": 1.0}, "candidate": {"generated_at": "2026-07-14T14:35:00+00:00"}}


@pytest.fixture(autouse=True)
def _iso(tmp_path, monkeypatch):
    monkeypatch.setattr(SC, "CERT_DB", tmp_path / "certs.db")
    L._CERT_STATE.clear()
    monkeypatch.setattr(L, "_data_qa_ok", lambda sym: True)      # green QA for the unit
    yield


def test_all_green_equity_signal_is_backend_enter():
    action, cert = L._certify_signal(_cand(), _sig(), _rd(), conf=0.6, src="webull",
                                     healthy=True, age_min=1, removed=None)
    assert action == "ENTER", (action, cert)
    assert cert["overall"] == "ORDER_READY" and cert["hash"]


def test_context_symbol_is_never_enter():
    """NQ is CONTEXT (profitability not certified) — the certificate must refuse ENTER."""
    action, cert = L._certify_signal(_cand("NQ"), _sig("NQ"), _rd(), conf=0.6, src="yahoo",
                                     healthy=True, age_min=1, removed=None)
    assert action == "DO NOT ENTER"
    assert "profitability" in cert["blocking"], cert


def test_forming_bar_blocks_causality():
    action, cert = L._certify_signal(_cand(), _sig(bars_ago=0), _rd(), conf=0.6, src="webull",
                                     healthy=True, age_min=1, removed=None)
    assert action == "DO NOT ENTER" and "causality" in cert["blocking"], cert


def test_certificate_persists_on_transition_only():
    for _ in range(3):                                           # same verdict 3 cycles
        L._certify_signal(_cand(), _sig(), _rd(), conf=0.6, src="webull",
                          healthy=True, age_min=1, removed=None)
    con = sqlite3.connect(str(SC.CERT_DB))
    n = con.execute("SELECT count(*) FROM certificates").fetchone()[0]
    con.close()
    assert n == 1, f"one verdict = one persisted certificate (got {n} — a 60s-cycle spam bug)"


def test_autotrade_requires_backend_enter(monkeypatch):
    """The one door: a tradeable grade-A signal WITHOUT action=ENTER must never submit."""
    import bot.api.server as srv
    submitted = []
    svc = SimpleNamespace(submit=lambda *a, **k: submitted.append(a) or
                          SimpleNamespace(action="submitted", reason="", to_dict=lambda: {}))
    monkeypatch.setattr(srv, "_exec_service", lambda: svc)
    monkeypatch.setattr(srv, "_paper_broker",
                        lambda: SimpleNamespace(is_market_open=lambda: True))
    monkeypatch.setattr(srv, "settings",
                        SimpleNamespace(alpaca_paper=True, alpaca_key_id="k", alpaca_secret="s"))
    srv._state["paper_autotrade"] = True
    base = {"symbol": "QQQ", "side": "long", "family": "breakout", "grade": "A",
            "tradeable": True, "signal_state": "active", "entry": 100.0, "stop": 99.0,
            "tp2": 104.0, "tf": "5m", "candidate_id": "C1"}
    srv._latest["signals"] = [dict(base, action="DO NOT ENTER"),          # cert blocked
                              dict(base, candidate_id="C2")]              # no action field at all
    srv._paper_autotrade()
    assert not submitted, "without a backend ENTER the door must stay shut"
    srv._latest["signals"] = [dict(base, action="ENTER",
                                   certificate={"overall": "ORDER_READY", "hash": "h"})]
    srv._paper_autotrade()
    assert submitted, "an ENTER-certified signal must pass the door"
    srv._state["paper_autotrade"] = False
