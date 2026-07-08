"""Black-Scholes pricing + Greeks + implied-vol solve (stdlib only — no scipy).

T is in YEARS. For 0DTE use the fraction of a year to the close (helper `year_frac`). Greeks are
returned per natural unit: delta per $1 underlying, gamma per $1, vega per 1.00 vol (÷100 for per
1%), theta per YEAR (÷365 for per calendar day), rho per 1.00 rate.
"""
from __future__ import annotations

import math
from dataclasses import dataclass

SQRT2PI = math.sqrt(2 * math.pi)


def _N(x: float) -> float:          # standard normal CDF
    return 0.5 * (1 + math.erf(x / math.sqrt(2)))


def _n(x: float) -> float:          # standard normal PDF
    return math.exp(-0.5 * x * x) / SQRT2PI


def year_frac(minutes_to_expiry: float) -> float:
    """Convert minutes-to-expiry to a year fraction (floored so 0DTE isn't exactly 0)."""
    return max(minutes_to_expiry, 1.0) / (365.0 * 24 * 60)


@dataclass
class Greeks:
    price: float
    delta: float
    gamma: float
    vega: float        # per 1% vol
    theta: float       # per calendar day
    rho: float         # per 1% rate


def _d1d2(S, K, T, r, sigma):
    if T <= 0 or sigma <= 0 or S <= 0 or K <= 0:
        return None, None
    vt = sigma * math.sqrt(T)
    d1 = (math.log(S / K) + (r + 0.5 * sigma * sigma) * T) / vt
    return d1, d1 - vt


def price(S, K, T, r, sigma, right="C") -> float:
    d1, d2 = _d1d2(S, K, T, r, sigma)
    if d1 is None:                                   # intrinsic at expiry / degenerate
        return max(0.0, (S - K) if right == "C" else (K - S))
    disc = math.exp(-r * T)
    if right == "C":
        return S * _N(d1) - K * disc * _N(d2)
    return K * disc * _N(-d2) - S * _N(-d1)


def greeks(S, K, T, r, sigma, right="C") -> Greeks:
    d1, d2 = _d1d2(S, K, T, r, sigma)
    px = price(S, K, T, r, sigma, right)
    if d1 is None:
        intr = (S > K) if right == "C" else (S < K)
        return Greeks(px, 1.0 if (right == "C" and intr) else (-1.0 if intr else 0.0), 0, 0, 0, 0)
    disc = math.exp(-r * T)
    delta = _N(d1) if right == "C" else _N(d1) - 1
    gamma = _n(d1) / (S * sigma * math.sqrt(T))
    vega = S * _n(d1) * math.sqrt(T)
    theta_y = (-(S * _n(d1) * sigma) / (2 * math.sqrt(T))
               - (r * K * disc * _N(d2) if right == "C" else -r * K * disc * _N(-d2)))
    rho = (K * T * disc * _N(d2)) if right == "C" else (-K * T * disc * _N(-d2))
    return Greeks(round(px, 4), round(delta, 4), round(gamma, 6),
                  round(vega / 100, 4), round(theta_y / 365, 4), round(rho / 100, 4))


def implied_vol(target, S, K, T, r, right="C", lo=1e-4, hi=5.0) -> float:
    """Bisection IV solve (robust). Returns annualised sigma, or nan if no bracket."""
    if target <= max(0.0, (S - K) if right == "C" else (K - S)):
        return float("nan")
    f = lambda s: price(S, K, T, r, s, right) - target
    flo, fhi = f(lo), f(hi)
    if flo * fhi > 0:
        return float("nan")
    for _ in range(80):
        mid = 0.5 * (lo + hi)
        fm = f(mid)
        if abs(fm) < 1e-6:
            return round(mid, 4)
        if flo * fm < 0:
            hi, fhi = mid, fm
        else:
            lo, flo = mid, fm
    return round(0.5 * (lo + hi), 4)


# --- OPRA calibration (F85, research/opra_study.py, 2026-07-08) -----------------------------
# 264 real ATM QQQ IV solves over 22 sessions proved the shipped flat 0.20 underprices badly:
# market ATM IV averaged 30.8% (0DTE 38.1%, weekly 23.5%), and a realized-vol estimate underprices
# market IV by ~1.56x. These map an estimate (or a bare default) onto what the chain actually charges.
OPRA_VRP_K = 1.557                                    # market ATM IV / realized vol
_OPRA_ATM_IV = ((0, 0.381), (7, 0.235), (30, 0.22))   # ATM IV term structure by DTE


def default_iv(dte: int = 0) -> float:
    """OPRA-calibrated ATM IV for a given days-to-expiry — the replacement for the flat 0.20."""
    dte = max(0, int(dte))
    if dte <= _OPRA_ATM_IV[0][0]:
        return _OPRA_ATM_IV[0][1]
    for (d0, v0), (d1, v1) in zip(_OPRA_ATM_IV, _OPRA_ATM_IV[1:]):
        if dte <= d1:
            return round(v0 + (v1 - v0) * (dte - d0) / (d1 - d0), 4)
    return _OPRA_ATM_IV[-1][1]


def calibrate_realized_iv(realized_vol: float, dte: int = 0, lo: float = 0.10,
                          hi: float = 0.90) -> float:
    """Lift a raw realized-vol estimate to the market ATM IV it should imply (x VRP_K), floored at
    the DTE term structure so a quiet trailing window still prices near what 0DTE actually costs."""
    est = max(float(realized_vol) * OPRA_VRP_K, default_iv(dte))
    return round(min(max(est, lo), hi), 4)


if __name__ == "__main__":   # self-test: put-call parity, IV round-trip, Greek signs
    S, K, T, r, sig = 100.0, 100.0, 30 / 365, 0.04, 0.20
    c, p = price(S, K, T, r, sig, "C"), price(S, K, T, r, sig, "P")
    parity = c - p - (S - K * math.exp(-r * T))
    assert abs(parity) < 1e-6, parity
    print(f"ATM 30d: call {c:.3f} put {p:.3f} | put-call parity residual {parity:.2e}")
    iv = implied_vol(c, S, K, T, r, "C")
    assert abs(iv - sig) < 1e-3, iv
    print(f"IV round-trip: input {sig} -> solved {iv}")
    gc = greeks(S, K, T, r, sig, "C"); gp = greeks(S, K, T, r, sig, "P")
    assert 0.4 < gc.delta < 0.6 and -0.6 < gp.delta < -0.4 and gc.theta < 0, (gc, gp)
    print(f"call greeks: {gc}")
    print(f"put  greeks: {gp}")
    print("options pricing OK")
