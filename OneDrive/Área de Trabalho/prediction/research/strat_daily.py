#!/usr/bin/env python3
"""
F52 — FOUR new STANDALONE strategies on DAILY bars, each through the gauntlet (exp>0 net of costs, bootstrap
CI>0, both sides where applicable, >=70% years +, 70/30 OOS-out>0). These are NOT ORB filters — they are
independent return streams to assess for diversification vs the intraday breakout stack.

  vix     : VIX-spike mean-reversion — VIX close > sma5*(1+thr) (panic) -> LONG the equity index, exit in N days
            or when VIX falls back under sma5. Long-only, equities only (NQ/ES/QQQ/SPY).
  donchian: Turtle channel breakout — enter on a break of the prior N-day high/low (stop fill at the level),
            exit on the opposite M-day channel (M=N//2) or a 2*ATR stop. Both directions. N in {20,55}.
  connors : Connors RSI-2 mean reversion — close>SMA200 & RSI2<thr -> LONG (exit close>SMA5); mirror short.
  volbreak: Crabel/Williams volatility breakout — intraday break of open +/- k*prior-day-range, EOD (close) exit.

Entry/exit are causal (signals from completed bars; breakout fills at the level, MOC fills at the close).
Costs: round-trip slippage+commission per the asset, converted to %.

    python research/strat_daily.py [SYM ...]      (default NQ ES QQQ SPY GC)
"""
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "engine"))
import numpy as np, pandas as pd
import hs_db, hs_validate as V

rng = np.random.default_rng(7)
EQ = {"NQ", "ES", "QQQ", "SPY"}


def load(con, sym):
    d = hs_db.bars(con, "1d", "rth", sym=sym).sort_values("ts").reset_index(drop=True)
    d["dt"] = pd.to_datetime(d["ts"], utc=True)
    return d


def atr(d, n=14):
    h, l, c = d["high"].to_numpy(), d["low"].to_numpy(), d["close"].to_numpy()
    pc = np.concatenate([[c[0]], c[:-1]])
    tr = np.maximum(h - l, np.maximum(np.abs(h - pc), np.abs(l - pc)))
    return pd.Series(tr).rolling(n, min_periods=1).mean().to_numpy()


def rsi(c, n):
    s = pd.Series(c); dlt = s.diff()
    up = dlt.clip(lower=0).rolling(n, min_periods=n).mean()
    dn = (-dlt.clip(upper=0)).rolling(n, min_periods=n).mean()
    rs = up / dn.replace(0, np.nan)
    return (100 - 100 / (1 + rs)).to_numpy()


def cost_pct(sym, price):
    if sym in EQ and sym in ("QQQ", "SPY"):
        return (2 * 0.01) / price                      # 1 tick/side
    pt, tick, slip, comm = 2.0, 0.25, 2, 0.52          # MNQ-style futures
    return (2 * tick * slip + 2 * comm / pt) / price


# ───────────────────────── strategies: each returns list of (entry_dt, dir, ret_pct, ret_R) ─────────────────────────
def s_vix(d, vix, thr=0.10, hold=5):
    if d.attrs["sym"] not in EQ: return []
    c = d["close"].to_numpy(); a = atr(d); dt = d["dt"]
    m = d.merge(vix, left_on=d["dt"].dt.normalize().dt.tz_localize(None), right_on="date", how="left")
    vc, vs = m["vix_close"].to_numpy(), m["vix_sma5"].to_numpy()
    tr = []
    i = 0; n = len(c)
    while i < n - 1:
        if not np.isnan(vs[i]) and vc[i] > vs[i] * (1 + thr):          # panic spike at close[i]
            e = c[i]; j = min(i + hold, n - 1)
            for k in range(i + 1, min(i + hold, n - 1) + 1):
                if not np.isnan(vs[k]) and vc[k] < vs[k]: j = k; break  # VIX normalised -> exit
            x = c[j]; ret = (x - e) / e - cost_pct(d.attrs["sym"], e)
            tr.append((dt[i], 1, ret, (x - e) / a[i]))
            i = j + 1
        else:
            i += 1
    return tr


