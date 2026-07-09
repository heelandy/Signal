# HIGHSTRIKE WATCHDOG - keeps the signal engine alive. Every $EverySec it pings /api/health; if the
# server is down (crash, OOM, killed), it relaunches via start.ps1 (same single-process, self-scanning,
# training-off model). Run it detached at logon with install_autostart.ps1, or foreground to watch:
#   .\watchdog.ps1                 # default: check :8000 every 30s, (re)launch with 30s scan
#   .\watchdog.ps1 -EverySec 15
# Stop the whole thing with .\stop.ps1 (kills the server); close this watchdog window to stop guarding.
param(
  [int]$Port     = 8000,
  [int]$EverySec = 30,   # how often to health-check
  [int]$ScanSec  = 30    # scan cadence passed to start.ps1 on (re)launch
)
$here = Split-Path -Parent $MyInvocation.MyCommand.Path
$log  = Join-Path $here "config\watchdog.log"
function Log($m){ "$([DateTime]::Now.ToString('yyyy-MM-dd HH:mm:ss'))  $m" | Out-File -FilePath $log -Append -Encoding utf8 }

# SINGLE-INSTANCE guard: two watchdogs would race to relaunch the server. Named mutex = only one wins.
$script:mtx = New-Object System.Threading.Mutex($false, "Global\HIGHSTRIKE_WATCHDOG")
if (-not $script:mtx.WaitOne(0)) { Log "another watchdog already running - exiting"; exit }

Log "watchdog started (health-check :$Port every ${EverySec}s)"
while ($true) {
  $up = $false
  try { Invoke-RestMethod "http://127.0.0.1:$Port/api/health" -TimeoutSec 5 | Out-Null; $up = $true } catch {}
  if (-not $up) {
    Log "server DOWN -> relaunching via start.ps1"
    try { & (Join-Path $here "start.ps1") -Port $Port -ScanSec $ScanSec -NoBrowser | Out-Null; Log "relaunch issued" }
    catch { Log "relaunch ERROR: $_" }
  }
  Start-Sleep -Seconds $EverySec
}
