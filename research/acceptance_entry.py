"""ACCEPTANCE ENTRY (F92, user 2026-07-10: QQQ ground 2.4pts above its OR high all afternoon and
the stack never fired — "a 2.4 point is still something we need to take advantage of"). The stack
demands a STRONG confirmed breakout bar; grind days never print one. This tests the complementary
cohort: enter when price simply HOLDS beyond the OR edge for N consecutive 5m closes (acceptance,
not momentum), stop at the OR midpoint, first-touch to TP1 1.5R / TP2 4R / 14:30 flat — same
bracket geometry as the stack so the records are comparable.

Judged per symbol: n, WR, exp net R, PF, years+, 70/30 OOS. PASS bar = exp>0 net AND OOS>0 AND
>=70% years positive. Dedup: one acceptance trade per day per side (the first).

    python research/acceptance_entry.py [SYM ...]      (default QQQ SPY NQ)
"""
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "engine"))
import numpy as np
import pandas as pd
import hs_db

N_HOLD = [2, 3, 4]          # consecutive 5m closes beyond the edge = acceptance
TP1_R, TP2_R = 1.5, 4.0
OR_S, OR_E, CUT = 570, 600, 870          # 09:30 OR build to 10:00 · force-flat 14:30 ET
EQ = {"QQQ", "SPY"}


def cost_r(sym, entry, risk):
    c = (2 * 0.01) if sym in EQ else (2 * 0.25 * 2 + 2 * 0.52 / 2.0)   # $ per unit round-trip
    return c / risk if risk > 0 else 0.0


def day_frames(con, sym):
    b = hs_db.bars(con, "5m", "rth", sym=sym).sort_values("ts").reset_index(drop=True)
    b["dt"] = pd.to_datetime(b["ts"], utc=True).dt.tz_convert("America/New_York")
    b["day"] = b["dt"].dt.strftime("%Y-%m-%d")
    b["hm"] = b["dt"].dt.hour * 60 + b["dt"].dt.minute
    return b


def run_sym(sym, con, n_hold):
    b = day_frames(con, sym)
    out = []
    for day, g in b.groupby("day", sort=True):
        g = g.reset_index(drop=True)
        orb = g[(g["hm"] >= OR_S) & (g["hm"] < OR_E)]
        if len(orb) < 4:
            continue
        orh, orl = float(orb["high"].max()), float(orb["low"].min())
        mid = (orh + orl) / 2.0
        sess = g[(g["hm"] >= OR_E) & (g["hm"] < CUT)].reset_index(drop=True)
        if not len(sess):
            continue
        cl = sess["close"].to_numpy(float); hi = sess["high"].to_numpy(float)
        lo = sess["low"].to_numpy(float)
        for sign, edge in ((1, orh), (-1, orl)):
            run = 0; ei = None
            for i in range(len(sess)):
                run = run + 1 if (cl[i] - edge) * sign > 0 else 0
                if run >= n_hold:
                    ei = i; break
            if ei is None:
                continue
            e = cl[ei]; stop = mid
            risk = (e - stop) * sign
            if risk <= 0:
                continue
            tp1 = e + sign * TP1_R * risk; tp2 = e + sign * TP2_R * risk
            r = None; tp1_hit = False
            for j in range(ei + 1, len(sess)):
                if (lo[j] <= stop if sign == 1 else hi[j] >= stop):
                    r = -1.0 if not tp1_hit else -1.0            # full-to-TP2 (stack convention)
                    break
                if (hi[j] >= tp2 if sign == 1 else lo[j] <= tp2):
                    r = TP2_R; break
                if not tp1_hit and (hi[j] >= tp1 if sign == 1 else lo[j] <= tp1):
                    tp1_hit = True
            if r is None:                                        # 14:30 force-flat
                r = sign * (cl[-1] - e) / risk
            out.append((day, sign, r - cost_r(sym, e, risk)))
    return out


def report(tag, tr):
    if not tr:
        print(f"  {tag}: no trades"); return
    rs = np.array([t[2] for t in tr]); yrs = {}
    for day, _, r in tr:
        yrs[day[:4]] = yrs.get(day[:4], 0.0) + r
    cut = int(len(rs) * 0.7); oos = rs[cut:]
    w, l = rs[rs > 0].sum(), -rs[rs <= 0].sum()
    pf = w / l if l > 0 else float("inf")
    ypos = sum(1 for v in yrs.values() if v > 0)
    ok = rs.mean() > 0 and (oos.mean() if len(oos) else -9) > 0 and ypos >= 0.7 * len(yrs)
    print(f"  {tag}: n={len(rs)} WR {100*(rs>0).mean():.0f}% exp {rs.mean():+.3f}R PF {pf:.2f} "
          f"yrs+ {ypos}/{len(yrs)} OOS {oos.mean() if len(oos) else float('nan'):+.3f} "
          f"{'PASS' if ok else 'fail'}")


def main():
    syms = [s.upper() for s in (sys.argv[1:] or ["QQQ", "SPY", "NQ"])]
    con = hs_db.connect()
    for sym in syms:
        print(f"\n######## {sym} — acceptance entry (hold N closes beyond OR edge · stop OR-mid · 1.5R/4R/14:30) ########")
        for n in N_HOLD:
            report(f"hold {n} closes", run_sym(sym, con, n))
    con.close()
    print("\nPASS = exp>0 net AND OOS>0 AND >=70% yrs+. The GRIND cohort the stack's strong-body "
          "confirm skips; if a cell passes, it goes to the full gauntlet before anything is wired.")


if __name__ == "__main__":
    main()
