$ErrorActionPreference = "Stop"

$Root = Split-Path -Parent $PSScriptRoot
$Server = Join-Path $Root "server"
$Agent = Join-Path $Root "pc-agent"
$LogDir = Join-Path $Root "logs"

New-Item -ItemType Directory -Force -Path $LogDir | Out-Null

$ServerPython = Join-Path $Server ".venv\Scripts\python.exe"
$AgentPython = Join-Path $Agent ".venv\Scripts\python.exe"

if (-not (Test-Path $ServerPython)) {
    throw "Server virtual environment is missing. Run scripts\setup_windows.ps1 first."
}
if (-not (Test-Path $AgentPython)) {
    throw "PC agent virtual environment is missing. Run scripts\setup_windows.ps1 first."
}

$existing = Get-CimInstance Win32_Process |
    Where-Object {
        $_.CommandLine -and (
            ($_.Name -like "python*" -and $_.CommandLine -like "*uvicorn app.main:app*") -or
            ($_.Name -like "python*" -and $_.CommandLine -like "*pc-agent*agent.py*") -or
            ($_.Name -like "python*" -and $_.CommandLine -like "* agent.py*")
        )
    }
if ($existing) {
    $ids = $existing | Select-Object -ExpandProperty ProcessId
    throw "App already appears to be running. Stop it first with scripts\stop_app.ps1. PIDs: $($ids -join ', ')"
}

Start-Process -FilePath $ServerPython `
    -WorkingDirectory $Server `
    -WindowStyle Hidden `
    -RedirectStandardOutput (Join-Path $LogDir "server.stdout.log") `
    -RedirectStandardError (Join-Path $LogDir "server.stderr.log") `
    -ArgumentList @("-m", "uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000")

Start-Process -FilePath $AgentPython `
    -WorkingDirectory $Agent `
    -WindowStyle Hidden `
    -RedirectStandardOutput (Join-Path $LogDir "agent.stdout.log") `
    -RedirectStandardError (Join-Path $LogDir "agent.stderr.log") `
    -ArgumentList @("agent.py")

Start-Sleep -Seconds 2
Get-CimInstance Win32_Process |
    Where-Object {
        $_.CommandLine -and (
            ($_.Name -like "python*" -and $_.CommandLine -like "*uvicorn app.main:app*") -or
            ($_.Name -like "python*" -and $_.CommandLine -like "*pc-agent*agent.py*") -or
            ($_.Name -like "python*" -and $_.CommandLine -like "* agent.py")
        )
    } |
    Select-Object ProcessId,Name,CommandLine
