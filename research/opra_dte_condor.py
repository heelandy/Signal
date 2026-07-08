#!/usr/bin/env python3
"""LONGER-DTE MANAGED CONDOR SWEEP — the only path to the band (user 2026-07-08, goal unchanged).

Goal stays WR 75-85 · PF 1.6-1.8 · DD <= 11%. Proven ceilings on this OPRA window: the 0DTE credit
spread caps at PF 1.11 (480 configs swept) and the 0DTE condor at ~1.35 — both below the band's PF
floor, because 0DTE has heavy negative skew (small frequent wins, large tail losses). The ONE credit
structure with PF headroom is the 14DTE iron condor (PF 2.32 hold-to-expiry, n=14) — but that number
was hold-only. This runs it through a REAL multi-day intraday manager (TP/stop on live OPRA marks),
on the SAME shared geometry the live path builds (native.build structure=condor), and sweeps the
knobs to see whether a managed longer-DTE condor lands in the band.

Entry once per session at 10:00 ET, expiry nearest D+target (7/14). Manage on a 30-min grid across
every session from entry to expiry: TP at tp*credit, hard stop at stop_mult*credit, else settle the
condor intrinsic at the expiry's QQQ close (native.settle_pnl). directional=False so we isolate the
CONDOR (trend days stand aside) — this is a pure structure read, not the min-1 production strategy.

    python research/opra_dte_condor.py
Report -> BOT/data/ml/reports/opra_dte_condor.json
"""
from __future__ import annotations

import json
import sys
from itertools import product
from pathlib import Path

import duckdb
import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "BOT"))
from bot.options import native                        # shared geometry — research == live build

CHAIN = ROOT / "data" / "opra_qqq_cbbo.parquet"
QQQ = ROOT / "data" / "qqq_continuous_1m.parquet"
REPORT = ROOT / "BOT" / "data" / "ml" / "reports" / "opra_dte_condor.json"
TARGETS = (7, 14)
ENTRY_HM = 600                                        # 10:00 ET
MARK_MINUTES = tuple(list(range(570, 955, 30)) + [954])   # 30-min grid + settle
BAND_WIN, BAND_PF, BAND_DD, RISK_PCT = (75.0, 85.0), (1.6, 1.8), 11.0, 2.0


def _utf8():
    for s in (sys.stdout, sys.stderr):
        try:
            s.reconfigure(encoding="utf-8", errors="backslashreplace")
        except Exception:
            pass


def _qqq():
    b = pd.read_parquet(QQQ, columns=["ts_et", "open", "close", "session"])
    et = pd.to_datetime(b["ts_et"]).dt.tz_convert("America/New_York").dt.tz_localize(None)
    b = b.assign(d=et.dt.date, hm=et.dt.hour * 60 + et.dt.minute)
    rth = b[b["session"] == "RTH"]
    spot = {(r.d, int(r.hm)): float(r.close) for r in rth.itertuples()}
    close = rth.groupby("d")["close"].last().to_dict()
    opng = {r.d: float(r.open) for r in rth[rth["hm"] == 570].itertuples()}
    return spot, close, opng


def load(target: int, mark_minutes) -> tuple[dict, dict, list]:
    """Index the chain for ONE target DTE: q[(expiry,session,cp,strike,hm)]=(bid,ask,mid) on the
    30-min mark grid, plus strikes[(expiry,session)]={C,P} and the list of (D,E) entry candidates."""
    con = duckdb.connect()
    con.execute("SET memory_limit='2GB'; SET threads=1; SET preserve_insertion_order=false")
    p = str(CHAIN).replace(chr(92), "/")
    mm = ",".join(str(m) for m in mark_minutes)
    # entry candidates: sessions where an expiry sits ~target days out (dte within +-3)
    cand = con.execute(
        f"SELECT DISTINCT session, expiry, dte FROM read_parquet('{p}') "
        f"WHERE dte BETWEEN {target-3} AND {target+3}").df()
    cand["session"] = pd.to_datetime(cand["session"]).dt.date
    cand["expiry"] = pd.to_datetime(cand["expiry"]).dt.date
    # for each session pick the expiry closest to target
    entries = []
    for D, g in cand.groupby("session"):
        row = g.iloc[(g["dte"] - target).abs().argmin()]
        entries.append((D, row["expiry"]))
    exp_set = sorted({e for _, e in entries})
    exp_lit = ",".join("'" + str(e) + "'" for e in exp_set)
    # load the full intraday life (mark grid) of just those expiries
    df = con.execute(
        f"SELECT session, expiry, cp, strike, "
        f"  (extract('hour' FROM minute)*60+extract('minute' FROM minute)) hm, bid, ask, mid "
        f"FROM read_parquet('{p}') "
        f"WHERE expiry IN ({exp_lit}) "
        f"  AND (extract('hour' FROM minute)*60+extract('minute' FROM minute)) IN ({mm})").df()
    con.close()
    df["session"] = pd.to_datetime(df["session"]).dt.date
    df["expiry"] = pd.to_datetime(df["expiry"]).dt.date
    q, strikes = {}, {}
    for r in df.itertuples():
        q[(r.expiry, r.session, r.cp, float(r.strike), int(r.hm))] = (float(r.bid), float(r.ask), float(r.mid))
    for (e, s), gg in df.groupby(["expiry", "session"]):
        strikes[(e, s)] = {cp: np.array(sorted(gg.loc[gg["cp"] == cp, "strike"].unique())) for cp in ("C", "P")}
    return q, strikes, entries


