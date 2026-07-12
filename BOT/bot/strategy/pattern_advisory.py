"""PATTERN ADVISORY v1 — read-only re-presentation of the live scan as the pattern panel.

ADVISORY / DISPLAY ONLY (freeze-safe, docs/PATTERN_RECOGNITION_V1.md §13): creates NO orders,
changes NO entries, touches NOT the certified signal path. It re-presents `live.scan_watchlist`
proposals as the pattern-recognition panel, so it CANNOT drift from what the system actually sees.

The one thing it adds is the CORRECTED evidence chip (PR1, 2026-07-12):
  QQQ/SPY  ORB-C  -> CERTIFIED  (robust edge; actionable via the EXISTING certified path)
  NQ/MNQ   ORB-C+RT -> CONTEXT/UNPROVEN  (corrected engine flat-to-neg — advisory only, NEVER ACTION)
  ES/MES   -> UNPROVEN ·  GC/MGC -> UNVERIFIED
ML stays ABSTAIN (no pattern-specific model). Only a CERTIFIED asset may ever read as an ENTER
prompt; everything else reads CONTEXT / WATCH ONLY.

    python -m bot.strategy.pattern_advisory NQ          # tonight's NQ 5m + 15m advisory snapshot
"""
from __future__ import annotations

# Corrected evidence per asset (PR1 supersedes asset_config.status, which still says NQ 'validated').
EVIDENCE = {"QQQ": "CERTIFIED", "SPY": "CERTIFIED", "NQ": "CONTEXT", "MNQ": "CONTEXT",
            "ES": "UNPROVEN", "MES": "UNPROVEN", "GC": "UNVERIFIED", "MGC": "UNVERIFIED"}
ACTIONABLE = {"QQQ", "SPY"}                    # only CERTIFIED assets may surface an ENTER prompt


def _form(sym: str) -> str:
    """The ORB form the asset trades (§13): retest machinery -> ORB-C+RT, else pure ORB-C."""
    try:
        from bot.strategy.asset_config import asset_config
        a = asset_config(sym)
        return "ORB-C+RT" if (getattr(a, "retest_mode", None) == "impulse_mid"
                              or getattr(a, "chase_atr", 0.0) >= 1.0) else "ORB-C"
    except Exception:
        return "ORB-C"


def _day_type(p: dict) -> str:
    if p.get("source_healthy") is False:
        return "UNKNOWN — feed unhealthy"
    if p.get("vol_expansion"):
        return "VOLATILITY EXPANSION"
    s = p.get("slope_S")
    if s is None:
        return "UNKNOWN"
    d = "UP" if s > 0 else "DOWN"
    if abs(s) >= 0.30:
        return f"TREND {d} (strong)"
    if abs(s) >= 0.10:
        return f"TREND {d}"
    return "RANGE / BALANCE"


def _state(p: dict) -> str:
    """Display state from the live zone read + status (causal — the scan already computed it)."""
    if p.get("removed"):
        return "BLOCKED (removed)"
    z = str(p.get("signal_state") or "").lower()
    if z == "invalid":
        return "INVALIDATED"
    if z == "active":
        return "CONFIRMED"                     # on-side, past the OR edge — the breakout is live
    if z == "watch":
        return "WATCHING"                      # past the mid, edge not yet taken (or pulled back)
    return "ARMED" if p.get("tradeable") else "WAIT"


def _location(p: dict) -> str:
    side = str(p.get("side") or "long")
    loc = f"OR {'HIGH' if side == 'long' else 'LOW'}"
    air = p.get("air_atr")
    if air is not None and p.get("clean_air"):
        loc += f" + CLEAN AIR {air} ATR"
    elif air is not None and p.get("clean_air") is False:
        loc += f" + WALL {air} ATR ahead"
    return loc


def _action(sym: str, p: dict, evidence: str) -> str:
    if evidence != "CERTIFIED":
        return "CONTEXT — WATCH ONLY (not actionable)"
    if p.get("removed"):
        return "BLOCKED — removed group"
    if p.get("skip_reco") or not p.get("tradeable"):
        return "NO TRADE — info only"
    st = _state(p)
    if st == "CONFIRMED":
        return "READY — confirm the close, then enter manually"
    if st == "WATCHING":
        return "WAIT FOR CONFIRMATION"
    if st == "INVALIDATED":
        return "INVALID — stand down"
    return "ARMED — watch the mid"


