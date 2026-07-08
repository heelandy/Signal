#!/usr/bin/env python3
"""CREDIT-SPREAD GEOMETRY SWEEP — turn the -0.008R loser positive (user 2026-07-08).

The single 0DTE credit spread is the one red PF on the panel (WR 63.6 · PF 0.78 · AVG -0.008R).
That is NOT a market verdict — it is a CALIBRATION one: it wins +0.044R and loses -0.098R, so its
reward:risk demands a ~69% break-even win rate but it only hits 63.6%. This sweeps the four levers
that move that break-even line, on the SAME shared path the live journal uses:

    native.build(spec | structure="credit_spread")   # identical geometry to record_session / live
    native.walk_manage(pos, cost_fn, spec, ...)       # identical manager (TP tp*credit, stop dir*credit)

so a config that wins here wins live too (no research!=live artifact). For each config it reports
actual WR, the geometry's BREAK-EVEN WR (avgLoss / (avgWin+avgLoss)), and the MARGIN between them
(positive margin = positive expectancy). Ranks by expectancy, then PF, then closeness to the band.

    python research/opra_credit_spread.py
Report -> BOT/data/ml/reports/opra_credit_spread.json
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
sys.path.insert(0, str(ROOT / "research"))

import opra_condor as OC                              # reuse load_0dte / build_book / _spot / _open_price
from bot.options import native                        # shared geometry — research == live

REPORT = ROOT / "BOT" / "data" / "ml" / "reports" / "opra_credit_spread.json"
BAND_WIN = (75.0, 85.0)
BAND_PF = (1.6, 1.8)
BAND_DD = 11.0
RISK_PCT = 2.0
ENTRIES = (600, 780)                                  # 10:00 primary, 13:00 secondary


def _one(book: dict, strikes: dict, qday, entry_hm: int, p: dict) -> dict | None:
    """Build + MANAGE one credit spread through the shared native path (identical to live)."""
    spot, open_px = OC._spot(qday, entry_hm), OC._open_price(qday)
    if spot is None or open_px is None:
        return None
    q = lambda cp, K: book.get((cp, K, entry_hm))
    pos = native.build(spot, open_px, q, strikes, spec=dict(p, structure="credit_spread"))
    if pos is None:
        return None
    s_close = OC._spot(qday, 955) or OC._spot(qday, 954) or spot
    outcome, exit_hm, pnl = native.walk_manage(
        pos, lambda h: native._cost_to_close(pos, book, h), p, entry_hm, float(s_close))
    ml = pos["max_loss"]
    if ml <= 0:
        return None
    return {"ret": pnl / ml, "pnl": round(pnl, 3), "credit": pos["credit"], "max_loss": ml,
            "outcome": outcome, "kind": pos["kind"], "em": round(pos["em"], 2)}


def backtest(books_by_sess: dict, q_by_sess: dict, p: dict) -> dict:
    trades, per_sess = [], {}
    for sess, (book, strikes) in books_by_sess.items():
        qday = q_by_sess.get(sess)
        if qday is None:
            continue
        got = 0
        for entry_hm in ENTRIES:
            if got >= 2:
                break
            r = _one(book, strikes, qday, entry_hm, p)
            if r is None:
                continue
            trades.append(r)
            got += 1
        per_sess[str(sess)] = got
    if len(trades) < 15:
        return {"n": len(trades), "note": "thin"}
    rr = np.array([t["ret"] for t in trades])
    wins, losses = rr[rr > 0], rr[rr <= 0]
    wr = float((rr > 0).mean())
    avg_win = float(wins.mean()) if len(wins) else 0.0
    avg_loss = float(losses.mean()) if len(losses) else 0.0          # <= 0
    pf = float(wins.sum() / abs(losses.sum())) if losses.sum() < 0 else None
    # BREAK-EVEN WR the geometry demands: WR* s.t. WR*avgWin + (1-WR)*avgLoss = 0
    denom = avg_win - avg_loss                                       # = avgWin + |avgLoss| > 0
    be_wr = (-avg_loss / denom) if denom > 0 else None               # fraction
    margin = (wr - be_wr) if be_wr is not None else None             # +ve => positive expectancy
    eq = np.cumsum(rr) * (RISK_PCT / 100.0)
    peak = np.maximum.accumulate(np.concatenate([[0], eq]))
    dd_pct = float((peak - np.concatenate([[0], eq])).max() * 100)
    sig = np.array(list(per_sess.values()))
    win_pct = round(100 * wr, 1)
    in_band = ((BAND_WIN[0] <= win_pct <= BAND_WIN[1]) and pf is not None
               and BAND_PF[0] <= pf <= BAND_PF[1] and dd_pct <= BAND_DD)
    return {"n": len(trades), "sessions": len(per_sess), "win_pct": win_pct,
            "be_wr_pct": round(100 * be_wr, 1) if be_wr is not None else None,
            "margin_pts": round(100 * margin, 1) if margin is not None else None,
            "pf": round(pf, 2) if pf is not None else None, "avg_ret": round(float(rr.mean()), 4),
            "avg_win": round(avg_win, 3), "avg_loss": round(avg_loss, 3),
            "avg_credit": round(float(np.mean([t["credit"] for t in trades])), 3),
            "maxDD_pct": round(dd_pct, 1),
            "signals_per_session": {"min": int(sig.min()), "max": int(sig.max()),
                                    "mean": round(float(sig.mean()), 2),
                                    "sessions_with_0": int((sig == 0).sum())},
            "outcomes": {k: sum(1 for t in trades if t["outcome"] == k)
                         for k in ("tp", "stop", "settle")},
            "in_band": bool(in_band), "params": {k: p[k] for k in
                ("em_mult", "wing", "tp", "dir_stop_mult")}}


def main() -> None:
    OC._utf8()
    if not OC.CHAIN.exists():
        raise SystemExit("need data/opra_qqq_cbbo.parquet (run research/opra_extract.py)")
    day = OC.load_0dte()
    qm = OC._qqq_minutes()
    books_by_sess = {s: OC.build_book(d) for s, d in day.groupby("session")}
    q_by_sess = {s: d for s, d in qm.groupby("date")}
    print(f"0DTE chain: {len(day):,} rows, {len(books_by_sess)} sessions", flush=True)

    base = dict(native.SPEC)                                          # inherit min_credit etc.
    grid = {"em_mult": [0.7, 0.85, 1.0, 1.1, 1.25, 1.5],             # short-strike distance (xEM)
            "wing": [3, 4, 5, 6],                                     # defined-risk width ($)
            "tp": [0.4, 0.5, 0.6, 0.7],                               # take-profit (fraction of credit)
            "dir_stop_mult": [0.75, 1.0, 1.25, 1.5, 2.0]}            # hard stop (x credit)
    keys = list(grid)
    results = []
    for combo in product(*[grid[k] for k in keys]):
        p = dict(base, **dict(zip(keys, combo)))
        r = backtest(books_by_sess, q_by_sess, p)
        if r.get("n", 0) >= 15 and r.get("pf") is not None:
            results.append(r)

    baseline = backtest(books_by_sess, q_by_sess, native.SPEC)       # current shipped credit spread

    # rank: positive expectancy first, then PF, then closeness to the band
    def score(r):
        return (-(r["avg_ret"] > 0), -(r["pf"] or 0), -(r["margin_pts"] or -99))
    positive = sorted([r for r in results if r["avg_ret"] > 0], key=score)
    best = positive[0] if positive else None

    out = {"generated_at": pd.Timestamp.now("UTC").isoformat(),
           "band": {"win_pct": BAND_WIN, "pf": BAND_PF, "maxDD_pct": BAND_DD},
           "shared_path": "native.build(structure=credit_spread) + native.walk_manage",
           "in_sample_caveat": "22 OPRA sessions, config chosen on this window (in-sample). "
                               "Break-even margin is the honest lever; forward-paper before trusting.",
           "baseline_current_spec": baseline,
           "n_positive_configs": len(positive),
           "best_expectancy": best, "top10": positive[:10], "in_band": [r for r in results if r["in_band"]]}
    REPORT.parent.mkdir(parents=True, exist_ok=True)
    REPORT.write_text(json.dumps(out, indent=2), encoding="utf-8")

    b = baseline
    print(f"\nBASELINE (shipped SPEC): WR {b['win_pct']}% (needs {b['be_wr_pct']}%) "
          f"margin {b['margin_pts']:+}pts  PF {b['pf']}  AVG {b['avg_ret']:+}R  DD {b['maxDD_pct']}%")
    print(f"\n=== positive-expectancy configs: {len(positive)} / {len(results)} tested ===")
    print(f"{'em':>4} {'wing':>4} {'tp':>4} {'stop':>4} | {'WR%':>5} {'be%':>5} {'marg':>6} "
          f"{'PF':>5} {'AVG_R':>7} {'DD%':>5}  outcomes")
    for r in positive[:12]:
        pr = r["params"]
        print(f"{pr['em_mult']:>4} {pr['wing']:>4} {pr['tp']:>4} {pr['dir_stop_mult']:>4} | "
              f"{r['win_pct']:>5} {r['be_wr_pct']:>5} {r['margin_pts']:>+6} {str(r['pf']):>5} "
              f"{r['avg_ret']:>+7} {r['maxDD_pct']:>5}  {r['outcomes']}"
              f"{'  ** IN-BAND **' if r['in_band'] else ''}")
    print("\nreport ->", REPORT)


if __name__ == "__main__":
    main()
