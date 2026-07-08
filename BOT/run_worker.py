#!/usr/bin/env python3
"""HIGHSTRIKE SCAN + TRAINING WORKER — the persistent backbone (user 2026-07-08: make the API
reloadable WITHOUT restarting the scan/training).

Run this ONCE. It runs the scan loop + (optional) continuous training and writes the shared scan
snapshot the reloadable API reads (data/latest_scan.json). The API (run_server.bat, uvicorn
--reload) reloads on every file change WITHOUT touching this process. Code changes to the scan or
training themselves still need a restart of THIS window — but that is a deliberate, rare act, not
the every-edit reload storm that was disrupting things.

    python run_worker.py            # scan only
    set BOT_CONT_TRAINING=1 & python run_worker.py    # + continuous training
"""
import os
import sys
import threading
import time

os.environ["BOT_AUTOSCAN"] = "1"                      # THIS process is the scanner
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from bot.api import server  # noqa: E402


def main() -> None:
    for s in (sys.stdout, sys.stderr):
        try:
            s.reconfigure(encoding="utf-8", errors="backslashreplace")
        except Exception:
            pass
    server._restore_runtime()
    threading.Thread(target=server._scan_loop, daemon=True).start()
    if os.environ.get("BOT_CONT_TRAINING", "0") == "1":
        server._cont["interval_min"] = max(30, int(os.environ.get("BOT_CONT_INTERVAL_MIN", "360")))
        server._cont["on"] = True
        threading.Thread(target=server._cont_loop, daemon=True).start()
    print("HIGHSTRIKE worker: scan loop"
          + (" + continuous training" if server._cont.get("on") else "")
          + " running (writes data/latest_scan.json). Ctrl-C to stop.", flush=True)
    while True:
        time.sleep(60)


if __name__ == "__main__":
    main()
