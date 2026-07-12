# ============================================================================
# DEV-ONLY TOPOLOGY (remediation Phase 7, 2026-07-11): the single production
# topology is run_all.bat (persistent worker + reloadable API) guarded by
# watchdog.ps1. This single-process launcher stays for development/debugging;
# do NOT point autostart at it - training and durability behave differently.
# ============================================================================
# HIGHSTRIKE signal engine - START (detached, survives closing the terminal)
#   .\start.ps1            # start on :8000, scan every 60s, open dashboard
#   .\start.ps1 -ScanSec 30 -Port 8000 -NoBrowser
# Stop it later with .\stop.ps1
param(
  [int]$Port = 8000,
  [int]$ScanSec = 60,
  [switch]$NoBrowser
)
$ErrorActionPreference = "Stop"
$here = Split-Path -Parent $MyInvocation.MyCommand.Path        # ...\BOT
$py   = Join-Path (Split-Path -Parent $here) ".venv\Scripts\python.exe"
if (-not (Test-Path $py)) { $py = "python" }
$pidFile = Join-Path $here "config\server.pid"
$logFile = Join-Path $here "config\server.log"

# already running?
$listen = Get-NetTCPConnection -LocalPort $Port -State Listen -ErrorAction SilentlyContinue
if ($listen) {
  $existing = ($listen.OwningProcess | Select-Object -Unique) -join ","
  Write-Host "Already running on port $Port (PID $existing). Use .\stop.ps1 first to restart." -ForegroundColor Yellow
  if (-not $NoBrowser) { Start-Process "http://127.0.0.1:$Port" }
  return
}

$env:PYTHONIOENCODING = "utf-8"
$env:BOT_SCAN_SEC     = "$ScanSec"
if (-not $env:BOT_MODE) { $env:BOT_MODE = "paper" }   # default PAPER (study) — populates account + risk gauge; live stays gate-locked
$uvArgs = @("-m","uvicorn","bot.api.server:app","--host","127.0.0.1","--port","$Port","--log-level","warning")
$proc = Start-Process -FilePath $py -ArgumentList $uvArgs -WorkingDirectory $here `
        -WindowStyle Hidden -PassThru -RedirectStandardOutput $logFile -RedirectStandardError "$logFile.err"
$proc.Id | Out-File -FilePath $pidFile -Encoding ascii -Force

# wait for health
$ok = $false
for ($i = 0; $i -lt 20; $i++) {
  Start-Sleep -Milliseconds 500
  try { Invoke-RestMethod "http://127.0.0.1:$Port/api/health" -TimeoutSec 2 | Out-Null; $ok = $true; break } catch {}
}
if ($ok) {
  Write-Host "HIGHSTRIKE up -> http://127.0.0.1:$Port  (PID $($proc.Id), scan ${ScanSec}s, log: config\server.log)" -ForegroundColor Green
  if (-not $NoBrowser) { Start-Process "http://127.0.0.1:$Port" }
} else {
  Write-Host "Started PID $($proc.Id) but health check failed - see config\server.log.err" -ForegroundColor Red
}
