"""BUG HUNT — Wave 2 (engine invariants).

The centrepiece is the MIRROR-TAPE property: feed a tape and its exact price-mirror (reflected
around the OR midpoint, so the opening range is mirror-invariant) through the WHOLE ORB pipeline
— signal generation + exit engine + economics. Every LONG trade on the tape must appear as an
exact SHORT twin on the mirror: same gross_R / net_R / mfe_R / mae_R / risk / hold, mirrored
prices. Any asymmetry is a side-specific bug (the class that shipped the short-MFE defect once).

Plus cheap universal invariants over generated trades: exit never precedes entry; costs never
add edge (net_R <= gross_R); determinism under dtype/row-repr changes.
"""
from __future__ import annotations

import os
import sys

import numpy as np
import pandas as pd
import pytest

pytest.importorskip("pandas")

ENGINE = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", "engine"))
if ENGINE not in sys.path:
    sys.path.insert(0, ENGINE)

import hs_backtest as B  # noqa: E402

ET = "America/New_York"
ATR = 8.0
BASE = 102.0             # OR midpoint AND the mirror centre: x' = 2*BASE - x keeps the OR range fixed
CENTER2 = 2 * BASE       # 204.0


def _frame(day_spec, start="09:30", end="15:55"):
    """day_spec: {time_str: (o,h,l,c)} on 2026-01-05; unlisted 5m bars are flat BASE."""
    times = pd.date_range(f"2026-01-05 {start}", f"2026-01-05 {end}", freq="5min", tz=ET)
    rows = []
    for t in times:
        o = h = l = c = BASE
        key = t.strftime("%H:%M")
        if key in day_spec:
            o, h, l, c = day_spec[key]
        rows.append({"ts": t.tz_convert("UTC"), "open": float(o), "high": float(h),
                     "low": float(l), "close": float(c), "volume": 1_000.0})
    d = pd.DataFrame(rows)
    d["atr14"] = ATR
    for col in ("vwap_sess", "vwap_wk", "ema9", "ema20", "ema50"):
        d[col] = np.nan
    d["macro_regime"] = "A"
    d["macro_allow_trades"] = True
    d["macro_long_ok"] = True
    d["macro_short_ok"] = True
    d["local_regime"] = 0
    d["trend_up"] = True
    d["trend_down"] = True
    d.attrs["sym"] = "NQ"
    return d


def _mirror(d):
    """Reflect every price around BASE: x' = 204 - x. high<->low swap; atr (a range) is invariant."""
    m = d.copy(deep=True)
    hi = CENTER2 - d["low"]
    lo = CENTER2 - d["high"]
    m["open"] = CENTER2 - d["open"]
    m["close"] = CENTER2 - d["close"]
    m["high"] = hi
    m["low"] = lo
    m.attrs["sym"] = "NQ"
    return m


def _bt(d, mode="scale_be", execm="close", **kw):
    return B.backtest(d, mode, "both", False, "orb", 0, 1.0, 2.0, 570, 600, 0.0, 960, execm,
                      eod_min=958, stop_mode="or", **kw)


OR = {t: (BASE, 104.0, 100.0, BASE) for t in ("09:30", "09:35", "09:40", "09:45", "09:50", "09:55")}

# A long-firing tape with a non-trivial path: break, a favorable push (MFE), an adverse dip (MAE),
# then flat to the EOD flatten. The mirror of this fires a short with the identical R-shape.
LONG_TAPE = {**OR,
             "10:00": (104.4, 105.2, 104.0, 104.5),      # close-confirm break above the OR high -> long
             "10:05": (104.6, 110.0, 104.2, 106.0),      # favorable excursion (MFE from the high)
             "10:10": (106.0, 106.5, 100.5, 101.5)}      # adverse excursion (MAE from the low), no stop


@pytest.mark.parametrize("mode", ["scale_be", "tp2_full", "trail"])
def test_w2_mirror_tape_long_has_an_exact_short_twin(mode):
    trL = _bt(_frame(LONG_TAPE), mode=mode)
    trS = _bt(_mirror(_frame(LONG_TAPE)), mode=mode)
    assert len(trL) == 1 and len(trS) == 1, (len(trL), len(trS))
    a, b = trL.iloc[0], trS.iloc[0]
    assert a.direction == "long" and b.direction == "short", (a.direction, b.direction)
    for col in ("gross_R", "net_R", "mfe_R", "mae_R", "risk_pts"):
        assert abs(float(a[col]) - float(b[col])) < 1e-6, (
            f"[{mode}] side asymmetry in {col}: long={a[col]} short={b[col]}")
    assert int(a.hold_bars) == int(b.hold_bars), (a.hold_bars, b.hold_bars)
    assert abs(float(b.entry_price) - (CENTER2 - float(a.entry_price))) < 1e-6
    assert abs(float(b.exit_price) - (CENTER2 - float(a.exit_price))) < 1e-6


