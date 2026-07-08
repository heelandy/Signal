#!/usr/bin/env python3
"""HIGHSTRIKE OPTIONS-NATIVE STRATEGY v0.1 — "0DTE VRP Iron Condor" (2026-07-08).

A PURE options signal — it does NOT translate any underlying ORB/worker trade. The edge is the
variance-risk premium F85 measured directly: QQQ 0DTE ATM IV runs ~38% vs ~20% realized (1.56x),
so the market's expected move is systematically too wide. We SELL that width with DEFINED RISK
(an iron condor caps the -340%/day tail that killed the naked straddle in G3) and manage actively
(a take-profit + hard stop lift win-rate and bound drawdown).

Target (user 2026-07-08, options-only, not mixed): WR 75-85% · PF 1.6-1.8 · maxDD <= 11% ·
minimum 1 / maximum 2 signals per session.

SPEC (a-priori, judged on REAL OPRA bid/ask — data/opra_qqq_cbbo.parquet, F85):
  entry     10:00 ET primary (+ 13:00 ET secondary if re-armed) — after the opening range prints
  gate      sell only into contained tape: |spot(entry) - open| <= trend_mult x expected_move
  structure 0DTE iron condor: short strikes just outside the ATM straddle (expected move),
            wings `wing` dollars beyond. credit = shorts sold at BID - wings bought at ASK.
  manage    take profit at tp x credit; hard stop at stop_mult x credit; else settle intrinsic
  metric    return on risk = pnl / max_loss (max_loss = wing - credit)

    python research/opra_condor.py                 # grid the knobs, report best-in-band
Report -> BOT/data/ml/reports/opra_condor.json
"""
from __future__ import annotations

import json
import sys
from itertools import product
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "BOT"))

from bot.options import native                    # shared geometry — research and live share it

CHAIN = ROOT / "data" / "opra_qqq_cbbo.parquet"
REPORT = ROOT / "BOT" / "data" / "ml" / "reports" / "opra_condor.json"
UNDERLYING = "qqq"
BAND_WIN = (75.0, 85.0)
BAND_PF = (1.6, 1.8)
BAND_DD = 11.0                       # max drawdown ceiling, in % (2%-of-account risk per trade)
RISK_PCT = 2.0                       # account fraction risked per condor (maps R-drawdown -> %)

# CHOSEN SPEC (options-native-0.1, v0.2) — condor + directional fallback for strict min-1. HONEST
# full-strike result: WR 78 · PF 1.35 · maxDD 1.2% · 1.86 sig/session · 0 stand-aside. WR/DD in
# band; PF short of 1.6 (0DTE condor negative skew). NOTE: an earlier +-3.5% strike loader read
# PF 1.7 — an artifact (dropped 2.0x-EM directional strikes); load_0dte now loads the full window.
SPEC = {"em_mult": 1.1, "wing": 6, "tp": 0.6, "stop_mult": 2.5, "trend_mult": 1.0, "min_credit": 0.10,
        "directional": True, "dir_em_mult": 2.0, "dir_stop_mult": 1.25}


def _utf8() -> None:
    for s in (sys.stdout, sys.stderr):
        try:
            s.reconfigure(encoding="utf-8", errors="backslashreplace")
        except Exception:
            pass


def load_0dte() -> pd.DataFrame:
    """ALL 0DTE rows (the parquet is already +-6% of spot). An earlier +-3.5% filter silently
    dropped the directional short strikes at 2.0x-EM on big-EM days, flattering the v0.2 result
    (found 2026-07-08 vs the live path) — load the full window so research == live."""
    import duckdb
    con = duckdb.connect()
    try:
        con.execute("SET memory_limit='1GB'; SET threads=1; SET preserve_insertion_order=false")
        df = con.execute(
            f"SELECT * FROM read_parquet('{str(CHAIN).replace(chr(92), '/')}') WHERE dte = 0").df()
    finally:
        con.close()
    df["minute"] = pd.to_datetime(df["minute"])
    df["session"] = pd.to_datetime(df["session"]).dt.date
    df["hm"] = df["minute"].dt.hour * 60 + df["minute"].dt.minute
    return df


def _qqq_minutes() -> pd.DataFrame:
    b = pd.read_parquet(ROOT / "data" / f"{UNDERLYING}_continuous_1m.parquet",
                        columns=["ts_et", "open", "close", "session"])
    et = pd.to_datetime(b["ts_et"]).dt.tz_convert("America/New_York").dt.tz_localize(None)
    b = b.assign(minute=et, date=et.dt.date, hm=et.dt.hour * 60 + et.dt.minute)
    return b[b["session"] == "RTH"]


