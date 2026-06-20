$ErrorActionPreference = "Stop"

$principal = New-Object Security.Principal.WindowsPrincipal([Security.Principal.WindowsIdentity]::GetCurrent())
if (-not $principal.IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)) {
    throw "Run this script from an elevated PowerShell window."
}

Get-Process SignalRgb,SignalRGB,Signal-x64 -ErrorAction SilentlyContinue | Stop-Process -Force
Start-Sleep -Seconds 1

$devices = Get-PnpDevice | Where-Object {
    $_.InstanceId -like "USB\VID_303A&PID_1001*" -or
    $_.InstanceId -like "HID\VID_303A&PID_1001*"
}

foreach ($device in $devices) {
    Write-Host "Removing $($device.InstanceId)"
    pnputil /remove-device "$($device.InstanceId)"
}

Write-Host "Scanning for hardware changes..."
pnputil /scan-devices

Write-Host ""
Write-Host "Now reset or unplug/replug the ESP32, wait 5 seconds, then restart SignalRGB."
Write-Host "After re-enumeration, TinyUSB Vendor should be OK instead of Error."
