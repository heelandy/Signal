@echo off
rem HIGHSTRIKE API — RELOADABLE UI/endpoints (user 2026-07-08). The SCAN + TRAINING run in the
rem separate persistent worker (run_worker.bat), so this hot-reloads on every .py/.html change
rem WITHOUT restarting them (BOT_AUTOSCAN=0 -> this process only READS the worker's scan snapshot).
rem   1) start run_worker.bat  (the backbone)   2) start run_server.bat  (this, reloadable)
rem   or just run run_all.bat to launch both.
cd /d "%~dp0"
set BOT_AUTOSCAN=0
..\.venv\Scripts\python.exe -m uvicorn bot.api.server:app --host 127.0.0.1 --port 8000 ^
    --reload --reload-dir bot --reload-include "*.py" --reload-include "*.html"
