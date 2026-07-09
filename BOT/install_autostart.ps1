# RUN ONCE (right-click > Run with PowerShell, or:  .\install_autostart.ps1).
# Makes HIGHSTRIKE survive reboots: puts a silent launcher for watchdog.ps1 in your Startup folder,
# so every logon starts the watchdog hidden (which then keeps the server alive, relaunching on crash).
# No admin needed — plain per-user Startup folder (Task Scheduler is blocked on this machine).
#   Undo:   Remove-Item "$env:APPDATA\Microsoft\Windows\Start Menu\Programs\Startup\HIGHSTRIKE.vbs"
#   Check:  Get-Content .\config\watchdog.log -Tail 20
param(
  [int]$Port    = 8000,
  [int]$ScanSec = 30
)
$ErrorActionPreference = "Stop"
$here    = Split-Path -Parent $MyInvocation.MyCommand.Path
$wd      = Join-Path $here "watchdog.ps1"
$startup = [Environment]::GetFolderPath("Startup")           # ...\Start Menu\Programs\Startup
$vbs     = Join-Path $startup "HIGHSTRIKE.vbs"

# VBS wrapper = completely hidden window (a .bat here would flash a console at every logon)
$cmd = "powershell.exe -NoProfile -WindowStyle Hidden -ExecutionPolicy Bypass -File ""$wd"" -Port $Port -ScanSec $ScanSec"
@(
  "' HIGHSTRIKE auto-start (installed $(Get-Date -Format yyyy-MM-dd)) - launches the watchdog hidden at logon."
  "' The watchdog health-checks :$Port and relaunches the signal engine via start.ps1 if it ever dies."
  "CreateObject(""Wscript.Shell"").Run ""$($cmd -replace '"','""')"", 0, False"
) | Out-File -FilePath $vbs -Encoding ascii -Force

if (Test-Path $vbs) {
  Write-Host "Installed: $vbs" -ForegroundColor Green
  Write-Host "HIGHSTRIKE now auto-starts at every logon (watchdog -> server on :$Port, scan ${ScanSec}s)." -ForegroundColor Green
  # start it NOW too if no watchdog is already guarding (mirrors what the next logon will do)
  $running = Get-CimInstance Win32_Process -Filter "Name='powershell.exe'" -ErrorAction SilentlyContinue |
             Where-Object { $_.CommandLine -like '*-File*watchdog.ps1*' -and $_.ProcessId -ne $PID }
  if (-not $running) { Start-Process "wscript.exe" -ArgumentList "`"$vbs`""; Write-Host "Watchdog started now (hidden)." -ForegroundColor Green }
  else { Write-Host "Watchdog already running (PID $($running.ProcessId)) - not starting a second one." -ForegroundColor Yellow }
} else {
  Write-Host "FAILED - could not write $vbs" -ForegroundColor Red
}
