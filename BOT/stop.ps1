# HIGHSTRIKE signal engine - STOP
#   .\stop.ps1             # stop EVERYTHING: the watchdog guard AND the server on :8000
#   .\stop.ps1 -KeepGuard  # stop only the server; the watchdog relaunches it in ~30s (= easy RESTART)
param(
  [int]$Port = 8000,
  [switch]$KeepGuard
)
$ErrorActionPreference = "SilentlyContinue"
$here    = Split-Path -Parent $MyInvocation.MyCommand.Path
$pidFile = Join-Path $here "config\server.pid"
$stopped = @()

# 0) the watchdog FIRST - otherwise it resurrects the server ~30s after we stop it
if (-not $KeepGuard) {
  Get-CimInstance Win32_Process -Filter "Name='powershell.exe'" -ErrorAction SilentlyContinue |
    Where-Object { $_.CommandLine -like '*-File*watchdog.ps1*' -and $_.ProcessId -ne $PID } |
    ForEach-Object { Stop-Process -Id $_.ProcessId -Force; Write-Host "Stopped watchdog (PID $($_.ProcessId))." -ForegroundColor Green }
}

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
