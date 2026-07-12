#!/usr/bin/env python3
"""HIGHSTRIKE SCAN + TRAINING WORKER — the persistent backbone (user 2026-07-08: make the API
reloadable WITHOUT restarting the scan/training).

Run this ONCE. It runs the scan loop + (optional) continuous training and writes the shared scan
snapshot the reloadable API reads (data/latest_scan.json). The API (run_server.bat, uvicorn
--reload) reloads on every file change WITHOUT touching this process. Code changes to the scan or
training themselves still need a restart of THIS window — but that is a deliberate, rare act, not
the every-edit reload storm that was disrupting things.

PHASE 7 HARDENING (2026-07-11):
  * SINGLE INSTANCE — a Windows named mutex; a duplicate worker after an abnormal restart would
    run a second scan loop (double orders, double journals). Second copies exit immediately.
  * CRASH RECORDS — any uncaught exception (main OR the scan/training threads) writes
    data/crash_<ts>.txt with the traceback + the last beats, and fires the alerts channel.
    The 28 unexplained July 9-10 restarts had no captured cause; now every death leaves one.
  * LOG ROTATION — *.log files over 5 MB rotate at boot (.1/.2/.3 kept).

    python run_worker.py            # scan only
    set BOT_CONT_TRAINING=1 & python run_worker.py    # + continuous training
"""
import json
import os
import sys
import threading
import time
import traceback

os.environ["BOT_AUTOSCAN"] = "1"                      # THIS process is the scanner
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from bot.api import server  # noqa: E402

_HERE = os.path.dirname(os.path.abspath(__file__))


def _single_instance() -> bool:
    """One worker only (Phase 7) — the watchdog's named-mutex pattern, held for process life."""
    try:
        import ctypes
        # use_last_error=True is MANDATORY: plain windll GetLastError() can be clobbered by
        # interleaved ctypes machinery — the 2026-07-11 boot drill produced TWO live workers
        # because both read a stale 0 (duplicate scan loops = the exact failure this guard
        # exists to prevent).
        k32 = ctypes.WinDLL("kernel32", use_last_error=True)
        k32.CreateMutexW(None, False, "Global\\HIGHSTRIKE_WORKER")
        return ctypes.get_last_error() != 183                    # ERROR_ALREADY_EXISTS
    except Exception:
        return True                                              # non-Windows: no guard, proceed


def _rotate_logs(max_mb: int = 5, keep: int = 3) -> None:
    for root in (_HERE, os.path.join(_HERE, "config")):
        if not os.path.isdir(root):
            continue
        for fn in os.listdir(root):
            p = os.path.join(root, fn)
            if fn.endswith(".log") and os.path.isfile(p) and os.path.getsize(p) > max_mb * 1 << 20:
                for i in range(keep - 1, 0, -1):
                    a, b = f"{p}.{i}", f"{p}.{i + 1}"
                    if os.path.exists(a):
                        os.replace(a, b)
                os.replace(p, f"{p}.1")


def _crash_record(where: str, exc: BaseException) -> None:
    """Every death leaves a cause (Phase 7): traceback + last beats -> data/crash_<ts>.txt."""
    try:
        ts = time.strftime("%Y%m%dT%H%M%SZ", time.gmtime())
        p = os.path.join(_HERE, "data", f"crash_{ts}.txt")
        os.makedirs(os.path.dirname(p), exist_ok=True)
        with open(p, "w", encoding="utf-8") as f:
            f.write(f"where: {where}\nat: {ts}\npid: {os.getpid()}\n\n")
            f.write("".join(traceback.format_exception(exc)))
            try:
                f.write("\nlast beats:\n" + json.dumps(server._beats, indent=1, default=str))
            except Exception:
                pass
        try:
            from bot.alerts import alert
            alert(f"WORKER CRASH in {where}: {type(exc).__name__}: {str(exc)[:120]} "
                  f"(crash record {os.path.basename(p)})", level="critical", source="worker")
        except Exception:
            pass
    except Exception:
        pass


def _thread_hook(args: threading.ExceptHookArgs) -> None:
    _crash_record(f"thread {args.thread.name if args.thread else '?'}", args.exc_value)


def main() -> None:
    for s in (sys.stdout, sys.stderr):
        try:
            s.reconfigure(encoding="utf-8", errors="backslashreplace")
        except Exception:
            pass
    if not _single_instance():
        print("HIGHSTRIKE worker: another instance holds the mutex — exiting (single-instance "
              "guard, Phase 7).", flush=True)
        return
    _rotate_logs()
    threading.excepthook = _thread_hook
    server._restore_runtime()
    threading.Thread(target=server._scan_loop, daemon=True, name="scan").start()
    if os.environ.get("BOT_CONT_TRAINING", "0") == "1":
        server._cont["interval_min"] = max(30, int(os.environ.get("BOT_CONT_INTERVAL_MIN", "360")))
        server._cont["on"] = True
        threading.Thread(target=server._cont_loop, daemon=True, name="training").start()
    print("HIGHSTRIKE worker: scan loop"
          + (" + continuous training" if server._cont.get("on") else "")
          + " running (writes data/latest_scan.json). Ctrl-C to stop.", flush=True)
    while True:
        time.sleep(60)


def _reap_children() -> None:
    """Reap multiprocessing children on exit so none orphan (orphan-reap fix 2026-07-12 — an
    mp-fork child outlived a killed worker and held hive handles). Belt to stop.ps1's external
    process-TREE kill (taskkill /T), which covers the externally-killed case atexit can't."""
    try:
        import multiprocessing
        for c in multiprocessing.active_children():
            try:
                c.terminate(); c.join(timeout=2)
            except Exception:
                pass
    except Exception:
        pass


if __name__ == "__main__":
    import atexit
    atexit.register(_reap_children)
    try:
        main()
    except KeyboardInterrupt:
        _reap_children()
    except BaseException as e:                        # noqa: BLE001 — the whole point: record it
        _crash_record("main", e)
        _reap_children()
        raise