def _passes(sym: str, p: dict, evidence: str) -> bool:
    """Does this advisory PASS the gate (would lead to a trade)? Only a CERTIFIED asset with a live,
    tradeable, non-removed, non-skip state passes — NQ/ES/GC can never pass (advisory only).
    BOTH gates required (bug hunt ADV1): the symbol must be in ACTIONABLE **and** its evidence must
    be CERTIFIED — so the two lists diverging can never mint a false pass."""
    if sym.upper() not in ACTIONABLE or evidence != "CERTIFIED":
        return False
    if p.get("removed") or p.get("skip_reco") or not p.get("tradeable"):
        return False
    return _state(p) in ("CONFIRMED", "WATCHING", "ARMED")


def panel_for(sym: str, p: dict, tf: str) -> dict:
    """One side-panel from one live proposal (pure — no network)."""
    sym = sym.upper()
    ev = EVIDENCE.get(sym, "INSUFFICIENT")
    side = str(p.get("side") or "long").upper()
    form = _form(sym)
    conf = _confluence(p)
    return {
        "symbol": sym, "session": p.get("session"), "tf": tf, "side": side.lower(),
        "day_type": _day_type(p),
        "pattern": f"{form} {side}",
        "location": _location(p),
        "state": _state(p),
        "grade": p.get("grade"),
        "next": (f"{tf} close beyond {p.get('or_high') if side == 'LONG' else p.get('or_low')}"
                 if _state(p) in ("ARMED", "WATCHING") else "—"),
        "entry": p.get("entry"), "stop": p.get("stop"),
        "tp1": p.get("tp1"), "tp2": p.get("tp2"),
        "evidence": f"{sym} {form} | {ev}",
        "evidence_status": ev,
        "action": _action(sym, p, ev),
        "ml": "ABSTAIN",                       # spec §6: no default probability dressed as confidence
        "evidence_basis": "HISTORICAL ONLY",
        "confluence": conf,
        "has_confluence": bool(conf),
        "passes": _passes(sym, p, ev),
        "active": True,                        # from a real proposal (vs the WAIT placeholder)
    }


def _confluence(p: dict) -> list[str]:
    out = []
    if p.get("struct_aligned"):
        out.append("structure aligned")
    if p.get("clean_air") is True:
        out.append("clean air")
    elif p.get("clean_air") is False:
        out.append("WALL overhead")
    if p.get("vol_expansion"):
        out.append("vol expansion")
    sg = p.get("slope_grade")
    if sg:
        out.append(f"slope {sg}")
    tr = p.get("tranche")
    if tr and tr != "full":
        out.append(f"tranche {tr}")
    return out


def advisory_from_proposals(sym: str, proposals: list[dict], tf: str) -> dict:
    """Build the advisory (header + one panel per active side) from scan proposals. Pure/testable."""
    sym = sym.upper()
    # isinstance guard (bug hunt ADV2): a malformed snapshot (non-dict entries) must not crash the
    # advisory — the endpoint reads whatever the scan wrote; fail safe, never 500.
    mine = [p for p in proposals if isinstance(p, dict)
            and str(p.get("symbol", "")).upper() == sym and "error" not in p]
    panels = [panel_for(sym, p, tf) for p in mine]
    ev = EVIDENCE.get(sym, "INSUFFICIENT")
    header = {"symbol": sym, "tf": tf, "evidence": ev, "actionable": sym in ACTIONABLE,
              "day_type": (_day_type(mine[0]) if mine else "UNKNOWN"),
              "note": ("advisory only - NEVER an order (freeze); the certified path is untouched"
                       if sym not in ACTIONABLE else "certified base - actions flow through the certified path")}
    if not panels:
        panels = [{"symbol": sym, "tf": tf, "pattern": f"{_form(sym)} -", "state": "WAIT",
                   "action": "no active ORB setup", "evidence": f"{sym} | {ev}",
                   "evidence_status": ev, "ml": "ABSTAIN", "confluence": [], "has_confluence": False,
                   "passes": False, "active": False}]
    return {"header": header, "panels": panels}


