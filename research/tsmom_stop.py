"""TSMOM + DISASTER STOP (F94, user 2026-07-10: "first rule I have is risk management" — the
validated tsmom has NO stop and its 1.5xATR risk unit is ~983 NQ pts, more than a $1,800 budget
even on one micro. NQ trades ~23h so a working stop is ENFORCEABLE, unlike equity overnight gaps).

Long-only 12-1mo trend (the adopted duelist rule), hold 21d exit at close — with a stop grid
s x ATR(entry) checked bar-by-bar, GAP-AWARE (a bar opening through the stop fills at the OPEN).
The question: which stop keeps the trend edge while capping the per-trade risk unit?

Judged per cell: n, WR, exp net %, PF, years+, 70/30 OOS, and the REALIZED worst trade (the
disaster the stop is for). Compare vs no-stop baseline.

    python research/tsmom_stop.py [SYM ...]   (default NQ)
"""
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "engine"))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import numpy as np
import hs_db
from strat_daily import load, cost_pct, atr

LOOKBACK, SKIP, HOLD = 252, 21, 21
STOPS = [None, 1.0, 1.5, 2.0, 3.0]      # None = the adopted no-stop baseline


def run(d, stop_mult):
    c = d["close"].to_numpy(); o = d["open"].to_numpy(); lo = d["low"].to_numpy()
    a = atr(d); dt = d["dt"]; sym = d.attrs["sym"]; n = len(c)
    tr = []
    i = LOOKBACK
    while i + 1 < n:
        past = c[i - SKIP] / c[i - LOOKBACK] - 1.0
        if not (np.isfinite(past) and past > 0):          # LONG-ONLY (the adopted duelist rule)
            i += 1
            continue
        e = c[i]
        stop = e - stop_mult * a[i] if stop_mult else None
        exit_px = None
        j_end = min(i + HOLD, n - 1)
        for j in range(i + 1, j_end + 1):
            if stop is not None:
                if o[j] <= stop:                          # GAP through the stop -> fill at the OPEN
                    exit_px = o[j]; break
                if lo[j] <= stop:                         # intraday touch -> stop price (23h market)
                    exit_px = stop; break
        if exit_px is None:
            exit_px = c[j_end]                            # time exit at the close of day 21
        ret = (exit_px - e) / e - cost_pct(sym, e)
        tr.append((str(dt.iloc[i])[:10], ret, (exit_px - e) / a[i] if a[i] > 0 else 0.0))
        i = j_end + 1 if exit_px == c[j_end] else i + HOLD  # non-overlapping either way
    return tr


def report(tag, tr, risk_pts):
    if not tr:
        print(f"  {tag}: no trades"); return
    rs = np.array([t[1] for t in tr])
    cut = int(len(rs) * 0.7); oos = rs[cut:]
    w, l = rs[rs > 0].sum(), -rs[rs <= 0].sum()
    pf = w / l if l > 0 else float("inf")
    yrs = {}
    for day, ret, _ in tr:
        yrs[day[:4]] = yrs.get(day[:4], 0.0) + ret
    yp = sum(1 for v in yrs.values() if v > 0)
    worst = float(rs.min()) * 100
    print(f"  {tag:14} n={len(rs):>3} WR {100*(rs>0).mean():>3.0f}% exp {100*rs.mean():+.3f}% "
          f"PF {pf:4.2f} yrs+ {yp:>2}/{len(yrs)} OOS {100*(oos.mean() if len(oos) else float('nan')):+.3f}% "
          f"worst {worst:+.1f}% · risk unit ~{risk_pts:.0f} pts")


def main():
    syms = [s.upper() for s in (sys.argv[1:] or ["NQ"])]
    con = hs_db.connect()
    for sym in syms:
        d = load(con, sym); d.attrs["sym"] = sym
        a_now = float(atr(d)[-1])
        print(f"\n######## {sym} — tsmom long-only 12-1mo, hold {HOLD}d, DISASTER-STOP grid "
              f"(ATR now ~{a_now:.0f} pts) ########")
        for s in STOPS:
            tag = "no stop (prod)" if s is None else f"stop {s}xATR"
            report(tag, run(d, s), (s or 1.5) * a_now)
    con.close()
    print("\ngap-aware: a bar OPENING through the stop fills at the open (the honest fill). "
          "PASS bar = exp>0 net AND OOS>0 AND >=70% yrs+ AND keeps >=80% of the no-stop exp.")


if __name__ == "__main__":
    main()
