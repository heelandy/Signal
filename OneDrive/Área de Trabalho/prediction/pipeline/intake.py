#!/usr/bin/env python3
"""ONE-COMMAND DATA INTAKE (user 2026-07-07: "drop the xnas files — these files need to be used
for OTHER training as well"). Point it at a folder of Databento files (trades/MBO/MBP, csv/zst)
and it runs the FULL breadth, serially and memory-safe:

  1. REGISTER   every data file, symbol AUTO-DETECTED from the file (never a manual pick)
  2. SYNTHESIZE l2_* per-minute features — one file per subprocess (no memory accumulation)
  3. BARS       extend each symbol's continuous-1m store from the trade prints (official bars
                always win on overlap; provenance in the manifest) + resample the hive
  4. QA         hs_data_qa over the affected symbols
  5. DATASETS   rebuild per symbol: 5m lineage (+15m for QQQ/SPY) + reject labels
  6. TRAIN      ml + nn + heads per affected symbol, --no-promote (pendings await your click)

    python pipeline/intake.py "E:/data/xnas-trades"          # or wherever the files land
    python pipeline/intake.py "..." --no-train               # stop after datasets

Everything downstream (workers, veto, evolution, gauntlets, similarity) reads the same stores,
so one intake feeds ALL training. Safe to re-run: registration dedups, bars append-after-last.
"""
from __future__ import annotations

import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
BOT = ROOT / "BOT"
PY = sys.executable
EQ_15M = ("QQQ", "SPY")                       # lineages that also train at 15m


def run(cmd, cwd=ROOT, timeout=3600) -> str:
    p = subprocess.run(cmd, cwd=str(cwd), capture_output=True, text=True,
                       encoding="utf-8", errors="replace", timeout=timeout)
    tail = (p.stdout or p.stderr or "").strip().splitlines()[-2:]
    print(f"  $ {' '.join(str(c) for c in cmd[1:])[:90]} -> rc={p.returncode} {' | '.join(tail)}",
          flush=True)
    return p.stdout or ""


def main(folder: str, train: bool = True):
    sys.path.insert(0, str(BOT))
    from bot.ml.l2_features import register, _load, synthesize  # noqa: F401
    print(f"=== INTAKE {folder} ===", flush=True)

    # 1) register (auto-label; folder scan dedups)
    r = register(folder)                       # symbol=None -> pure auto-detect
    n_reg = r.get("registered", 1 if "error" not in r else 0)
    print(f"1) registered: {n_reg} source(s)", flush=True)
    if "error" in r:
        print("   ", r["error"]); return

    # 2) synthesize — one subprocess per pending source (the OOM lesson: never accumulate)
    pend = [x for x in _load() if x.get("status") != "synthesized"]
    print(f"2) synthesizing {len(pend)} source(s), one process each…", flush=True)
    syms = set()
    for x in pend:
        out = run([PY, "-c",
                   "import sys; sys.argv=['x']\n"
                   "from bot.ml.l2_features import synthesize\n"
                   f"r = synthesize('{x['id']}')\n"
                   "print(r.get('feature_rows', 0), r.get('span') or r.get('error'))"], cwd=BOT)
        syms.add(str(x["symbol"]).upper())

    # 3) bars from trade prints + resample (per symbol; append-after-last, manifest provenance)
    print(f"3) bar extension + resample for {sorted(syms)}", flush=True)
    for s in sorted(syms):
        pat = str(Path(folder) / "*.csv*")
        run([PY, str(ROOT / "pipeline" / "hs_mbo_bars.py"), s, pat])
        for attempt in range(3):               # OneDrive-era lock lesson: retry + rename-aside
            out = run([PY, str(ROOT / "pipeline" / "hs_resample.py"), s], timeout=1200)
            if "PermissionError" not in out and "Error" not in out.splitlines()[-1:][0] if out.splitlines() else True:
                break
            time.sleep(10)

    # 4) QA
    run([PY, str(ROOT / "pipeline" / "hs_data_qa.py")], timeout=1200)

    # 5) datasets + rejects (5m always; 15m for the equity lineages)
    print("5) datasets + rejects", flush=True)
    for s in sorted(syms):
        run([PY, "-m", "bot.ml.dataset", s], cwd=BOT)
        if s in EQ_15M:
            run([PY, "-m", "bot.ml.dataset", s, "--tf=15m"], cwd=BOT)
        run([PY, "-c", f"from bot.ml.dataset import build_rejects; "
                       f"df = build_rejects('{s}'); print('{s}', len(df), 'rejects')"], cwd=BOT)

    # 6) training (--no-promote — pendings wait for the human click)
    if train:
        print("6) training (ml + nn + heads per symbol)", flush=True)
        for s in sorted(syms):
            run([PY, "-m", "bot.ml.pipeline", s, "--no-promote"], cwd=BOT, timeout=3600)
            if s in EQ_15M:
                run([PY, "-m", "bot.ml.pipeline", s, "--tf=15m", "--no-promote"], cwd=BOT, timeout=3600)
            run([PY, "-m", "bot.nn.train", s, "--no-promote"], cwd=BOT, timeout=3600)
            run([PY, "-m", "bot.ml.heads", s, "--no-promote"], cwd=BOT, timeout=3600)
    print("=== INTAKE COMPLETE — pendings/reports on /training ===", flush=True)


if __name__ == "__main__":
    main(sys.argv[1], train="--no-train" not in sys.argv)
