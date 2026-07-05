@echo off
rem HIGHSTRIKE server launcher — AUTO-RELOAD: uvicorn watches the code and restarts itself the
rem moment a .py file changes, so NEW CODE RUNS WITHOUT a manual restart (user ask 2026-07-05).
rem The Training Lab's "restart the server" warning should never appear when launched this way.
rem   run_server.bat            -> http://127.0.0.1:8000  (+ /training)
rem   set BOT_CONT_TRAINING=1   -> continuous training arms itself on startup
cd /d "%~dp0"
..\.venv\Scripts\python.exe -m uvicorn bot.api.server:app --host 127.0.0.1 --port 8000 ^
    --reload --reload-dir bot --reload-include "*.html"
