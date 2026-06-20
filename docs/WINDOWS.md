# Windows Bring-Up

This path runs the FastAPI server and PC agent on the Windows gaming/workstation PC.
The ESP32 then polls the Windows PC over the LAN.

## 1. Install Python

Install Python 3.11 or newer from python.org or the Microsoft Store. Confirm PowerShell can run:

```powershell
py -3 --version
```

## 2. Create Virtual Environments

From the repository root:

```powershell
.\scripts\setup_windows.ps1
```

This creates:

- `server\.venv`
- `pc-agent\.venv`
- `server\config.json` if missing
- `pc-agent\config.json` if missing

Change the `api_key` in both config files before using anything beyond a local MVP.

## 3. Start the Tray App

For normal use, start the tray app:

```powershell
.\scripts\start_tray.ps1
```

Right-click the tray icon to control the stack:

- `Start`
- `Stop`
- `Restart`
- `Restart Server`
- `Restart Agent`
- `Open Logo Review`
- `Open Logs`
- `Check Device`
- `Transport: Auto`
- `Transport: USB Only`
- `Transport: WiFi Only`
- `Install Startup Task`

Tray colors:

- Green: server and agent are running, and RawUSB telemetry is working.
- Yellow: server and agent are running, but USB is missing or disabled; the ESP32 can use WiFi fallback.
- Purple: SignalRGB is running or owns USB.
- Red: server, agent, or health checks are failing.

The tray starts the FastAPI server and PC agent as hidden Python worker processes. Logs are written to:

```text
logs\server.stdout.log
logs\server.stderr.log
logs\agent.stdout.log
logs\agent.stderr.log
pc-agent\logs\agent.log
pc-agent\logs\status.json
```

The older scripts are still useful for debugging:

```powershell
.\scripts\start_app.ps1
.\scripts\stop_app.ps1
```

If you want to run the pieces manually in visible consoles, start the server first:

```powershell
.\scripts\run_server.ps1
```

The server listens on `0.0.0.0:8000`, so the ESP32 can reach it by using the PC's LAN IP.

Find the LAN IP:

```powershell
Get-NetIPAddress -AddressFamily IPv4 |
  Where-Object { $_.IPAddress -notlike "169.254.*" -and $_.IPAddress -ne "127.0.0.1" } |
  Select-Object IPAddress, InterfaceAlias
```

Allow inbound access if Windows Firewall asks. If it does not ask, add a rule manually:

```powershell
New-NetFirewallRule `
  -DisplayName "Open AIO Server" `
  -Direction Inbound `
  -Action Allow `
  -Protocol TCP `
  -LocalPort 8000
```

## 4. Start the PC Agent Manually

In a second PowerShell window, if you are running manually:

```powershell
.\scripts\run_agent.ps1
```

The agent posts the foreground executable basename and telemetry every second. Logs are written to:

```text
pc-agent\logs\agent.log
```

The tray reads:

```text
pc-agent\logs\status.json
```

Important status values:

- `ok`: RawUSB state writes are working.
- `missing`: the RawUSB app device is not present.
- `owned_by_signalrgb`: SignalRGB is running, so the agent paused USB writes.
- `disabled`: transport mode is `wifi_only`.
- `write_failed`: the device was present but the USB write failed.

### Transport Modes

The PC agent always posts telemetry to the local server. Transport mode controls whether it also pushes the resolved state to the display over RawUSB.

- `auto`: prefer RawUSB when `Open AIO` / `VID_303A&PID_4004` exists; otherwise the firmware can poll over WiFi.
- `usb_only`: try RawUSB and report USB failures clearly. The local server still runs because it resolves apps/assets.
- `wifi_only`: do not write RawUSB. The ESP32 polls the server over WiFi.

When RawUSB app telemetry is active, the firmware suspends WiFi except when it briefly needs to fetch a new app logo. When USB stops, the firmware resumes WiFi polling.

### CPU Temperature

Windows does not expose CPU package temperature through `psutil` on most systems. The agent supports:

- LibreHardwareMonitor WMI: `root\LibreHardwareMonitor`
- OpenHardwareMonitor WMI: `root\OpenHardwareMonitor`
- LibreHardwareMonitor's local DLL, if installed
- Windows ACPI thermal zones, when the firmware/BIOS exposes them

Install LibreHardwareMonitor:

```powershell
winget install --id LibreHardwareMonitor.LibreHardwareMonitor --accept-source-agreements --accept-package-agreements
```

For many CPUs, sensor values are only available from an elevated process. Start the agent elevated:

```powershell
.\scripts\run_agent_admin.ps1
```

The log line includes `cpu_source=...`; if it says `cpu_source=none`, Windows still is not exposing a readable CPU temperature source to the agent.

## 5. Point the ESP32 at Windows

Edit `firmware\src\config.h`:

```cpp
#define SERVER_BASE_URL "http://YOUR_WINDOWS_LAN_IP:8000"
#define DEVICE_NAME "Open AIO"
#define DEVICE_ID "cooler-display-01"
#define API_KEY "same-key-as-server-config"
```

Then flash the firmware:

```powershell
cd firmware
pio run --target upload
```

## Windows Icon Discovery

When the server sees an unknown Windows process, it tries to match the `.exe` name to a Start Menu shortcut. If a match is found, it extracts the executable's associated icon through PowerShell/.NET, preprocesses it to RGB565, and queues it for review.

Open the review page on the Windows PC:

```text
http://127.0.0.1:8000/review
```

Use the same API key as `server\config.json`.

## Autostart Option

The easiest option is the tray menu item:

```text
Install Startup Task
```

This installs a hidden logon task named `Open AIO Tray`. It starts `desktop-app\.venv\Scripts\pythonw.exe` directly, so no PowerShell console should appear at login.

If you prefer Task Scheduler manually, use a logon task rather than a Windows service. Foreground-window detection is tied to the logged-in user session.

Suggested actions:

1. Create a task triggered "At log on".
2. Run `desktop-app\.venv\Scripts\pythonw.exe`.
3. Arguments:

```text
"C:\path\to\esp_cooler_block\desktop-app\cooler_tray.py"
```

The elevated CPU sensor bridge is a separate hidden logon task named `Open AIO Sensor Bridge`. It launches `SensorBridge.exe` directly.
