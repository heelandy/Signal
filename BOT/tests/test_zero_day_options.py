"""Regression tests for THE 0-DAY ERROR class — O7/O9/O10 in docs/BUGS_AND_FAILURE_MODES.md.

The bugs doc is "the checklist to run against before shipping any change", but the 0-day guards
had no automated test. These pin the P&L-affecting ones so a future edit (or a stale server, R1)
can't silently reintroduce them.

  O7  a non-0DTE position must NEVER be priced/settled as if it expires TODAY:
        · the live-chain gate (`_chain_book`, split out of `alpaca_chain_0dte`) REFUSES when the
          nearest expiry != today — on a day with no same-day expiry the nearest is 1-2 DTE and
          settling it at today's intrinsic is wrong.
        · `manage_open` settles ONLY at the position's STORED expiry close (via settle_close_fn),
          never an earlier day's — it must query the expiry date, so a future expiry stays open.
  O9  0DTE greeks use LIVE minutes-to-close, not a fixed 6h (extrinsic value shrinks intraday).
  O10 P&L must never divide by a non-positive max-loss (credit >= wing): the guarded divisions
        (`ret_on_risk`, `describe.ret_at_max`) return a safe value instead of crashing, and every
        position `build` emits carries max_loss > 0.

Run: pytest BOT/tests/test_zero_day_options.py -q
"""
import sys
from pathlib import Path

BOT_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BOT_DIR))                            # BOT/ on path

from bot.market_data.options_data import _chain_book
from bot.options import native


# ============================ O7 — live-chain 0DTE gate ============================

def _chain_rows(expiry, strikes=(498, 499, 500, 501, 502, 503, 504, 505, 506)):
    rows = []
    for k in strikes:
        for cp in ("C", "P"):
            rows.append({"expiry": expiry, "cp": cp, "strike": float(k),
                         "bid": 1.00, "ask": 1.10, "mid": 1.05})
    return rows


def test_chain_gate_refuses_when_nearest_expiry_is_not_today():
    # the only expiry present is TOMORROW -> a true-0DTE strategy must refuse, not trade a 1-DTE
    ch = _chain_book(_chain_rows("2026-07-09"), spot=502, today="2026-07-08")
    assert ch["ok"] is False
    assert ch["is_0dte"] is False
    assert "no 0DTE" in ch["error"] and "2026-07-09" in ch["error"]


def test_chain_gate_accepts_a_true_0dte():
    ch = _chain_book(_chain_rows("2026-07-08"), spot=502, today="2026-07-08")
    assert ch["ok"] is True
    assert ch["is_0dte"] is True
    assert ch["expiry"] == "2026-07-08"
    assert ch["n"] > 0 and ("C", 502.0) in ch["book"]


def test_chain_gate_picks_the_nearest_and_still_refuses_without_a_same_day():
    # both 1-DTE and 2-DTE present, no same-day: nearest is the 1-DTE, and it is still refused
    rows = _chain_rows("2026-07-10") + _chain_rows("2026-07-09")
    ch = _chain_book(rows, spot=502, today="2026-07-08")
    assert ch["ok"] is False and "2026-07-09" in ch["error"]   # nearest, not the far one


def test_chain_gate_opt_out_still_flags_non_0dte():
    # research may disable the gate, but the chain is still labelled is_0dte=False so a caller can tell
    ch = _chain_book(_chain_rows("2026-07-09"), spot=502, require_0dte=False, today="2026-07-08")
    assert ch["ok"] is True and ch["is_0dte"] is False


# ==================== O7 — manage_open settles at the STORED expiry ====================

def _redirect_stores(monkeypatch, tmp_path):
    monkeypatch.setattr(native, "open_path", lambda: tmp_path / "open.jsonl")
    monkeypatch.setattr(native, "journal_path", lambda: tmp_path / "journal.jsonl")


def _naked_long(expiry, long_k=502.0, debit=1.5):
    return {"kind": "long_call", "structure_type": "debit", "cp": "C", "long_k": long_k,
            "short_k": None, "debit": debit, "credit": 0.0, "max_loss": debit, "wing": 0.0,
            "underlying": "QQQ", "date": expiry, "slot": "am", "structure": "long_single",
            "expiry": expiry, "status": "open", "lineage": native.LINEAGE}


def test_non_0dte_position_is_not_force_settled_at_an_earlier_close(monkeypatch, tmp_path):
    """THE 0-day error: a position expiring TOMORROW must not settle at TODAY's close. manage_open
    queries the EXPIRY date, so with only today's close available it stays open."""
    _redirect_stores(monkeypatch, tmp_path)
    native._save_open([_naked_long("2026-07-09")])            # expiry = tomorrow

    def settle_close(d):                                       # only TODAY's close exists
        return 505.0 if d == "2026-07-08" else None
    closed = native.manage_open(lambda r: None, settle_close, now_hm=960)  # well past 15:55
    assert closed == []                                       # NOT settled
    assert len(native.load_open()) == 1                       # still open
    assert native.load_journal() == []                        # nothing journalled


