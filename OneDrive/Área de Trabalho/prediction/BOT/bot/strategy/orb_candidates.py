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
# CANONICAL ENTRY STANDARD: the replay emits the same entry the Pine + live BOT trade.
# The ML layer trains against ONE rule version at a time — bump this string whenever entry rules change.
# .1 (2026-07-05): pullback refinements — retest modes, min pullback depth 0.05 ATR, timeout 8 bars.
# .2 (2026-07-05): INSTANT FILL when the arming pair is aligned (no next-candle wait — user rule);
#     frozen OR-mid day bias superseded by the LIVE mid (watch machine) on mid-armed assets.
STRATEGY_VERSION = "orb-standard-2026.07.2"


@contextlib.contextmanager
def _in_repo_root():
    """The engine's hs_db uses repo-root-relative data/ paths."""
    cwd = os.getcwd()
    os.chdir(REPO_ROOT)
    try:
        yield
    finally:
        os.chdir(cwd)


RESAMPLE_TF = {"1m": None, "3m": "3min", "2h": "2h", "1w": "1W"}   # tfs built by resampling
_TF_SRC = {"3m": "1m", "2h": "1h", "1w": "1d"}                      # resample source per tf


def _bars_tf(con, sym: str, tf: str, sess: str):
    """Bars for ANY timeframe: direct from the partitioned store when it has the tf, else
    resampled causally (1m from the continuous view; 3m<-1m; 2h<-1h; 1w<-1d). RTH filter for
    resampled intraday tfs = 09:30-16:00 ET."""
    import hs_db
    import pandas as pd
    if tf not in RESAMPLE_TF:
        return hs_db.bars(con, tf, sess, sym=sym)
    if tf == "1m":
        b = con.execute(f"SELECT * FROM {sym.lower()}_1m ORDER BY 1").df()
        tcol = next((c for c in ("ts_utc", "ts_et", "ts") if c in b.columns), None)
        b = b.rename(columns={tcol: "ts"})
    else:
        src = _TF_SRC[tf]
        b = (con.execute(f"SELECT * FROM {sym.lower()}_1m ORDER BY 1").df()
             .rename(columns=lambda c: "ts" if c in ("ts_utc", "ts_et") else c)
             if src == "1m" else hs_db.bars(con, src, sess, sym=sym))
    b["ts"] = pd.to_datetime(b["ts"], utc=True)
    if tf in ("1m", "3m"):                      # continuous 1m is full-session -> clip to RTH
        et = b["ts"].dt.tz_convert("America/New_York")
        mm = et.dt.hour * 60 + et.dt.minute
        b = b[(mm >= 570) & (mm < 960)]
    rule = RESAMPLE_TF[tf]
    if rule is None:
        return b.reset_index(drop=True)
    o = (b.set_index("ts")
          .resample(rule, label="left", closed="left")
          .agg({"open": "first", "high": "max", "low": "min", "close": "last", "volume": "sum"})
          .dropna(subset=["open"]).reset_index())
    return o


def load_state(sym: str = "QQQ", tf: str = "5m", sess: str = "rth"):
    """Build the engine harness-state DataFrame (bars + indicators) for `sym` at ANY timeframe
    (1m/3m/5m/15m/30m/1h/2h/4h; 1d/1w belong to the swing module — ORB needs intraday bars)."""
    if tf in ("1d", "1w"):
        raise ValueError("tf 1d/1w: the ORB day-trading replay needs intraday bars — "
                         "daily/weekly training belongs to the SWING module (spec_only)")
    import hs_db, hs_harness as H, hs_backtest as B
    with _in_repo_root():
        con = hs_db.connect()
        bars = B._externals(con, _bars_tf(con, sym, tf, sess), sym)
        con.close()
    from bot.strategy.asset_config import struct_lb, asset_config, resolve_ctx_mode
    from bot.strategy.orb_state import ENTRY_STANDARD as ES
    import numpy as np
    d = H.compute_state(bars, H.P(struct_lb_fix=struct_lb(sym)))   # futures lb=3 / equity lb=5
    d.attrs["sym"] = sym
    # ENTRY STANDARD Layer 1 — Market Context PAIR per asset (DIR-FAST A, user 2026-07-05):
    # mid_vwap = VWAP side here (the OR-MID side is enforced by the watch machine);
    # struct_vwap = previous standard (fallback B); none = plain ORB.
    mode = resolve_ctx_mode(asset_config(sym)) if ES.ctx_gate else "none"
    if mode != "none" and "vwap_sess" in d and "st_state" in d:
        st = d["st_state"].to_numpy(); cl = d["close"].to_numpy(float)
        vw = d["vwap_sess"].to_numpy(float)
        with np.errstate(invalid="ignore"):
            if mode == "mid_vwap":
                d["trend_up"] = cl > vw
                d["trend_down"] = cl < vw
            else:
                d["trend_up"] = (st == 1) & (cl > vw)
                d["trend_down"] = (st == 2) & (cl < vw)
    else:
        d["trend_up"] = True
        d["trend_down"] = True                   # F58 plain-ORB gate (pre-standard default)
    return d


def run_backtest(d):
    """The ONE canonical backtest call (entry standard) — candidates, the ML dataset and any
    research replay must all come through here so they see the identical rule version.
    Per-asset Layer-3 overrides (gauntlet-adopted, e.g. SPY cd0/stale12/retest0.25) come from
    asset_config keyed by the frame's symbol."""
    import hs_backtest as B
    from bot.strategy.orb_state import ENTRY_STANDARD as ES
    from bot.strategy.asset_config import asset_config
    a = asset_config(str(d.attrs.get("sym", "")))
    return B.backtest(d, "tp2_full", "both", False, "orb", 0, T1, T2, ORS, ORE, 0.0, CUT, "close",
                      eod_min=EOD, stop_mode="struct", entry_delay=DELAY,
                      strong_body=STRONG, ft_confirm=True, dir_seq=True,
                      watch_live=ES.watch_gate,
                      cooldown_bars=a.cooldown_bars if a.cooldown_bars is not None else ES.cooldown_bars,
                      stale_bars=a.stale_bars if a.stale_bars is not None else ES.stale_bars,
                      retest_atr=a.retest_atr if a.retest_atr is not None else ES.retest_atr,
                      retest_mode=ES.retest_mode, min_pullback_atr=ES.min_pullback_atr,
                      pullback_timeout=ES.pullback_timeout, vol_confirm_x=ES.vol_confirm_x,
                      instant_aligned=a.instant_fill)


def emit_from_state(d, sym: str = "QQQ", tf: str = "5m", sess: str = "rth",
                    strategy_version: str = STRATEGY_VERSION) -> list[TradeCandidate]:
    """Emit candidates from a pre-built state frame (so a replay can share `d` with the broker)."""
    tr = run_backtest(d)
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
                    strategy_version: str = STRATEGY_VERSION) -> list[TradeCandidate]:
    """Replay the CANONICAL entry standard over all history for `sym` → list[TradeCandidate]."""
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
