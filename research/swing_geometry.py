"""SWING GEOMETRY SWEEP (user 2026-07-10: "what are the target/stop... let's look at the geometry
for the best outcome"). The duel's swing rule (up-stack close>EMA20>EMA50 + pullback to EMA20 +
close back above; mirrored short) with a GRID of stop x target x horizon, judged in R net of costs,
70/30 OOS. The adopted default is stop 1.5xATR / target 3.0xATR / 20d — this asks whether a tighter
or wider geometry serves the goal band (WR 75-85 - PF >= 1.7) better on the SAME entries.

Causal walk: entry at the signal close; each later bar checks stop first (worst case when both
touch), then target, then the horizon close. Gap-aware: a gap through the stop fills at the open.

    python research/swing_geometry.py [SYM ...]     (default QQQ NQ)
"""
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "engine"))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import numpy as np
import hs_db
from strat_daily import load, cost_pct, atr

STOPS = [1.0, 1.5, 2.0]
TGTS = [0.5, 0.75, 1.0, 1.5, 2.0, 3.0, 4.0]
HORIZONS = [5, 10, 20]
CUT = 0.7                                            # IS/OOS split


def entries(d):
    """The duel's equities/futures swing entry on every historical bar (long + short)."""
    c = d["close"].to_numpy(); h = d["high"].to_numpy(); lo = d["low"].to_numpy()
    e20 = d["close"].ewm(span=20, adjust=False).mean().to_numpy()
    e50 = d["close"].ewm(span=50, adjust=False).mean().to_numpy()
    a = atr(d)
    out = []
    for i in range(60, len(c) - 1):
        if not np.isfinite(a[i]) or a[i] <= 0:
            continue
        up = c[i] > e20[i] > e50[i]
        dn = c[i] < e20[i] < e50[i]
        if up and lo[i] <= e20[i] and c[i] > e20[i]:
            out.append((i, 1, c[i], a[i]))
        elif dn and h[i] >= e20[i] and c[i] < e20[i]:
            out.append((i, -1, c[i], a[i]))
    return out


def walk(d, ent, s_mult, t_mult, hz, sym):
    """One geometry cell over all entries -> list of net R."""
    o = d["open"].to_numpy(); h = d["high"].to_numpy(); lo = d["low"].to_numpy(); c = d["close"].to_numpy()
    rs = []
    for i, sign, e, a in ent:
        stop = e - sign * s_mult * a
        tgt = e + sign * t_mult * a
        risk = s_mult * a
        cost_r = cost_pct(sym, e) * e / risk        # % cost -> R units of THIS stop distance
        r = None
        for j in range(i + 1, min(i + 1 + hz, len(c))):
            gap_stop = (o[j] - e) * sign <= (stop - e) * sign
            if gap_stop:                             # gapped through the stop -> fill at the open
                r = sign * (o[j] - e) / risk; break
            hit_stop = (lo[j] <= stop) if sign == 1 else (h[j] >= stop)
            if hit_stop:                             # stop FIRST when both touch (worst case)
                r = -1.0; break
            hit_tgt = (h[j] >= tgt) if sign == 1 else (lo[j] <= tgt)
            if hit_tgt:
                r = t_mult / s_mult; break
        if r is None:                                # horizon exit at the close
            j = min(i + hz, len(c) - 1)
            r = sign * (c[j] - e) / risk
        rs.append(r - cost_r)
    return np.asarray(rs, float)


def main():
    syms = [s.upper() for s in (sys.argv[1:] or ["QQQ", "NQ"])]
    con = hs_db.connect()
    for sym in syms:
        d = load(con, sym); d.attrs["sym"] = sym
        ent = entries(d)
        cut = int(len(ent) * CUT)
        print(f"\n######## {sym} swing geometry — {len(ent)} entries (IS {cut} / OOS {len(ent)-cut}) ########")
        print(f"{'stop':>5} {'tgt':>5} {'hz':>4} {'n':>5} {'WR%':>6} {'avgR':>7} {'PF':>6} {'OOS avgR':>9}  band")
        rows = []
        for s_m in STOPS:
            for t_m in TGTS:
                for hz in HORIZONS:
                    rs = walk(d, ent, s_m, t_m, hz, sym)
                    if not len(rs):
                        continue
                    oos = walk(d, ent[cut:], s_m, t_m, hz, sym)
                    wr = 100 * float((rs > 0).mean())
                    w, l = rs[rs > 0].sum(), -rs[rs <= 0].sum()
                    pf = float(w / l) if l > 0 else float("inf")
                    band = 75 <= wr <= 85 and pf >= 1.7 and (oos.mean() if len(oos) else -9) > 0
                    rows.append((s_m, t_m, hz, len(rs), wr, float(rs.mean()), pf,
                                 float(oos.mean()) if len(oos) else float("nan"), band))
        # top by avg R, then every band cell, then the adopted default
        rows.sort(key=lambda r: -r[5])
        shown = rows[:8] + [r for r in rows[8:] if r[8]]
        dflt = next((r for r in rows if r[0] == 1.5 and r[1] == 3.0 and r[2] == 20), None)
        if dflt and dflt not in shown:
            shown.append(dflt)
        for r in shown:
            tag = " <== BAND" if r[8] else (" (adopted default)" if r is dflt else "")
            print(f"{r[0]:>5} {r[1]:>5} {r[2]:>4} {r[3]:>5} {r[4]:>6.1f} {r[5]:>+7.3f} {r[6]:>6.2f} {r[7]:>+9.3f}{tag}")
    con.close()
    print("\nread: stop/tgt in ATR multiples · hz = max days held · R normalized by the cell's own "
          "stop · band = WR 75-85 AND PF>=1.7 AND OOS>0 (the goal) · stop-first on double-touch bars.")


if __name__ == "__main__":
    main()
