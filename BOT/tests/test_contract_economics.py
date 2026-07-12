"""CONTRACT ECONOMICS + ROLL-ADJUSTMENT TESTS (remediation Phase 3, T3.1-T3.2 — RED-first).

T3.2  every symbol's simulated costs must come from the contract registry (the audit found ALL
      futures priced as MNQ — $2/pt, $0.52 commission — wrong for NQ/$20, ES/$50, GC/$100+0.10 tick).
T3.1  momentum indicators (ATR/EMA) must be computed roll-adjusted: a futures roll jump must not
      spike ATR or detach EMAs from price. Levels stay raw (executable).
T3.3  grep gate: no economics constant tuples outside engine/hs_contracts.py.
"""
from __future__ import annotations

import os
import re
import sys

import numpy as np
import pandas as pd

ENGINE = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", "engine"))
if ENGINE not in sys.path:
    sys.path.insert(0, ENGINE)

import hs_backtest as B  # noqa: E402
import hs_contracts as C  # noqa: E402
import hs_harness as H  # noqa: E402

ET = "America/New_York"
ATR = 8.0
BASE = 102.0
OR = {t: (BASE, 104.0, 100.0, BASE) for t in ("09:30", "09:35", "09:40", "09:45", "09:50", "09:55")}


def _frame(days_spec, sym="NQ"):
    rows = []
    for day, spec_ in days_spec.items():
        for t in pd.date_range(f"{day} 09:30", f"{day} 15:55", freq="5min", tz=ET):
            o = h = l = c = BASE
            key = t.strftime("%H:%M")
            if key in spec_:
                o, h, l, c = spec_[key]
            rows.append({"ts": t.tz_convert("UTC"), "open": float(o), "high": float(h),
                         "low": float(l), "close": float(c), "volume": 1_000.0})
    d = pd.DataFrame(rows)
    d["atr14"] = ATR
    for col in ("vwap_sess", "vwap_wk", "ema9", "ema20", "ema50"):
        d[col] = np.nan
    d["macro_regime"] = "A"; d["macro_allow_trades"] = True
    d["macro_long_ok"] = True; d["macro_short_ok"] = True
    d["local_regime"] = 0; d["trend_up"] = True; d["trend_down"] = True
    d.attrs["sym"] = sym
    return d


def _one_stop_out(sym):
    """One clean stop-out (no gap): entry 104.5 close-confirm, next bar trades to the stop."""
    d = _frame({"2026-01-05": {**OR,
                               "10:00": (104.4, 105.2, 104.0, 104.5),
                               "10:05": (104.0, 104.2, 80.0, 97.0)}}, sym=sym)
    # bar low 80 is far through every stop; close 97 keeps it a plain intrabar stop (no gap: open 104)
    tr = B.backtest(d, "tp2_full", "both", False, "orb", 0, 1.0, 2.0, 570, 600, 0.0, 960, "close",
                    eod_min=958, stop_mode="or")
    assert len(tr) == 1, f"{sym}: fixture must produce exactly one trade"
    return tr.iloc[0]


def test_t32_costs_come_from_the_registry_per_symbol():
    for sym in ("NQ", "ES", "GC", "QQQ"):
        t = _one_stop_out(sym)
        s = C.spec(sym)
        orders = 2                                     # entry + stop exit
        slip_d = s.slip_ticks * s.tick * s.point_value * (2 * B.CONTRACTS)
        cost_d = s.commission * orders + slip_d
        exp_cost_R = cost_d / (t.risk_pts * s.point_value * B.CONTRACTS)
        got_cost_R = float(t.gross_R - t.net_R)
        assert abs(got_cost_R - exp_cost_R) < 1e-3, (
            f"{sym}: simulated cost {got_cost_R:.4f}R != registry cost {exp_cost_R:.4f}R "
            f"(point value {s.point_value}, tick {s.tick}, comm {s.commission} — "
            f"MNQ economics applied to a non-MNQ contract?)")


def test_t32b_unknown_symbol_fails_loud():
    try:
        C.spec("CL")
    except KeyError:
        return
    raise AssertionError("unknown symbol must raise — silent defaults are the audited defect")


def test_t31_roll_jump_does_not_contaminate_indicators():
    """Two sessions with a ratio roll between them: raw prices jump +150 at the boundary while the
    ADJUSTED series is continuous. ATR must stay at bar-range scale and EMA20 must track price —
    on raw prices the roll prints a 150-point 'move' into both."""
    rows = []
    for day, px, af in (("2026-01-05", 15_000.0, 1.01), ("2026-01-06", 15_150.0, 1.0)):
        for t in pd.date_range(f"{day} 09:30", f"{day} 15:55", freq="5min", tz=ET):
            rows.append({"ts": t.tz_convert("UTC"), "open": px, "high": px + 1.0,
                         "low": px - 1.0, "close": px, "volume": 1_000.0, "adj_factor": af})
    d = pd.DataFrame(rows)                              # 15000*1.01 == 15150: adjusted-continuous
    out = H.compute_state(d, H.P(struct_lb_fix=3))
    boundary = 78                                       # first bar of the new contract's session
    tail = out.iloc[boundary:boundary + 20]             # right after the roll, where the spike lives
    assert float(tail["atr14"].max()) < 6.0, (
        f"ATR carries the roll jump (max {tail['atr14'].max():.1f} — a 150-pt roll 'move' leaked "
        f"into true range; indicators must use the adjusted series)")
    gap20 = float((tail["ema20"] - tail["close"]).abs().max())
    assert gap20 < 10.0, (
        f"EMA20 detached from price by {gap20:.1f} pts after the roll — EMAs must be computed "
        f"adjusted and rescaled to raw contract units")
    pd.testing.assert_series_equal(out["close"].reset_index(drop=True),
                                   d["close"].reset_index(drop=True), check_names=False)


def test_t33_no_economics_constants_outside_the_registry():
    pat = re.compile(r"^\s*(?:PT_VALUE|SLIP_TICKS)\b[^=\n]*=", re.M)   # tuple or single assignment
    bad = [fn for fn in os.listdir(ENGINE)
           if fn.endswith(".py") and fn != "hs_contracts.py"
           and pat.search(open(os.path.join(ENGINE, fn), encoding="utf-8").read())]
    assert not bad, (
        f"economics constants defined outside engine/hs_contracts.py: {bad} — "
        f"the registry is the single source (research/ is exempt until Phase R)")
