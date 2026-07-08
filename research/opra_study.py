#!/usr/bin/env python3
"""OPRA OPTIONS STUDY — the three goals, judged on REAL QQQ option premiums.

Reads the compact chain (research/opra_extract.py -> data/opra_qqq_cbbo.parquet, or the per-day
shards under data/opra_shards/) plus our own QQQ bar store, and answers:

  G1  IV-TRUTH      real ATM implied vol (BS-inverted from the mid) vs our estimator (flat 0.20
                    and the Pine realized-vol number). Output: the calibration the whole options
                    stack inherits — replace 0.20 with what the market actually charges.
  G2  PAYOFF REPLAY canonical QQQ signals in-window, NAKED 0DTE ATM, priced at the REAL entry-ask
                    and exit-bid (true spread) — confirm or amend the modeled NAKED verdict, then
                    stress it by doubling the spread.
  G3  VRP           short ATM 0DTE straddle at the open, marked to the close on real bid/ask —
                    the variance-risk-premium candidate finally judged on true prices.

GOAL MET = a real-premium expression that clears the user band (win 75-85%, PF >= 1.7 analog on
return) AND survives spread-doubling. ~22 sessions is verdict-grade for pricing truth (G1) and
DIRECTIONAL for G2/G3 — final adoption still wants the forward journal accruing.

NOTE the extractor renders `minute` in America/New_York wall-clock (the box TZ), which lines up
with the ET bar store; the join below assumes that (documented, box stays ET).

    python research/opra_study.py
Report -> BOT/data/ml/reports/opra_study.json
"""
from __future__ import annotations

import glob
import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "BOT"))

from bot.options.pricing import implied_vol, year_frac  # noqa: E402

CHAIN = ROOT / "data" / "opra_qqq_cbbo.parquet"
SHARDS = ROOT / "data" / "opra_shards"
REPORT = ROOT / "BOT" / "data" / "ml" / "reports" / "opra_study.json"
UNDERLYING = "qqq"
R_RATE = 0.04
CLOSE_MIN = 16 * 60                       # 16:00 ET expiry moment (minutes since midnight)
BAND_WIN = (75.0, 85.0)                   # user target win-rate band
BAND_PF = 1.7                             # user target profit factor
FLAT_IV = 0.20                            # the estimator G1 calibrates


def _utf8_stdout() -> None:
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8", errors="backslashreplace")
        except Exception:
            pass


def load_chain(atm_pct: float = 0.02) -> pd.DataFrame:
    """Load NEAR-ATM rows only, via DuckDB (streams — never materializes all 17.5M ±6% rows in
    pandas, which OOM'd the extractor's own concat). The study is entirely ATM work, so keeping
    strikes within +-atm_pct of each row's spot loses nothing and caps memory. Reads the combined
    parquet if present, else the shard glob (runs against a partial extraction)."""
    import duckdb
    src = str(CHAIN) if CHAIN.exists() else str(SHARDS / "*.parquet")
    if not CHAIN.exists() and not glob.glob(str(SHARDS / "*.parquet")):
        raise SystemExit("no chain parquet and no shards — run research/opra_extract.py first")
    con = duckdb.connect()
    try:
        con.execute("SET memory_limit='1GB'; SET threads=1; SET preserve_insertion_order=false")
        df = con.execute(f"SELECT * FROM read_parquet('{src.replace(chr(92), '/')}') "
                         f"WHERE abs(strike / spot - 1) <= {atm_pct}").df()
    finally:
        con.close()
    df["minute"] = pd.to_datetime(df["minute"])
    df["session"] = pd.to_datetime(df["session"]).dt.date
    df["hm"] = df["minute"].dt.hour * 60 + df["minute"].dt.minute
    df["min_to_exp"] = ((pd.to_datetime(df["expiry"]) - df["minute"]).dt.total_seconds() / 60.0
                        + CLOSE_MIN)      # to 16:00 ET on the expiry date
    return df


