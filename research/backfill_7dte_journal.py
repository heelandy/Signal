#!/usr/bin/env python3
"""BACKFILL the 7DTE managed-condor BACKTEST into the options-native journal (F89, user 2026-07-08).

The per-structure scorecard reads the sealed journal. The 0DTE structures (condor/credit_spread/
naked) got their backtest rows from `native.record_session`; the 7DTE condor's backtest lives only
in the research sweep, so its panel row showed N=0. This writes the SAME F89 trades (the chosen
config em1.0/wing5/tp0.6/stop2.0, run through the shared `native.build` + multi-day manager) into the
journal tagged `priced_from="opra_chain"`, so it shows as `bt` exactly like the others.

IDEMPOTENT: dedups on (date, slot, structure) — safe to re-run. Honest: these are the real managed
backtest results (WR 83.3 · PF 1.73 · +0.122R on 18 in-sample trades), not a fabrication.

    python research/backfill_7dte_journal.py
"""
from __future__ import annotations

import datetime
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "BOT"))
sys.path.insert(0, str(ROOT / "research"))

import opra_dte_condor as M                              # the F89 sweep module (shared native path)
from bot.options import native

CONFIG = dict(native.SPEC, em_mult=1.0, wing=5, tp=0.6, stop_mult=2.0)   # F89 chosen 7DTE condor
SLOT = "7d"
STRUCT = "condor_7dte"


def main() -> None:
    M._utf8()
    spot, close, opng = M._qqq()
    q, strikes, entries = M.load(7, M.MARK_MINUTES)
    ss = sorted({s for (_, s, *_2) in q.keys()})

    done = {(r.get("date"), r.get("slot"), r.get("structure")) for r in native.load_journal()}
    written, skipped, aside = 0, 0, 0
    for D, E in entries:
        key = (str(D), SLOT, STRUCT)
        if key in done:
            skipped += 1
            continue
        r = M.trade(q, strikes, spot, close, opng, D, E, CONFIG, ss)
        if r is None:
            continue
        if r.get("stand_aside"):
            aside += 1
            continue
        ml = r["ml"]
        rec = {"lineage": native.LINEAGE, "date": str(D), "slot": SLOT, "structure": STRUCT,
               "kind": "condor", "entry_hm": M.ENTRY_HM, "exit": r["outcome"],
               "credit": round(r["credit"], 3), "max_loss": round(ml, 3),
               "ret": round(r["ret"], 3), "pnl": round(r["ret"] * ml, 3),
               "outcome": "win" if r["ret"] > 0 else "loss", "expiry": str(E),
               "dte": 7, "priced_from": "opra_chain",
               "resolved_at": datetime.datetime.utcnow().isoformat() + "Z"}
        native._append_journal(rec)
        written += 1

    perf = native.performance_by_structure().get(STRUCT, {})
    print(f"backfill {STRUCT}: wrote {written}, skipped {skipped} (already present), stand-aside {aside}")
    print(f"scorecard now: n={perf.get('n')} WR {perf.get('win_pct')} PF {perf.get('pf')} "
          f"avg {perf.get('avg_ret')} (source {perf.get('source')})")


if __name__ == "__main__":
    main()
