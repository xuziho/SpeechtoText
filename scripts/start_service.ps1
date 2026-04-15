$ErrorActionPreference = "Stop"

$projectRoot = Split-Path -Parent $PSScriptRoot
$logDir = Join-Path $projectRoot "logs"
$pidFile = Join-Path $logDir "service.pid"
$outLog = Join-Path $logDir "service.out.log"
$errLog = Join-Path $logDir "service.err.log"

New-Item -ItemType Directory -Force -Path $logDir | Out-Null

if (Test-Path $pidFile) {
    $existingPid = Get-Content $pidFile -ErrorAction SilentlyContinue
    if ($existingPid) {
        $running = Get-Process -Id $existingPid -ErrorAction SilentlyContinue
        if ($running) {
            Write-Output "Service is already running with PID $existingPid"
            exit 0
        }
    }
    Remove-Item $pidFile -Force -ErrorAction SilentlyContinue
}

$env:ASR_BASE_URL = if ($env:ASR_BASE_URL) { $env:ASR_BASE_URL } else { "http://127.0.0.1:8000/v1" }
$env:SERVICE_BASE_URL = if ($env:SERVICE_BASE_URL) { $env:SERVICE_BASE_URL } else { "http://127.0.0.1:8010" }
$env:ASR_MODEL = if ($env:ASR_MODEL) { $env:ASR_MODEL } else { "Qwen3-ASR-0.6B" }

$python = Join-Path $env:LOCALAPPDATA "Programs\Python\Python311\python.exe"
if (-not (Test-Path $python)) {
    $python = "python.exe"
}

$process = Start-Process `
    -FilePath $python `
    -ArgumentList "-m", "uvicorn", "app.main:app", "--host", "127.0.0.1", "--port", "8010" `
    -WorkingDirectory $projectRoot `
    -RedirectStandardOutput $outLog `
    -RedirectStandardError $errLog `
    -WindowStyle Hidden `
    -PassThru

Set-Content -Path $pidFile -Value $process.Id
Write-Output "Service started in background with PID $($process.Id)"
Write-Output "Logs: $outLog"
