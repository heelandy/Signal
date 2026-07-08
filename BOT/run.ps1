# HIGHSTRIKE signal engine - one-command launcher (Windows PowerShell)
#   Right-click > Run with PowerShell,  OR  from a terminal:  .\run.ps1
# It frees port 8000, starts the server (continuous auto-scan), and opens the dashboard.
param(
  [int]$Port = 8000,
  [int]$ScanSec = 60,          # how often the background loop re-scans the watchlist
  [switch]$NoBrowser
)
$ErrorActionPreference = "Stop"
$here = Split-Path -Parent $MyInvocation.MyCommand.Path      # ...\BOT
$py   = Join-Path (Split-Path -Parent $here) ".venv\Scripts\python.exe"
if (-not (Test-Path $py)) { $py = "python" }                 # fall back to PATH python

# 1) free the port if something is already listening
$c = Get-NetTCPConnection -LocalPort $Port -State Listen -ErrorAction SilentlyContinue
if ($c) { $c.OwningProcess | Select-Object -Unique | ForEach-Object { try { Stop-Process -Id $_ -Force } catch {} }; Start-Sleep -Milliseconds 500 }

# 2) launch the server (foreground; Ctrl+C to stop)
$env:PYTHONIOENCODING = "utf-8"
$env:BOT_SCAN_SEC     = "$ScanSec"
Set-Location $here
if (-not $NoBrowser) { Start-Process "http://127.0.0.1:$Port" }
Write-Host "HIGHSTRIKE signal engine -> http://127.0.0.1:$Port   (scan every ${ScanSec}s, Ctrl+C to stop)" -ForegroundColor Green
& $py -m uvicorn bot.api.server:app --host 127.0.0.1 --port $Port --log-level warning
