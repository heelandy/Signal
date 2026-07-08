#!/usr/bin/env python3
"""
F35 — FEASIBILITY of the Structure Projection Engine spec (predict next HH/HL/LL/LH + projection band).
Before building a visual indicator, test the two claims it stands on:

  CLAIM 1 — PREDICTIVE: a linear projection of the next swing (proj = 2*last - prev) beats the naive
            "next = last" baseline. If it doesn't, the projected HH/HL band is decorative.
  CLAIM 2 — TRADEABLE: a structure-continuation trade (enter on fresh HH+HL state, target the projected
            next HH, stop on a close below the last HL) has edge — and does CONFIDENCE (HH/HL streak +
            ATR/volume expansion, the spec's inputs) separate winners from losers?

NQ 5m. Uses the harness structure columns (sph/spl running swings, is_hh/is_hl, st_state).

    python research/orb_projection_test.py [SYM ...]
"""
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "engine"))
import numpy as np, pandas as pd
import hs_db, hs_harness as H, hs_backtest as B, hs_validate as V

rng = np.random.default_rng(7)


def swing_seq(values, change_eps=1e-9):
    """Compress a per-bar running-swing array into the ordered sequence of DISTINCT swing levels,
    keeping the bar index where each new swing was first registered."""
    seq = []; idx = []
    last = np.nan
    for i, v in enumerate(values):
        if np.isnan(v):
            continue
        if np.isnan(last) or abs(v - last) > change_eps:
            seq.append(v); idx.append(i); last = v
    return np.array(seq), np.array(idx)


def proj_accuracy(seq, label):
    """proj = 2*last - prev (linear) vs naive = last. Report directional + magnitude skill."""
    if len(seq) < 4:
        print(f"    {label}: too few swings"); return
    prev, last, actual = seq[:-2], seq[1:-1], seq[2:]
    proj = 2 * last - prev
    mae_proj = np.mean(np.abs(proj - actual))
    mae_naive = np.mean(np.abs(last - actual))
    # directional: does proj get the SIGN of (actual-last) right more than 50%?
    move = actual - last
    dir_proj = np.sign(proj - last)
    hit = np.mean((dir_proj == np.sign(move))[move != 0]) * 100 if np.any(move != 0) else 0
    corr = np.corrcoef(proj - last, move)[0, 1] if len(move) > 2 else 0
    skill = 100 * (1 - mae_proj / mae_naive) if mae_naive > 0 else 0
    print(f"    {label:12} n={len(actual):>5}  MAE proj {mae_proj:>6.1f} vs naive {mae_naive:>6.1f}  "
          f"skill {skill:>+5.1f}%  dir-hit {hit:>4.1f}%  corr(Δproj,Δactual) {corr:+.3f}")


def continuation_test(d):
    """Spec's trade: on a fresh state→1 (HH+HL) bar, enter at close, TARGET = projected next HH
    (2*sph_last - sph_prev), STOP = spl_last (last HL). Walk to target / close<stop / 60-bar cap.
    Bucketed by CONFIDENCE = (proj distance in ATR) small=tight structure + ATR rising."""
    h, l, c = d["high"].to_numpy(), d["low"].to_numpy(), d["close"].to_numpy()
    atr = d["atr14"].to_numpy()
    st = d["st_state"].to_numpy()
    sph, spl = d["sph"].to_numpy(), d["spl"].to_numpy()
    # track previous distinct swing high for the projection
    sph_prev = np.full(len(d), np.nan); last_sph = np.nan; prev_sph = np.nan
    for i in range(len(d)):
        if not np.isnan(sph[i]) and (np.isnan(last_sph) or sph[i] != last_sph):
            prev_sph, last_sph = last_sph, sph[i]
        sph_prev[i] = prev_sph
    res = []
    i = 1; n = len(d)
    while i < n:
        fresh_long = st[i] == 1 and st[i-1] != 1
        if fresh_long and not np.isnan(sph[i]) and not np.isnan(sph_prev[i]) and not np.isnan(spl[i]) and atr[i] > 0:
            entry = c[i]; target = 2 * sph[i] - sph_prev[i]; stop = spl[i]
            if target <= entry or stop >= entry:
                i += 1; continue
            risk = entry - stop
            conf_atr = (target - entry) / atr[i]              # projection reach in ATR (spec confidence proxy)
            j = i + 1; out = None
            while j < n and j - i <= 60:
                if c[j] < stop:
                    out = (c[j] - entry) / risk; break
                if h[j] >= target:
                    out = (target - entry) / risk; break
                j += 1
            if out is None and j < n:
                out = (c[min(j, n-1)] - entry) / risk
            if out is not None:
                res.append((out, conf_atr, (sph[i] - sph_prev[i]) / atr[i]))
            i = j + 1
        else:
            i += 1
    if not res:
        print("    continuation: no setups"); return
    r = np.array([x[0] for x in res]); conf = np.array([x[1] for x in res])
    print(f"    continuation ALL  n={len(r):>4} exp {r.mean():+.3f}R  PF {V.pf(r):>4.2f}  win {100*np.mean(r>0):>2.0f}%")
    # confidence buckets: tight projection (<1 ATR reach) vs wide (>2 ATR)
    for lo, hi, lbl in [(0, 1, "tight (<1ATR)"), (1, 2, "mid (1-2ATR)"), (2, 99, "wide (>2ATR)")]:
        m = (conf >= lo) & (conf < hi)
        if m.sum() >= 20:
            rr = r[m]
            print(f"      conf {lbl:14} n={m.sum():>4} exp {rr.mean():+.3f}R  PF {V.pf(rr):>4.2f}  win {100*np.mean(rr>0):>2.0f}%")


def main():
    syms = [s.upper() for s in (sys.argv[1:] or ["NQ"])]
    con = hs_db.connect()
    for sym in syms:
        d = H.compute_state(B._externals(con, hs_db.bars(con, "5m", "full", sym=sym), sym), H.P())
        d.attrs["sym"] = sym
        print(f"\n######## {sym} 5m — Structure Projection feasibility ########")
        print("  CLAIM 1 — does linear swing projection beat the naive 'next=last'?")
        sh, _ = swing_seq(d["sph"].to_numpy())
        sl, _ = swing_seq(d["spl"].to_numpy())
        proj_accuracy(sh, "swing highs")
        proj_accuracy(sl, "swing lows")
        print("  CLAIM 2 — structure-continuation trade (target=proj HH, stop=last HL):")
        continuation_test(d)
    con.close()


if __name__ == "__main__":
    main()
