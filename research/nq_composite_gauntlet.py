"""NQ PATTERN COMPOSITE (F104, user 2026-07-10: "cluster the NQ patterns into one strategy and
test it"). ONE day-trade built from the F99 census pass-cells as VOTES — confluence trading:

  votes at 10:30 ET (first-hour info available), each pre-registered from F99 (no new mining):
    +1 long  if MONDAY                       (Mon drift +8.1bps)
    +sign(first hour) if |FH move| in top tercile   (FH momentum +5.1bps)
    -sign(yesterday's RTH)                   (day-over-day reversal -3.9bps)
    +1 long  if OVERNIGHT GAP UP             (gap-up follow +3.5bps)
  position: direction = sign(vote sum), entered 10:30, exit 16:00 (rest-of-day window).
  cells: |sum| >= 1 (any edge) and |sum| >= 2 (confluence) — a 2-cell menu, not a search.
  V2 note: vol-clustering (F99[7]) is a SIZING overlay, not a vote — reported separately.

Judged with the standard seven checks. Stacked-mining bias is real even with pre-registration —
a pass here still goes research -> ladder -> SHADOW before anything else, like every lineage.

    python research/nq_composite_gauntlet.py
"""
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "engine"))
import numpy as np
import pandas as pd
import hs_db

rng = np.random.default_rng(31)
TICK, SLIP_TICKS, COMM, PT = 0.25, 2, 0.52, 2.0


EQ = {"QQQ", "SPY"}
_COST_SYM = {"sym": "NQ"}                # set per-run; equities pay ticks, not futures slippage


def cost_pct(price, slip_mult=1.0):
    # COST-MODEL FIX (2026-07-10): the futures model (~30-40bps on a $500 ETF!) was applied to
    # QQQ/SPY and poisoned every equity verdict; equities pay ~1 tick/side (strat_daily model).
    if _COST_SYM["sym"] in EQ:
        return (2 * 0.01 * slip_mult) / price
    return (2 * TICK * SLIP_TICKS * slip_mult + 2 * COMM / PT) / price


def day_frames(con, sym="NQ"):
    b = hs_db.bars(con, "5m", "full", sym=sym).sort_values("ts").reset_index(drop=True)
    dt = pd.to_datetime(b["ts"], utc=True).dt.tz_convert("America/New_York")
    b = b.assign(hm=dt.dt.hour * 60 + dt.dt.minute, day=dt.dt.strftime("%Y-%m-%d"),
                 dow=dt.dt.dayofweek)
    out = []
    for d, g in b.groupby("day", sort=True):
        rth = g[g["hm"].between(570, 959)]
        if len(rth) < 30:
            continue
        fh = rth[rth["hm"] < 630]; rest = rth[rth["hm"] >= 630]
        if len(fh) < 4 or len(rest) < 4:
            continue
        out.append({"day": d, "dow": int(g["dow"].iloc[0]),
                    "o": float(rth["open"].iloc[0]), "c": float(rth["close"].iloc[-1]),
                    "h": float(rth["high"].max()), "l": float(rth["low"].min()),
                    "fh_ret": (float(fh["close"].iloc[-1]) - float(fh["open"].iloc[0])) / float(fh["open"].iloc[0]),
                    "rest_o": float(rest["open"].iloc[0]), "rest_c": float(rest["close"].iloc[-1])})
    D = pd.DataFrame(out)
    D["ret"] = (D["c"] - D["o"]) / D["o"]
    D["rng"] = (D["h"] - D["l"]) / D["o"]
    D["prev_ret"] = D["ret"].shift(1)
    D["prev_rng"] = D["rng"].shift(1)
    D["gap"] = (D["o"] - D["c"].shift(1)) / D["c"].shift(1)
    # CAUSAL vote inputs only: fh tercile threshold from the TRAILING year (no full-sample stat)
    D["fh_big"] = D["fh_ret"].abs() >= D["fh_ret"].abs().rolling(252, min_periods=100).quantile(2 / 3)
    return D.dropna(subset=["prev_ret", "gap", "rest_o", "rest_c"]).reset_index(drop=True)


# PER-SYMBOL vote sets — each symbol votes ONLY with its OWN census pass-cells (F104b lesson:
# the NQ rule transplanted verbatim loses 30-40bps on equities; the METHOD transfers, votes don't)
VOTE_SETS = {
    "NQ": {"monday", "fh", "fade", "gap"},
    "QQQ": {"monday", "fh", "fade"},                  # QQQ census: no gap cell
    "SPY": {"monday"},                                # SPY census: calendar cells only
}


