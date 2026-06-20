$ErrorActionPreference = "Stop"

$Root = Split-Path -Parent $PSScriptRoot
$Agent = Join-Path $Root "pc-agent"

Push-Location $Agent
try {
    if (-not (Test-Path ".venv\Scripts\python.exe")) {
        throw "PC agent virtual environment is missing. Run scripts\setup_windows.ps1 first."
    }
    & ".\.venv\Scripts\python.exe" "agent.py"
}
finally {
    Pop-Location
}
