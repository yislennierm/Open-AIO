$ErrorActionPreference = "Stop"

$Root = Split-Path -Parent $PSScriptRoot
$Server = Join-Path $Root "server"

Push-Location $Server
try {
    if (-not (Test-Path ".venv\Scripts\python.exe")) {
        throw "Server virtual environment is missing. Run scripts\setup_windows.ps1 first."
    }
    & ".\.venv\Scripts\python.exe" -m uvicorn app.main:app --host 0.0.0.0 --port 8000
}
finally {
    Pop-Location
}
