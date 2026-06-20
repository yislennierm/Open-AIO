$ErrorActionPreference = "Stop"

$processes = Get-CimInstance Win32_Process |
    Where-Object {
        $_.CommandLine -and (
            ($_.Name -like "python*" -and $_.CommandLine -like "*uvicorn app.main:app*") -or
            ($_.Name -like "python*" -and $_.CommandLine -like "*pc-agent*agent.py*") -or
            ($_.Name -like "python*" -and $_.CommandLine -like "* agent.py*") -or
            $_.CommandLine -like "*scripts\run_server.ps1*" -or
            $_.CommandLine -like "*scripts\run_agent.ps1*"
        )
    }

foreach ($process in $processes) {
    try {
        Stop-Process -Id $process.ProcessId -Force -ErrorAction Stop
    } catch {
        Write-Warning "Could not stop PID $($process.ProcessId): $($_.Exception.Message)"
    }
}

Start-Sleep -Seconds 1
Get-CimInstance Win32_Process |
    Where-Object {
        $_.CommandLine -and (
            ($_.Name -like "python*" -and $_.CommandLine -like "*uvicorn app.main:app*") -or
            ($_.Name -like "python*" -and $_.CommandLine -like "*pc-agent*agent.py*") -or
            ($_.Name -like "python*" -and $_.CommandLine -like "* agent.py*") -or
            $_.CommandLine -like "*scripts\run_server.ps1*" -or
            $_.CommandLine -like "*scripts\run_agent.ps1*"
        )
    } |
    Select-Object ProcessId,Name,CommandLine
