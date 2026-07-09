"""OPTIONS-NATIVE STRATEGY options-native-0.1 (F86) — the shared geometry.

A PURE options signal (not a translation of any underlying trade): sell the 0DTE variance-risk
premium F85 measured (ATM IV ~38% vs ~20% realized) with DEFINED RISK. On a contained day it is an
iron condor; on a trend day it is a one-sided credit spread on the safe side (v0.2, so the strategy
still fires — honoring "minimum 1 signal/session" — without selling into the trend).

FEED-AGNOSTIC by design: the caller supplies `quote(cp, strike) -> (bid, ask, mid) | None` and a
sorted strike array per side. Research passes the REAL OPRA book; live passes a Black-Scholes
estimate at the F85-calibrated IV until a live options feed exists. Geometry, gate and settle are
IDENTICAL on both paths — one source of truth, no drift between the backtest and the live signal.

    from bot.options.native import build, settle_pnl, SPEC, LINEAGE
    pos = build(spot, open_px, quote, strikes)          # None if no tradeable structure
    pnl = settle_pnl(pos, qqq_close)                    # 0DTE intrinsic settle, on the credit
"""
from __future__ import annotations

import json

import numpy as np

LINEAGE = "options-native-0.1"
# v0.2 spec (F86): the iron condor on contained days PLUS a directional credit spread on trend days
# (dir_em_mult further OTM on the safe side, dir_stop_mult tighter) so the strategy fires EVERY
# session (strict min-1). HONEST full-strike managed result on the 22-session OPRA window:
# WR 78 · PF 1.35 · maxDD 1.2% · 1.86 signals/session · 0 stand-aside days. WR and DD are in the
# user band; PF (target 1.6-1.8) falls short — 0DTE condors carry small wins / large losses, so PF
# is the binding constraint on this sample. (An earlier +-3.5% strike loader read PF 1.7; that was
# an artifact — it silently dropped the 2.0x-EM directional strikes. Do not narrow the strike load.)
SPEC = {"em_mult": 1.1, "wing": 6, "tp": 0.6, "stop_mult": 2.5, "trend_mult": 1.0, "min_credit": 0.10,
        "directional": True, "dir_em_mult": 2.0, "dir_stop_mult": 1.25}

# 7DTE MANAGED CONDOR (F89) — the FIRST structure to reach the user band on the OPRA window:
# WR 83.3 · PF 1.73 · DD 4.4% · +0.122R (18 in-sample trades; leave-one-out PF 1.53-2.60, so not a
# single-trade artifact). 0DTE premium selling structurally caps below the band's PF floor (spread
# 1.11, condor 1.35 — negative skew); a 7-day hold with a TP-early/settle manager clears it. Its OWN
# spec so tuning it never perturbs the 0DTE SPEC (the two were coupled before). IN-SAMPLE — accrues
# forward paper before it's trusted. NOTE the stop rarely binds (losses settle at full max-loss), so
# size on the full wing. 14DTE is untestable on this window (its EM pushes shorts past ±6% coverage).
SPEC_7DTE = dict(SPEC, em_mult=1.0, wing=5, tp=0.6, stop_mult=2.0, dte=7)
STRUCTURE_SPECS = {"condor_7dte": SPEC_7DTE}


def spec_for(structure: str) -> dict:
    """The geometry spec for a structure (its own overrides if any, else SPEC), tagged with the
    structure so build() dispatches correctly. Keeps per-structure tuning decoupled."""
    return dict(STRUCTURE_SPECS.get(structure, SPEC), structure=structure)


def snap(strikes: np.ndarray, target: float, tol: float = 1.5) -> float | None:
    """Nearest available strike to target (within tol dollars, else None)."""
    if strikes is None or len(strikes) == 0:
        return None
    k = float(strikes[int(np.abs(np.asarray(strikes) - target).argmin())])
    return k if abs(k - target) <= tol else None


def expected_move(quote, strikes: dict, spot: float) -> float | None:
    """The market's own expected move = ATM straddle mid at entry."""
    kc, kp = snap(strikes["C"], spot), snap(strikes["P"], spot)
    c, p = quote("C", kc), quote("P", kp)
    if not c or not p or c[2] <= 0 or p[2] <= 0:
        return None
    return c[2] + p[2]