def _summarize(symbol_advisories: dict) -> dict:
    """Count ACTIVE advisories, how many SHOW CONFLUENCE, and how many PASS the gate."""
    total = conf = passing = 0
    for adv in symbol_advisories.values():
        for panel in adv.get("panels", []):
            if not panel.get("active"):
                continue
            total += 1
            conf += 1 if panel.get("has_confluence") else 0
            passing += 1 if panel.get("passes") else 0
    return {"advisories": total, "with_confluence": conf, "passing": passing}


def watchlist_advisory(proposals: list[dict], symbols, tf: str) -> dict:
    """Build the advisory for every symbol from ALREADY-SCANNED proposals (pure — no network) +
    the confluence/pass summary. The endpoint feeds it the live scan snapshot."""
    out = {s.upper(): advisory_from_proposals(s, proposals, tf) for s in symbols}
    return {"tf": tf, "symbols": out, "summary": _summarize(out)}


def scan_advisory(sym: str, tf: str) -> dict:
    """Fetch via the LIVE scan machine (network) and build the advisory. Read-only (persist=False)."""
    from bot.live import scan_watchlist
    props = scan_watchlist([sym], tf=tf, with_options=False, persist=False)
    return advisory_from_proposals(sym, props, tf)


def render(adv: dict) -> str:
    h = adv["header"]
    lines = [f"{h['symbol']} | {h['tf']}  [{h['evidence']}]  day-type: {h['day_type']}",
             f"  {h['note']}"]
    for p in adv["panels"]:
        lines.append("  " + "-" * 58)
        lines.append(f"  PATTERN   {p.get('pattern')}      STATE  {p.get('state')}"
                     + (f"      GRADE {p['grade']}" if p.get("grade") else ""))
        if p.get("location"):
            lines.append(f"  LOCATION  {p['location']}")
        if p.get("entry") is not None:
            lines.append(f"  ENTRY {p.get('entry')}  STOP {p.get('stop')}  "
                         f"TP1 {p.get('tp1')}  TP2 {p.get('tp2')}")
        if p.get("next") and p.get("next") != "—":
            lines.append(f"  NEXT      {p['next']}")
        if p.get("confluence"):
            lines.append(f"  CONFLUENCE {', '.join(p['confluence'])}")
        lines.append(f"  EVIDENCE  {p.get('evidence')}   ML: {p.get('ml')} - {p.get('evidence_basis','')}")
        lines.append(f"  ACTION    {p.get('action')}")
    return "\n".join(lines)


def snapshot(syms=("NQ", "QQQ", "SPY"), tfs=("5m", "15m")) -> None:
    """Tonight's runner: print the advisory for each symbol at each tf, + the confluence/pass tally.
    Any (symbol, tf) that FAILS is skipped ('leave out whatever fails')."""
    if isinstance(syms, str):
        syms = (syms,)
    print(f"=== PATTERN ADVISORY — {', '.join(s.upper() for s in syms)} "
          f"(read-only, advisory only, no orders) ===")
    for tf in tfs:
        try:
            from bot.live import scan_watchlist
            props = scan_watchlist(list(syms), tf=tf, with_options=False, persist=False)
        except Exception as e:
            print(f"\n[{tf}] scan failed — skipped: {str(e)[:120]}")
            continue
        wl = watchlist_advisory(props, syms, tf)
        for sym in syms:
            print("\n" + render(wl["symbols"][sym.upper()]))
        s = wl["summary"]
        print(f"\n  [{tf} SUMMARY] {s['advisories']} advisories · {s['with_confluence']} show "
              f"confluence · {s['passing']} PASS the gate (actionable)")


if __name__ == "__main__":
    import sys
    args = sys.argv[1:]
    snapshot(tuple(a.upper() for a in args) if args else ("NQ", "QQQ", "SPY"))
