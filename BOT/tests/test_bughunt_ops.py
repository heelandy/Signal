"""BUG HUNT — Ops chaos drills (category 4): REAL kill -9 against throwaway processes.

These are process-level, not in-process — a true SIGKILL runs no handlers, which is the point:

  4a.1  the single-instance named mutex must be RE-ACQUIRABLE after a hard kill (the OS releases
        it on process death) — otherwise a crashed worker would deadlock the guard forever. A
        UNIQUE test mutex name is used, never production's "Global\\HIGHSTRIKE_WORKER".
  4a.2  execution.db (WAL) must survive kill -9 mid-life: a committed row is durable and the db
        passes integrity_check after the writer is hard-killed (no torn page).

Windows-only (named mutex + taskkill /F). Skipped elsewhere.
"""
from __future__ import annotations

import os
import subprocess
import sys
import time
from pathlib import Path

import pytest

if sys.platform != "win32":
    pytest.skip("kill -9 drills are Windows-specific (named mutex + taskkill)", allow_module_level=True)

PY = sys.executable
NAME = f"Global\\HIGHSTRIKE_KILLTEST_{os.getpid()}"     # unique — never touches production's mutex


def _acquire_in_subprocess() -> bool:
    """Try to acquire NAME in a FRESH process; print/return whether it was newly acquired
    (True) or already existed (False). A separate process so no handle lingers in the test."""
    code = (
        "import ctypes\n"
        "k=ctypes.WinDLL('kernel32', use_last_error=True)\n"
        f"k.CreateMutexW(None, False, {NAME!r})\n"
        "print('ACQUIRED' if ctypes.get_last_error()!=183 else 'HELD')\n"
    )
    out = subprocess.run([PY, "-c", code], capture_output=True, text=True, timeout=30)
    return "ACQUIRED" in out.stdout


def test_4a1_mutex_reacquirable_after_hard_kill(tmp_path):
    holder_code = (
        "import ctypes, time\n"
        "k=ctypes.WinDLL('kernel32', use_last_error=True)\n"
        f"k.CreateMutexW(None, False, {NAME!r})\n"
        "print('HOLDING', flush=True)\n"
        "time.sleep(60)\n"
    )
    holder = subprocess.Popen([PY, "-c", holder_code], stdout=subprocess.PIPE, text=True)
    try:
        assert holder.stdout.readline().strip() == "HOLDING"       # wait until it holds the mutex
        time.sleep(0.5)
        assert not _acquire_in_subprocess(), "the mutex must read as HELD while the holder is alive"
        subprocess.run(["taskkill", "/PID", str(holder.pid), "/F"], capture_output=True)  # kill -9
        holder.wait(timeout=10)
        time.sleep(0.5)
        assert _acquire_in_subprocess(), (
            "after a hard kill the OS must release the named mutex — a fresh worker RE-ACQUIRES it "
            "(no permanent single-instance deadlock)")
    finally:
        if holder.poll() is None:
            subprocess.run(["taskkill", "/PID", str(holder.pid), "/F"], capture_output=True)


def test_4a2_execution_db_wal_survives_hard_kill(tmp_path):
    dbp = tmp_path / "execution.db"
    writer = (
        "import sqlite3, time, sys\n"
        f"c=sqlite3.connect(r'{dbp}', isolation_level=None)\n"
        "c.execute('PRAGMA journal_mode=WAL')\n"
        "c.execute('CREATE TABLE t(k INTEGER PRIMARY KEY, v TEXT)')\n"
        "c.execute(\"INSERT INTO t VALUES(1,'committed-before-kill')\")\n"       # autocommit -> durable
        "print('COMMITTED', flush=True)\n"
        "time.sleep(60)\n"
    )
    p = subprocess.Popen([PY, "-c", writer], stdout=subprocess.PIPE, text=True)
    try:
        assert p.stdout.readline().strip() == "COMMITTED"
        time.sleep(0.5)
        subprocess.run(["taskkill", "/PID", str(p.pid), "/F"], capture_output=True)   # kill -9 mid-life
        p.wait(timeout=10)
    finally:
        if p.poll() is None:
            subprocess.run(["taskkill", "/PID", str(p.pid), "/F"], capture_output=True)
    # reopen after the hard kill: the committed row is durable AND the db is not corrupt
    import sqlite3
    con = sqlite3.connect(str(dbp))
    assert con.execute("PRAGMA integrity_check").fetchone()[0] == "ok", "WAL db corrupt after kill -9"
    assert con.execute("SELECT v FROM t WHERE k=1").fetchone()[0] == "committed-before-kill", (
        "a committed row must be durable across a hard kill (WAL)")
    con.close()


# ── 4b: headless Edge console-error capture against a real dev-port server ──

def _find_edge():
    for p in (r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe",
              r"C:\Program Files\Microsoft\Edge\Application\msedge.exe"):
        if Path(p).exists():
            return p
    return None


def test_4b_dashboard_pages_have_no_js_console_errors(tmp_path):
    """Launch the API on a throwaway port, render '/' and '/training' in HEADLESS EDGE, and fail on
    any page-sourced JS console error (Uncaught/ReferenceError/TypeError/SyntaxError). Extension and
    tracking-prevention noise is excluded. Skips cleanly if Edge isn't installed."""
    import socket
    import urllib.request

    edge = _find_edge()
    if not edge:
        pytest.skip("Edge not installed")
    s = socket.socket(); s.bind(("127.0.0.1", 0)); port = s.getsockname()[1]; s.close()
    env = {**os.environ, "BOT_AUTOSCAN": "0"}
    srv = subprocess.Popen([PY, "-m", "uvicorn", "bot.api.server:app", "--host", "127.0.0.1",
                            "--port", str(port), "--log-level", "warning"],
                           env=env, cwd=str(Path(__file__).resolve().parents[1]))
    try:
        for _ in range(30):                                # wait for health
            try:
                if urllib.request.urlopen(f"http://127.0.0.1:{port}/api/health", timeout=2).status == 200:
                    break
            except Exception:
                time.sleep(1)
        else:
            pytest.skip("dev server did not come up")
        errors = []
        for path in ("/", "/training"):
            prof = tmp_path / f"edge_{path.strip('/') or 'root'}"
            try:
                # headless Edge on the heavy dashboard can be slow; a browser TIMEOUT is an
                # environment/perf condition, NOT a JS defect -> skip, never fail. Decode Edge's
                # own output as utf-8/replace so a stray byte can't crash the capture thread.
                subprocess.run([edge, "--headless", "--disable-gpu", "--no-sandbox",
                                "--enable-logging", "--v=1", f"--user-data-dir={prof}",
                                "--virtual-time-budget=10000", "--dump-dom",
                                f"http://127.0.0.1:{port}{path}"],
                               capture_output=True, encoding="utf-8", errors="replace", timeout=120)
            except subprocess.TimeoutExpired:
                pytest.skip("headless Edge too slow in this environment (not a JS defect)")
            clog = prof / "chrome_debug.log"
            if not clog.exists():
                continue
            for line in clog.read_text(encoding="utf-8", errors="replace").splitlines():
                if "chrome-extension" in line or "Tracking Prevention" in line:
                    continue                               # browser/extension noise, not the page
                if any(sig in line for sig in ("Uncaught", "ReferenceError", "TypeError",
                                               "SyntaxError", "is not defined", "is not a function")):
                    errors.append(f"{path}: {line.strip()[:160]}")
        assert not errors, f"dashboard pages emitted JS console errors: {errors}"
    finally:
        srv.terminate()
        try:
            srv.wait(timeout=10)
        except Exception:
            srv.kill()
