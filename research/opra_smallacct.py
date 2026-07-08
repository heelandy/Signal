"""SMALL-ACCOUNT OPTIONS STRUCTURES — which one actually works, on REAL OPRA premiums (2026-07-08).

The iron condor hits WR but not PF (76.9% / 1.28). For a small account the user wants alternatives
(1 naked long · 2 credit spread · 3 debit spread) and: "if the strategy doesn't work, find another
one." This backtests each structure on the F85 OPRA chain (22 QQQ 0DTE sessions), with the credit
spread swept across short-strike distances (the panel's bug was selling far-OTM for $0.12), and
reports WR / PF / maxDD / avg capital-at-risk so we can pick what clears the goal band
(WR 75-85 · PF 1.6-1.8) with the least buying power.

    python research/opra_smallacct.py
Report -> BOT/data/ml/reports/opra_smallacct.json
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "research"))
sys.path.insert(0, str(ROOT / "BOT"))

import opra_condor as OC          # reuse load_0dte / build_book / _spot / _open_price
from bot.options import native    # noqa: E402

REPORT = ROOT / "BOT" / "data" / "ml" / "reports" / "opra_smallacct.json"
BAND = {"win": (75.0, 85.0), "pf": (1.6, 1.8)}
ENTRY_HM, CLOSE_HM = 600, 955     # 10:00 ET entry, 15:55 settle


def _band(win, pf):
    return bool(BAND["win"][0] <= win <= BAND["win"][1] and pf is not None
                and BAND["pf"][0] <= pf <= BAND["pf"][1])


def _stats(rets, capital):
    r = np.array(rets)
    if not len(r):
        return {"n": 0}
    wins, losses = r[r > 0], r[r <= 0]
    pf = float(wins.sum() / abs(losses.sum())) if losses.sum() < 0 else None
    eq = np.cumsum(r); dd = float(-(eq - np.maximum.accumulate(eq)).min())
    win = round(100 * float((r > 0).mean()), 1)
    return {"n": int(len(r)), "win_pct": win, "pf": round(pf, 2) if pf else None,
            "avg_ret": round(float(r.mean()), 3), "max_dd_r": round(dd, 1),
            "avg_capital_$": round(float(np.mean(capital)) * 100, 0),   # per 1 contract
            "in_band": _band(win, pf)}


def run(day_by_sess, q_by_sess):
    strikes_of = {s: OC.build_book(d)[1] for s, d in day_by_sess.items()}
    books = {s: OC.build_book(d)[0] for s, d in day_by_sess.items()}
    out = {}

    def entry_ctx(sess):
        qday = q_by_sess.get(sess)
        if qday is None:
            return None
        spot, opx = OC._spot(qday, ENTRY_HM), OC._open_price(qday)
        sclose = OC._spot(qday, CLOSE_HM) or OC._spot(qday, 954) or spot
        if spot is None or opx is None or sclose is None:
            return None
        book, strikes = books[sess], strikes_of[sess]
        em = native.expected_move(lambda cp, K: book.get((cp, K, ENTRY_HM)), strikes, spot)
        return spot, opx, sclose, book, strikes, em

    def q(book, cp, K):
        return book.get((cp, K, ENTRY_HM)) if K is not None else None

    # ---- 1) NAKED LONG (directional by the open lean) ----
    rets, cap = [], []
    for sess in day_by_sess:
        c = entry_ctx(sess)
        if not c:
            continue
        spot, opx, sclose, book, strikes, em = c
        cp = "C" if spot >= opx else "P"
        K = native.snap(strikes[cp], spot)                 # ATM
        qq = q(book, cp, K)
        if qq is None or qq[1] <= 0:
            continue
        debit = qq[1]                                      # pay the ask
        intrinsic = max((sclose - K) if cp == "C" else (K - sclose), 0.0)
        rets.append((intrinsic - debit) / debit)
        cap.append(debit)
    out["1_naked_long"] = _stats(rets, cap) | {"note": "ATM 0DTE, directional by open lean; risk=premium"}

    # ---- 2) CREDIT SPREAD swept across short-strike distance (fraction of EM) ----
    out["2_credit_spread"] = {}
    for frac in (0.3, 0.5, 0.7, 1.0):
        rets, cap = [], []
        for sess in day_by_sess:
            c = entry_ctx(sess)
            if not c:
                continue
            spot, opx, sclose, book, strikes, em = c
            if not em:
                continue
            cp = "P" if spot >= opx else "C"               # sell the safe side
            sgn = -1 if cp == "P" else +1
            sp = native._spread(lambda r, K: q(book, r, K), cp, strikes[cp],
                                spot + sgn * frac * em, 3.0, sgn)   # $3 wing (small account)
            if sp is None:
                continue
            ks, kl, wing, credit = sp
            if credit < 0.10:
                continue
            loss = np.clip((sclose - ks) if cp == "C" else (ks - sclose), 0, wing)
            pnl = credit - float(loss)
            ml = wing - credit
            if ml <= 0:                          # credit >= wing (0-day guard): skip, no divide-by-zero
                continue
            rets.append(pnl / ml); cap.append(ml)
        out["2_credit_spread"][f"{frac}xEM"] = _stats(rets, cap)

    # ---- 3) DEBIT SPREAD (directional by lean, ATM long / OTM short) ----
    rets, cap = [], []
    for sess in day_by_sess:
        c = entry_ctx(sess)
        if not c:
            continue
        spot, opx, sclose, book, strikes, em = c
        if not em:
            continue
        cp = "C" if spot >= opx else "P"
        sgn = +1 if cp == "C" else -1
        kl = native.snap(strikes[cp], spot)                # long ATM
        ks = native.snap(strikes[cp], spot + sgn * 0.7 * em)   # short OTM
        ql, qs = q(book, cp, kl), q(book, cp, ks)
        if ql is None or qs is None or kl is None or ks is None:
            continue
        debit = ql[1] - qs[0]                              # pay long ask, sell short bid
        width = abs(ks - kl)
        if debit <= 0 or width <= 0:
            continue
        li = max((sclose - kl) if cp == "C" else (kl - sclose), 0.0)
        si = max((sclose - ks) if cp == "C" else (ks - sclose), 0.0)
        payoff = min(li - si, width)
        rets.append((payoff - debit) / debit); cap.append(debit)
    out["3_debit_spread"] = _stats(rets, cap) | {"note": "ATM long / 0.7EM short, directional; risk=debit"}
    return out


def main():
    for s in (sys.stdout, sys.stderr):
        try:
            s.reconfigure(encoding="utf-8", errors="backslashreplace")
        except Exception:
            pass
    day = OC.load_0dte(); qm = OC._qqq_minutes()
    day_by_sess = {s: d for s, d in day.groupby("session")}
    q_by_sess = {s: d for s, d in qm.groupby("date")}
    res = run(day_by_sess, q_by_sess)
    out = {"generated_at": pd.Timestamp.now("UTC").isoformat(), "goal": BAND,
           "sessions": len(day_by_sess), "structures": res}
    REPORT.parent.mkdir(parents=True, exist_ok=True)
    REPORT.write_text(json.dumps(out, indent=2), encoding="utf-8")
    print(f"=== SMALL-ACCOUNT STRUCTURES ({len(day_by_sess)} QQQ 0DTE sessions) ===")
    n = res["1_naked_long"]; print(f"1 NAKED LONG : WR {n['win_pct']} PF {n['pf']} exp {n['avg_ret']}R "
                                   f"cap ~${n['avg_capital_$']} {'IN-BAND' if n['in_band'] else ''}")
    for k, v in res["2_credit_spread"].items():
        print(f"2 CREDIT {k:7}: WR {v['win_pct']} PF {v['pf']} exp {v['avg_ret']}R cap ~${v['avg_capital_$']} "
              f"{'<<< IN-BAND' if v['in_band'] else ''}")
    d = res["3_debit_spread"]; print(f"3 DEBIT SPRD : WR {d['win_pct']} PF {d['pf']} exp {d['avg_ret']}R "
                                     f"cap ~${d['avg_capital_$']} {'IN-BAND' if d['in_band'] else ''}")
    print("report ->", REPORT)


if __name__ == "__main__":
    main()
