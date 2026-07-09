"""STRATEGY DUEL — approved lineages shadow-trade their rules daily, head-to-head (user
2026-07-06: "put them against each other").

Every gauntlet-passed module whose lineage carries at least a RESEARCH approval plays: its
daily rules run causally on completed daily bars, positions are tracked in data/duel.json and
resolved as new bars arrive, and /api/duel serves the leaderboard (n, WR, avg R, PF, total R,
open positions) next to the ORB core's live shadow scorecard. Shadow only — the duel never
places orders; paper/live execution stays behind its own gates.

R convention: every module's PnL is normalized by its own risk unit so the leaderboard is
comparable — swing/breakout risk = 1.5×ATR(14) stop distance; volbreak risk = the k·range stop;
Connors (no hard stop by rule) uses 1.5×ATR as the R denominator.

    python -m bot.strategy.duel        # self-test on synthetic bars + one live run
"""
from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pandas as pd

from bot.config import BOT_ROOT

STATE = BOT_ROOT / "data" / "duel.json"
STOP_ATR, TGT_ATR, HORIZON = 1.5, 3.0, 20        # swing triple-barrier (matches the gauntlet)
VB_K = 0.3                                        # volbreak band (F52 graduate)
CONNORS_MAX_HOLD = 10

# module id -> (lineage version, [symbols])
DUELISTS = {
    "equities_swing": ("swing-1d-0.1", ["QQQ"]),
    "futures_swing": ("swing-fut-1d-0.1", ["NQ"]),
    "futures_volbreak": ("volbreak-fut-0.1", ["NQ"]),          # OUTRIGHT futures (shares book)
    "equities_volbreak": ("volbreak-0dte-0.1", ["QQQ", "SPY"]),  # 0DTE naked options book
    "equities_overnight": ("overnight-1d-0.1", ["QQQ", "SPY"]),   # shares book (night effect)
    "futures_tsmom": ("tsmom-fut-0.1", ["NQ"]),                   # 12-mo trend, long-only (shares book)
    # equities_connors_rsi2 DROPPED 2026-07-09 (weak — "no structure passed, underlying only")
}

# GATE-PASSED options expression per module (user 2026-07-06: "they will show the information
# according to the gate they pass — volbreak for naked, swing for QQQ debit"). From the
# cross-strategy payoff replay (research/options_cross.py, F74).
OPTIONS_EXPRESSION = {
    "futures_volbreak": "OUTRIGHT FUTURES — NQ +0.094R PF 1.53 17/17 yrs (thin ~12bps; futures cost only, no options)",
    "equities_volbreak": "0DTE NAKED — QQQ +1.01/prem PF 3.30 9/9 · SPY +0.63 PF 2.51 9/9",
    "equities_swing": "21DTE NAKED +0.311 & DEBIT +0.236 (QQQ, both 6/6 yrs)",
    "futures_swing": "no options gate run (futures options untested)",
    "futures_tsmom": "OUTRIGHT FUTURES — NQ 12-mo trend long-only PF 1.58, 81% of years (tsmom.py)",
    "equities_overnight": "SHARES only — options frictions (spread + overnight theta) exceed the ~0.03%/night edge",
}


def _load() -> dict:
    if STATE.exists():
        try:
            return _migrate(json.loads(STATE.read_text(encoding="utf-8")))
        except Exception:
            pass
    return {"open": [], "closed": [], "last_day": None}


# volbreak was SPLIT by asset (2026-07-09) — remap orphaned daily_volbreak history to the book
# that owns its symbol so the trades stay visible; futures symbols -> the outright-futures book.
_VB_SPLIT = {"NQ": "futures_volbreak", "ES": "futures_volbreak", "GC": "futures_volbreak"}


def _migrate(st: dict) -> dict:
    """State hygiene on every load: (a) closed trades of RENAMED modules remap into the current
    book (daily_volbreak split); (b) open positions of modules no longer in DUELISTS are armed
    markers with no owner — drop them (they'd sit 'open' forever and skew the open count)."""
    for t in st.get("closed", []):
        m = t.get("module")
        if m not in DUELISTS and "volbreak" in str(m):
            t["module"] = _VB_SPLIT.get(t.get("symbol"), "equities_volbreak")
    st["open"] = [p for p in st.get("open", []) if p.get("module") in DUELISTS]
    return st


def _save(d: dict) -> None:
    STATE.parent.mkdir(parents=True, exist_ok=True)
    STATE.write_text(json.dumps(d, indent=1), encoding="utf-8")