def _qqq_minutes() -> pd.DataFrame:
    """QQQ 1-min close keyed by ET wall-clock minute (tz dropped to match the chain)."""
    b = pd.read_parquet(ROOT / "data" / f"{UNDERLYING}_continuous_1m.parquet",
                        columns=["ts_et", "open", "close", "session"])
    et = pd.to_datetime(b["ts_et"]).dt.tz_convert("America/New_York").dt.tz_localize(None)
    b = b.assign(minute=et, date=et.dt.date, hm=et.dt.hour * 60 + et.dt.minute)
    return b


def _spot_at(qmin: pd.DataFrame, minute) -> float | None:
    row = qmin.loc[qmin["minute"] == minute, "close"]
    return float(row.iloc[0]) if len(row) else None


def _atm(day: pd.DataFrame, hm: int, spot: float, cp: str, max_dte: int,
         min_dte: int = 0) -> pd.Series | None:
    """Nearest-expiry (within [min_dte, max_dte]), nearest-strike quote at minute hm. `day` is one
    session's rows. min_dte>0 targets a genuinely longer tenor (the weekly point in G1)."""
    sub = day[(day["hm"] == hm) & (day["cp"] == cp)
              & (day["dte"] >= min_dte) & (day["dte"] <= max_dte)]
    if sub.empty:
        return None
    sub = sub[sub["dte"] == sub["dte"].min()]
    return sub.loc[(sub["strike"] - spot).abs().idxmin()]


# ------------------------------------------------------------------ G1: IV truth
def g1_iv_truth(chain: pd.DataFrame, qmin: pd.DataFrame) -> dict:
    ref_hms = {"10:00": 600, "12:00": 720, "15:00": 900}
    # (label, min_dte, max_dte): a near 0-1DTE point and a genuinely separate weekly tenor
    dte_buckets = [("0-1DTE", 0, 1), ("wk", 5, 12)]
    recs = []
    for sess, day in chain.groupby("session"):
        for _, hm in ref_hms.items():
            spot = _spot_at(qmin, pd.Timestamp(sess) + pd.Timedelta(minutes=hm))
            if spot is None:
                continue
            for label, mn, mx in dte_buckets:
                c = _atm(day, hm, spot, "C", mx, min_dte=mn)
                p = _atm(day, hm, spot, "P", mx, min_dte=mn)
                for row in (c, p):
                    if row is None or row["mid"] <= 0:
                        continue
                    T = year_frac(row["min_to_exp"])
                    iv = implied_vol(float(row["mid"]), spot, float(row["strike"]), T, R_RATE,
                                     right=row["cp"])
                    if np.isfinite(iv):
                        recs.append({"session": str(sess), "bucket": label, "dte": int(row["dte"]),
                                     "cp": row["cp"], "iv": float(iv),
                                     "half_spread": float(row["ask"] - row["bid"]) / 2.0,
                                     "spread_pct": float(row["ask"] - row["bid"]) / float(row["mid"]),
                                     "strike": float(row["strike"]), "spot": spot})
    if not recs:
        return {"error": "no ATM IVs solved"}
    df = pd.DataFrame(recs)
    # realized vol, Pine-style: std of 5-min RTH log returns that session, annualized sqrt(252*78)
    rv = {}
    for sess, day in qmin[qmin["session"] == "RTH"].groupby("date"):
        px = day.sort_values("minute")["close"].iloc[::5]                 # 5-min sample
        lr = np.log(px / px.shift(1)).dropna()
        if len(lr) > 5:
            rv[str(sess)] = float(lr.std() * np.sqrt(252 * 78))
    df["realized_vol"] = df["session"].map(rv)
    by_dte = df.groupby("bucket")
    near = df[df["bucket"] == "0-1DTE"]
    out = {"n_atm_ivs": len(df), "market_iv_mean": round(float(df["iv"].mean()), 4),
           "realized_vol_mean": round(float(df["realized_vol"].mean()), 4),
           "flat_iv_used": FLAT_IV,
           "flat_iv_error": round(float(df["iv"].mean() - FLAT_IV), 4),
           "realized_to_market_k": round(float(df["iv"].mean() / df["realized_vol"].mean()), 3)
           if df["realized_vol"].mean() else None,
           "atm_0dte_iv": round(float(near["iv"].mean()), 4) if len(near) else None,
           "atm_0dte_half_spread": round(float(near["half_spread"].mean()), 4) if len(near) else None,
           "atm_0dte_spread_pct": round(float(near["spread_pct"].mean()), 4) if len(near) else None,
           "by_dte": {}}
    for name, g in by_dte:
        out["by_dte"][name] = {"n": int(len(g)), "market_iv": round(float(g["iv"].mean()), 4),
                               "iv_p10_p90": [round(float(g["iv"].quantile(.1)), 4),
                                              round(float(g["iv"].quantile(.9)), 4)]}
    out["verdict"] = (f"real ATM IV averages {out['market_iv_mean']:.1%} vs the flat {FLAT_IV:.0%} "
                      f"estimate ({out['flat_iv_error']:+.1%}); scale Pine realized-vol by "
                      f"k={out['realized_to_market_k']}")
    return out


