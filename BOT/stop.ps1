# HIGHSTRIKE signal engine - STOP
#   .\stop.ps1             # stop EVERYTHING: the watchdog guard AND the server on :8000
#                          # (stays down until you start it again OR until the next logon)
#   .\stop.ps1 -KeepGuard  # stop only the server; the watchdog relaunches it in ~30s (= easy RESTART)
#   .\stop.ps1 -Uninstall  # stop everything AND remove the logon autostart - never comes back
#                          # by itself, even after a reboot (reinstall: .\install_autostart.ps1)
param(
  [int]$Port = 8000,
  [switch]$KeepGuard,
  [switch]$Uninstall
)
$ErrorActionPreference = "SilentlyContinue"
$here    = Split-Path -Parent $MyInvocation.MyCommand.Path
$pidFile = Join-Path $here "config\server.pid"
$stopped = @()

# 0) the watchdog FIRST - otherwise it resurrects the server ~30s after we stop it.
# TOPOLOGY GUARD (2026-07-11): the watchdog + worker belong to PRODUCTION (:8000) — stopping a
# DEV instance (any other -Port) must never touch them.
if ((-not $KeepGuard) -and ($Port -eq 8000)) {
  Get-CimInstance Win32_Process -Filter "Name='powershell.exe'" -ErrorAction SilentlyContinue |
    Where-Object { $_.CommandLine -like '*-File*watchdog.ps1*' -and $_.ProcessId -ne $PID } |
    ForEach-Object { Stop-Process -Id $_.ProcessId -Force; Write-Host "Stopped watchdog (PID $($_.ProcessId))." -ForegroundColor Green }
}

# 0a) the WORKER + its CHILD TREE (split topology, Phase 7 + orphan-reap fix 2026-07-12): the
# worker spawns multiprocessing-fork children AND subprocesses (resample, QA, training, evolve,
# nightly battery) that DON'T die when the worker is name-killed — that left an orphaned mp child
# holding hive file handles (bug hunt 2026-07-12). Kill the whole TREE (taskkill /T), then sweep
# any leftover BOT-marked python. Production only (:8000); a dev-port stop never touches these.
if ($Port -eq 8000) {
  # roots: worker + the reloadable API (both spawn children)
  $roots = Get-CimInstance Win32_Process -Filter "Name like 'python%'" -ErrorAction SilentlyContinue |
    Where-Object { $_.CommandLine -like '*run_worker.py*' -or $_.CommandLine -like '*uvicorn*bot.api.server*' }
  foreach ($r in $roots) {
    & taskkill.exe /PID $r.ProcessId /T /F 2>$null | Out-Null   # /T = terminate the child tree too
    $stopped += $r.ProcessId
    Write-Host "Stopped worker/API tree (root PID $($r.ProcessId) + children)." -ForegroundColor Green
  }
  # SWEEP orphans: any surviving python whose command line marks it as ours — a mp-fork child
  # whose parent we just killed, or a lingering pipeline/training subprocess.
  $markers = '*run_worker*','*bot.api.server*','*multiprocessing-fork*','*pipeline\hs_*',
             '*bot.ml*','*bot.nn*','*nightly_battery*','*research\*gauntlet*','*evolve*'
  $mine = Get-CimInstance Win32_Process -Filter "Name like 'python%'" -ErrorAction SilentlyContinue |
    Where-Object { $cl = $_.CommandLine; ($markers | Where-Object { $cl -like $_ }).Count -gt 0 -and $_.ProcessId -ne $PID }
  foreach ($m in $mine) {
    # only reap a multiprocessing-fork child if its parent is dead (a true orphan) OR it carries a
    # BOT script marker — never a stray unrelated python
    try { Stop-Process -Id $m.ProcessId -Force -ErrorAction Stop; $stopped += $m.ProcessId
          Write-Host "Reaped BOT child (PID $($m.ProcessId))." -ForegroundColor DarkGreen } catch {}
  }
  # gate bookkeeping: a stop.ps1 stop is a DELIBERATE, explained restart (forward gate 1)
  $wl = Join-Path $here "config\watchdog.log"
  "$([DateTime]::Now.ToString('yyyy-MM-dd HH:mm:ss'))  DELIBERATE STOP via stop.ps1 (KeepGuard=$KeepGuard) - tree+orphan reaped - explained, not a gate violation" | Out-File -FilePath $wl -Append -Encoding utf8
}

# 0b) -Uninstall: remove the logon autostart so it NEVER comes back by itself (even after reboot)
if ($Uninstall) {
  $vbs = Join-Path ([Environment]::GetFolderPath("Startup")) "HIGHSTRIKE.vbs"
  if (Test-Path $vbs) { Remove-Item $vbs -Force; Write-Host "Removed logon autostart ($vbs)." -ForegroundColor Green }
  else { Write-Host "No logon autostart installed." -ForegroundColor Yellow }
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