def _spread(quote, cp: str, strikes: np.ndarray, short_target: float, wing: float, side_out: int):
    """Price one vertical credit spread: short at short_target, long `wing` further OUT (side_out
    = +1 for calls / above, -1 for puts / below). Returns (short_K, long_K, wing, credit) or None.
    Credit = short sold at BID − long bought at ASK (honest fill)."""
    ks = snap(strikes, short_target)
    kl = snap(strikes, (ks + side_out * wing) if ks is not None else short_target + side_out * wing)
    s, l = quote(cp, ks), quote(cp, kl)
    if ks is None or kl is None or s is None or l is None:
        return None
    w = abs(kl - ks)
    if w <= 0:
        return None
    return ks, kl, w, (s[0] - l[1])


def build(spot: float, open_px: float, quote, strikes: dict, spec: dict = SPEC,
          directional: bool = True) -> dict | None:
    """Build the position for THIS entry. Iron condor on a contained day; on a trend day, a
    one-sided credit spread on the side AWAY from the trend (only when directional=True — else the
    trend day stands aside, returning None). Returns a normalized position dict or None."""
    em = expected_move(quote, strikes, spot)
    if not em or em <= 0:
        return None
    trend = abs(spot - open_px) > spec["trend_mult"] * em
    ksc = klc = ksp = klp = None
    wings = []
    structure = spec.get("structure", "condor")   # condor | credit_spread | long_single (small acct)
    if structure == "long_single":
        # SMALL-ACCOUNT WINNER (opra_smallacct.py): a naked ATM 0DTE long, directional by the open
        # lean. Risk = premium only (~$300); the one structure with positive hold-to-settle
        # expectancy (+0.22R, PF 1.34) when there's no live feed to manage a spread.
        cp = "C" if spot >= open_px else "P"
        kl = snap(strikes[cp], spot)
        ql = quote(cp, kl)
        if kl is None or ql is None or ql[1] <= 0:
            return None
        debit = ql[1]
        return {"kind": f"long_{'call' if cp == 'C' else 'put'}", "structure_type": "debit",
                "cp": cp, "long_k": float(kl), "short_k": None, "debit": round(debit, 3),
                "credit": 0.0, "max_loss": round(debit, 3), "wing": 0.0, "em": round(em, 3),
                "trend": bool(trend), "spot_entry": round(float(spot), 2)}
    if structure == "credit_spread":
        # SMALL-ACCOUNT variant: ONE credit spread instead of two — half the legs/commissions and a
        # single directional lean. Sell the side AWAY from the drift (up -> put spread, down/flat ->
        # call spread) at the normal em distance; wing tunable smaller to shrink max loss (BP).
        dem = spec["em_mult"]
        if spot >= open_px:
            ps = _spread(quote, "P", strikes["P"], spot - dem * em, spec["wing"], -1)
            if ps is None:
                return None
            ksp, klp, wp, credit = ps
            wings, kind = [wp], "put_spread"
        else:
            cs = _spread(quote, "C", strikes["C"], spot + dem * em, spec["wing"], +1)
            if cs is None:
                return None
            ksc, klc, wc, credit = cs
            wings, kind = [wc], "call_spread"
    elif not trend:
        cs = _spread(quote, "C", strikes["C"], spot + spec["em_mult"] * em, spec["wing"], +1)
        ps = _spread(quote, "P", strikes["P"], spot - spec["em_mult"] * em, spec["wing"], -1)
        if cs is None or ps is None:
            return None
        ksc, klc, wc, cc = cs
        ksp, klp, wp, cp_ = ps
        credit, wings, kind = cc + cp_, [wc, wp], "condor"
    elif directional:
        dem = spec.get("dir_em_mult", spec["em_mult"])   # trend day: place the safe-side short
        if spot >= open_px:                       # up-trend: call side would be run over -> sell PUTS
            ps = _spread(quote, "P", strikes["P"], spot - dem * em, spec["wing"], -1)
            if ps is None:
                return None
            ksp, klp, wp, credit = ps
            wings, kind = [wp], "put_spread"
        else:                                     # down-trend: sell the CALL spread (safe side)
            cs = _spread(quote, "C", strikes["C"], spot + dem * em, spec["wing"], +1)
            if cs is None:
                return None
            ksc, klc, wc, credit = cs
            wings, kind = [wc], "call_spread"
    else:
        return None                               # trend day, directional disabled -> stand aside
    wing = min(wings)
    if credit < spec["min_credit"]:
        return None
    max_loss = wing - credit                      # only one side can finish ITM -> loss capped here
    if max_loss <= 0:
        return None
    return {"kind": kind, "ksc": ksc, "klc": klc, "ksp": ksp, "klp": klp,
            "wing": round(wing, 2), "credit": round(credit, 3), "max_loss": round(max_loss, 3),
            "em": round(em, 3), "trend": bool(trend), "spot_entry": round(float(spot), 2)}


