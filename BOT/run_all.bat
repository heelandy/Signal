@echo off
rem HIGHSTRIKE — launch BOTH: the persistent scan/training worker (backbone) + the reloadable API.
rem Edit any .py/.html and the API hot-reloads; the worker (scan + training) keeps running untouched.
cd /d "%~dp0"
start "HIGHSTRIKE worker (scan+training)" /min cmd /c run_worker.bat
timeout /t 4 >nul
start "HIGHSTRIKE API (reloadable)" /min cmd /c run_server.bat
echo Launched worker + reloadable API. UI: http://127.0.0.1:8000/training
