#!/usr/bin/env python3
"""
RESEARCH (F37 candidate) — do RSI and the Accelerator/Decelerator oscillator add value as FILTERS on the
validated 5m ORB stack (F21 HH/HL st_state gate + VWAP-cap k2)? Same protocol + the F36 redundancy control.

Indicators (textbook params, no mining):
  RSI(14)  Wilder. AO = SMA(hl2,5) - SMA(hl2,34) (Awesome Osc). AC = AO - SMA(AO,5) (Accel/Decel).
Causal: every filter column is the PRIOR confirmed bar (shift 1) — nothing later than an intrabar stop-fill sees.
AND-ed into the stack trend gate (long needs st_state==1 AND kernel-agree; short st_state==2 AND ...), exactly
how orb_stack_walkforward / orb_kernel_filter inject a gate.

Variants:
  rsi_side  : RSI>50 long / <50 short            (momentum agreement)
  rsi_cap   : DON'T-CHASE — skip long if RSI>70, short if RSI<30   (overbought/oversold = the VWAP-cap analog)
  rsi_slope : RSI rising for long / falling short
  ac_sign   : AC>0 long / AC<0 short
  ac_accel  : AC rising for long / falling for short                (acceleration in the trade direction)
  ac_agree  : AC>0 AND rising (long) / AC<0 AND falling (short)     (Bill Williams' two-condition rule)

Gate (F15/F36): beat the stack on the four metrics AND PASS (both sides>0, CI>0) on NQ+QQQ+SPY, every year+,
OOS holds — THEN the redundancy control: does it beat tightening the EXISTING vwap-cap k to the same n?

    python research/orb_momentum_filter.py [SYM ...]        (default NQ QQQ SPY)
    python research/orb_momentum_filter.py --robust         (ES + 2x slip + redundancy control)
"""
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "engine"))
import numpy as np, pandas as pd
import hs_db, hs_harness as H, hs_backtest as B, hs_validate as V
from orb_kernel_filter import loci, slip2x, ORS, ORE, CUT, T1, T2, EOD, KCAP

RSI_LEN, RSI_OB, RSI_OS = 14, 70, 30


def momentum_state(d):
    """Causal (prior-bar) RSI + Accelerator/Decelerator filter columns."""
    c = d["close"]; h = d["high"]; l = d["low"]
    delta = c.diff()
    up = delta.clip(lower=0.0); dn = (-delta).clip(lower=0.0)
    rs = H.rma(up, RSI_LEN) / H.rma(dn, RSI_LEN).replace(0, np.nan)
    rsi = (100.0 - 100.0 / (1.0 + rs)).fillna(100.0)
    hl2 = (h + l) / 2.0
    ao = H.sma(hl2, 5) - H.sma(hl2, 34)
    ac = ao - H.sma(ao, 5)
    sh = lambda s: s.shift(1).to_numpy()
    return dict(rsi=sh(rsi), rsi_d=sh(rsi - rsi.shift(1)),
                ac=sh(ac), ac_d=sh(ac - ac.shift(1)))


def gates(v, M):
    r, rd, ac, acd = M["rsi"], M["rsi_d"], M["ac"], M["ac_d"]
    if v == "rsi_side":  return r > 50, r < 50
    if v == "rsi_cap":   return r <= RSI_OB, r >= RSI_OS           # don't chase overbought longs / oversold shorts
    if v == "rsi_slope": return rd > 0, rd < 0
    if v == "ac_sign":   return ac > 0, ac < 0
    if v == "ac_accel":  return acd > 0, acd < 0
    if v == "ac_agree":  return (ac > 0) & (acd > 0), (ac < 0) & (acd < 0)
    raise ValueError(v)

VARIANTS = ("rsi_side", "rsi_cap", "rsi_slope", "ac_sign", "ac_accel", "ac_agree")


def run(d, v=None, M=None, vcap=KCAP):
    st = d["st_state"].to_numpy(); tu = st == 1; td = st == 2
    if v is not None:
        kl, ks = gates(v, M); tu = tu & kl; td = td & ks
    d["trend_up"] = tu; d["trend_down"] = td
    return B.backtest(d, "scale_be", "both", False, "orb", 0, T1, T2, ORS, ORE, 0.0, CUT, "stop",
                      eod_min=EOD, vwap_cap=vcap)


def report(tag, tr):
    r = tr["net_R"].to_numpy()
    L = tr[tr.direction == "long"]["net_R"].to_numpy(); S = tr[tr.direction == "short"]["net_R"].to_numpy()
    both = len(L) > 5 and L.mean() > 0 and len(S) > 5 and S.mean() > 0
    lo = loci(r)
    t = tr.copy(); t["year"] = pd.to_datetime(t["entry_time"], utc=True).dt.tz_convert("America/New_York").dt.year
    yrs = [(int(y), g["net_R"].mean()) for y, g in t.groupby("year") if len(g) >= 10]
    pos = sum(1 for _, e in yrs if e > 0); tot = len(yrs); neg = [y for y, e in yrs if e <= 0]
    t = t.sort_values("entry_time").reset_index(drop=True); k = int(len(t) * 0.7)
    IN = t.iloc[:k]["net_R"].to_numpy(); OUT = t.iloc[k:]["net_R"].to_numpy()
    g = "PASS" if (both and lo > 0) else "fail"
    print(f"  {tag:12} n={len(r):>4} exp {r.mean():+.3f} PF {V.pf(r):>5.2f} win {100*np.mean(r>0):>2.0f}% "
          f"DD {V.maxdd(r):>+5.0f} CI {lo:+.3f} {g} | yrs +{pos}/{tot}{'  NEG=' + str(neg) if neg else ''} "
          f"| OOS {IN.mean():+.3f}->{OUT.mean():+.3f}")