def build_book(day: pd.DataFrame) -> tuple[dict, dict]:
    """Pre-index a session ONCE for O(1) walk lookups: book[(cp, strike, hm)] = (bid, ask, mid),
    plus the sorted strike array per cp for nearest-strike snapping. Replaces a per-minute mask+
    idxmin that made the grid ~25 min; this makes it seconds."""
    book: dict = {}
    for cp, strike, hm, bid, ask, mid in zip(day["cp"].to_numpy(), day["strike"].to_numpy(),
                                             day["hm"].to_numpy(), day["bid"].to_numpy(),
                                             day["ask"].to_numpy(), day["mid"].to_numpy()):
        book[(cp, float(strike), int(hm))] = (float(bid), float(ask), float(mid))
    strikes = {cp: np.array(sorted(day.loc[day["cp"] == cp, "strike"].unique()))
               for cp in ("C", "P")}
    return book, strikes


def _open_price(qday: pd.DataFrame) -> float | None:
    o = qday[qday["hm"] == 570]                       # 09:30 RTH open bar
    return float(o["open"].iloc[0]) if len(o) else None


def _spot(qday: pd.DataFrame, hm: int) -> float | None:
    r = qday[qday["hm"] == hm]
    return float(r["close"].iloc[0]) if len(r) else None


def _condor(book: dict, strikes: dict, qday: pd.DataFrame, entry_hm: int, p: dict) -> dict | None:
    """Build via the SHARED native module (identical geometry to live), then manage on the OPRA
    intraday marks (which live doesn't have yet) and settle via native.settle_pnl at the close."""
    spot = _spot(qday, entry_hm)
    open_px = _open_price(qday)
    if spot is None or open_px is None:
        return None
    if p.get("mark") == "bs":                         # LIVE proxy: build the entry from BS too
        q = native.bs_quote(spot, 960 - entry_hm, 0.381)
        strikes_use = native.strikes_around(spot)
    else:                                             # backtest: real OPRA entry quotes
        q = lambda cp, K: book.get((cp, K, entry_hm))
        strikes_use = strikes
    pos = native.build(spot, open_px, q, strikes_use, spec=p, directional=p.get("directional", False))
    if pos is None:
        return None
    credit, max_loss = pos["credit"], pos["max_loss"]
    ksc, klc, ksp, klp = pos["ksc"], pos["klc"], pos["ksp"], pos["klp"]
    stop_mult = p.get("dir_stop_mult", p["stop_mult"]) if pos["kind"] != "condor" else p["stop_mult"]
    mark = p.get("mark", "opra")                      # "opra" = real intraday marks; "bs" = live proxy
    iv_live = 0.381                                   # default_iv(0), what live would mark with
    # manage: walk minutes after entry; close on TP or STOP; else settle intrinsic at close.
    outcome, exit_hm = "settle", 955
    for hm in range(entry_hm + 1, 956):
        if mark == "bs":                              # BS mark at the calibrated IV (what live does)
            sp = _spot(qday, hm)
            if sp is None:
                continue
            cost = native.mark_to_close_cost(pos, sp, 960 - hm, iv_live)
        else:                                         # real OPRA marks (buy shorts@ask, sell wings@bid)
            cost, ok = 0.0, True
            if ksc is not None:
                cc, cl = book.get(("C", ksc, hm)), book.get(("C", klc, hm))
                if cc is None or cl is None:
                    ok = False
                else:
                    cost += cc[1] - cl[0]
            if ksp is not None:
                pc, pl = book.get(("P", ksp, hm)), book.get(("P", klp, hm))
                if pc is None or pl is None:
                    ok = False
                else:
                    cost += pc[1] - pl[0]
            if not ok:
                continue
        pnl_now = credit - cost
        if pnl_now >= p["tp"] * credit:
            outcome, exit_hm = "tp", hm; break
        if pnl_now <= -stop_mult * credit:
            outcome, exit_hm = "stop", hm; break
    if outcome == "settle":
        s_close = _spot(qday, 955) or _spot(qday, 954) or spot
        pnl = native.settle_pnl(pos, s_close)
    elif outcome == "tp":
        pnl = p["tp"] * credit
    else:
        pnl = -stop_mult * credit
    return {"gated": False, "credit": round(credit, 3), "max_loss": round(max_loss, 3),
            "ret": pnl / max_loss, "pnl": round(pnl, 3), "outcome": outcome, "kind": pos["kind"],
            "entry_hm": entry_hm, "exit_hm": exit_hm, "em": round(pos["em"], 2)}