def _cost(q, pos, E, s, hm):
    """Cost to close the condor at (expiry E, session s, minute hm): buy shorts@ask, sell wings@bid.
    None if any active leg is unquoted that mark."""
    cost, ok = 0.0, True
    if pos.get("ksc") is not None:
        cc, cl = q.get((E, s, "C", pos["ksc"], hm)), q.get((E, s, "C", pos["klc"], hm))
        if cc is None or cl is None:
            ok = False
        else:
            cost += cc[1] - cl[0]
    if pos.get("ksp") is not None:
        pc, pl = q.get((E, s, "P", pos["ksp"], hm)), q.get((E, s, "P", pos["klp"], hm))
        if pc is None or pl is None:
            ok = False
        else:
            cost += pc[1] - pl[0]
    return cost if ok else None


def trade(q, strikes, spot, close, opng, D, E, p, sessions_sorted) -> dict | None:
    """Build a condor at (D,E) and MANAGE it minute-grid across sessions D..E (native geometry +
    the walk_manage RULE, generalized to multi-day). Settle native.settle_pnl at E's QQQ close."""
    s_entry, o_entry = spot.get((D, ENTRY_HM)), opng.get(D)
    if s_entry is None or o_entry is None or E not in close or (E, D) not in strikes:
        return None
    qe = lambda cp, K: q.get((E, D, cp, K, ENTRY_HM))
    pos = native.build(s_entry, o_entry, qe, strikes[(E, D)], spec=dict(p, structure="condor"),
                       directional=False)
    if pos is None or pos["kind"] != "condor":            # trend day stands aside (directional=False)
        return {"stand_aside": True}
    credit, ml = pos["credit"], pos["max_loss"]
    stop = p["stop_mult"]
    hold = [s for s in sessions_sorted if D <= s <= E]
    for s in hold:
        for hm in MARK_MINUTES:
            if s == D and hm <= ENTRY_HM:
                continue
            c = _cost(q, pos, E, s, hm)
            if c is None:
                continue
            pnl_now = credit - c
            if pnl_now >= p["tp"] * credit:
                return {"ret": (p["tp"] * credit) / ml, "outcome": "tp", "credit": credit, "ml": ml}
            if pnl_now <= -stop * credit:
                return {"ret": (-stop * credit) / ml, "outcome": "stop", "credit": credit, "ml": ml}
    pnl = native.settle_pnl(pos, float(close[E]))         # held to expiry -> intrinsic settle
    return {"ret": pnl / ml, "outcome": "settle", "credit": credit, "ml": ml}