def test_0dte_position_settles_at_its_expiry_close(monkeypatch, tmp_path):
    _redirect_stores(monkeypatch, tmp_path)
    native._save_open([_naked_long("2026-07-08", long_k=502.0, debit=1.5)])  # expiry = today

    def settle_close(d):
        return 505.0 if d == "2026-07-08" else None
    closed = native.manage_open(lambda r: None, settle_close, now_hm=960)
    assert len(closed) == 1
    c = closed[0]
    assert c["exit"] == "settle"
    assert abs(c["pnl"] - 1.5) < 1e-9                          # (505-502) intrinsic - 1.5 debit
    assert c["outcome"] == "win" and c["status"] == "closed"
    assert native.load_open() == []                           # removed from the open store


def test_position_before_close_time_is_left_open(monkeypatch, tmp_path):
    _redirect_stores(monkeypatch, tmp_path)
    native._save_open([_naked_long("2026-07-08")])
    closed = native.manage_open(lambda r: None, lambda d: 505.0, now_hm=600)  # 10:00, before 15:55
    assert closed == [] and len(native.load_open()) == 1


# ==================== O10 — no divide-by-(non-positive)-max-loss ====================

def test_ret_on_risk_guards_zero_max_loss():
    pos = {"structure_type": None, "ksc": None, "ksp": 500.0, "klp": 494.0,
           "wing": 6.0, "credit": 1.0, "max_loss": 0.0}       # credit == wing -> ml 0
    assert native.ret_on_risk(pos, 505.0) == 0.0              # returns 0.0, never ZeroDivisionError


def test_describe_guards_zero_max_loss():
    pos = {"kind": "put_spread", "ksp": 500.0, "klp": 494.0, "ksc": None, "klc": None,
           "wing": 6.0, "credit": 1.0, "max_loss": 0.0}
    d = native.describe(pos, spot=502.0, mins_to_close=120)
    assert d["ret_at_max"] is None                            # guarded, not a crash


def test_build_only_emits_positive_max_loss():
    import numpy as np
    strikes = np.arange(480.0, 525.0)

    def q(cp, K):                                             # monotone, ATM ~2.0, decays with dist
        if K is None:
            return None
        m = max(0.05, 2.0 - 0.04 * abs(K - 502.0))
        return (m - 0.05, m + 0.05, m)

    pos = native.build(502.0, 502.0, q, {"C": strikes, "P": strikes})
    assert pos is not None and pos["kind"] == "condor"
    assert pos["max_loss"] > 0                                # the O10 invariant build enforces
    assert pos["credit"] >= native.SPEC["min_credit"]


# ==================== settle_pnl — the math O7's settle relies on ====================

def test_settle_pnl_naked_long_caps_loss_at_debit():
    pos = _naked_long("2026-07-08", long_k=502.0, debit=1.5)
    assert abs(native.settle_pnl(pos, 505.0) - 1.5) < 1e-9    # 3 intrinsic - 1.5 debit
    assert abs(native.settle_pnl(pos, 500.0) - (-1.5)) < 1e-9  # OTM: lose the debit, no more


def test_settle_pnl_credit_spread_caps_loss_at_max_loss():
    pos = {"kind": "put_spread", "ksp": 500.0, "klp": 494.0, "ksc": None, "klc": None,
           "wing": 6.0, "credit": 1.0, "max_loss": 5.0, "structure_type": None}
    assert abs(native.settle_pnl(pos, 505.0) - 1.0) < 1e-9    # above the short: full credit
    assert abs(native.settle_pnl(pos, 496.0) - (-3.0)) < 1e-9  # partial: 1 - 4
    assert abs(native.settle_pnl(pos, 490.0) - (-5.0)) < 1e-9  # past the long wing: capped at -wing+credit


# ==================== O9 — 0DTE greeks use LIVE minutes-to-close ====================

def test_describe_extrinsic_value_shrinks_into_the_close():
    """A near-the-money 0DTE long is worth more with 6h left than with 5min — the fix wired the
    live minutes-to-close through instead of a fixed 360-min T (a 15:00 contract priced as 6h)."""
    pos = _naked_long("2026-07-08", long_k=502.0, debit=1.5)
    early = native.describe(pos, spot=502.0, mins_to_close=360)["legs"][0]["px"]
    late = native.describe(pos, spot=502.0, mins_to_close=5)["legs"][0]["px"]
    assert early > late > 0                                   # extrinsic decays as expiry nears