def _rsi2(c: pd.Series) -> pd.Series:
    delta = c.diff()
    up = delta.clip(lower=0).ewm(alpha=1 / 2, adjust=False).mean()
    dn = (-delta.clip(upper=0)).ewm(alpha=1 / 2, adjust=False).mean()
    rs = up / dn.replace(0, np.nan)
    return 100 - 100 / (1 + rs)


def _approved(version: str) -> bool:
    from bot.approval import status
    return bool(status(version)["stages"].get("research"))


def _entries_for(module: str, sym: str, b: pd.DataFrame) -> list[dict]:
    """Signal on the LAST COMPLETED daily bar -> new open position dicts (shadow entry at that
    bar's close; volbreak is intraday so it resolves same-day inside _resolve)."""
    i = len(b) - 1
    c = b["close"].to_numpy(float); h = b["high"].to_numpy(float); lo = b["low"].to_numpy(float)
    e20 = b["ema20"].to_numpy(float); e50 = b["ema50"].to_numpy(float)
    atr = float(b["atr14"].iloc[-1])
    if not np.isfinite(atr) or atr <= 0 or i < 60:
        return []
    day = str(b["ts"].iloc[-1])[:10]
    out = []
    if module == "equities_swing":
        up = c[i] > e20[i] > e50[i]; dn = c[i] < e20[i] < e50[i]
        sign = 1 if (up and lo[i] <= e20[i] and c[i] > e20[i]) else \
            -1 if (dn and h[i] >= e20[i] and c[i] < e20[i]) else 0
        if sign:
            out.append({"entry": c[i], "sign": sign, "stop": c[i] - sign * STOP_ATR * atr,
                        "tp": c[i] + sign * TGT_ATR * atr, "risk": STOP_ATR * atr,
                        "max_days": HORIZON})
    elif module == "futures_swing":
        hh20 = float(h[max(0, i - 20):i].max()); ll20 = float(lo[max(0, i - 20):i].min())
        sign = 1 if (c[i] > hh20 and c[i] > e50[i]) else \
            -1 if (c[i] < ll20 and c[i] < e50[i]) else 0
        if sign:
            out.append({"entry": c[i], "sign": sign, "stop": c[i] - sign * STOP_ATR * atr,
                        "tp": c[i] + sign * TGT_ATR * atr, "risk": STOP_ATR * atr,
                        "max_days": HORIZON})
    elif module in ("futures_volbreak", "equities_volbreak"):   # same signal, isolated books
        rng = float(h[i] - lo[i])
        if rng > 0:
            out.append({"kind": "volbreak", "prev_range": rng, "max_days": 1})
    elif module == "equities_connors_rsi2":
        rsi = _rsi2(b["close"]); sma200 = b["close"].rolling(200).mean()
        if len(b) >= 200 and np.isfinite(rsi.iloc[-1]) and np.isfinite(sma200.iloc[-1]):
            sign = 1 if (c[i] > sma200.iloc[-1] and rsi.iloc[-1] < 10) else \
                -1 if (c[i] < sma200.iloc[-1] and rsi.iloc[-1] > 90) else 0
            if sign:
                out.append({"kind": "connors", "entry": c[i], "sign": sign,
                            "risk": STOP_ATR * atr, "max_days": CONNORS_MAX_HOLD})
    elif module == "equities_overnight":
        # buy MOC -> sell next MOO; the drift concentrates AFTER a down close (QQQ 9/9 yrs) — the
        # validated conditioning. Risk-normalised by ATR so R is comparable to the other duelists.
        if i >= 1 and c[i] < c[i - 1]:
            out.append({"kind": "overnight", "entry": c[i], "sign": 1, "risk": atr, "max_days": 1})
    elif module == "futures_tsmom":
        # 12-mo time-series momentum, LONG-ONLY (short side loses on secularly-rising indices). Enter
        # long when the trailing 12mo (skip last mo) return is positive; hold ~1 month (21 trading days).
        if i >= 252:
            past = c[i - 21] / c[i - 252] - 1.0
            if past > 0:
                out.append({"kind": "tsmom", "entry": c[i], "sign": 1, "risk": STOP_ATR * atr, "max_days": 21})
    for t in out:
        t.update({"module": module, "symbol": sym, "opened": day, "days_held": 0})
    return out


