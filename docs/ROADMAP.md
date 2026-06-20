# Open AIO Roadmap

This project now has two active development tracks. The rule for both tracks is simple: keep the current firmware display and RawUSB/WiFi telemetry path working while new PC-side features are added behind optional switches.

## Track 1: Native Sensor Backend

Goal: read CPU/GPU/motherboard/liquid sensors without requiring FanControl, LibreHardwareMonitor, OpenHardwareMonitor, or another desktop app to be running.

Current state:

- The Python agent reads CPU load, RAM, NVIDIA GPU temp/load, and active app state.
- CPU temp is missing on this Windows PC because the standard WMI namespaces are not populated.
- FanControl can see CPU temp through its own .NET/LibreHardwareMonitor stack, using `/intelcpu/0/temperature/1`.

Target architecture:

```text
pc-agent Python process
  -> built-in lightweight telemetry
  -> optional native sensor bridge
       -> LibreHardwareMonitor/PawnIO/NVAPI/ADLX/etc.
       -> JSON to stdout
  -> FastAPI server
  -> RawUSB if present, WiFi fallback otherwise
```

Near-term implementation:

- Add an optional `external_sensor_command` to the PC agent config.
- Build a tiny .NET console helper under `sensor-bridge/`.
- The helper prints normalized JSON:

```json
{
  "cpu_temp": 43.5,
  "cpu_source": "native-lhm",
  "gpu_temp": 32.0,
  "gpu_source": "native-nvidia"
}
```

Provider order:

1. Native bridge, if configured and healthy.
2. Built-in Python methods.
3. FanControl IPC bridge, as a compatibility fallback if FanControl is running.
4. `null` values with explicit source names when unavailable.

The native bridge should not own display transport, app mapping, logos, or tray state. It is only a sensor reader.

## Track 2: Display Designer

Goal: create our own editor inspired by `nzxt-esc`, but for this project’s round display, firmware protocol, and app-logo workflow.

`nzxt-esc` is useful as a product/design reference:

- flexible overlay elements
- draggable/resizable/rotatable objects
- metric mapping with tolerant field names
- preset import/export
- live preview

It is not a Windows sensor backend. It relies on NZXT CAM injecting telemetry into `window.nzxt.v1`.

Target architecture:

```text
FastAPI server
  -> /designer web UI
  -> layout JSON/presets
  -> preview renderer
  -> firmware-compatible display state

Firmware
  -> keeps current built-in screen as fallback
  -> later accepts a compact layout/state payload
```

Near-term implementation:

- Add a server-hosted designer page rather than a separate app first.
- Keep the current built-in firmware layout as `classic`.
- Define a layout schema for:
  - text
  - clock/date
  - app logo
  - metric values
  - arcs/gauges
  - background color/media later
- Export/import presets as JSON.
- Render a browser preview before changing firmware behavior.

Only after the schema and preview feel good should the firmware accept custom layout packets. Until then, the device keeps the current screen.
