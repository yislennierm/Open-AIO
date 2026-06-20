from __future__ import annotations

import json
import platform
import re
import shutil
import subprocess
import threading
import time
from pathlib import Path
from typing import Any

import psutil

CREATE_NO_WINDOW = 0x08000000 if platform.system().lower() == "windows" else 0
_last_cpu_source = "none"
_last_gpu_source = "none"
_last_cpu_temp: float | None = None
_last_cpu_temp_at = 0.0
_last_gpu_temp: float | None = None
_last_gpu_temp_at = 0.0
_last_ssd_temp: float | None = None
_last_ssd_temp_at = 0.0
_last_ssd_query_at = 0.0
_ssd_query_running = False
_ssd_lock = threading.Lock()
TEMP_CACHE_SECONDS = 12.0
STORAGE_TEMP_QUERY_SECONDS = 30.0
STORAGE_TEMP_CACHE_SECONDS = 120.0


def get_last_cpu_source() -> str:
    return _last_cpu_source


def get_last_gpu_source() -> str:
    return _last_gpu_source


def _safe_cpu_temperature() -> float | None:
    global _last_cpu_source
    _last_cpu_source = "none"
    if platform.system().lower() == "windows":
        value = _windows_cpu_temperature()
        if value is not None:
            return value

    try:
        temps = psutil.sensors_temperatures(fahrenheit=False)
    except (AttributeError, OSError, RuntimeError):
        return None

    preferred = ("coretemp", "k10temp", "zenpower", "cpu_thermal", "acpitz")
    for key in preferred:
        for entry in temps.get(key, []):
            current = getattr(entry, "current", None)
            if current is not None:
                _last_cpu_source = f"psutil:{key}"
                return float(current)
    for entries in temps.values():
        for entry in entries:
            current = getattr(entry, "current", None)
            if current is not None and 0.0 <= float(current) <= 125.0:
                _last_cpu_source = "psutil"
                return float(current)
    return None