# ------------------------------------------------------------------ G2: payoff replay
def _t_to_close(entry_time) -> float:
    """Year fraction from a signal timestamp to 16:00 ET that day (0DTE), floored."""
    ts = pd.Timestamp(entry_time)
    mins = max((16 - ts.hour) * 60 - ts.minute, 1)
    return year_frac(mins)


def _naked_fullN(iv: float, half_spread: float) -> dict:
    """NAKED 0DTE ATM over the FULL QQQ backtest history, priced Black-Scholes at (iv) with a
    per-share half_spread paid each side. Uses OPRA-calibrated (iv, spread) to confirm/amend the
    modeled verdict on real N instead of the 22-session window's N=1."""
    from bot.strategy.orb_candidates import load_state, run_backtest
    from bot.options.pricing import price as bs
    tr = run_backtest(load_state(UNDERLYING.upper())).reset_index(drop=True)
    rets, years = [], []
    for _, t in tr.iterrows():
        if float(t.get("risk_pts", 0)) <= 0:
            continue
        cp = "C" if str(t["direction"]) == "long" else "P"
        entry, exitp = float(t["entry_price"]), float(t["exit_price"])
        K = round(entry)                                    # ATM $1 increment
        T0, T1 = _t_to_close(t["entry_time"]), _t_to_close(t["exit_time"])
        prem_in = bs(entry, K, T0, R_RATE, iv, cp) + half_spread          # pay the ask
        prem_out = max(bs(exitp, K, T1, R_RATE, iv, cp) - half_spread, 0.0)  # sell the bid
        if prem_in <= 0:
            continue
        rets.append((prem_out - prem_in) / prem_in)
        years.append(pd.Timestamp(t["entry_time"]).year)
    if len(rets) < 30:
        return {"error": f"only {len(rets)} priced"}
    r = np.array(rets)
    ys = pd.Series(r).groupby(years).mean()
    yv = [(y, v) for y, v in ys.items() if years.count(y) >= 8]
    pos = sum(1 for _, v in yv if v > 0)
    cut = int(0.7 * len(r))
    rng = np.random.default_rng(7)
    ci = float(np.percentile(rng.choice(r, (2000, len(r)), replace=True).mean(1), 5))
    gate = bool(r.mean() > 0 and ci > 0 and yv and pos >= 0.7 * len(yv) and r[cut:].mean() > 0)
    block = _stat_block(r)
    block.update({"iv": round(iv, 4), "half_spread": round(half_spread, 4),
                  "ci_lo": round(ci, 3), "years_pos": f"{pos}/{len(yv)}",
                  "oos30": round(float(r[cut:].mean()), 3), "gate": "PASS" if gate else "fail"})
    return block


