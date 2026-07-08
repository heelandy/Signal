@echo off
rem HIGHSTRIKE WORKER — persistent scan + training backbone (NOT reloaded). Pair with run_server.bat
rem (the reloadable API). Only THIS window's code changes need a manual restart; edit the API/UI
rem freely and it hot-reloads without touching the scan or training. Start this FIRST.
cd /d "%~dp0"
set BOT_CONT_TRAINING=1
..\.venv\Scripts\python.exe run_worker.py