def settle_pnl(pos: dict, s_close: float) -> float:
    """0DTE intrinsic settle P&L. DEBIT structures (naked long / debit spread): long intrinsic
    (minus short intrinsic, capped) − debit. CREDIT structures (condor / spread): credit − (call-
    spread loss + put-spread loss), each capped at its wing."""
    if pos.get("structure_type") == "debit":
        cp, kl = pos["cp"], pos["long_k"]
        li = max((s_close - kl) if cp == "C" else (kl - s_close), 0.0)
        if pos.get("short_k") is not None:                 # debit spread
            ks = pos["short_k"]
            si = max((s_close - ks) if cp == "C" else (ks - s_close), 0.0)
            payoff = min(li - si, pos.get("wing") or (abs(ks - kl)))
        else:                                              # naked long
            payoff = li
        return payoff - pos["debit"]
    wing, cost = pos["wing"], 0.0
    if pos.get("ksc") is not None:
        cost += float(np.clip(s_close - pos["ksc"], 0, wing))
    if pos.get("ksp") is not None:
        cost += float(np.clip(pos["ksp"] - s_close, 0, wing))
    return pos["credit"] - cost


def ret_on_risk(pos: dict, s_close: float) -> float:
    return settle_pnl(pos, s_close) / pos["max_loss"] if pos["max_loss"] > 0 else 0.0


# --- Black-Scholes quote provider (LIVE, until a real options feed exists) -------------------
# No live chain yet, so the live loop builds and MARKS positions with Black-Scholes at the F85-
# calibrated IV (default_iv). Estimated, but consistent with the whole options stack; the settle
# (outcome) uses only the underlying close, so the resolved P&L is real up to the entry credit.
def bs_quote(spot: float, mins_to_close: float, iv: float, r: float = 0.04):
    from bot.options.pricing import price, year_frac
    T = year_frac(mins_to_close)

    def q(cp: str, K: float | None):
        if K is None:
            return None
        mid = price(spot, K, T, r, iv, cp)
        sp = max(0.02, mid * 0.05)                    # OTM 0DTE spread estimate (no live chain)
        return (max(mid - sp / 2, 0.0), mid + sp / 2, mid)
    return q


def strikes_around(spot: float, width: float = 0.04, step: float = 1.0) -> dict:
    import numpy as _np
    arr = _np.arange(round(spot * (1 - width)), round(spot * (1 + width)) + step, step)
    return {"C": arr, "P": arr}


def mark_to_close_cost(pos: dict, spot_now: float, mins_to_close: float, iv: float,
                       r: float = 0.04) -> float:
    """BS estimate of the cost to CLOSE the position now (buy back shorts, sell wings) — the live
    TP/stop check. Cost < (1-tp)*credit => take profit; cost-credit >= stop*credit => stop."""
    q = bs_quote(spot_now, mins_to_close, iv, r)
    cost = 0.0
    if pos.get("ksc") is not None:
        s, l = q("C", pos["ksc"]), q("C", pos["klc"])
        cost += s[1] - l[0]
    if pos.get("ksp") is not None:
        s, l = q("P", pos["ksp"]), q("P", pos["klp"])
        cost += s[1] - l[0]
    return cost


# --- dedicated options-native journal (SEALED; NOT the directional decisions table) ----------
# A multi-leg options position does not map onto the entry/stop/tp schema, so it gets its own
# append-only store. Sealed from core analytics by construction (separate file), visible in the
# UI via /api/options_native, and it accrues the strategy's real-premium track record.
def journal_path():
    from bot.config import BOT_ROOT
    return BOT_ROOT.parent / "data" / "options_native_journal.jsonl"


def load_journal(lineage: str | None = None) -> list[dict]:
    """All journaled options rows, or only one lineage's (the journal is a single file tagged by
    `lineage` — user 2026-07-08: every approved options lineage shares it, keyed by its category id).
    Rows without a lineage tag are the original options-native ones."""
    p = journal_path()
    if not p.exists():
        return []
    rows = [json.loads(ln) for ln in p.read_text(encoding="utf-8").splitlines() if ln.strip()]
    if lineage is None:
        return rows
    return [r for r in rows if (r.get("lineage") or LINEAGE) == lineage]


