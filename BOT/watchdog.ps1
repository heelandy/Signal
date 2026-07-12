# HIGHSTRIKE WATCHDOG - keeps the signal engine alive. PHASE 7 (2026-07-11): the check is
# SEMANTIC - it reads /api/live's `healthy` verdict (kill switch off + fresh scan heartbeat +
# no core subsystem failing), not merely "HTTP responded". The audited watchdog was satisfied
# by any 200 while the scan loop sat dead behind it.
#
# Topology (Phase 7 single production topology): relaunch = run_all.bat (persistent WORKER +
# reloadable API). The worker's named mutex and the API's port bind make a relaunch-while-alive
# a safe no-op. start.ps1 stays DEV-ONLY.
#   .\watchdog.ps1                 # default: check :8000 every 30s
# Stop with .\stop.ps1; close this watchdog window to stop guarding.
param(
  [int]$Port     = 8000,
  [int]$EverySec = 30,   # how often to health-check
  [int]$ScanSec  = 30    # scan cadence exported to the worker on (re)launch
)
$here = Split-Path -Parent $MyInvocation.MyCommand.Path
$log  = Join-Path $here "config\watchdog.log"
function Log($m){ "$([DateTime]::Now.ToString('yyyy-MM-dd HH:mm:ss'))  $m" | Out-File -FilePath $log -Append -Encoding utf8 }

# SINGLE-INSTANCE guard: two watchdogs would race to relaunch the server. Named mutex = only one wins.
$script:mtx = New-Object System.Threading.Mutex($false, "Global\HIGHSTRIKE_WATCHDOG")
if (-not $script:mtx.WaitOne(0)) { Log "another watchdog already running - exiting"; exit }

function Relaunch($why){
  Log "$why -> relaunching run_all.bat (worker mutex + API port bind make duplicates a no-op)"
  try { Start-Process -FilePath "cmd.exe" -ArgumentList "/c", (Join-Path $here "run_all.bat") -WorkingDirectory $here -WindowStyle Minimized; Log "relaunch issued" }
  catch { Log "relaunch ERROR: $_" }
  # BOOT GRACE (2026-07-11 drill finding): uvicorn's first boot takes ~60-90s; without this the
  # 30s down-checks stacked FOUR relaunches during one boot (mutex/port made them no-ops, but
  # four consoles spawned). One relaunch, then wait out the boot.
  Start-Sleep -Seconds 90
}

Log "watchdog started (SEMANTIC health-check :$Port/api/live every ${EverySec}s; topology=run_all)"
$sick = 0
while ($true) {
  $verdict = "down"
  try {
    $h = Invoke-RestMethod "http://127.0.0.1:$Port/api/live" -TimeoutSec 5
    if ($h.healthy -eq $true) { $verdict = "ok" }
    else { $verdict = "unhealthy"; Log ("semantic UNHEALTHY: kill=$($h.kill_switch) scan_age=[$($h.scan_age_sec)]s core_fails=[" + ($h.core_beats_failing -join ',') + "] broker=$($h.broker)") }
  } catch {}
  if ($verdict -eq "ok") { $sick = 0 }
  elseif ($verdict -eq "down") { $sick = 0; Relaunch "server DOWN (no response)" }
  else {
    # responding but semantically dead: a blind relaunch cannot kill the sick process, so log
    # loudly and only relaunch after 3 consecutive unhealthy checks (covers the dead-worker /
    # live-API split: the fresh worker takes over via the shared snapshot).
    $sick += 1
    if ($sick -ge 3) { Relaunch "UNHEALTHY x$sick (dead scan behind a live API?)"; $sick = 0 }
  }
  Start-Sleep -Seconds $EverySec
}