def _live_daily_frame(sym: str) -> pd.DataFrame:
    """hs_db daily frame EXTENDED with live daily bars. The stored snapshot is curated and can
    lag weeks (equities ended 2026-06-08) — without the extension the duel armed positions on
    month-old bars and 1-day volbreak markers could never resolve (frozen 'open' forever)."""
    from bot.ml.swing_dataset import _daily_frame, add_daily_indicators
    b = _daily_frame(sym, "1d")
    try:
        from bot.market_data.providers import get_bars
        live = get_bars(sym, tf="1d", period="3mo")
        if live is not None and len(live):
            live = live.copy()
            live["ts"] = pd.to_datetime(live["ts_et"] if "ts_et" in live.columns else live["ts"],
                                        utc=True)     # providers frame carries ts_et, not ts
            # COMPLETED bars only: today's forming daily bar would resolve 1-day positions early
            today_et = pd.Timestamp.now(tz="America/New_York").strftime("%Y-%m-%d")
            live = live[live["ts"].dt.strftime("%Y-%m-%d") < today_et]
            cols = [c for c in ("ts", "open", "high", "low", "close", "volume") if c in live.columns]
            add = live[live["ts"] > b["ts"].max()][cols]
            if len(add):
                base = b[[c for c in ("ts", "open", "high", "low", "close", "volume") if c in b.columns]]
                b = pd.concat([base, add], ignore_index=True)
                for c in ("open", "high", "low", "close"):
                    b[c] = b[c].astype(float)
                b = add_daily_indicators(b)
    except Exception:
        pass                                          # live feed down -> stored frame still works
    return b


def _resolve(pos: dict, bar: pd.Series, b: pd.DataFrame) -> float | None:
    """Walk ONE new daily bar for an open position -> realized R or None (still open)."""
    o, h, lo, c = (float(bar["open"]), float(bar["high"]), float(bar["low"]), float(bar["close"]))
    if pos.get("kind") == "volbreak":                 # intraday: both bands, EOD flat, gap-aware
        k = VB_K * pos["prev_range"]
        up_lvl, dn_lvl = o + k, o - k
        risk = k if k > 0 else None
        if risk is None:
            return 0.0
        long_hit, short_hit = h >= up_lvl, lo <= dn_lvl
        if long_hit and not short_hit:
            return (c - max(up_lvl, o)) / risk
        if short_hit and not long_hit:
            return (min(dn_lvl, o) - c) / risk
        if long_hit and short_hit:                    # both bands = whipsaw day, book the loss
            return -1.0
        return 0.0                                    # no trigger, no trade (scratch, 0R)
    sign, entry, risk = pos["sign"], pos["entry"], pos["risk"]
    if pos.get("kind") == "overnight":                # MOC in at prev close -> MOO out at this open
        return sign * (o - entry) / risk if risk > 0 else 0.0
    if pos.get("kind") == "tsmom":                    # long-only 12-mo trend: hold to max_days, exit at close
        return sign * (c - entry) / risk if (pos["days_held"] + 1 >= pos["max_days"] and risk > 0) else None
    if pos.get("kind") == "connors":
        rsi = _rsi2(b["close"]).iloc[-1]
        if (sign == 1 and rsi > 90) or (sign == -1 and rsi < 10) or \
                pos["days_held"] + 1 >= pos["max_days"]:
            return sign * (c - entry) / risk
        return None
    adverse = lo if sign == 1 else h
    favor = h if sign == 1 else lo
    if sign * (adverse - pos["stop"]) <= 0:
        return sign * (pos["stop"] - entry) / risk
    if sign * (favor - pos["tp"]) >= 0:
        return sign * (pos["tp"] - entry) / risk
    if pos["days_held"] + 1 >= pos["max_days"]:
        return sign * (c - entry) / risk
    return None


