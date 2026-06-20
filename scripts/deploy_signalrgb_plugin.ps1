param(
  [string]$Destination
)

$ErrorActionPreference = "Stop"

$repoRoot = Split-Path -Parent $PSScriptRoot
$pluginSource = Join-Path $repoRoot "signalrgb\Open_AIO_Display.js"

if (-not (Test-Path -LiteralPath $pluginSource)) {
  throw "SignalRGB plugin not found: $pluginSource"
}

if (-not $Destination) {
  $documentsPath = [Environment]::GetFolderPath("MyDocuments")
  $Destination = Join-Path $documentsPath "WhirlwindFX\Plugins"
}

New-Item -ItemType Directory -Path $Destination -Force | Out-Null

$legacyPlugin = Join-Path $Destination "Open_AIO.js"
if (Test-Path -LiteralPath $legacyPlugin) {
  Remove-Item -LiteralPath $legacyPlugin -Force
}

$oldRawUsbPlugin = Join-Path $Destination "Open_AIO_RawUSB.js"
if (Test-Path -LiteralPath $oldRawUsbPlugin) {
  Remove-Item -LiteralPath $oldRawUsbPlugin -Force
}

$pluginDestination = Join-Path $Destination "Open_AIO_Display.js"
Copy-Item -LiteralPath $pluginSource -Destination $pluginDestination -Force

Write-Host "Deployed Open AIO Display SignalRGB plugin to:"
Write-Host $pluginDestination
if (-not (Test-Path -LiteralPath $legacyPlugin)) {
  Write-Host "Legacy serial SignalRGB plugin is not present:"
  Write-Host $legacyPlugin
}
if (-not (Test-Path -LiteralPath $oldRawUsbPlugin)) {
  Write-Host "Old RawUSB SignalRGB plugin name is not present:"
  Write-Host $oldRawUsbPlugin
}
Write-Host "Restart SignalRGB so it reloads custom user plugins."