def votes(r, enabled):
    v = 0
    if "monday" in enabled and r.dow == 0:
        v += 1                                        # Monday drift (long)
    if "fh" in enabled and r.fh_big:
        v += int(np.sign(r.fh_ret))                   # first-hour momentum
    if "fade" in enabled:
        v -= int(np.sign(r.prev_ret))                 # day-over-day reversal
    if "gap" in enabled and r.gap > 0:
        v += 1                                        # gap-up follow
    return v


def trades(D, min_votes, slip=1.0, enabled=None, at_open=False):
    """at_open=True (user 2026-07-10 'instead of 10:35, watch at 9:30'): enter the OPEN with the
    votes knowable at 9:30 (no first-hour vote yet — that's the trade-off being measured), exit
    the close. Default: 10:35 entry with all votes, rest-of-day window (the F104 pass)."""
    enabled = set(enabled or VOTE_SETS["NQ"])
    if at_open:
        enabled = enabled - {"fh"}                    # FH doesn't exist at 9:30
    out = []
    for r in D.itertuples():
        v = votes(r, enabled)
        if abs(v) < min_votes:
            continue
        d = 1 if v > 0 else -1
        if at_open:
            out.append((r.day, d * (r.c - r.o) / r.o - cost_pct(r.o, slip), r.prev_rng))
        else:
            out.append((r.day, d * (r.rest_c - r.rest_o) / r.rest_o - cost_pct(r.rest_o, slip),
                        r.prev_rng))
    return out


def gauntlet(tag, tr, tr2):
    rs = np.array([t[1] for t in tr])
    if len(rs) < 30:
        print(f"### {tag}: n={len(rs)} too thin"); return
    lo = float(np.percentile(rng.choice(rs, (3000, len(rs)), replace=True).mean(1), 5))
    cut = int(len(rs) * 0.7); oos = rs[cut:]
    yrs = {}
    for d, r, _ in tr:
        yrs[d[:4]] = yrs.get(d[:4], 0.0) + r
    yp, yn = sum(1 for v in yrs.values() if v > 0), len(yrs)
    w, l = rs[rs > 0].sum(), -rs[rs <= 0].sum()
    pf = float(w / l) if l > 0 else float("inf")
    rs2 = np.array([t[1] for t in tr2])
    ok = {"1 n>=100": len(rs) >= 100, "2 exp>0": rs.mean() > 0, "3 CI>0": lo > 0,
          "4 yrs>=70%": yp >= 0.7 * yn, "5 OOS>0": len(oos) and oos.mean() > 0,
          "6 2xslip>0": len(rs2) and rs2.mean() > 0, "7 PF>=1.2": pf >= 1.2}
    print(f"\n### {tag}")
    print(f"  n={len(rs)} exp {1e4*rs.mean():+.1f}bps WR {100*(rs>0).mean():.0f}% PF {pf:.2f} "
          f"CI_lo {1e4*lo:+.1f} yrs+ {yp}/{yn} OOS {1e4*oos.mean():+.1f} 2xslip {1e4*rs2.mean():+.1f}")
    for k, v in ok.items():
        print(f"  {'PASS' if v else 'FAIL'}  {k}")
    print(f"  VERDICT: {'ADOPT_CANDIDATE' if all(ok.values()) else 'REJECT'}")
    # V2 preview — vol-cluster SIZING overlay (risk-normalize by yesterday's range tercile)
    pr = np.array([t[2] for t in tr])
    hi_t = np.nanquantile(pr, 2 / 3)
    calm, wild = rs[pr < hi_t], rs[pr >= hi_t]
    if len(calm) > 30 and len(wild) > 30:
        print(f"  vol-overlay: calm-day exp {1e4*calm.mean():+.1f}bps (n{len(calm)}) vs "
              f"high-vol-day exp {1e4*wild.mean():+.1f}bps (n{len(wild)}) — sizing input, F99[7]")


def main():
    syms = [s.upper() for s in (sys.argv[1:] or ["NQ"])]
    con = hs_db.connect()
    for sym in syms:
        _COST_SYM["sym"] = sym
        D = day_frames(con, sym)
        en = VOTE_SETS.get(sym, VOTE_SETS["NQ"])
        print(f"\n######## F104 — {sym} pattern COMPOSITE, {len(D)} days · votes: {sorted(en)} ########")
        gauntlet("composite |votes|>=1 (any edge)", trades(D, 1, 1.0, en), trades(D, 1, 2.0, en))
        gauntlet("composite |votes|>=2 (CONFLUENCE)", trades(D, 2, 1.0, en), trades(D, 2, 2.0, en))
        gauntlet("9:30-OPEN variant |votes|>=2 (no FH vote, full day)",
                 trades(D, 2, 1.0, en, at_open=True), trades(D, 2, 2.0, en, at_open=True))
    con.close()


if __name__ == "__main__":
    main()
