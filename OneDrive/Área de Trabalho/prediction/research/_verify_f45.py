import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "engine"))
import numpy as np, pandas as pd
import hs_db, hs_harness as H, hs_backtest as B
from orb_stack_combined import line   # full report (exp/PF/win/DD/CI/per-year/OOS/2x slip)

# F45 in LIVE/Pine semantics: entry_delay (window opens 60min after OR close) + ob_confluence, native engine.
print("==== F45 native (LIVE semantics: entry_delay=60 + ob_confluence) — re-validation ====")
con = hs_db.connect()
for sym in ("NQ", "ES", "QQQ", "SPY"):
    eq = sym in ("QQQ", "SPY")
    bars = B._externals(con, hs_db.bars(con, "5m", "full", sym=sym), sym)
    d = H.compute_state(bars, H.P()); d.attrs["sym"] = sym
    st = d["st_state"].to_numpy(); d["trend_up"] = st == 1; d["trend_down"] = st == 2
    tr = B.backtest(d, "scale_be", "both", False, "orb", 0, 1.0, 4.0, 570, 600, 0.0, 900, "stop",
                    eod_min=958, vwap_cap=2.0, entry_delay=60, ob_confluence=True)
    line(f"{sym} F45-live", tr, eq)
con.close()
