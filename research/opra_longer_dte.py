"""LONGER-DTE OPTIONS STRUCTURES — 7 & 14 DTE, HOLD-to-expiry vs MANAGED (user 2026-07-08).

0DTE premium selling only works with intraday management (F87). Longer DTE changes the math:
smoother theta, and you can MANAGE by closing early at a profit target (now possible — the Alpaca
feed is wired). This tests, on the F85 OPRA chain (expiries out to 30d):

  credit spread · iron condor · naked long   at 7 and 14 DTE
  HOLD-to-expiry  vs  MANAGED (close early when the position reaches +50% of the credit)

Entry/mark at the daily close snapshot (~15:55 ET); settle at the expiry date's QQQ close.
Report -> BOT/data/ml/reports/opra_longer_dte.json
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import duckdb
import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
CHAIN = ROOT / "data" / "opra_qqq_cbbo.parquet"
REPORT = ROOT / "BOT" / "data" / "ml" / "reports" / "opra_longer_dte.json"
TARGETS = (7, 14)
WING = 5.0
TP_FRAC = 0.50            # managed: close when the credit position is +50% of credit
BAND = {"win": (75.0, 85.0), "pf": (1.6, 1.8)}


def _snap(arr, target, tol=2.0):
    if not len(arr):
        return None
    k = float(arr[int(np.abs(np.asarray(arr) - target).argmin())])
    return k if abs(k - target) <= tol else None


def load():
    con = duckdb.connect()
    con.execute("SET memory_limit='1GB'; SET threads=1; SET preserve_insertion_order=false")
    # one daily-close snapshot per (session, expiry, strike, cp)
    df = con.execute(
        "SELECT session, expiry, dte, cp, strike, bid, ask, "
        "row_number() OVER (PARTITION BY session,expiry,cp,strike "
        "  ORDER BY minute DESC) rn "
        "FROM read_parquet('" + str(CHAIN).replace(chr(92), '/') + "') "
        "WHERE (extract('hour' FROM minute)*60+extract('minute' FROM minute)) BETWEEN 950 AND 959 "
        "QUALIFY rn=1").df()
    con.close()
    df["session"] = pd.to_datetime(df["session"]).dt.date
    df["expiry"] = pd.to_datetime(df["expiry"]).dt.date
    return df


def _qqq_close():
    b = pd.read_parquet(ROOT / "data" / "qqq_continuous_1m.parquet", columns=["ts_et", "close", "session"])
    et = pd.to_datetime(b["ts_et"]).dt.tz_convert("America/New_York")
    rth = b[b["session"] == "RTH"].assign(d=et.dt.date)
    return rth.groupby("d")["close"].last().to_dict()


def _book(g):                       # {(cp,strike): (bid,ask)} for one (session,expiry) snapshot
    return {(r.cp, float(r.strike)): (float(r.bid), float(r.ask)) for r in g.itertuples()}


def _stats(rets, band=True):
    r = np.array(rets)
    if len(r) < 8:
        return {"n": int(len(r)), "note": "thin"}
    wins, losses = r[r > 0], r[r <= 0]
    pf = float(wins.sum() / abs(losses.sum())) if losses.sum() < 0 else None
    eq = np.cumsum(r); dd = float(-(eq - np.maximum.accumulate(eq)).min())
    win = round(100 * float((r > 0).mean()), 1)
    d = {"n": int(len(r)), "win_pct": win, "pf": round(pf, 2) if pf else None,
         "avg_ret": round(float(r.mean()), 3), "max_dd_r": round(dd, 1)}
    if band:
        d["in_band"] = bool(BAND["win"][0] <= win <= BAND["win"][1] and pf is not None
                            and BAND["pf"][0] <= pf <= BAND["pf"][1])
    return d


def study():
    df = load()
    qc = _qqq_close()
    sessions = sorted(df["session"].unique())
    # index snapshots: books[(session, expiry)] = book, strikes[(session,expiry)] = {C:.., P:..}
    books, strikes = {}, {}
    for (s, e), g in df.groupby(["session", "expiry"]):
        books[(s, e)] = _book(g)
        strikes[(s, e)] = {cp: np.array(sorted(g.loc[g["cp"] == cp, "strike"].unique())) for cp in ("C", "P")}
    out = {}
    for T in TARGETS:
        cs_hold, cs_mgd, cond_hold, naked = [], [], [], []
        for D in sessions:
            spot = qc.get(D)
            if spot is None:
                continue
            # expiry closest to T days out, present at D, with a QQQ settle close available
            cands = [e for (s, e) in books if s == D and (e - D).days >= 3 and e in qc]
            if not cands:
                continue
            E = min(cands, key=lambda e: abs((e - D).days - T))
            if abs((E - D).days - T) > 4:
                continue
            bk, stk = books[(D, E)], strikes[(D, E)]
            q = lambda cp, K: bk.get((cp, float(K))) if K is not None else None
            s_settle = qc[E]
            # expected move for THIS expiry (ATM straddle)
            kc0, kp0 = _snap(stk["C"], spot), _snap(stk["P"], spot)
            qc0, qp0 = q("C", kc0), q("P", kp0)
            if not qc0 or not qp0:
                continue
            em = (qc0[0] + qc0[1]) / 2 + (qp0[0] + qp0[1]) / 2
            if em <= 0:
                continue
            # --- CREDIT SPREAD: short ~0.5*EM OTM on the safe side (sell puts if flat/up) ---
            ksp = _snap(stk["P"], spot - 0.5 * em); klp = _snap(stk["P"], (ksp or spot) - WING)
            sp, lp = q("P", ksp), q("P", klp)
            if sp and lp and ksp and klp:
                credit = sp[0] - lp[1]; wing = abs(ksp - klp)
                if credit >= 0.10 and wing > credit:      # wing>credit => max_loss>0 (0-day guard)
                    ml = wing - credit
                    loss = np.clip(ksp - s_settle, 0, wing)          # settle intrinsic
                    cs_hold.append((credit - float(loss)) / ml)
                    # MANAGED: close early at +50% credit if any intermediate day's mark allows
                    closed = False
                    for Dm in [d for d in sessions if D < d < E and (Dm := d) and (Dm, E) in books]:
                        b2 = books[(Dm, E)]
                        s2, l2 = b2.get(("P", ksp)), b2.get(("P", klp))
                        if s2 and l2:
                            cost_close = s2[1] - l2[0]               # buy back short@ask, sell wing@bid
                            if credit - cost_close >= TP_FRAC * credit:
                                cs_mgd.append(TP_FRAC * credit / ml); closed = True; break
                    if not closed:
                        cs_mgd.append((credit - float(loss)) / ml)
            # --- IRON CONDOR (hold) ---
            ksc = _snap(stk["C"], spot + 0.5 * em); klc = _snap(stk["C"], (ksc or spot) + WING)
            sc, lc = q("C", ksc), q("C", klc)
            if sp and lp and sc and lc and ksc and klc and ksp and klp:
                cr = (sp[0] - lp[1]) + (sc[0] - lc[1]); wing = min(abs(ksp - klp), abs(klc - ksc))
                if cr >= 0.10 and wing > cr:              # wing>credit => max_loss>0 (0-day guard)
                    ml = wing - cr
                    cost = np.clip(s_settle - ksc, 0, wing) + np.clip(ksp - s_settle, 0, wing)
                    cond_hold.append((cr - float(cost)) / ml)
            # --- NAKED LONG (ATM, directional by a simple up/down vs prior close) ---
            cp = "C" if s_settle >= spot else "P"        # (reference — uses realized dir; optimistic)
            kL = _snap(stk[cp], spot); qL = q(cp, kL)
            if qL and qL[1] > 0:
                debit = qL[1]
                intr = max((s_settle - kL) if cp == "C" else (kL - s_settle), 0.0)
                naked.append((intr - debit) / debit)
        out[f"{T}DTE"] = {
            "credit_spread_HOLD": _stats(cs_hold),
            "credit_spread_MANAGED_50pct": _stats(cs_mgd),
            "iron_condor_HOLD": _stats(cond_hold),
            "naked_long_ref": _stats(naked, band=False)}
    return out


def main():
    for s in (sys.stdout, sys.stderr):
        try:
            s.reconfigure(encoding="utf-8", errors="backslashreplace")
        except Exception:
            pass
    res = study()
    out = {"generated_at": pd.Timestamp.now("UTC").isoformat(), "goal": BAND,
           "wing": WING, "tp_frac": TP_FRAC, "results": res}
    REPORT.parent.mkdir(parents=True, exist_ok=True)
    REPORT.write_text(json.dumps(out, indent=2), encoding="utf-8")
    for dte, r in res.items():
        print(f"=== {dte} ===")
        for k, v in r.items():
            if v.get("n", 0) >= 8:
                print(f"  {k:26}: n={v['n']} WR {v.get('win_pct')} PF {v.get('pf')} "
                      f"exp {v.get('avg_ret')}R DD {v.get('max_dd_r')}R {'<<< IN-BAND' if v.get('in_band') else ''}")
            else:
                print(f"  {k:26}: thin (n={v.get('n')})")
    print("report ->", REPORT)


if __name__ == "__main__":
    main()