def backtest(q, strikes, spot, close, opng, entries, p) -> dict:
    sessions_sorted = sorted({s for (_, s, *_2) in q.keys()})
    trades, aside = [], 0
    for D, E in entries:
        r = trade(q, strikes, spot, close, opng, D, E, p, sessions_sorted)
        if r is None:
            continue
        if r.get("stand_aside"):
            aside += 1
            continue
        trades.append(r)
    if len(trades) < 10:
        return {"n": len(trades), "note": "thin", "stand_aside": aside}
    rr = np.array([t["ret"] for t in trades])
    wins, losses = rr[rr > 0], rr[rr <= 0]
    wr = float((rr > 0).mean())
    aw = float(wins.mean()) if len(wins) else 0.0
    al = float(losses.mean()) if len(losses) else 0.0
    pf = float(wins.sum() / abs(losses.sum())) if losses.sum() < 0 else None
    denom = aw - al
    be = (-al / denom) if denom > 0 else None
    eq = np.cumsum(rr) * (RISK_PCT / 100.0)
    peak = np.maximum.accumulate(np.concatenate([[0], eq]))
    dd = float((peak - np.concatenate([[0], eq])).max() * 100)
    wp = round(100 * wr, 1)
    in_band = (BAND_WIN[0] <= wp <= BAND_WIN[1] and pf is not None
               and BAND_PF[0] <= pf <= BAND_PF[1] and dd <= BAND_DD)
    return {"n": len(trades), "stand_aside": aside, "win_pct": wp,
            "be_wr_pct": round(100 * be, 1) if be is not None else None,
            "margin_pts": round(100 * (wr - be), 1) if be is not None else None,
            "pf": round(pf, 2) if pf is not None else None, "avg_ret": round(float(rr.mean()), 4),
            "avg_win": round(aw, 3), "avg_loss": round(al, 3), "maxDD_pct": round(dd, 1),
            "outcomes": {k: sum(1 for t in trades if t["outcome"] == k) for k in ("tp", "stop", "settle")},
            "avg_credit": round(float(np.mean([t["credit"] for t in trades])), 3),
            "in_band": bool(in_band),
            "params": {k: p[k] for k in ("em_mult", "wing", "tp", "stop_mult")}}


def main():
    _utf8()
    if not CHAIN.exists():
        raise SystemExit("need data/opra_qqq_cbbo.parquet")
    spot, close, opng = _qqq()
    grid = {"em_mult": [0.8, 1.0, 1.2], "wing": [5, 8, 10], "tp": [0.5, 0.6, 0.75],
            "stop_mult": [1.5, 2.0, 2.5]}
    keys = list(grid)
    out = {"generated_at": pd.Timestamp.now("UTC").isoformat(), "band": {"win": BAND_WIN, "pf": BAND_PF, "dd": BAND_DD},
           "shared_path": "native.build(structure=condor) + multi-day walk_manage rule",
           "caveat": "in-sample OPRA window, ~20 trades/DTE, 30-min mark grid. Isolated condor "
                     "(directional=False). Forward-paper before trusting.", "by_dte": {}}
    for target in TARGETS:
        print(f"\n=== loading {target}DTE chain ...", flush=True)
        q, strikes, entries = load(target, MARK_MINUTES)
        print(f"    {len(entries)} entry candidates, {len(q):,} quote marks", flush=True)
        results = []
        for combo in product(*[grid[k] for k in keys]):
            p = dict(native.SPEC, **dict(zip(keys, combo)))
            r = backtest(q, strikes, spot, close, opng, entries, p)
            if r.get("n", 0) >= 10 and r.get("pf") is not None:
                results.append(r)
        results.sort(key=lambda r: (-(r["in_band"]), -(r["avg_ret"])))
        out["by_dte"][f"{target}DTE"] = {"n_configs": len(results),
                                         "in_band": [r for r in results if r["in_band"]],
                                         "top8": results[:8]}
        print(f"--- {target}DTE: {len(results)} configs, {sum(r['in_band'] for r in results)} in-band ---")
        print(f"{'em':>4} {'wing':>4} {'tp':>4} {'stop':>4} | {'WR%':>5} {'be%':>5} {'marg':>6} "
              f"{'PF':>6} {'AVG_R':>8} {'DD%':>5}  outcomes")
        for r in results[:8]:
            pr = r["params"]
            print(f"{pr['em_mult']:>4} {pr['wing']:>4} {pr['tp']:>4} {pr['stop_mult']:>4} | "
                  f"{r['win_pct']:>5} {r['be_wr_pct']:>5} {r['margin_pts']:>+6} {str(r['pf']):>6} "
                  f"{r['avg_ret']:>+8} {r['maxDD_pct']:>5}  {r['outcomes']}"
                  f"{'  ** IN-BAND **' if r['in_band'] else ''}")
    REPORT.parent.mkdir(parents=True, exist_ok=True)
    REPORT.write_text(json.dumps(out, indent=2), encoding="utf-8")
    print("\nreport ->", REPORT)


if __name__ == "__main__":
    main()
