@echo off
rem HIGHSTRIKE WORKER — persistent scan + training backbone (NOT reloaded). Pair with run_server.bat
rem (the reloadable API). Only THIS window's code changes need a manual restart; edit the API/UI
rem freely and it hot-reloads without touching the scan or training. Start this FIRST.
cd /d "%~dp0"
rem BOT_CONT_TRAINING=0 (2026-07-09): the continuous-training loop was crashing the worker (scan went
rem dead/empty). Scan-only runs stably. The ML champions all fail the gates anyway, so nothing useful
rem is lost — re-enable (=1) once the training-loop crash is fixed.
set BOT_CONT_TRAINING=0
set BOT_SCAN_SEC=30
..\.venv\Scripts\python.exe run_worker.py