def robust(con):
    print("==== ROBUSTNESS: cross-asset (+ES) and 2x-slippage stress (best variants) ====")
    feat = ("ac_agree", "ac_sign", "rsi_side")
    for sym in ["NQ", "ES", "QQQ", "SPY"]:
        eq = sym in ("QQQ", "SPY")
        bars = B._externals(con, hs_db.bars(con, "5m", "full", sym=sym), sym)
        d = H.compute_state(bars, H.P()); d.attrs["sym"] = sym
        M = momentum_state(d)
        print(f"\n## {sym} 5m{'  (equity)' if eq else '  (futures, 2x-slip shown)'}")
        for tag, v in [("STACK", None)] + [("+" + x, x) for x in feat]:
            tr = run(d, v, M) if v else run(d)
            r = tr["net_R"].to_numpy()
            sl = "" if eq else f" | 2xslip exp {slip2x(tr, eq).mean():+.3f} PF {V.pf(slip2x(tr, eq)):.2f}"
            print(f"  {tag:12} n={len(r):>4} exp {r.mean():+.3f} PF {V.pf(r):>5.2f} win {100*np.mean(r>0):>2.0f}% "
                  f"DD {V.maxdd(r):>+5.0f} CI {loci(r):+.3f}{sl}")

    # the deciding test: does any momentum cull sit ABOVE the existing vwap-cap frequency<->quality frontier?
    print("\n\n==== REDUNDANCY CONTROL: momentum cull vs equal-frequency vwap-cap tighten (NQ + QQQ) ====")
    print("REAL only if the variant sits ABOVE the vwap-cap frontier at its own trade count, on BOTH assets.\n")
    for sym in ("NQ", "QQQ"):
        bars = B._externals(con, hs_db.bars(con, "5m", "full", sym=sym), sym)
        d = H.compute_state(bars, H.P()); d.attrs["sym"] = sym
        M = momentum_state(d)
        print(f"  ---- {sym} : vwap-cap frontier ----")
        for k in (2.0, 1.8, 1.6, 1.4, 1.2, 1.0):
            r = run(d, vcap=k)["net_R"].to_numpy()
            lbl = "STACK (vcap2.0)" if k == 2.0 else f"vwap-cap k={k}"
            print(f"  {lbl:22} n={len(r):>4} exp {r.mean():+.3f} PF {V.pf(r):.2f}")
        print(f"  ---- {sym} : momentum filters (vcap held 2.0) ----")
        for v in VARIANTS:
            r = run(d, v, M)["net_R"].to_numpy()
            print(f"  {'+' + v:22} n={len(r):>4} exp {r.mean():+.3f} PF {V.pf(r):.2f}")
        print()


def additive(con):
    """Decisive orthogonality test: does ac_agree lift the WHOLE vwap-cap frontier, or just sit near it?
    Build the vwap-only frontier and the (ac_agree + vwap) frontier over the same k grid; at each
    ac_agree point, interpolate the vwap-only exp at the SAME n and print the delta. Consistently +ve
    across k on BOTH assets = additive/orthogonal; ~0 or mixed = redundant (F36 verdict)."""
    print("==== ADDITIVITY TEST: does ac_agree lift the vwap-cap frontier? (NQ + QQQ) ====")
    print("delta = ac_agree+vwap exp  MINUS  vwap-only exp interpolated at the SAME trade count.\n")
    ks = [2.0, 1.8, 1.6, 1.4, 1.2, 1.0]
    for sym in ("NQ", "QQQ"):
        bars = B._externals(con, hs_db.bars(con, "5m", "full", sym=sym), sym)
        d = H.compute_state(bars, H.P()); d.attrs["sym"] = sym
        M = momentum_state(d)
        vo = []   # vwap-only frontier (n, exp)
        for k in ks:
            r = run(d, vcap=k)["net_R"].to_numpy(); vo.append((len(r), r.mean()))
        vo_sorted = sorted(vo)
        ns = np.array([x[0] for x in vo_sorted]); es = np.array([x[1] for x in vo_sorted])
        print(f"  ---- {sym} ----")
        for k in ks:
            r = run(d, "ac_agree", M, vcap=k)["net_R"].to_numpy()
            n_ac, e_ac = len(r), r.mean()
            e_vo = float(np.interp(n_ac, ns, es))    # vwap-only exp at the SAME trade count
            print(f"  ac_agree+vwap k={k}  n={n_ac:>4} exp {e_ac:+.3f}  |  vwap-only@n {e_vo:+.3f}  |  delta {e_ac - e_vo:+.3f}")
        print()


def main():
    args = [a for a in sys.argv[1:]]
    con = hs_db.connect()
    if "--additive" in args:
        additive(con); con.close(); return
    if "--robust" in args:
        robust(con); con.close(); return
    syms = [s.upper() for s in (args or ["NQ", "QQQ", "SPY"])]
    for sym in syms:
        bars = B._externals(con, hs_db.bars(con, "5m", "full", sym=sym), sym)
        d = H.compute_state(bars, H.P()); d.attrs["sym"] = sym
        M = momentum_state(d)
        print(f"\n############ {sym} 5m  (STACK vs STACK + RSI / AccelDecel filter) ############")
        report("STACK", run(d))
        for v in VARIANTS:
            report("+" + v, run(d, v, M))
    con.close()


if __name__ == "__main__":
    main()
