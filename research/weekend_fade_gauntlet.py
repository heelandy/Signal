"""WEEKEND FADE — full gauntlet + stop grid (F97b, 2026-07-10). The F96 'asia-fade' pass was
DECOMPOSED: the weekday 18:00->03:00 cohort has NO OOS edge (-0.3bps); the edge concentrates in
the WEEKEND hand-off — weak FRIDAY RTH close -> LONG the SUNDAY 18:00 reopen -> exit Monday 03:00
(n=259 +7.2bps PF 1.40 13/17yrs OOS +18.4). This respecifies the rule, runs the 7 checks, and the
stop grid (stops are enforceable — the position spans the OPEN Sunday-evening session).

    python research/weekend_fade_gauntlet.py [SYM ...]   (default NQ)
"""
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "engine"))
import numpy as np
import pandas as pd
import hs_db

rng = np.random.default_rng(19)
TICK, SLIP_TICKS, COMM, PT = 0.25, 2, 0.52, 2.0
STOPS = [None, 0.5, 0.75, 1.0, 1.5]


def cost_pct(price, slip_mult=1.0):
    return (2 * TICK * SLIP_TICKS * slip_mult + 2 * COMM / PT) / price


def setups(con, sym):
    """Weak-FRIDAY-close -> the following ASIA instance (Sunday evening), with its bar arrays."""
    b = hs_db.bars(con, "5m", "full", sym=sym).sort_values("ts").reset_index(drop=True)
    dt = pd.to_datetime(b["ts"], utc=True).dt.tz_convert("America/New_York")
    hm = dt.dt.hour * 60 + dt.dt.minute
    shifted = (hm - 18 * 60) % (24 * 60)
    seg = np.where(shifted < 9 * 60, "ASIA",
                   np.where(hm.between(9 * 60 + 30, 15 * 60 + 59), "RTH", "off"))
    b = b.assign(seg=seg, dt=dt)
    b = b[b["seg"] != "off"].reset_index(drop=True)
    inst = (b["seg"] != b["seg"].shift()).cumsum()
    groups = [(g["seg"].iloc[0], g) for _, g in b.groupby(inst)]
    out = []
    for gi, (segname, g) in enumerate(groups):
        if segname != "RTH" or g["dt"].iloc[0].dayofweek != 4:      # FRIDAYS only
            continue
        h, l, c = float(g["high"].max()), float(g["low"].min()), float(g["close"].iloc[-1])
        rng_ = h - l
        if rng_ <= 0 or (c - l) / rng_ > 1 / 3:
            continue
        nxt = next((gg for sname, gg in groups[gi + 1:] if sname == "ASIA"), None)
        if nxt is None or len(nxt) < 10:
            continue
        if (nxt["dt"].iloc[0] - g["dt"].iloc[-1]).total_seconds() < 24 * 3600:
            continue                                                 # must be the WEEKEND hand-off
        out.append({"day": str(g["dt"].iloc[0])[:10], "risk": rng_,
                    "entry": float(nxt["open"].iloc[0]),
                    "op": nxt["open"].to_numpy(float), "lo": nxt["low"].to_numpy(float),
                    "close": float(nxt["close"].iloc[-1])})
    return out


def trades(S, stop_mult, slip_mult=1.0):
    out = []
    for s in S:
        e, rng_ = s["entry"], s["risk"]
        stop = e - stop_mult * rng_ if stop_mult else None
        x = None
        if stop is not None:
            for j in range(1, len(s["op"])):
                if s["op"][j] <= stop:
                    x = s["op"][j]; break
                if s["lo"][j] <= stop:
                    x = stop; break
        if x is None:
            x = s["close"]
        out.append((s["day"], (x - e) / e - cost_pct(e, slip_mult)))
    return out


def gauntlet(tag, tr, tr2, base=None):
    rs = np.array([t[1] for t in tr])
    if not len(rs):
        print(f"  {tag}: none"); return None
    lo = float(np.percentile(rng.choice(rs, (3000, len(rs)), replace=True).mean(1), 5))
    cut = int(len(rs) * 0.7); oos = rs[cut:]
    yrs = {}
    for d, r in tr:
        yrs[d[:4]] = yrs.get(d[:4], 0.0) + r
    yp, yn = sum(1 for v in yrs.values() if v > 0), len(yrs)
    w, l = rs[rs > 0].sum(), -rs[rs <= 0].sum()
    pf = float(w / l) if l > 0 else float("inf")
    rs2 = np.array([t[1] for t in tr2])
    ok = {"1 n>=100": len(rs) >= 100, "2 exp>0": rs.mean() > 0, "3 CI>0": lo > 0,
          "4 yrs>=70%": yp >= 0.7 * yn, "5 OOS>0": len(oos) and oos.mean() > 0,
          "6 2xslip>0": len(rs2) and rs2.mean() > 0, "7 PF>=1.2": pf >= 1.2}
    keep = f" keeps {100*rs.mean()/base:3.0f}%" if base else ""
    print(f"  {tag:12} n={len(rs):>3} exp {1e4*rs.mean():+6.1f}bps WR {100*(rs>0).mean():3.0f}% "
          f"PF {pf:4.2f} CI_lo {1e4*lo:+5.1f} yrs+ {yp:>2}/{yn} OOS {1e4*oos.mean():+6.1f} "
          f"worst {100*rs.min():+5.2f}%{keep}  [{'ALL 7 PASS' if all(ok.values()) else 'fail: ' + ','.join(k for k, v in ok.items() if not v)}]")
    return float(rs.mean())


def main():
    syms = [s.upper() for s in (sys.argv[1:] or ["NQ"])]
    con = hs_db.connect()
    for sym in syms:
        S = setups(con, sym)
        print(f"\n######## {sym} — WEEKEND FADE (weak Fri close -> long Sun 18:00 -> Mon 03:00) "
              f"— gauntlet + stop grid ########")
        base = gauntlet("no stop", trades(S, None), trades(S, None, 2.0))
        for s in STOPS[1:]:
            gauntlet(f"stop {s}x", trades(S, s), trades(S, s, 2.0), base)
    con.close()
    print("\nadoption: widest stop keeping >=80% AND all-7. The weekday cohort is DEAD OOS — this "
          "Friday-only rule replaces the F96 daily spec before any approval.")


if __name__ == "__main__":
    main()
