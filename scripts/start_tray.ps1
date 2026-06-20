$ErrorActionPreference = "Stop"

$Root = Split-Path -Parent $PSScriptRoot
$Tray = Join-Path $Root "desktop-app"
$Python = Join-Path $Tray ".venv\Scripts\pythonw.exe"

if (-not (Test-Path $Python)) {
    throw "Desktop app virtual environment is missing. Run scripts\setup_windows.ps1 first."
}

Start-Process -FilePath $Python `
    -WorkingDirectory $Tray `
    -WindowStyle Hidden `
    -ArgumentList @("cooler_tray.py")