def backtest(books_by_sess: dict, q_by_sess: dict, p: dict) -> dict:
    trades, per_sess = [], {}
    for sess, (book, strikes) in books_by_sess.items():
        qday = q_by_sess.get(sess)
        if qday is None:
            continue
        got = 0
        for entry_hm in (600, 780):                   # 10:00 primary, 13:00 secondary
            if got >= 2:
                break
            r = _condor(book, strikes, qday, entry_hm, p)
            if r is None or r.get("gated"):
                continue
            r["session"] = str(sess)
            trades.append(r)
            got += 1
        per_sess[str(sess)] = got
    if not trades:
        return {"n": 0, "note": "no condors placed"}
    rr = np.array([t["ret"] for t in trades])
    wins, losses = rr[rr > 0], rr[rr <= 0]
    pf = float(wins.sum() / abs(losses.sum())) if losses.sum() < 0 else None
    # drawdown of the fixed-fractional equity curve (RISK_PCT of account per trade)
    eq = np.cumsum(rr) * (RISK_PCT / 100.0)
    peak = np.maximum.accumulate(np.concatenate([[0], eq]))
    dd_pct = float((peak - np.concatenate([[0], eq])).max() * 100)
    sig = np.array(list(per_sess.values()))
    win_pct = round(100 * float((rr > 0).mean()), 1)
    in_band = ((BAND_WIN[0] <= win_pct <= BAND_WIN[1]) and pf is not None
               and BAND_PF[0] <= pf <= BAND_PF[1] and dd_pct <= BAND_DD)
    return {"n": len(trades), "sessions": len(per_sess),
            "win_pct": win_pct, "pf": round(pf, 2) if pf is not None else None,
            "avg_ret": round(float(rr.mean()), 3), "maxDD_pct": round(dd_pct, 1),
            "signals_per_session": {"min": int(sig.min()), "max": int(sig.max()),
                                    "mean": round(float(sig.mean()), 2),
                                    "sessions_with_0": int((sig == 0).sum())},
            "outcomes": {k: sum(1 for t in trades if t["outcome"] == k)
                         for k in ("tp", "stop", "settle")},
            "avg_credit": round(float(np.mean([t["credit"] for t in trades])), 2),
            "in_band": bool(in_band), "params": p}


def main() -> None:
    _utf8()
    if not CHAIN.exists():
        raise SystemExit("run research/opra_extract.py first (need data/opra_qqq_cbbo.parquet)")
    day = load_0dte()
    qm = _qqq_minutes()
    books_by_sess = {s: build_book(d) for s, d in day.groupby("session")}   # index each session ONCE
    q_by_sess = {s: d for s, d in qm.groupby("date")}
    print(f"0DTE chain: {len(day):,} rows, {len(books_by_sess)} sessions", flush=True)

    grid = {"em_mult": [0.9, 1.0, 1.1, 1.25], "wing": [3, 4, 5, 6], "tp": [0.5, 0.6, 0.7],
            "stop_mult": [2.0, 2.5], "trend_mult": [1.0], "min_credit": [0.10],
            "directional": [True], "dir_em_mult": [1.75, 2.0], "dir_stop_mult": [1.0, 1.25]}
    keys = list(grid)
    results = []
    for combo in product(*[grid[k] for k in keys]):
        p = dict(zip(keys, combo))
        results.append(backtest(books_by_sess, q_by_sess, p))
    results = [r for r in results if r.get("n", 0) >= 15]
    # rank: in-band first, then by a band-distance score
    def score(r):
        w = 0 if BAND_WIN[0] <= r["win_pct"] <= BAND_WIN[1] else min(
            abs(r["win_pct"] - BAND_WIN[0]), abs(r["win_pct"] - BAND_WIN[1]))
        pf = r["pf"] or 0
        pfd = 0 if BAND_PF[0] <= pf <= BAND_PF[1] else min(abs(pf - BAND_PF[0]), abs(pf - BAND_PF[1])) * 40
        ddd = max(0, r["maxDD_pct"] - BAND_DD) * 3
        return (not r["in_band"], w + pfd + ddd)
    results.sort(key=score)
    best = results[0] if results else {"note": "no config placed >=15 trades"}
    chosen = backtest(books_by_sess, q_by_sess, SPEC)      # the locked spec (options-native-0.1)
    out = {"generated_at": pd.Timestamp.now("UTC").isoformat(),
           "target": {"win_pct": BAND_WIN, "pf": BAND_PF, "maxDD_pct": BAND_DD,
                      "signals_per_session": [1, 2]},
           "chosen_spec": chosen, "in_sample_caveat":
           "22 OPRA sessions / 28 trades, config chosen on this window — in-sample. The VRP edge is "
           "independently established (F85, 264 solves); this needs forward paper or a wider OPRA "
           "window to validate. Mechanics are honest: real bid/ask, causal, defined risk.",
           "grid_best": best, "top5": results[:5]}
    REPORT.parent.mkdir(parents=True, exist_ok=True)
    REPORT.write_text(json.dumps(out, indent=2), encoding="utf-8")
    print(f"\n=== options-native-0.1 CHOSEN SPEC: WR {chosen['win_pct']}% · PF {chosen['pf']} · "
          f"DD {chosen['maxDD_pct']}% · {chosen['signals_per_session']['mean']} sig/sess · "
          f"in_band={chosen['in_band']} ===")
    print("\n=== grid (best of tuning) ===")
    for r in results[:6]:
        sps = r["signals_per_session"]
        print(f"  WR {r['win_pct']:>5}%  PF {str(r['pf']):>5}  DD {r['maxDD_pct']:>4}%  "
              f"n={r['n']:>3}  sig/sess {sps['mean']} (0-days {sps['sessions_with_0']})  "
              f"{r['outcomes']}  {'** IN-BAND **' if r['in_band'] else ''}\n"
              f"       {r['params']}")
    print("report ->", REPORT)


if __name__ == "__main__":
    main()
