$ErrorActionPreference = "Stop"

$Root = Split-Path -Parent $PSScriptRoot
$TaskName = "Open AIO Tray"
$Tray = Join-Path $Root "desktop-app"
$Python = Join-Path $Tray ".venv\Scripts\pythonw.exe"
$Script = Join-Path $Tray "cooler_tray.py"
$User = "$env:USERDOMAIN\$env:USERNAME"

if (-not (Test-Path $Python)) {
    throw "Desktop app virtual environment is missing. Run scripts\setup_windows.ps1 first."
}
if (-not (Test-Path $Script)) {
    throw "Missing tray app: $Script"
}

$Action = New-ScheduledTaskAction -Execute $Python -Argument "`"$Script`"" -WorkingDirectory $Tray
$Trigger = New-ScheduledTaskTrigger -AtLogOn -User $User
$Principal = New-ScheduledTaskPrincipal -UserId $User -LogonType Interactive -RunLevel Limited
$Settings = New-ScheduledTaskSettingsSet -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries -MultipleInstances IgnoreNew -Hidden

Register-ScheduledTask `
    -TaskName $TaskName `
    -Action $Action `
    -Trigger $Trigger `
    -Principal $Principal `
    -Settings $Settings `
    -Description "Starts the Open AIO tray controller without opening a console window." `
    -Force | Out-Null

Start-ScheduledTask -TaskName $TaskName
Write-Host "Installed and started scheduled task: $TaskName"
