$ErrorActionPreference = "Stop"

$principal = New-Object Security.Principal.WindowsPrincipal([Security.Principal.WindowsIdentity]::GetCurrent())
if (-not $principal.IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)) {
    throw "Run this script from an elevated PowerShell window."
}

$Root = Split-Path -Parent $PSScriptRoot
$Inf = Join-Path $Root "drivers\open-aio-winusb\open-aio-winusb.inf"
if (-not (Test-Path -LiteralPath $Inf)) {
    throw "Missing driver INF: $Inf"
}

Get-Process SignalRgb,SignalRGB,Signal-x64 -ErrorAction SilentlyContinue | Stop-Process -Force

Write-Host "Installing WinUSB binding for USB\VID_303A&PID_1001..."
pnputil /add-driver "$Inf" /install

Write-Host "Restarting matching device instances..."
$devices = Get-PnpDevice | Where-Object { $_.InstanceId -like "USB\VID_303A&PID_1001*" }
foreach ($device in $devices) {
    Write-Host "Restarting $($device.InstanceId)"
    pnputil /restart-device "$($device.InstanceId)"
}

Write-Host "Scanning for hardware changes..."
pnputil /scan-devices

Write-Host "Done. Unplug/replug or reset the ESP32 if Windows still shows problem code 28."
