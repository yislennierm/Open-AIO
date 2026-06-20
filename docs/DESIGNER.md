# Display Designer

The display designer is our own editor for Open AIO, adapted from `nxzt-esc`/`nzxt-esc` ideas but not coupled to NZXT CAM.

Primary active direction: `docs/RAWUSB_NXZT_ESC.md`.

## What To Borrow From `nzxt-esc`

- Element-based layouts.
- Live preview before applying changes.
- Presets with import/export.
- Tolerant metric mapping:
  - `cpuTemp`
  - `cpuLoad`
  - `gpuTemp`
  - `gpuLoad`
  - future `liquidTemp`
- Transform operations:
  - move
  - resize
  - rotate where useful
  - z-order

## What Not To Borrow

- NZXT CAM API dependency.
- Browser-injected CAM telemetry dependency.
- Kraken-specific display assumptions.
- Its project structure wholesale.

Our stack already has a server, app mapping, RGB565 assets, RawUSB, WiFi fallback, and a tray controller. The designer should attach to that.

## First Layout Schema

The first schema should describe a circular 480x480 canvas and be easy to render both in the browser and later in firmware.

```json
{
  "version": 1,
  "name": "Classic",
  "canvas": {
    "width": 480,
    "height": 480,
    "shape": "circle"
  },
  "elements": [
    {
      "id": "cpu_arc",
      "type": "arc_metric",
      "metric": "cpu_load",
      "x": 240,
      "y": 240,
      "radius": 224,
      "start_deg": 120,
      "sweep_deg": 300,
      "color": "#027BFF"
    },
    {
      "id": "gpu_arc",
      "type": "arc_metric",
      "metric": "gpu_load",
      "x": 240,
      "y": 240,
      "radius": 204,
      "start_deg": 120,
      "sweep_deg": 300,
      "color": "#76FF00"
    },
    {
      "id": "app_logo",
      "type": "app_logo",
      "x": 146,
      "y": 104,
      "width": 188,
      "height": 188
    },
    {
      "id": "cpu_temp",
      "type": "metric_text",
      "metric": "cpu_temp",
      "x": 70,
      "y": 326,
      "width": 168,
      "style": "seven_segment",
      "color": "#027BFF"
    }
  ]
}
```

## Server Endpoints

Initial endpoints can live in the existing FastAPI server:

- `GET /designer`
- `GET /api/v1/layouts`
- `GET /api/v1/layouts/{layout_id}`
- `POST /api/v1/layouts`
- `POST /api/v1/device/{device_id}/layout`

The current firmware can ignore custom layouts until the preview/schema is stable.

## Implementation Order

1. Create schema and examples under `server/layouts/`. Done.
2. Add `/designer` with a browser preview of the current display state. Done.
3. Add preset save/load on the server. Done.
4. Add drag/resize controls.
5. Add export/import JSON.
6. Add firmware support for a compact subset:
   - arcs
   - app logo
   - metric text
   - clock/date
7. Keep `classic` firmware rendering as fallback.

## Firmware Safety Rule

The firmware should always have a known-good built-in screen. Custom layouts are an enhancement, not a boot requirement.

## Current Direction

The designer direction is now the adapted `nzxt-esc` TypeScript/Vite app, served by the FastAPI server at `/designer`.

The old Python inline designer was only a prototype. The TS editor is the real path because it already has preset management, element transforms, media/background handling, import/export, and a mature circular preview.

## Current Safety Boundary

The designer is PC-side. It renders presets/media on the PC and sends final frames to the device over the same RawUSB `SRGB` protocol used by SignalRGB.

The firmware remains the stable RawUSB lab stream firmware:

- Boot animation when no stream is active.
- Smooth USB stream playback.
- Local USB identity `VID_303A PID_4004`, product `Open AIO`.
- No NZXT CAM spoofing or NZXT USB IDs.

For development:

```powershell
.\scripts\run_designer_dev.ps1
```

For normal use, build the designer and open it through the server:

```powershell
cd nzxt-esc
npm.cmd run build
```

Then open:

```text
http://127.0.0.1:8000/designer
```
