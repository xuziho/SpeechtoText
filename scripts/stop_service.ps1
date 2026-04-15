$ErrorActionPreference = "Stop"

$projectRoot = Split-Path -Parent $PSScriptRoot
$pidFile = Join-Path $projectRoot "logs\service.pid"

if (-not (Test-Path $pidFile)) {
    Write-Output "Service is not running (no PID file found)."
    exit 0
}

$servicePid = Get-Content $pidFile -ErrorAction SilentlyContinue
if (-not $servicePid) {
    Remove-Item $pidFile -Force -ErrorAction SilentlyContinue
    Write-Output "PID file was empty and has been removed."
    exit 0
}

$process = Get-Process -Id $servicePid -ErrorAction SilentlyContinue
if ($process) {
    Stop-Process -Id $servicePid -Force
    Write-Output "Stopped service PID $servicePid"
}
else {
    Write-Output "Process $servicePid was not running."
}

Remove-Item $pidFile -Force -ErrorAction SilentlyContinue