def _append_journal(rec: dict) -> None:
    p = journal_path()
    p.parent.mkdir(parents=True, exist_ok=True)
    with open(p, "a", encoding="utf-8") as f:
        f.write(json.dumps(rec) + "\n")


def _cost_to_close(pos: dict, book: dict, hm: int):
    """Real cost to close the position at minute hm from a full-day book {(cp,strike,hm):(b,a,m)}:
    buy back shorts @ ask, sell wings @ bid. None if any active leg is unquoted that minute."""
    cost, ok = 0.0, True
    if pos.get("ksc") is not None:
        cc, cl = book.get(("C", pos["ksc"], hm)), book.get(("C", pos["klc"], hm))
        if cc is None or cl is None:
            ok = False
        else:
            cost += cc[1] - cl[0]
    if pos.get("ksp") is not None:
        pc, pl = book.get(("P", pos["ksp"], hm)), book.get(("P", pos["klp"], hm))
        if pc is None or pl is None:
            ok = False
        else:
            cost += pc[1] - pl[0]
    return cost if ok else None


def walk_manage(pos: dict, mark_fn, spec: dict, entry_hm: int, settle_close: float,
                close_hm: int = 955) -> tuple[str, int, float]:
    """Manage minute-by-minute: take profit at tp*credit, hard stop at (dir_)stop*credit, else
    settle 0DTE intrinsic at the close. `mark_fn(hm) -> cost_to_close | None`. The SHARED manager —
    research and the live journal both call this, so the backtest and the live stream can't drift."""
    credit = pos["credit"]
    stop = spec.get("dir_stop_mult", spec["stop_mult"]) if pos["kind"] != "condor" else spec["stop_mult"]
    for hm in range(entry_hm + 1, close_hm + 1):
        cost = mark_fn(hm)
        if cost is None:
            continue
        pnl_now = credit - cost
        if pnl_now >= spec["tp"] * credit:
            return "tp", hm, spec["tp"] * credit
        if pnl_now <= -stop * credit:
            return "stop", hm, -stop * credit
    return "settle", close_hm, settle_pnl(pos, settle_close)


def _structure_of(kind) -> str:
    """Normalize a position kind to its strategy bucket (per-structure performance / dedup)."""
    k = str(kind or "")
    if k == "condor":
        return "condor"
    if k in ("put_spread", "call_spread"):
        return "credit_spread"
    if k in ("long_call", "long_put"):
        return "long_single"
    return k or "?"


STRUCTURES = ("condor", "credit_spread", "long_single")

# Approved OPTIONS lineages surfaced on the Selected-Contract panel (user 2026-07-08). Each carries
# the journal STRUCTURE buckets that form its per-strategy scorecard + the underlyings it prices.
# All share the one journal file, tagged by `lineage` (their "category id").
# Ordered + tiered by measured edge vs the goal WR75-85 · PF>=1.7 · DD<=10% (user 2026-07-09). T1
# carries the book · T2 = real edge, watch. The opt-native STRUCTURES are ALSO tier-ordered (7DTE
# condor is the only in-band one -> first; credit-spread is a loser PF 0.78 -> last, flagged DROP).
DROP_STRUCTURES = {"credit_spread"}   # loser (VRP credit spread PF 0.78, -0.008R) — deprioritized in the UI
OPTIONS_LINEAGES = {
    "volbreak-0dte-0.1":  {"tier": 1, "label": "volbreak · 0DTE naked", "underlyings": ["QQQ", "SPY"],
                           "structures": ("long_single",), "kind": "naked", "dte": 0,
                           "headline": "0DTE NAKED — QQQ PF 3.30 9/9 · SPY PF 2.51 9/9 (options_cross) — strongest edge"},
    "options-native-0.1": {"tier": 1, "label": "opt-native (VRP)", "underlyings": ["QQQ", "SPY"],
                           "structures": ("condor_7dte", "condor", "long_single", "credit_spread"), "dte": 0,
                           "headline": "VRP — 7DTE condor WR83%/PF1.73 IN-BAND · condor/naked edge · credit-spread DROP"},
    "swing-1d-0.1":       {"tier": 2, "label": "swing · 21DTE naked/debit", "underlyings": ["QQQ"],
                           "structures": ("long_single",), "kind": "naked", "dte": 21,
                           "headline": "21DTE NAKED PF 1.98 6/6 · DEBIT PF 1.88 6/6 (options_cross); underlying swing 7/7"},
    "options-0.1":        {"tier": 2, "label": "ORB · 0DTE naked", "underlyings": ["QQQ", "SPY"],
                           "structures": ("long_single",), "kind": "naked", "dte": 0,
                           "headline": "ORB → 0DTE NAKED — gauntlet PASS both sides (options_replay F74)"},
}


