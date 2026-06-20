param(
  [switch]$NoInstall
)

$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent $PSScriptRoot
$ElectronDir = Join-Path $Root "electron-app"

# Some earlier diagnostics run Electron in Node mode. The desktop app needs real
# Electron APIs like app, BrowserWindow, and Tray.
Remove-Item Env:ELECTRON_RUN_AS_NODE -ErrorAction SilentlyContinue

if (-not (Test-Path (Join-Path $ElectronDir "node_modules\electron"))) {
  if ($NoInstall) {
    throw "Electron dependencies are missing. Run without -NoInstall to install them."
  }
  Push-Location $ElectronDir
  try {
    npm install
  } finally {
    Pop-Location
  }
}

Push-Location $ElectronDir
try {
  npm start
} finally {
  Pop-Location
}
