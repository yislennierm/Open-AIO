$ErrorActionPreference = "Stop"

$Root = Split-Path -Parent $PSScriptRoot

function Find-Python {
    $candidates = @(
        @{ Command = "py"; Args = @("-3") },
        @{ Command = "python"; Args = @() },
        @{ Command = "python3"; Args = @() },
        @{ Command = (Join-Path $env:USERPROFILE ".platformio\penv\Scripts\python.exe"); Args = @() }
    )

    foreach ($candidate in $candidates) {
        $command = $candidate["Command"]
        if (-not (Get-Command $command -ErrorAction SilentlyContinue)) {
            continue
        }
        $versionArgs = @($candidate["Args"]) + @("--version")
        try {
            & $command @versionArgs 1>$null 2>$null
        }
        catch {
            continue
        }
        if ($LASTEXITCODE -eq 0) {
            return $candidate
        }
    }

    throw "Python 3 was not found. Install Python 3.11+ or make it available as py, python, or python3."
}

$Python = Find-Python

function Sync-PythonEnv {
    param(
        [Parameter(Mandatory = $true)][string]$Name,
        [Parameter(Mandatory = $true)][string]$Path
    )

    Push-Location $Path
    try {
        if (-not (Test-Path ".venv")) {
            $pythonCommand = $Python["Command"]
            $pythonArgs = @($Python["Args"])
            & $pythonCommand @pythonArgs -m venv .venv
        }
        & ".\.venv\Scripts\python.exe" -m pip install --upgrade pip
        & ".\.venv\Scripts\python.exe" -m pip install -r requirements.txt
        if (-not (Test-Path "config.json") -and (Test-Path "config.example.json")) {
            Copy-Item "config.example.json" "config.json"
        }
        Write-Host "$Name ready"
    }
    finally {
        Pop-Location
    }
}

Sync-PythonEnv -Name "server" -Path (Join-Path $Root "server")
Sync-PythonEnv -Name "pc-agent" -Path (Join-Path $Root "pc-agent")
Sync-PythonEnv -Name "desktop-app" -Path (Join-Path $Root "desktop-app")

Write-Host ""
Write-Host "Next:"
Write-Host "  1. Edit server\config.json and pc-agent\config.json if you do not want the default API key."
Write-Host "  2. Run scripts\start_tray.ps1."
Write-Host "  3. Right-click the tray icon and choose Install Sensor Startup Task for CPU temperature at login."
Write-Host "  4. Right-click the tray icon to start, stop, restart, and inspect telemetry."