def approved_options_lineages() -> list[dict]:
    """The options lineages for the Selected-Contract dropdown, TIER-ORDERED, each with its category
    id + paper-approval state (data-driven so a newly-approved options lineage shows up in its tier)."""
    from bot.approval import paper_approved
    items = sorted(OPTIONS_LINEAGES.items(), key=lambda kv: kv[1].get("tier", 9))
    return [{"lineage": lin, "tier": m.get("tier", 9), "label": m["label"], "underlyings": m["underlyings"],
             "structures": list(m["structures"]), "approved": bool(paper_approved(lin))}
            for lin, m in items]


def record_session(date: str, day_book: dict, strikes: dict, ref: dict, spec: dict = SPEC,
                   priced_from: str = "opra_chain") -> list[dict]:
    """Journal EVERY structure (condor · credit_spread · naked long) for both entry slots of one
    CLOSED session — so per-structure performance shows which strategy is working (user 2026-07-08).
    Credit structures are MANAGED (TP/stop on the day's real marks); the naked long holds to settle.
    Dedup by (date, slot, structure). HONEST: priced_from!='opra_chain' is advisory (0DTE skew, F86)."""
    import datetime
    done = {(r["date"], r["slot"], r.get("structure") or _structure_of(r.get("kind")))
            for r in load_journal()}
    out = []
    for slot, hm in (("am", 600), ("pm", 780)):
        spot, open_px = ref["spot"].get(hm), ref.get("open")
        if spot is None or open_px is None or ref.get("close") is None:
            continue
        q = (lambda cp, K, _hm=hm: day_book.get((cp, K, _hm)) if K is not None else None)
        for structure in STRUCTURES:
            if (date, slot, structure) in done:
                continue
            pos = build(spot, open_px, q, strikes, spec=dict(spec, structure=structure))
            if pos is None:
                continue
            if pos.get("structure_type") == "debit":       # naked long: hold to settle (no intraday mgmt)
                outcome, exit_hm, pnl = "settle", 955, settle_pnl(pos, float(ref["close"]))
            else:                                           # credit structures: MANAGED (TP/stop)
                outcome, exit_hm, pnl = walk_manage(pos, lambda h: _cost_to_close(pos, day_book, h),
                                                    spec, hm, float(ref["close"]))
            ml = pos.get("max_loss") or 0.0
            ret = pnl / ml if ml > 0 else 0.0
            rec = {"lineage": LINEAGE, "date": date, "slot": slot, "structure": structure,
                   "entry_hm": hm, "exit_hm": exit_hm, "kind": pos["kind"], "exit": outcome,
                   "credit": pos.get("credit"), "debit": pos.get("debit"),
                   "structure_type": pos.get("structure_type"), "max_loss": pos["max_loss"],
                   "wing": pos.get("wing"), "cp": pos.get("cp"), "long_k": pos.get("long_k"),
                   "short_k": pos.get("short_k"), "ksc": pos.get("ksc"), "klc": pos.get("klc"),
                   "ksp": pos.get("ksp"), "klp": pos.get("klp"), "em": pos.get("em"),
                   "spot_entry": pos.get("spot_entry"), "close": round(float(ref["close"]), 2),
                   "ret": round(ret, 3), "pnl": round(pnl, 3),
                   "outcome": "win" if ret > 0 else "loss", "priced_from": priced_from,
                   "resolved_at": datetime.datetime.utcnow().isoformat() + "Z"}
            _append_journal(rec)
            out.append(rec)
    return out


def performance_by_structure(lineage: str = LINEAGE) -> dict:
    """Per-structure scorecard from the journal (which strategy is working, after each entry).
    Buckets: condor · credit_spread · long_single (naked). Includes paper-traded rows if present."""
    from collections import defaultdict
    g = defaultdict(list)
    for r in load_journal(lineage):
        g[r.get("structure") or _structure_of(r.get("kind"))].append(r)
    structs = OPTIONS_LINEAGES.get(lineage, {}).get("structures") or (STRUCTURES + ("condor_7dte",))
    out = {}
    for name in structs:                          # per-lineage buckets (naked-only lineages -> just long_single)
        rows = g.get(name, [])
        rr = np.array([x.get("ret", 0.0) for x in rows if x.get("ret") is not None])
        if not len(rr):
            out[name] = {"n": 0}
            continue
        wins, losses = rr[rr > 0], rr[rr <= 0]
        pf = float(wins.sum() / abs(losses.sum())) if losses.sum() < 0 else None
        live_n = sum(1 for x in rows if x.get("priced_from") == "alpaca_live")
        out[name] = {"n": int(len(rr)), "win_pct": round(100 * float((rr > 0).mean()), 1),
                     "pf": round(pf, 2) if pf else None, "avg_ret": round(float(rr.mean()), 3),
                     "sessions": len({x.get("date") for x in rows}),
                     "backtest_n": len(rr) - live_n, "live_n": live_n,   # opra_chain vs alpaca_live
                     "source": "live" if live_n and live_n == len(rr) else
                               ("backtest" if not live_n else "mixed")}
    return out