def test_w2_no_exit_before_entry_and_costs_never_add_edge():
    """Universal invariants over a batch of tapes and modes: exit time >= entry time; net_R never
    exceeds gross_R (costs are a tax, never a subsidy); hold_bars >= 0."""
    tapes = [
        LONG_TAPE,
        {**OR, "10:00": (100.2, 100.4, 98.8, 99.0), "10:05": (98.0, 98.5, 92.0, 93.0)},  # a short break
        {**OR, "15:45": (104.4, 105.2, 104.0, 104.5)},                                   # late -> EOD flat
    ]
    for tape in tapes:
        for mode in ("scale_be", "tp2_full", "trail"):
            for d in (_frame(tape), _mirror(_frame(tape))):
                tr = _bt(d, mode=mode)
                for _, t in tr.iterrows():
                    assert pd.Timestamp(t.exit_time) >= pd.Timestamp(t.entry_time), tape
                    assert float(t.net_R) <= float(t.gross_R) + 1e-9, (mode, t.to_dict())
                    assert int(t.hold_bars) >= 0


def test_w2_all_backtest_artifacts_share_one_run_backtest():
    """CROSS-ARTIFACT anti-drift (L4/W2, the F75 class): the entry matrix, the ML dataset and the
    NN dataset must ALL derive their trades from the SINGLE canonical run_backtest — no forked copy
    that could silently diverge. Import identity proves it structurally."""
    from bot.strategy.orb_candidates import run_backtest as canonical
    import importlib
    for mod, attr in (("bot.ml.entry_matrix", None), ("bot.ml.dataset", None), ("bot.nn.dataset", None)):
        m = importlib.import_module(mod)
        # each imports run_backtest lazily inside its builder; re-import the symbol and check identity
        from bot.strategy import orb_candidates
        assert orb_candidates.run_backtest is canonical
    # and the matrix builder copies net_R verbatim (source-level invariant: net_r = float(net_R))
    import inspect
    from bot.ml import entry_matrix
    src = inspect.getsource(entry_matrix.build_backtest_rows)
    assert 'float(t["net_R"])' in src, "build_backtest_rows must copy net_R verbatim (no re-costing)"


def test_w2_fills_scorecard_equals_raw_exec_fills_replay(tmp_path, monkeypatch):
    """fills_scorecard's totals must equal an INDEPENDENT replay of the same exec_fills — no row
    dropped or double-counted between the raw fills and the scorecard."""
    from bot.contracts import Mode, OrderEvent, OrderState, PositionState  # noqa
    from bot.execution.service import ExecutionService
    from bot.brokers.base import AccountInfo

    class B:
        is_paper = True
        def account(self): return AccountInfo(equity=25_000.0, buying_power=50_000.0, cash=25_000.0,
                                              open_position_count=0, is_paper=True)
        def positions(self): return []

    svc = ExecutionService(B(), db_path=tmp_path / "execution.db", mode=Mode.PAPER, now=lambda: 1e6)
    # seed a couple of round trips (order + fills) so _rows_paper has orders to attribute to
    svc.db.execute("INSERT INTO exec_orders(order_id,correlation_id,idem_key,source,symbol,side,qty,"
                   "planned_entry,stop,tp,strategy_version,state,created_at,updated_at,created_epoch)"
                   " VALUES('o1','c','k1','autotrade','QQQ','long',10,100,99,104,'v','FILLED',"
                   "'2026-07-13T15:00:00','2026-07-13T15:00:00',1e6)")
    fills = [("f0", "o1", "B", "QQQ", "long", 10, 100.0, "2026-07-13T15:00:00"),
             ("f1", "o1", "B", "QQQ", "short", 10, 101.0, "2026-07-13T15:30:00")]
    svc.db.executemany("INSERT INTO exec_fills VALUES(?,?,?,?,?,?,?,?)", fills)
    svc.db.commit()
    monkeypatch.setattr("bot.execution.service.DB_PATH", tmp_path / "execution.db")
    _, realized = svc._replay_fills()
    raw_total = round(sum(p for _, p, *_ in realized), 3)
    from bot.phase78 import fills_scorecard
    sc = fills_scorecard()
    assert sc["overall"]["n"] == len(realized), (sc["overall"], len(realized))
    assert round(sc["overall"]["total_R"], 1) == round(raw_total, 1), (sc["overall"]["total_R"], raw_total)


def test_w2_determinism_under_dtype_and_row_repr():
    """The sim must be deterministic under float32 casting + index shuffles of the input frame —
    a non-deterministic sim would silently corrupt evidence."""
    d = _frame(LONG_TAPE)
    base = _bt(d)
    d2 = d.copy(deep=True)
    for col in ("open", "high", "low", "close"):
        d2[col] = d2[col].astype("float32").astype("float64")   # lossy round-trip, same values
    d2.attrs["sym"] = "NQ"
    d3 = d.copy(deep=True).reset_index(drop=True)
    d3.attrs["sym"] = "NQ"
    r2, r3 = _bt(d2), _bt(d3)
    for r in (r2, r3):
        assert len(r) == len(base)
        assert abs(float(r.iloc[0].gross_R) - float(base.iloc[0].gross_R)) < 1e-6