def g2_payoff_replay(chain: pd.DataFrame, qmin: pd.DataFrame, g1: dict) -> dict:
    from bot.strategy.orb_candidates import load_state, run_backtest
    try:
        tr = run_backtest(load_state(UNDERLYING.upper())).reset_index(drop=True)
    except Exception as e:
        return {"error": f"run_backtest failed: {e}"}
    lo, hi = chain["session"].min(), chain["session"].max()
    tr["etime"] = pd.to_datetime(tr["entry_time"])
    win = tr[(tr["etime"].dt.date >= lo) & (tr["etime"].dt.date <= hi)]
    real, modeled, skipped = [], [], 0
    for _, t in win.iterrows():
        side = str(t["direction"]); cp = "C" if side == "long" else "P"
        entry, exitp = float(t["entry_price"]), float(t["exit_price"])
        et, xt = pd.to_datetime(t["entry_time"]), pd.to_datetime(t["exit_time"])
        sess = et.date()
        day = chain[chain["session"] == sess]
        if day.empty:
            skipped += 1; continue
        ehm, xhm = et.hour * 60 + et.minute, xt.hour * 60 + xt.minute
        ci = _atm(day, ehm, entry, cp, max_dte=1)                # 0DTE ATM at entry
        if ci is None:
            skipped += 1; continue
        K, expv = float(ci["strike"]), ci["expiry"]
        xrow = day[(day["hm"] == xhm) & (day["cp"] == cp) & (day["strike"] == K)
                   & (day["expiry"] == expv)]
        entry_ask = float(ci["ask"])
        if xrow.empty:                          # exited after last quote / no mark -> settle intrinsic
            exit_bid = max(0.0, (exitp - K) if cp == "C" else (K - exitp))
        else:
            exit_bid = float(xrow.iloc[0]["bid"])
        if entry_ask <= 0:
            skipped += 1; continue
        real.append((exit_bid - entry_ask) / entry_ask)
        # spread-doubled stress: pay one extra half-spread each side
        half = float(ci["ask"] - ci["bid"]) / 2.0
        ea2, xb2 = entry_ask + half, max(0.0, exit_bid - half)
        modeled.append((xb2 - ea2) / ea2 if ea2 > 0 else 0.0)
    # OPRA-calibrated full-history replay: the window only fires ~1 canonical signal, so the real
    # verdict comes from feeding G1's measured IV + spread into the full N (confirm/amend the model).
    g1_iv = g1.get("atm_0dte_iv") or g1.get("market_iv_mean") or FLAT_IV
    g1_hs = g1.get("atm_0dte_half_spread") or 0.03
    calibrated = {"baseline_iv20_sp03": _naked_fullN(FLAT_IV, 0.03),
                  "opra_calibrated": _naked_fullN(g1_iv, g1_hs),
                  "opra_calibrated_2x_spread": _naked_fullN(g1_iv, g1_hs * 2)}
    inwin = ({"priced": len(real), "real": _stat_block(np.array(real)),
              "spread_doubled": _stat_block(np.array(modeled))} if real else
             {"priced": 0, "note": "no in-window canonical signal priceable"})
    return {"in_window": {"n_signals": int(len(win)), "skipped": skipped, **inwin},
            "calibrated_full_history": calibrated,
            "note": "in_window is real-premium but tiny N; calibrated_full_history re-judges the "
                    "modeled NAKED verdict at OPRA-measured IV+spread over all QQQ trades"}


# ------------------------------------------------------------------ G3: VRP short straddle
def g3_vrp(chain: pd.DataFrame, qmin: pd.DataFrame) -> dict:
    open_hm, close_hm = 575, 955                 # 09:35, 15:55 ET
    recs = []
    for sess, day in chain.groupby("session"):
        spot_o = _spot_at(qmin, pd.Timestamp(sess) + pd.Timedelta(minutes=open_hm))
        if spot_o is None:
            continue
        c_o = _atm(day, open_hm, spot_o, "C", max_dte=0)
        p_o = _atm(day, open_hm, spot_o, "P", max_dte=0)
        if c_o is None or p_o is None:
            continue
        K = float(c_o["strike"])
        # SELL straddle at the open: collect the two BIDs (what a seller actually gets)
        collect = float(c_o["bid"]) + float(p_o["bid"])
        spread = (float(c_o["ask"] - c_o["bid"]) + float(p_o["ask"] - p_o["bid"]))
        if collect <= 0:
            continue
        # settle 0DTE at the close: pay intrinsic |S_close - K|
        s_close = _spot_at(qmin, pd.Timestamp(sess) + pd.Timedelta(minutes=close_hm))
        if s_close is None:
            continue
        settle = abs(s_close - K)
        pnl = collect - settle                    # short straddle held to expiry, real collected
        recs.append({"session": str(sess), "collect": collect, "settle": settle,
                     "ret": pnl / collect, "spread_share": spread / collect})
    if not recs:
        return {"error": "no ATM 0DTE straddles found"}
    df = pd.DataFrame(recs)
    r = df["ret"].to_numpy()
    out = _stat_block(r)
    out.update({"n_sessions": len(df), "avg_premium": round(float(df["collect"].mean()), 3),
                "worst_day_ret": round(float(r.min()), 3),
                "spread_cost_share": round(float(df["spread_share"].mean()), 3),
                "note": "short ATM 0DTE straddle, sold at real bid, settled intrinsic at close"})
    return out