def run_duel_once(frames: dict | None = None) -> dict:
    """One duel step (idempotent per completed trading day): resolve every open position on the
    newest completed daily bar, then open today's signals for every APPROVED module. `frames`
    (tests) = {sym: daily frame}; live loads bot.ml.swing_dataset._daily_frame."""
    st = _load()
    if frames is None:
        syms = sorted({s for _, (v, ss) in DUELISTS.items() for s in ss})
        frames = {}
        for s in syms:
            try:
                frames[s] = _live_daily_frame(s)
            except Exception:
                continue
    if not frames:
        return {"error": "no daily frames"}
    day = max(str(b["ts"].iloc[-1])[:10] for b in frames.values() if len(b))
    if st.get("last_day") == day:
        return {"skipped": f"already ran for {day}", "day": day}
    # 1) resolve open positions against each frame's NEW last bar
    still_open = []
    for pos in st["open"]:
        b = frames.get(pos["symbol"])
        if b is None or str(b["ts"].iloc[-1])[:10] <= pos.get("last_seen", pos["opened"]):
            still_open.append(pos)
            continue
        # STALE-ARM GUARD (2026-07-09): a 1-day volbreak marker resolves on the NEXT bar after it
        # armed; if a data gap left it open >4 days the current bar is the wrong day for its
        # bands — drop it as a scratch instead of booking a bogus fill.
        if pos.get("kind") == "volbreak" and \
                (pd.Timestamp(str(b["ts"].iloc[-1])[:10]) - pd.Timestamp(pos["opened"])).days > 4:
            continue
        r = _resolve(pos, b.iloc[-1], b)
        pos["days_held"] += 1
        pos["last_seen"] = str(b["ts"].iloc[-1])[:10]
        if r is None:
            still_open.append(pos)
        elif not (pos.get("kind") == "volbreak" and r == 0.0):   # volbreak no-trigger = no trade
            st["closed"].append({"module": pos["module"], "symbol": pos["symbol"],
                                 "opened": pos["opened"], "closed": pos["last_seen"],
                                 "r": round(float(r), 3)})
    st["open"] = still_open
    # 2) new entries for approved modules (dedup: one open position per module+symbol)
    live_keys = {(p["module"], p["symbol"]) for p in st["open"]}
    opened = 0
    for module, (version, syms) in DUELISTS.items():
        if not _approved(version):
            continue
        for sym in syms:
            b = frames.get(sym)
            if b is None or (module, sym) in live_keys:
                continue
            for t in _entries_for(module, sym, b):
                t["last_seen"] = t["opened"]
                st["open"].append(t)
                opened += 1
    st["last_day"] = day
    st["closed"] = st["closed"][-2000:]
    _save(st)
    return {"day": day, "opened": opened, "open": len(st["open"]), "closed": len(st["closed"])}


def leaderboard() -> dict:
    """Head-to-head table: every duelist's resolved shadow trades + the ORB core's live shadow
    scorecard (the tracker) for reference."""
    st = _load()
    rows = {}
    for t in st["closed"]:
        m = rows.setdefault(t["module"], [])
        m.append(t["r"])
    out = {}
    for module, rs in rows.items():
        r = np.asarray(rs, float)
        wins, losses = r[r > 0], r[r <= 0]
        out[module] = {"n": int(len(r)), "win_pct": round(100 * float((r > 0).mean()), 1),
                       "avg_r": round(float(r.mean()), 3), "total_r": round(float(r.sum()), 1),
                       "pf": round(float(wins.sum() / abs(losses.sum())), 2) if len(losses) and losses.sum() else None}
    open_by = {}
    for p in st["open"]:
        open_by[p["module"]] = open_by.get(p["module"], 0) + 1
    versions = {m: v for m, (v, _) in DUELISTS.items()}
    from bot.approval import status, STAGES
    stmap = {m: status(v)["stages"] for m, v in versions.items()}
    joined = {m: bool(s.get("research")) for m, s in stmap.items()}
    stage = {m: next((x for x in reversed(STAGES) if s.get(x)), None)          # highest approved
             for m, s in stmap.items()}                                        # stage -> dashboard badge
    return {"last_day": st.get("last_day"), "results": out, "open_positions": open_by,
            "lineage": versions, "joined": joined, "stage": stage, "options": OPTIONS_EXPRESSION,
            "note": "shadow duel — no orders; a module joins once its lineage has a research "
                    "approval (one-click on /training)"}


if __name__ == "__main__":                           # self-test on synthetic bars
    import tempfile, os
    n = 260
    rng = np.random.default_rng(2)
    c = pd.Series(100 + np.cumsum(rng.normal(0.1, 1.0, n)))
    b = pd.DataFrame({"ts": pd.date_range("2025-06-01", periods=n, freq="D"),
                      "open": c - 0.2, "high": c + 1.0, "low": c - 1.2, "close": c})
    tr = pd.concat([b.high - b.low, (b.high - b.close.shift()).abs(),
                    (b.low - b.close.shift()).abs()], axis=1).max(axis=1)
    b["atr14"] = tr.ewm(alpha=1 / 14, adjust=False).mean()
    b["ema20"] = b.close.ewm(span=20, adjust=False).mean()
    b["ema50"] = b.close.ewm(span=50, adjust=False).mean()
    sigs = _entries_for("equities_volbreak", "QQQ", b)
    assert sigs and sigs[0]["kind"] == "volbreak"
    r = _resolve(sigs[0], b.iloc[-1], b)
    assert r is not None
    pos = {"kind": None, "sign": 1, "entry": 100.0, "stop": 98.5, "tp": 103.0, "risk": 1.5,
           "days_held": 0, "max_days": 20}
    bar = pd.Series({"open": 101, "high": 103.5, "low": 100.5, "close": 103.2})
    assert abs(_resolve(pos, bar, b) - 2.0) < 1e-9   # tp hit = +2R
    print("duel engine OK — entries + resolution verified")
