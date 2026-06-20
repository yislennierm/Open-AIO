$ErrorActionPreference = "Stop"

$Root = Split-Path -Parent $PSScriptRoot
$Designer = Join-Path $Root "nzxt-esc"

if (-not (Test-Path (Join-Path $Designer "package.json"))) {
    throw "Designer app is missing: $Designer"
}

Push-Location $Designer
try {
    npm.cmd run dev -- --host 127.0.0.1 --port 5173
} finally {
    Pop-Location
}