def _run_command(args: list[str], timeout: float = 0.8) -> str | None:
    try:
        result = subprocess.run(
            args,
            capture_output=True,
            text=True,
            timeout=timeout,
            check=False,
            creationflags=CREATE_NO_WINDOW,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    if result.returncode != 0:
        return None
    return result.stdout.strip()


def _run_external_sensor_command(command: str | list[str], timeout: float) -> dict[str, Any]:
    if isinstance(command, str):
        if not command.strip():
            return {}
        args: str | list[str] = command
        shell = True
    elif isinstance(command, list) and command:
        args = [str(part) for part in command]
        shell = False
    else:
        return {}

    try:
        result = subprocess.run(
            args,
            capture_output=True,
            text=True,
            timeout=timeout,
            check=False,
            shell=shell,
            creationflags=CREATE_NO_WINDOW,
        )
    except (OSError, subprocess.SubprocessError):
        return {}
    if result.returncode != 0 or not result.stdout.strip():
        return {}
    try:
        data = json.loads(result.stdout)
    except json.JSONDecodeError:
        return {}
    return data if isinstance(data, dict) else {}


def _read_external_sensor_file(path_value: str | None, max_age_seconds: float) -> dict[str, Any]:
    if not path_value:
        return {}
    path = Path(path_value).expanduser()
    try:
        stat = path.stat()
    except OSError:
        return {}
    if max_age_seconds > 0 and time.time() - stat.st_mtime > max_age_seconds:
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return data if isinstance(data, dict) else {}


def _merge_external_sensors(payload: dict[str, Any], data: dict[str, Any]) -> dict[str, Any]:
    global _last_cpu_source, _last_gpu_source
    if not data:
        return payload

    if payload.get("cpu_temp") is None and isinstance(data.get("cpu_temp"), (int, float)):
        payload["cpu_temp"] = float(data["cpu_temp"])
        _last_cpu_source = str(data.get("cpu_source") or "external")

    if payload.get("gpu_temp") is None and isinstance(data.get("gpu_temp"), (int, float)):
        payload["gpu_temp"] = float(data["gpu_temp"])
        _last_gpu_source = str(data.get("gpu_source") or "external")

    if payload.get("gpu_load") is None and isinstance(data.get("gpu_load"), (int, float)):
        payload["gpu_load"] = float(data["gpu_load"])
        if _last_gpu_source == "none":
            _last_gpu_source = str(data.get("gpu_source") or "external")

    for key in ("ram_total_mb", "ssd_temp", "cpu_frequency", "gpu_frequency", "cpu_power", "gpu_power", "gpu_fan_speed"):
        if payload.get(key) is None and isinstance(data.get(key), (int, float)):
            payload[key] = float(data[key])

    return payload


def apply_external_sensors(payload: dict[str, Any], config: dict[str, Any]) -> dict[str, Any]:
    file_path = config.get("external_sensor_file")
    max_age = max(0.5, min(30.0, float(config.get("external_sensor_file_max_age_seconds", 5.0))))
    payload = _merge_external_sensors(payload, _read_external_sensor_file(file_path, max_age))

    command = config.get("external_sensor_command")
    if not command:
        return payload
    timeout = max(0.2, min(5.0, float(config.get("external_sensor_timeout_seconds", 1.5))))
    return _merge_external_sensors(payload, _run_external_sensor_command(command, timeout))


def _run_powershell(script: str, timeout: float = 1.5) -> str | None:
    powershell = shutil.which("pwsh") or shutil.which("powershell")
    if powershell is None:
        return None
    return _run_command([powershell, "-NoProfile", "-ExecutionPolicy", "Bypass", "-Command", script], timeout=timeout)


def _windows_cpu_temperature() -> float | None:
    global _last_cpu_source
    for namespace in ("root\\LibreHardwareMonitor", "root\\OpenHardwareMonitor"):
        value = _hardware_monitor_cpu_temperature(namespace)
        if value is not None:
            _last_cpu_source = namespace.rsplit("\\", 1)[-1]
            return value

    value = _libre_hardware_monitor_dll_temperature()
    if value is not None:
        _last_cpu_source = "LibreHardwareMonitorLib"
        return value

    value = _windows_acpi_temperature()
    if value is not None:
        _last_cpu_source = "MSAcpi_ThermalZoneTemperature"
        return value
    return None


def _hardware_monitor_cpu_temperature(namespace: str) -> float | None:
    script = rf"""
$items = Get-CimInstance -Namespace '{namespace}' -ClassName Sensor -ErrorAction SilentlyContinue |
  Where-Object {{
    $_.SensorType -eq 'Temperature' -and
    $_.Value -ge 0 -and $_.Value -le 125 -and
    ($_.Name -match 'CPU|Core|Package|Tctl|Tdie|CCD' -or $_.Parent -match 'CPU|Intel|AMD|Ryzen')
  }} |
  Select-Object Name,Value
$items | ConvertTo-Json -Compress
"""
    output = _run_powershell(script)
    if not output:
        return None
    try:
        data = json.loads(output)
    except json.JSONDecodeError:
        return None
    if isinstance(data, dict):
        data = [data]
    if not isinstance(data, list):
        return None

    package_values: list[float] = []
    core_values: list[float] = []
    other_values: list[float] = []
    for item in data:
        if not isinstance(item, dict):
            continue
        try:
            value = float(item.get("Value"))
        except (TypeError, ValueError):
            continue
        if not 0.0 <= value <= 125.0:
            continue
        name = str(item.get("Name") or "").lower()
        if any(token in name for token in ("package", "tctl", "tdie", "ccd")):
            package_values.append(value)
        elif "core" in name:
            core_values.append(value)
        else:
            other_values.append(value)

    if package_values:
        return max(package_values)
    if core_values:
        return max(core_values)
    if other_values:
        return max(other_values)
    return None


def _libre_hardware_monitor_dll_temperature() -> float | None:
    script = r"""
$roots = @(
  "$env:LOCALAPPDATA\Microsoft\WinGet\Packages",
  "$env:ProgramFiles",
  "${env:ProgramFiles(x86)}"
) | Where-Object { $_ -and (Test-Path $_) }
$dll = Get-ChildItem -LiteralPath $roots -Recurse -Filter LibreHardwareMonitorLib.dll -ErrorAction SilentlyContinue |
  Select-Object -First 1 -ExpandProperty FullName
if (-not $dll) { return }
Add-Type -Path $dll
$computer = New-Object LibreHardwareMonitor.Hardware.Computer
$computer.IsCpuEnabled = $true
$computer.IsMotherboardEnabled = $true
$computer.Open()
$values = @()
foreach ($hardware in $computer.Hardware) {
  $hardware.Update()
  foreach ($subHardware in $hardware.SubHardware) {
    $subHardware.Update()
  }
  foreach ($sensor in $hardware.Sensors) {
    if ($sensor.SensorType.ToString() -eq 'Temperature' -and $null -ne $sensor.Value -and $sensor.Value -ge 0 -and $sensor.Value -le 125) {
      $values += [pscustomobject]@{ Name = $sensor.Name; Value = $sensor.Value }
    }
  }
}
$computer.Close()
$values | ConvertTo-Json -Compress
"""
    output = _run_powershell(script, timeout=4.0)
    if not output:
        return None
    try:
        data = json.loads(output)
    except json.JSONDecodeError:
        return None
    if isinstance(data, dict):
        data = [data]
    if not isinstance(data, list):
        return None
    package_values: list[float] = []
    core_values: list[float] = []
    other_values: list[float] = []
    for item in data:
        if not isinstance(item, dict):
            continue
        try:
            value = float(item.get("Value"))
        except (TypeError, ValueError):
            continue
        name = str(item.get("Name") or "").lower()
        if any(token in name for token in ("package", "tctl", "tdie", "ccd")):
            package_values.append(value)
        elif "core" in name and "distance" not in name:
            core_values.append(value)
        elif "distance" not in name:
            other_values.append(value)
    if package_values:
        return max(package_values)
    if core_values:
        return max(core_values)
    if other_values:
        return max(other_values)
    return None


def _windows_acpi_temperature() -> float | None:
    script = r"""
Get-CimInstance -Namespace root\wmi -ClassName MSAcpi_ThermalZoneTemperature -ErrorAction SilentlyContinue |
  ForEach-Object { [math]::Round(($_.CurrentTemperature / 10.0) - 273.15, 1) } |
  Where-Object { $_ -ge 0 -and $_ -le 125 } |
  Select-Object -First 1
"""
    output = _run_powershell(script, timeout=1.0)
    if not output:
        return None
    match = re.search(r"([+-]?\d+(?:\.\d+)?)", output)
    if not match:
        return None
    value = float(match.group(1))
    if 0.0 <= value <= 125.0:
        return value
    return None


def _windows_storage_temperature() -> float | None:
    for namespace in ("root\\LibreHardwareMonitor", "root\\OpenHardwareMonitor"):
        value = _hardware_monitor_storage_temperature(namespace)
        if value is not None:
            return value

    value = _libre_hardware_monitor_dll_storage_temperature()
    if value is not None:
        return value

    return _windows_storage_reliability_temperature()


def _hardware_monitor_storage_temperature(namespace: str) -> float | None:
    script = rf"""
$items = Get-CimInstance -Namespace '{namespace}' -ClassName Sensor -ErrorAction SilentlyContinue |
  Where-Object {{
    $_.SensorType -eq 'Temperature' -and
    $_.Value -ge 0 -and $_.Value -le 125 -and
    ($_.Name -match 'SSD|NVMe|HDD|Disk|Drive|Storage|Composite|Temperature' -or $_.Parent -match 'SSD|NVMe|HDD|Disk|Drive|Storage') -and
    ($_.Name -notmatch 'CPU|Core|Package|Tctl|Tdie|CCD|GPU|Memory|VRM|Chipset' -and $_.Parent -notmatch 'CPU|Intel|AMD|Ryzen|GPU|NVIDIA|AMD Radeon')
  }} |
  Select-Object Name,Parent,Value
$items | ConvertTo-Json -Compress
"""
    output = _run_powershell(script, timeout=1.5)
    if not output:
        return None
    try:
        data = json.loads(output)
    except json.JSONDecodeError:
        return None
    if isinstance(data, dict):
        data = [data]
    if not isinstance(data, list):
        return None
    values: list[float] = []
    for item in data:
        if not isinstance(item, dict):
            continue
        try:
            value = float(item.get("Value"))
        except (TypeError, ValueError):
            continue
        if 0.0 <= value <= 125.0:
            values.append(value)
    return max(values) if values else None


def _libre_hardware_monitor_dll_storage_temperature() -> float | None:
    script = r"""
$roots = @(
  "$env:LOCALAPPDATA\Microsoft\WinGet\Packages",
  "$env:ProgramFiles",
  "${env:ProgramFiles(x86)}"
) | Where-Object { $_ -and (Test-Path $_) }
$dll = Get-ChildItem -LiteralPath $roots -Recurse -Filter LibreHardwareMonitorLib.dll -ErrorAction SilentlyContinue |
  Select-Object -First 1 -ExpandProperty FullName
if (-not $dll) { return }
Add-Type -Path $dll
$computer = New-Object LibreHardwareMonitor.Hardware.Computer
$computer.IsStorageEnabled = $true
$computer.Open()
$values = @()
foreach ($hardware in $computer.Hardware) {
  $hardware.Update()
  foreach ($sensor in $hardware.Sensors) {
    if ($sensor.SensorType.ToString() -eq 'Temperature' -and $null -ne $sensor.Value -and $sensor.Value -ge 0 -and $sensor.Value -le 125) {
      $values += [pscustomobject]@{ Name = $sensor.Name; Value = $sensor.Value }
    }
  }
}
$computer.Close()
$values | ConvertTo-Json -Compress
"""
    output = _run_powershell(script, timeout=4.0)
    if not output:
        return None
    try:
        data = json.loads(output)
    except json.JSONDecodeError:
        return None
    if isinstance(data, dict):
        data = [data]
    if not isinstance(data, list):
        return None
    values: list[float] = []
    for item in data:
        if not isinstance(item, dict):
            continue
        try:
            value = float(item.get("Value"))
        except (TypeError, ValueError):
            continue
        if 0.0 <= value <= 125.0:
            values.append(value)
    return max(values) if values else None


def _windows_storage_reliability_temperature() -> float | None:
    script = r"""
Get-PhysicalDisk -ErrorAction SilentlyContinue |
  Get-StorageReliabilityCounter -ErrorAction SilentlyContinue |
  Where-Object { $_.Temperature -ne $null -and $_.Temperature -ge 0 -and $_.Temperature -le 125 } |
  Select-Object -ExpandProperty Temperature |
  Sort-Object -Descending |
  Select-Object -First 1
"""
    output = _run_powershell(script, timeout=2.0)
    if not output:
        return None
    match = re.search(r"([+-]?\d+(?:\.\d+)?)", output)
    if not match:
        return None
    value = float(match.group(1))
    if 0.0 <= value <= 125.0:
        return value
    return None


def _refresh_storage_temperature_async() -> None:
    global _last_ssd_temp, _last_ssd_temp_at, _ssd_query_running
    try:
        try:
            value = _windows_storage_temperature()
        except Exception:
            value = None
        now = time.monotonic()
        with _ssd_lock:
            if value is not None:
                _last_ssd_temp = value
                _last_ssd_temp_at = now
    finally:
        with _ssd_lock:
            _ssd_query_running = False


def _start_storage_temperature_query(now: float) -> None:
    global _last_ssd_query_at, _ssd_query_running
    if platform.system().lower() != "windows":
        return
    with _ssd_lock:
        if _ssd_query_running or now - _last_ssd_query_at < STORAGE_TEMP_QUERY_SECONDS:
            return
        _last_ssd_query_at = now
        _ssd_query_running = True
    thread = threading.Thread(target=_refresh_storage_temperature_async, name="storage-temp-query", daemon=True)
    thread.start()


def _number_or_none(value: object) -> float | None:
    if value is None:
        return None
    text = str(value).strip()
    if not text or text.lower() in {"n/a", "[not supported]", "not supported"}:
        return None
    match = re.search(r"([+-]?\d+(?:\.\d+)?)", text)
    if not match:
        return None
    return float(match.group(1))


def _nvidia_gpu_stats() -> dict[str, float | None]:
    if not shutil.which("nvidia-smi"):
        return {}
    output = _run_command(
        [
            "nvidia-smi",
            "--query-gpu=temperature.gpu,utilization.gpu,clocks.current.graphics,power.draw,fan.speed",
            "--format=csv,noheader,nounits",
        ],
        timeout=1.2,
    )
    if not output:
        return {}
    for line in output.splitlines():
        parts = [part.strip() for part in line.split(",")]
        if len(parts) < 2:
            continue
        return {
            "gpu_temp": _number_or_none(parts[0]),
            "gpu_load": _number_or_none(parts[1]),
            "gpu_frequency": _number_or_none(parts[2]) if len(parts) > 2 else None,
            "gpu_power": _number_or_none(parts[3]) if len(parts) > 3 else None,
            "gpu_fan_speed": _number_or_none(parts[4]) if len(parts) > 4 else None,
        }
    return {}


def _nvidia_settings_temp() -> float | None:
    if not shutil.which("nvidia-settings"):
        return None
    output = _run_command(["nvidia-settings", "-q", "gpucoretemp", "-t"], timeout=1.2)
    if not output:
        return None
    match = re.search(r"([+-]?\d+(?:\.\d+)?)", output)
    if not match:
        return None
    value = float(match.group(1))
    if 0.0 <= value <= 125.0:
        return value
    return None


def _read_text(path: Path) -> str | None:
    try:
        return path.read_text(encoding="utf-8", errors="replace").strip()
    except OSError:
        return None


def _read_hwmon_temp(path: Path) -> float | None:
    text = _read_text(path)
    if not text:
        return None
    try:
        raw = float(text)
    except ValueError:
        return None
    value = raw / 1000.0 if raw > 1000.0 else raw
    if 0.0 <= value <= 125.0:
        return value
    return None


def _gpu_temp_from_hwmon() -> float | None:
    gpu_names = ("amdgpu", "radeon", "nouveau", "nvidia", "i915", "xe")
    candidates: list[float] = []
    for hwmon in Path("/sys/class/hwmon").glob("hwmon*"):
        name = (_read_text(hwmon / "name") or "").lower()
        device_path = str((hwmon / "device").resolve(strict=False)).lower()
        if not any(token in name or token in device_path for token in gpu_names):
            continue
        for temp_input in sorted(hwmon.glob("temp*_input")):
            value = _read_hwmon_temp(temp_input)
            if value is not None:
                candidates.append(value)
    return max(candidates) if candidates else None


def _gpu_temp_from_sensors() -> float | None:
    if not shutil.which("sensors"):
        return None
    output = _run_command(["sensors"], timeout=1.0)
    if not output:
        return None
    current_adapter = ""
    candidates: list[float] = []
    gpu_tokens = ("amdgpu", "radeon", "nouveau", "nvidia", "gpu", "i915", "xe")
    for raw in output.splitlines():
        line = raw.strip()
        if not line:
            continue
        if not raw.startswith(" ") and ":" not in line:
            current_adapter = line.lower()
            continue
        if not any(token in current_adapter or token in line.lower() for token in gpu_tokens):
            continue
        match = re.search(r"([+-]?\d+(?:\.\d+)?)\s*°?C", line)
        if not match:
            continue
        value = float(match.group(1))
        if 0.0 <= value <= 125.0:
            candidates.append(value)
    return max(candidates) if candidates else None


def _safe_gpu_stats() -> dict[str, float | None]:
    global _last_gpu_source
    _last_gpu_source = "none"
    stats = _nvidia_gpu_stats()
    if any(value is not None for value in stats.values()):
        _last_gpu_source = "nvidia-smi"
        return stats
    temp = _nvidia_settings_temp()
    if temp is not None:
        _last_gpu_source = "nvidia-settings"
        return {"gpu_temp": temp}
    if temp is None:
        temp = _gpu_temp_from_hwmon()
        if temp is not None:
            _last_gpu_source = "hwmon"
    if temp is None:
        temp = _gpu_temp_from_sensors()
        if temp is not None:
            _last_gpu_source = "sensors"
    return {"gpu_temp": temp}


def collect_telemetry() -> dict[str, Any]:
    global _last_cpu_temp, _last_cpu_temp_at, _last_gpu_temp, _last_gpu_temp_at, _last_ssd_temp, _last_ssd_temp_at, _last_ssd_query_at
    cpu_temp = _safe_cpu_temperature()
    gpu_stats = _safe_gpu_stats()
    gpu_temp = gpu_stats.get("gpu_temp")
    now = time.monotonic()
    ssd_temp = _last_ssd_temp
    _start_storage_temperature_query(now)
    if cpu_temp is not None:
        _last_cpu_temp = cpu_temp
        _last_cpu_temp_at = now
    elif _last_cpu_temp is not None and now - _last_cpu_temp_at <= TEMP_CACHE_SECONDS:
        cpu_temp = _last_cpu_temp

    if gpu_temp is not None:
        _last_gpu_temp = gpu_temp
        _last_gpu_temp_at = now
    elif _last_gpu_temp is not None and now - _last_gpu_temp_at <= TEMP_CACHE_SECONDS:
        gpu_temp = _last_gpu_temp

    if ssd_temp is not None and now - _last_ssd_temp_at > STORAGE_TEMP_CACHE_SECONDS:
        ssd_temp = None

    cpu_load = float(psutil.cpu_percent(interval=None))
    cpu_frequency = None
    try:
        freq = psutil.cpu_freq()
        if freq is not None and freq.current:
            cpu_frequency = float(freq.current)
    except (OSError, RuntimeError):
        cpu_frequency = None
    ram = psutil.virtual_memory()

    return {
        "cpu_temp": cpu_temp,
        "gpu_temp": gpu_temp,
        "cpu_load": cpu_load,
        "gpu_load": gpu_stats.get("gpu_load"),
        "ram_used_percent": float(ram.percent),
        "ram_total_mb": float(ram.total / 1024 / 1024),
        "ssd_temp": ssd_temp,
        "cpu_frequency": cpu_frequency,
        "gpu_frequency": gpu_stats.get("gpu_frequency"),
        "cpu_power": None,
        "gpu_power": gpu_stats.get("gpu_power"),
        "gpu_fan_speed": gpu_stats.get("gpu_fan_speed"),
    }