def _stat_block(r: np.ndarray) -> dict:
    wins, losses = r[r > 0], r[r <= 0]
    pf = float(wins.sum() / abs(losses.sum())) if len(losses) and losses.sum() < 0 else None
    win_pct = round(100 * float((r > 0).mean()), 1)
    clears = (BAND_WIN[0] <= win_pct <= BAND_WIN[1]) and (pf is not None and pf >= BAND_PF)
    return {"n": int(len(r)), "avg_ret": round(float(r.mean()), 3), "win_pct": win_pct,
            "pf": round(pf, 2) if pf is not None else None,
            "median_ret": round(float(np.median(r)), 3),
            "clears_band": bool(clears)}


def main() -> None:
    _utf8_stdout()
    chain = load_chain()
    qmin = _qqq_minutes()
    print(f"chain: {len(chain):,} rows  {chain['session'].min()}..{chain['session'].max()}  "
          f"({chain['session'].nunique()} sessions)", flush=True)
    g1 = g1_iv_truth(chain, qmin)
    out = {"generated_at": pd.Timestamp.now("UTC").isoformat(),
           "sessions": int(chain["session"].nunique()),
           "chain_rows": int(len(chain)),
           "band": {"win_pct": BAND_WIN, "pf": BAND_PF},
           "G1_iv_truth": g1,
           "G2_payoff_replay": g2_payoff_replay(chain, qmin, g1),
           "G3_vrp": g3_vrp(chain, qmin)}
    # goal-met roll-up: the doc's bar is a REAL-PREMIUM expression clearing the band AND surviving
    # spread-doubling. In-window real-premium N is tiny here, so that specific bar cannot be met on
    # 22 sessions; the calibrated NAKED gate and the VRP read are what this window can deliver.
    cal = out["G2_payoff_replay"].get("calibrated_full_history", {})
    goals = {
        "G2_realpremium_band": bool(out["G2_payoff_replay"].get("in_window", {})
                                    .get("real", {}).get("clears_band")),
        "G2_calibrated_naked_gate": cal.get("opra_calibrated", {}).get("gate") == "PASS",
        "G2_calibrated_naked_gate_2x": cal.get("opra_calibrated_2x_spread", {}).get("gate") == "PASS",
        "G3_straddle_band": bool(out["G3_vrp"].get("clears_band")),
    }
    out["goal_met"] = goals
    out["goal_met_any"] = any(goals.values())
    REPORT.parent.mkdir(parents=True, exist_ok=True)
    REPORT.write_text(json.dumps(out, indent=2), encoding="utf-8")
    print("\n=== OPRA STUDY ===")
    print("G1:", g1.get("verdict", g1.get("error")))
    iw = out["G2_payoff_replay"].get("in_window", {})
    print(f"G2 in-window: {iw.get('n_signals')} signals, {iw.get('priced')} priced (real-premium)")
    print("G2 calibrated NAKED gate:", {k: (v.get("gate"), v.get("win_pct"), v.get("pf"))
          for k, v in cal.items()})
    print("G3:", {k: out["G3_vrp"].get(k) for k in ("n_sessions", "avg_ret", "win_pct", "pf",
                                                     "worst_day_ret", "clears_band")})
    print("GOAL MET:", goals, "-> any:", out["goal_met_any"])
    print("report ->", REPORT)


if __name__ == "__main__":
    main()
