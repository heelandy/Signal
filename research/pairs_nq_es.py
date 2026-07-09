"""NQ-ES PAIRS — cointegration spread mean-reversion (Gatev-Goetzmann-Rouwenhorst, RFS 2006).
Trade the z-score of the spread log(NQ) - beta*log(ES) with a ROLLING hedge ratio (handles the
slow drift): enter when |z| > Zin, exit when z reverts through Zout (or a time stop). Two-leg,
dollar-neutral -> uncorrelated with every directional strategy in the book.

R is reported in units of the trade-return std (a positive scaling of ret, so the CI gate is on
the same sign). Reported through strat_daily's gauntlet.

    python research/pairs_nq_es.py [Zin Zout]     (default 2.0 0.5)
"""
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "engine"))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import numpy as np, pandas as pd
import hs_db
from strat_daily import load, cost_pct, report


def s_pairs(nq, es, dt, Zin=2.0, Zout=0.5, W=60, ZW=20, tstop=20):
    ln_a, ln_b = np.log(nq), np.log(es)
    sa, sb = pd.Series(ln_a), pd.Series(ln_b)
    beta = (sa.rolling(W).cov(sb) / sb.rolling(W).var()).to_numpy()   # rolling hedge ratio
    spread = pd.Series(ln_a - beta * ln_b)
    z = ((spread - spread.rolling(ZW).mean()) / spread.rolling(ZW).std()).to_numpy()
    n = len(nq); pos = 0; e_nq = e_es = 0.0; e_i = 0; raw = []
    for i in range(W + ZW, n):
        if not np.isfinite(z[i]):
            continue
        if pos == 0:
            if z[i] > Zin:   pos, e_nq, e_es, e_i = -1, nq[i], es[i], i   # short spread: short NQ / long ES
            elif z[i] < -Zin: pos, e_nq, e_es, e_i = 1, nq[i], es[i], i   # long spread:  long NQ / short ES
        else:
            hit = (pos == 1 and z[i] >= -Zout) or (pos == -1 and z[i] <= Zout) or (i - e_i >= tstop)
            if hit:
                rn, re = (nq[i] - e_nq) / e_nq, (es[i] - e_es) / e_es
                gross = pos * rn - pos * re                               # long-NQ/short-ES for pos=1
                ret = gross - (cost_pct("NQ", e_nq) + cost_pct("ES", e_es))
                raw.append((dt.iloc[i], pos, ret)); pos = 0
    if not raw:
        return []
    sig = np.std([r[2] for r in raw]) or 1.0                             # R = ret / trade-ret std
    return [(t, d, r, r / sig) for (t, d, r) in raw]


def main():
    Zin = float(sys.argv[1]) if len(sys.argv) > 1 else 2.0
    Zout = float(sys.argv[2]) if len(sys.argv) > 2 else 0.5
    con = hs_db.connect()
    a = load(con, "NQ").assign(day=lambda x: x["dt"].dt.normalize())
    b = load(con, "ES").assign(day=lambda x: x["dt"].dt.normalize())
    m = a.merge(b, on="day", suffixes=("_nq", "_es")).sort_values("day").reset_index(drop=True)
    con.close()
    print(f"\n######## NQ-ES pairs (z-score spread) — {len(m)} aligned sessions ########")
    for zin in (2.0, 2.5):
        report(f"pairs z{zin}", s_pairs(m["close_nq"].to_numpy(), m["close_es"].to_numpy(),
                                        m["dt_nq"], Zin=zin, Zout=Zout))
    print("\nPASS = exp>0 net costs AND bootstrap CI(R)>0 AND >=70% yrs+ AND OOS-out>0 AND both sides>0.")


if __name__ == "__main__":
    main()
