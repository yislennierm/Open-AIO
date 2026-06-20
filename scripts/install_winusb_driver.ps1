param(
  [string]$InfPath = "$PSScriptRoot\..\windows\driver\open-aio-winusb.inf"
)

$ErrorActionPreference = "Stop"

$logPath = Join-Path $PSScriptRoot "install_winusb_driver.log"
Start-Transcript -Path $logPath -Force | Out-Null

$resolvedInf = Resolve-Path -LiteralPath $InfPath
Write-Host "Installing WinUSB binding from $resolvedInf"
pnputil /add-driver $resolvedInf /install

Write-Host ""
Write-Host "Current ESP32 USB devices:"
Get-PnpDevice -PresentOnly |
  Where-Object { $_.InstanceId -match 'VID_303A' } |
  Select-Object Class,FriendlyName,InstanceId,Status,Problem |
  Format-List

Write-Host "Log written to $logPath"
Stop-Transcript | Out-Null
