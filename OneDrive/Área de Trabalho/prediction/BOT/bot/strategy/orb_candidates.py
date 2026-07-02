"""Strategy → TradeCandidate emitter.

Wraps the *validated* engine (`engine/hs_backtest.py`) instead of re-implementing the entry, so
the bot trades exactly what the research/Pine proved: the production ORB-stack default — F59
close-confirm (strong full body 0.25 + next-bar continuation), the F61 direction-sequence gate,
struct stop (F25b), skip-first-hour (F38), capped-TP2 4R exit (F34b), plain-ORB gate (F58).

Each fired signal becomes a canonical `TradeCandidate` (the same schema risk/execution/journal
speak). A replay over historical bars therefore yields the exact trade plan the bot would have
proposed, in the contract format.

    from bot.strategy.orb_candidates import emit_candidates
    cands = emit_candidates("QQQ")     # list[TradeCandidate]
"""
from __future__ import annotations

import contextlib
import os
import sys
from pathlib import Path

import pandas as pd

from bot.config import BOT_ROOT
from bot.contracts import TradeCandidate, Session

REPO_ROOT = BOT_ROOT.parent
sys.path.insert(0, str(REPO_ROOT / "engine"))

# production ORB-stack config (matches the shipped Pine default + F61)
ORS, ORE, CUT, EOD = 570, 600, 900, 958
T1, T2, DELAY, STRONG = 1.0, 4.0, 60, 0.25
_SESS = {"rth": Session.RTH, "asia": Session.ASIA, "london": Session.LONDON}


@contextlib.contextmanager
def _in_repo_root():
    """The engine's hs_db uses repo-root-relative data/ paths."""
    cwd = os.getcwd()
    os.chdir(REPO_ROOT)
    try:
        yield
    finally:
        os.chdir(cwd)


def load_state(sym: str = "QQQ", tf: str = "5m", sess: str = "rth"):
    """Build the engine harness-state DataFrame (bars + indicators) for `sym`, plain-ORB gate on."""
    import hs_db, hs_harness as H, hs_backtest as B
    with _in_repo_root():
        con = hs_db.connect()
        bars = B._externals(con, hs_db.bars(con, tf, sess, sym=sym), sym)
        con.close()
    from bot.strategy.asset_config import struct_lb
    d = H.compute_state(bars, H.P(struct_lb_fix=struct_lb(sym)))   # futures lb=3 / equity lb=5
    d.attrs["sym"] = sym
    d["trend_up"] = True
    d["trend_down"] = True                       # F58 plain-ORB gate (shipped default)
    return d


def emit_from_state(d, sym: str = "QQQ", tf: str = "5m", sess: str = "rth",
                    strategy_version: str = "orb-stack-f61-1.0") -> list[TradeCandidate]:
    """Emit candidates from a pre-built state frame (so a replay can share `d` with the broker)."""
    import hs_backtest as B
    tr = B.backtest(d, "tp2_full", "both", False, "orb", 0, T1, T2, ORS, ORE, 0.0, CUT, "close",
                    eod_min=EOD, stop_mode="struct", entry_delay=DELAY,
                    strong_body=STRONG, ft_confirm=True, dir_seq=True)
    cands: list[TradeCandidate] = []
    for _, row in tr.iterrows():
        sign = 1 if row["direction"] == "long" else -1
        entry, risk = float(row["entry_price"]), float(row["risk_pts"])
        if risk <= 0:
            continue
        ts = pd.Timestamp(row["entry_time"])
        gen = (ts.tz_localize("UTC") if ts.tz is None else ts.tz_convert("UTC")).isoformat()
        cands.append(TradeCandidate(
            symbol=sym, side=row["direction"], timeframe=tf, setup="orb_stack",
            entry=round(entry, 2), stop=round(entry - sign * risk, 2),
            tp1=round(entry + sign * risk * T1, 2), tp2=round(entry + sign * risk * T2, 2),
            strategy_version=strategy_version, regime=str(row["regime"]),
            session=_SESS.get(sess), generated_at=gen,
            evidence={"risk_pts": round(risk, 2), "mfe_r": float(row["mfe_R"]),
                      "mae_r": float(row["mae_R"]), "hold_bars": int(row["hold_bars"])},
        ))
    return cands


def emit_candidates(sym: str = "QQQ", tf: str = "5m", sess: str = "rth",
                    strategy_version: str = "orb-stack-f61-1.0") -> list[TradeCandidate]:
    """Replay the validated ORB+F61 entry over all history for `sym` → list[TradeCandidate]."""
    return emit_from_state(load_state(sym, tf, sess), sym, tf, sess, strategy_version)


if __name__ == "__main__":
    sym = sys.argv[1] if len(sys.argv) > 1 else "QQQ"
    cs = emit_candidates(sym)
    print(f"{sym}: {len(cs)} TradeCandidates emitted (ORB-stack + F61)")
    for c in cs[:3]:
        print(" ", c.to_json())
    if cs:
        rr = sum(c.rr for c in cs) / len(cs)
        longs = sum(c.side.value == "long" for c in cs)
        print(f"  avg R:R {rr:.2f} | {longs} long / {len(cs)-longs} short | "
              f"span {cs[0].generated_at[:10]}..{cs[-1].generated_at[:10]}")
