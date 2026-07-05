"""ONE-SHOT verification chain for a new rule version (first run: orb-standard-2026.07.2).

Runs, in order, everything a rule bump needs before re-approval:
    1. replay parity          (candidates == engine trades)
    2. backtest report matrix (+ cost stress)
    3. NN similarity clusters (promotes itself only if the OOS spread holds)
    4. DIR-fast combos        (8 ORMID-anchored variants incl. the 3 triples)
    5. entry-parameter sweep  (54 combos, IS-rank / OOS-judge)

Each stage writes its own report (Training Lab panels pick them up as they land).
    .venv/Scripts/python research/verify_072.py
"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "BOT"))
sys.path.insert(0, str(ROOT / "engine"))
sys.path.insert(0, str(ROOT / "research"))

SYMS = ["QQQ", "SPY", "NQ", "ES"]


def main():
    import replay_parity, backtest_report, dirfast_pairs, sweep_entry_params
    print("=== VERIFY 07.2 · 1/5 replay parity ===", flush=True)
    replay_parity.main(SYMS)
    print("=== VERIFY 07.2 · 2/5 report matrix ===", flush=True)
    backtest_report.main(SYMS)
    print("=== VERIFY 07.2 · 3/5 similarity clusters (ALL) ===", flush=True)
    from bot.nn.similarity import train_similarity
    r = train_similarity("ALL")
    print(f"  similarity: promote={r.get('promote')} {r.get('reason', '')}", flush=True)
    print("=== VERIFY 07.2 · 4/5 DIR-fast combos (8) ===", flush=True)
    dirfast_pairs.main(SYMS)
    print("=== VERIFY 07.2 · 5/5 entry-parameter sweep ===", flush=True)
    sweep_entry_params.main(SYMS)
    print("VERIFY 07.2 COMPLETE", flush=True)


if __name__ == "__main__":
    main()