def s_donchian(d, N=20, M=None, atr_stop=2.0):
    """Gap-aware fills: a buy-stop fills at max(level, open) (gap-up = worse); a long stop/channel exit fills
    at min(exit_level, open) (gap-down through it = worse). Exits only on bars AFTER the entry bar."""
    M = M or N // 2
    o, h, l, c = (d[x].to_numpy() for x in ("open", "high", "low", "close")); a = atr(d); dt = d["dt"]
    sym = d.attrs["sym"]; n = len(c)
    up = pd.Series(h).rolling(N).max().shift(1).to_numpy()             # prior N-day high (causal)
    dn = pd.Series(l).rolling(N).min().shift(1).to_numpy()
    ex_dn = pd.Series(l).rolling(M).min().shift(1).to_numpy()          # exit channels
    ex_up = pd.Series(h).rolling(M).max().shift(1).to_numpy()
    tr = []; i = N
    while i < n:
        if not np.isnan(up[i]) and h[i] >= up[i]:                      # long breakout
            e = max(up[i], o[i]); stop = e - atr_stop * a[i]; j = None; side = 1
            for k in range(i + 1, n):
                if l[k] <= stop: x = min(stop, o[k]); j = k; break                 # gap-aware stop
                if not np.isnan(ex_dn[k]) and l[k] <= ex_dn[k]: x = min(ex_dn[k], o[k]); j = k; break  # gap-aware channel exit
            if j is None: x = c[-1]; j = n - 1
            tr.append((dt[i], side, side * (x - e) / e - cost_pct(sym, e), side * (x - e) / a[i])); i = j + 1
        elif not np.isnan(dn[i]) and l[i] <= dn[i]:                    # short breakout
            e = min(dn[i], o[i]); stop = e + atr_stop * a[i]; j = None; side = -1
            for k in range(i + 1, n):
                if h[k] >= stop: x = max(stop, o[k]); j = k; break
                if not np.isnan(ex_up[k]) and h[k] >= ex_up[k]: x = max(ex_up[k], o[k]); j = k; break
            if j is None: x = c[-1]; j = n - 1
            tr.append((dt[i], side, side * (x - e) / e - cost_pct(sym, e), side * (x - e) / a[i])); i = j + 1
        else:
            i += 1
    return tr


def s_connors(d, rlen=2, lo=10, hi=90):
    c = d["close"].to_numpy(); a = atr(d); dt = d["dt"]; sym = d.attrs["sym"]; n = len(c)
    sma200 = pd.Series(c).rolling(200).mean().to_numpy()
    sma5 = pd.Series(c).rolling(5).mean().to_numpy()
    r = rsi(c, rlen); tr = []; i = 200
    while i < n - 1:
        if not np.isnan(sma200[i]) and c[i] > sma200[i] and r[i] < lo:        # long dip in uptrend, MOC
            e = c[i]; j = None
            for k in range(i + 1, n):
                if c[k] > sma5[k]: j = k; break
            if j is None: j = n - 1
            x = c[j]; tr.append((dt[i], 1, (x - e) / e - cost_pct(sym, e), (x - e) / a[i])); i = j + 1
        elif not np.isnan(sma200[i]) and c[i] < sma200[i] and r[i] > hi:      # short pop in downtrend
            e = c[i]; j = None
            for k in range(i + 1, n):
                if c[k] < sma5[k]: j = k; break
            if j is None: j = n - 1
            x = c[j]; tr.append((dt[i], -1, -(x - e) / e - cost_pct(sym, e), -(x - e) / a[i])); i = j + 1
        else:
            i += 1
    return tr


