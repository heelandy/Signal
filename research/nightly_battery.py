"""NIGHTLY RESEARCH BATTERY (F98, user 2026-07-10: "implement pattern discovery... the system
needs to react quick"). Re-runs the study library on fresh data, extracts every verdict line,
DIFFS against the previous run, and reports only CHANGES: a new PASS (a fresh edge appeared) or
a lost PASS (a known edge is decaying). The system hunts while you sleep.

Runs standalone or from the Training-Lab Run panel (kind=battery); the scan loop launches it
nightly ~02:30 ET. Report: BOT/data/ml/reports/nightly_research.json (latest) + dated history.

    python research/nightly_battery.py            (full battery)
"""
import json
import os
import re
import subprocess
import sys
import datetime

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
REPORTS = os.path.join(ROOT, "BOT", "data", "ml", "reports")
OUT = os.path.join(REPORTS, "nightly_research.json")
PY = sys.executable

# the battery: (name, argv, timeout_s) — every study whose verdict can change with new data
STUDIES = [
    ("session_relay_NQ", [PY, "research/session_relay.py", "NQ"], 420),
    ("session_fade_gauntlet_NQ", [PY, "research/session_fade_gauntlet.py", "NQ"], 420),
    ("asia_fade_stop_NQ", [PY, "research/asia_fade_stop.py", "NQ"], 420),
    ("overnight_drift", [PY, "research/overnight_drift.py", "QQQ", "SPY"], 420),
    ("tsmom_NQ", [PY, "research/tsmom.py", "NQ"], 420),
    ("turn_of_month_watch", [PY, "research/turn_of_month.py", "QQQ"], 300),
    ("acceptance_entry_QQQ", [PY, "research/acceptance_entry.py", "QQQ"], 420),
    ("swing_geometry_QQQ", [PY, "research/swing_geometry.py", "QQQ"], 420),
    ("weekend_fade_gauntlet_NQ", [PY, "research/weekend_fade_gauntlet.py", "NQ"], 480),
    ("nq_composite_gauntlet", [PY, "research/nq_composite_gauntlet.py", "NQ"], 480),
    ("census_gauntlet_watch", [PY, "research/census_gauntlet.py"], 480),
    ("tick_vs_1m_agreement", [PY, "research/tick_vs_1m.py"], 300),
]

MARKS = re.compile(r"(<== PASS|<== BAND|ADOPT_CANDIDATE|GAUNTLET-OK|PASS$|PASS\s)")


def run_study(name, argv, timeout):
    try:
        r = subprocess.run(argv, cwd=ROOT, capture_output=True, text=True, timeout=timeout,
                           encoding="utf-8", errors="replace")
        lines = (r.stdout or "").splitlines()
        passes = sorted({ln.strip()[:140] for ln in lines if MARKS.search(ln)})
        return {"rc": r.returncode, "passes": passes, "n_lines": len(lines)}
    except subprocess.TimeoutExpired:
        return {"rc": -1, "passes": [], "error": "timeout"}
    except Exception as e:
        return {"rc": -2, "passes": [], "error": str(e)[:120]}


def main():
    prev = {}
    if os.path.exists(OUT):
        try:
            prev = json.load(open(OUT, encoding="utf-8")).get("studies", {})
        except Exception:
            prev = {}
    ts = datetime.datetime.now().astimezone().isoformat()
    studies, changes = {}, []
    for name, argv, to in STUDIES:
        print(f"[battery] {name} ...", flush=True)
        res = run_study(name, argv, to)
        studies[name] = res
        old = set((prev.get(name) or {}).get("passes") or [])
        new = set(res["passes"])
        for ln in sorted(new - old):
            changes.append({"study": name, "kind": "NEW_PASS", "line": ln})
        for ln in sorted(old - new):
            changes.append({"study": name, "kind": "LOST_PASS", "line": ln})
        if res.get("error"):
            changes.append({"study": name, "kind": "STUDY_ERROR", "line": res["error"]})
    report = {"generated_at": ts, "studies": studies, "changes": changes,
              "note": "changes = verdict DIFFS vs the previous battery run — new edges or decay"}
    os.makedirs(REPORTS, exist_ok=True)
    json.dump(report, open(OUT, "w", encoding="utf-8"), indent=1)
    dated = os.path.join(REPORTS, f"nightly_research_{ts[:10]}.json")
    json.dump(report, open(dated, "w", encoding="utf-8"), indent=1)
    print(f"\n[battery] done — {len(changes)} change(s); report -> {OUT}")
    for c in changes[:20]:
        print(f"  {c['kind']:>10}  {c['study']}: {c['line'][:110]}")


if __name__ == "__main__":
    main()