def _mins_to_close() -> float:
    """LIVE minutes from now to the 16:00 ET close, floored at 1 (0DTE time-of-day, so a 15:00
    contract isn't priced as if 6h remain). Falls back to a half-session if the clock is unreadable."""
    try:
        import pandas as pd
        now = pd.Timestamp.now(tz="America/New_York")
        return max(1.0, (16 - now.hour) * 60.0 - now.minute)
    except Exception:
        return 360.0


def describe(pos: dict, spot: float, mins_to_close: float | None = None, iv: float | None = None) -> dict:
    mins_to_close = _mins_to_close() if mins_to_close is None else mins_to_close
    """Fully price a position for the Selected-Contract panel + options calculator: every leg with
    BS greeks at the F85-calibrated IV, plus net credit, max loss, and breakevens. This is what the
    options-native signal hands to the UI (user 2026-07-08)."""
    from bot.options.pricing import greeks, default_iv, year_frac
    iv = iv or default_iv(0)
    T = year_frac(mins_to_close)

    def leg(cp, K, side):
        g = greeks(float(spot), float(K), T, 0.04, iv, cp)
        return {"right": cp, "strike": float(K), "side": side, "px": g.price, "delta": g.delta,
                "gamma": g.gamma, "theta": g.theta, "vega": g.vega}
    if pos.get("structure_type") == "debit":               # naked long / debit spread
        cp, kl = pos["cp"], pos["long_k"]
        legs = [leg(cp, kl, "long")]
        be = [round(kl + (pos["debit"] if cp == "C" else -pos["debit"]), 2)]
        if pos.get("short_k") is not None:
            legs.append(leg(cp, pos["short_k"], "short"))
        return {"lineage": LINEAGE, "underlying": pos.get("underlying", "QQQ"), "kind": pos["kind"],
                "legs": legs, "spot": round(float(spot), 2), "iv": round(iv, 4),
                "debit": pos["debit"], "credit": 0.0, "max_loss": pos["max_loss"],
                "breakevens": be, "max_profit": "unlimited" if pos.get("short_k") is None else None,
                "ret_at_max": None}
    legs, be = [], []
    if pos.get("ksc") is not None:
        legs += [leg("C", pos["ksc"], "short"), leg("C", pos["klc"], "long")]
        be.append(round(pos["ksc"] + pos["credit"], 2))          # upper breakeven
    if pos.get("ksp") is not None:
        legs += [leg("P", pos["ksp"], "short"), leg("P", pos["klp"], "long")]
        be.append(round(pos["ksp"] - pos["credit"], 2))          # lower breakeven
    return {"lineage": LINEAGE, "underlying": pos.get("underlying", "QQQ"), "kind": pos["kind"],
            "legs": legs, "spot": round(float(spot), 2),
            "iv": round(iv, 4), "credit": pos["credit"], "max_loss": pos["max_loss"],
            "wing": pos.get("wing"), "breakevens": sorted(be),
            "max_profit": pos["credit"], "ret_at_max": round(pos["credit"] / pos["max_loss"], 2)
            if pos.get("max_loss") else None}


def latest_signal() -> dict | None:
    """The most recent journaled position, fully priced for the UI panels (or None if empty)."""
    j = load_journal()
    if not j:
        return None
    r = sorted(j, key=lambda x: (x["date"], x["slot"]))[-1]
    d = describe(r, r.get("spot_entry") or r.get("close"))
    d.update({"date": r["date"], "slot": r["slot"], "outcome": r.get("outcome"),
              "ret": r.get("ret"), "priced_from": r.get("priced_from")})
    return d