def s_volbreak(d, k=0.5):
    """Intraday break of open +/- k*prior-range, exit at the SAME bar's CLOSE (MOC) — no TP is booked on the
    fill bar (the exit is the close, not a favorable target). Gap-aware entry: fill at the worse of level/open."""
    o, h, l, c = (d[x].to_numpy() for x in ("open", "high", "low", "close")); a = atr(d); dt = d["dt"]
    sym = d.attrs["sym"]; n = len(c); rng_prev = pd.Series(h - l).shift(1).to_numpy(); tr = []
    for i in range(1, n):
        if np.isnan(rng_prev[i]): continue
        lvl_u = o[i] + k * rng_prev[i]; lvl_d = o[i] - k * rng_prev[i]
        if h[i] >= lvl_u:                                             # long break, fill worse of level/open, exit close
            e = max(lvl_u, o[i]); x = c[i]; tr.append((dt[i], 1, (x - e) / e - cost_pct(sym, e), (x - e) / a[i]))
        elif l[i] <= lvl_d:                                          # short break
            e = min(lvl_d, o[i]); x = c[i]; tr.append((dt[i], -1, -(x - e) / e - cost_pct(sym, e), -(x - e) / a[i]))
    return tr


# ───────────────────────── gauntlet report ─────────────────────────
def loci(r):
    return np.percentile(rng.choice(r, (2000, len(r)), replace=True).mean(1), 5) if len(r) > 1 else 0.0


def report(tag, tr):
    if len(tr) < 30:
        print(f"  {tag:22} n={len(tr)} (<30, skip)"); return
    df = pd.DataFrame(tr, columns=["dt", "dir", "ret", "R"])
    r = df["ret"].to_numpy() * 100                                    # %
    Rr = df["R"].to_numpy()
    sharpe = r.mean() / r.std() * np.sqrt(252 / max(1, (df["dt"].iloc[-1] - df["dt"].iloc[0]).days / len(df))) if r.std() > 0 else 0
    df["year"] = df["dt"].dt.year
    yrs = [(y, g["ret"].mean()) for y, g in df.groupby("year") if len(g) >= 5]
    pos = sum(1 for _, e in yrs if e > 0); tot = len(yrs); neg = [int(y) for y, e in yrs if e <= 0]
    df = df.sort_values("dt"); kk = int(len(df) * 0.7)
    OUT = df.iloc[kk:]["ret"].mean()
    both = True
    L = df[df["dir"] == 1]["ret"]; S = df[df["dir"] == -1]["ret"]
    if len(S) > 5 and len(L) > 5: both = L.mean() > 0 and S.mean() > 0
    ciR = loci(Rr)
    g = "PASS" if (r.mean() > 0 and ciR > 0 and tot and pos >= 0.7 * tot and OUT > 0 and both) else "fail"
    print(f"  {tag:22} n={len(r):>4} ret/t {r.mean():+.3f}% expR {Rr.mean():+.3f} PF {V.pf(r):>4.2f} "
          f"win {100*np.mean(r>0):>2.0f}% CIr {ciR:+.3f} yr+{pos}/{tot} OOS {OUT*100:+.3f}% {g}"
          f"{'  NEG'+str(neg) if neg else ''}")


def main():
    syms = [s.upper() for s in (sys.argv[1:] or ["NQ", "ES", "QQQ", "SPY", "GC"])]
    con = hs_db.connect()
    vix = con.execute("SELECT date, sma5 AS vix_sma5, close AS vix_close FROM vix_daily ORDER BY date").df()
    vix["date"] = pd.to_datetime(vix["date"])
    for sym in syms:
        d = load(con, sym); d.attrs["sym"] = sym
        print(f"\n######## {sym} 1d — new standalone strategies ########")
        report("vix-fade(thr.10,h5)", s_vix(d, vix))
        for N in (20, 55):
            report(f"donchian N{N}", s_donchian(d, N))
        report("connors RSI2(10/90)", s_connors(d))
        for k in (0.3, 0.5):
            report(f"volbreak k{k}", s_volbreak(d, k))
    con.close()
    print("\nPASS = exp>0 net costs AND bootstrap CI(R)>0 AND >=70% yrs+ AND OOS-out>0 AND (both sides if 2-sided).")


if __name__ == "__main__":
    main()
