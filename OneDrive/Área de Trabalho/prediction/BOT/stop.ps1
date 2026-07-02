# HIGHSTRIKE signal engine - STOP
#   .\stop.ps1            # stop the server on :8000 (uses config\server.pid, falls back to the port)
param(
  [int]$Port = 8000
)
$ErrorActionPreference = "SilentlyContinue"
$here    = Split-Path -Parent $MyInvocation.MyCommand.Path
$pidFile = Join-Path $here "config\server.pid"
$stopped = @()

# 1) by recorded PID
if (Test-Path $pidFile) {
  $savedPid = (Get-Content $pidFile | Select-Object -First 1).Trim()
  if ($savedPid -match '^\d+$') {
    $p = Get-Process -Id ([int]$savedPid) -ErrorAction SilentlyContinue
    if ($p) { Stop-Process -Id $p.Id -Force; $stopped += $p.Id }
  }
  Remove-Item $pidFile -Force
}

# 2) anything still holding the port
$listen = Get-NetTCPConnection -LocalPort $Port -State Listen -ErrorAction SilentlyContinue
if ($listen) {
  $listen.OwningProcess | Select-Object -Unique | ForEach-Object {
    try { Stop-Process -Id $_ -Force; $stopped += $_ } catch {}
  }
}

if ($stopped.Count -gt 0) {
  Write-Host ("Stopped HIGHSTRIKE (PID " + (($stopped | Select-Object -Unique) -join ", ") + ").") -ForegroundColor Green
} else {
  Write-Host "Nothing was running on port $Port." -ForegroundColor Yellow
}