def live_signal_from_alpaca(underlying: str = "QQQ", spot: float | None = None,
                            open_px: float | None = None, structure: str = "condor",
                            dte: int = 0) -> dict:
    """Build a LIVE options-native position from the real Alpaca chain (the F86 feed), fully priced
    for the Selected-Contract panel + calculator. Real bid/ask — NOT a BS estimate.
    structure: "condor" (0DTE VRP, needs management) | "long_single" (small-account winner, +0.22R
    hold-to-settle) | "credit_spread" (needs a live feed to manage) | "condor_7dte" (F89 band-reacher,
    pulls the ~7-day expiry). `dte`: 0 = the 0DTE chain; >0 = the expiry nearest that many days out."""
    from bot.market_data.options_data import alpaca_chain_0dte, alpaca_chain_dte
    ch = (alpaca_chain_dte(underlying, target_dte=dte, spot=spot) if dte > 0
          else alpaca_chain_0dte(underlying, spot=spot))      # filter strikes around the REAL spot
    if spot is None and ch.get("ok"):
        allk = sorted(set(list(ch["strikes"].get("C", [])) + list(ch["strikes"].get("P", []))))
        spot = float(allk[len(allk) // 2]) if allk else None
    if spot is None:
        return {"error": ch.get("error", "no spot")}
    spec = spec_for(structure)                                # per-structure geometry (7DTE has its own)
    op = open_px if open_px is not None else spot
    # REAL Alpaca chain ONLY — if the selected structure can't build on live quotes (e.g. after
    # hours, or thin OTM wings for a condor), return an error so the panel shows EMPTY rather than a
    # faked estimate (user 2026-07-08: "if there's no data for the condor leave it empty").
    if not ch.get("ok"):
        return {"error": ch.get("error", "no live chain")}
    q = (lambda cp, K: ch["book"].get((cp, K)) if K is not None else None)
    # a 7DTE condor is a condor (not a trend-day one-sided spread) — directional=False stands aside
    # on a trend entry rather than emitting a single spread the backtest never measured.
    pos = build(spot, op, q, ch["strikes"], spec=spec, directional=(dte == 0))
    if pos is None:
        return {"error": f"no live {structure} data (chain too thin at spot {round(spot, 2)})"}
    eff_dte = ch.get("dte", 0) or dte
    from bot.options.pricing import default_iv
    d = describe(pos, spot, mins_to_close=(eff_dte * 390.0 + _mins_to_close()) if eff_dte else None,
                 iv=default_iv(eff_dte))
    d.update({"priced_from": "alpaca_live", "structure": structure, "expiry": ch.get("expiry"),
              "dte": eff_dte, "is_0dte": ch.get("is_0dte", eff_dte == 0), "n_contracts": ch.get("n")})
    # O13 FIX (audit 2026-07-08): describe() emits only `legs` (for display) — it DROPS the raw
    # strikes. open_position/manage_open reconstruct the position from ksc/klc/ksp/klp, so without
    # these the manager marks all-None legs -> cost 0 -> pnl==credit -> INSTANT FALSE TP on tick 1.
    # Carry the geometry so a managed position can actually be re-priced on the live chain.
    d.update({k: pos.get(k) for k in ("structure_type", "cp", "long_k", "short_k",
                                      "ksc", "klc", "ksp", "klp", "spot_entry")})
    return d


# --- LIVE per-tick management (user 2026-07-08) -------------------------------------------------
# Credit structures lose hold-to-settle (F87/F88) and need MANAGEMENT: mark each open position on
# the live chain every tick, take profit at tp*credit, stop at stop*credit, else settle at expiry.
# Open positions live in their own store; the closed ones land in the journal like everything else.
def open_path():
    from bot.config import BOT_ROOT
    return BOT_ROOT.parent / "data" / "options_native_open.jsonl"


def load_open() -> list[dict]:
    p = open_path()
    if not p.exists():
        return []
    return [json.loads(ln) for ln in p.read_text(encoding="utf-8").splitlines() if ln.strip()]


def _save_open(rows: list[dict]) -> None:
    p = open_path()
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text("".join(json.dumps(r) + "\n" for r in rows), encoding="utf-8")


def open_position(sig: dict, date: str, slot: str, structure: str) -> dict | None:
    """Record a freshly-entered position as OPEN. Dedup by (date, slot, structure) against BOTH the
    open store AND the journal — otherwise a position that TP's inside its own entry window would
    re-enter on the next tick (the duplicate-entry class, audit 2026-07-08). `sig` carries the
    strikes + credit/debit + max_loss."""
    key = (date, slot, structure)
    rows = load_open()
    if any((r.get("date"), r.get("slot"), r.get("structure")) == key for r in rows):
        return None
    if any((r.get("date"), r.get("slot"), r.get("structure") or _structure_of(r.get("kind"))) == key
           for r in load_journal()):
        return None
    import datetime
    rec = {k: sig.get(k) for k in ("kind", "structure_type", "cp", "long_k", "short_k", "ksc",
                                   "klc", "ksp", "klp", "wing", "credit", "debit", "max_loss",
                                   "spot_entry", "underlying", "priced_from", "expiry")}
    rec.update({"lineage": LINEAGE, "date": date, "slot": slot, "structure": structure,
                "opened_at": datetime.datetime.utcnow().isoformat() + "Z", "status": "open"})
    rows.append(rec)
    _save_open(rows)
    return rec


def manage_open(mark_cost_fn, settle_close_fn, spec: dict = SPEC, close_hm: int = 955,
                now_hm: int | None = None) -> list[dict]:
    """One management pass over the open positions. `mark_cost_fn(pos) -> cost_to_close | None`
    (live chain); `settle_close_fn(date) -> underlying close | None`. Credit positions take profit
    at tp*credit / stop at stop*credit, else settle at/after close_hm; naked longs hold to settle.
    Closed positions are journalled; open ones are re-saved. Returns the rows just closed."""
    import datetime
    rows, still, closed = load_open(), [], []
    for r in rows:
        credit = r.get("credit") or 0.0
        exit_kind, pnl = None, None
        is_debit = r.get("structure_type") == "debit"
        # O12 FIX: resolve the spec PER POSITION — a 7DTE condor manages on SPEC_7DTE (tp/stop that
        # put it IN band), not on whatever single spec the caller passed. Held to expiry it's only
        # PF 1.08; the early TP is the whole edge, so the manager must use the structure's own tp.
        struct = r.get("structure") or _structure_of(r.get("kind"))
        ps = dict(spec, **STRUCTURE_SPECS.get(struct, {}))
        if not is_debit and credit > 0:                        # credit structure -> TP / stop live
            cost = mark_cost_fn(r)
            if cost is not None:
                pnl_now = credit - cost
                stop = (ps.get("dir_stop_mult", ps["stop_mult"])
                        if r.get("kind") != "condor" else ps["stop_mult"])
                if pnl_now >= ps["tp"] * credit:
                    exit_kind, pnl = "tp", ps["tp"] * credit
                elif pnl_now <= -stop * credit:
                    exit_kind, pnl = "stop", -stop * credit
        # settle only at the position's ACTUAL expiry (0-day fix): expiry's close must be available,
        # so a non-0DTE position is never force-settled at an earlier day's close
        if exit_kind is None and now_hm is not None and now_hm >= close_hm:
            sc = settle_close_fn(r.get("expiry") or r.get("date"))
            if sc is not None:
                exit_kind, pnl = "settle", settle_pnl(r, float(sc))
        if exit_kind is None:
            still.append(r)
            continue
        ret = pnl / r["max_loss"] if r.get("max_loss") else 0.0
        rec = dict(r, exit=exit_kind, ret=round(ret, 3), pnl=round(pnl, 3),
                   outcome="win" if ret > 0 else "loss", status="closed",
                   resolved_at=datetime.datetime.utcnow().isoformat() + "Z")
        _append_journal(rec)
        closed.append(rec)
    _save_open(still)
    return closed


def journal_summary(lineage: str = LINEAGE) -> dict:
    """WR / PF / avg-ret / maxDD over the journaled real-premium rows — the live scorecard."""
    j = [r for r in load_journal(lineage) if r.get("priced_from") == "opra_chain"]
    if not j:
        return {"n": 0, "rows": []}
    r = np.array([x["ret"] for x in j])
    wins, losses = r[r > 0], r[r <= 0]
    eq = np.cumsum(r) * 0.02
    peak = np.maximum.accumulate(np.concatenate([[0], eq]))
    dd = float((peak - np.concatenate([[0], eq])).max() * 100)
    return {"n": len(j), "win_pct": round(100 * float((r > 0).mean()), 1),
            "pf": round(float(wins.sum() / abs(losses.sum())), 2) if losses.sum() < 0 else None,
            "avg_ret": round(float(r.mean()), 3), "maxDD_pct": round(dd, 1),
            "sessions": len({x["date"] for x in j}),
            "signals_per_session": round(len(j) / max(len({x["date"] for x in j}), 1), 2)}
