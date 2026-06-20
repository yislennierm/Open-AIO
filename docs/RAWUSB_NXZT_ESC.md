# RawUSB + nxzt-esc Direction

Status: active direction as of 2026-06-19.

## Decision

The device firmware stays on the stable RawUSB lab stream path. We are not impersonating NZXT CAM devices.

Active goals:

- Boot animation runs when no stream is active.
- Smooth video/frame playback over USB remains the first priority.
- SignalRGB remains compatible.
- USB identity stays local: `VID_303A PID_4004`.
- No NZXT USB VID/PID is used.
- `nxzt-esc` is treated as our own PC-side designer/renderer, not as a CAM integration.

Abandoned route:

- Do not spoof Kraken, NZXT CAM, or `VID_1E71`.
- Do not use the experimental `drivers/nzxt-spoof-winusb` path for the active product.
- Do not add CAM HID descriptors to the production/lab firmware path.

## Firmware Source Of Truth

Use this PlatformIO target:

```powershell
cd firmware
python -m platformio run -e t-rgb-half-circle-rawusb
```

Flash only when the user confirms the board is ready:

```powershell
python -m platformio run -e t-rgb-half-circle-rawusb -t upload --upload-port COM4
```

Important build flags in this target:

- `USB_VID=0x303A`
- `USB_PID=0x4004`
- `SIGNALRGB_RAWUSB_EXPERIMENT=1`
- `SIGNALRGB_VIDEO_FAST_PATH=1`
- `NZXT_ESC_TEST_FIRMWARE=1`

The USB product string should be `Open AIO`.

## RawUSB Protocol

The shared PC-to-device stream protocol uses the `SRGB` magic handled by the firmware lab path.

Current commands:

- `0x03`: RGB565 rectangle, scaled on device.
- `0x05`: JPEG frame.

The Python transport lives in:

- `pc-agent/usb_transport.py`

It writes to:

- VID: `0x303A`
- PID: `0x4004`
- OUT endpoint: `0x01`
- IN endpoint: `0x81`

This is the same transport family used by the SignalRGB plugin and by our PC renderers.

## nxzt-esc Role

`nzxt-esc` is our designer/editor surface. It should render presets on the PC, then send frames to the device over RawUSB.

Responsibilities:

- Load bundled and imported presets.
- Render the 480x480 circular preview on the PC.
- Resolve media/backgrounds on the PC.
- Render video frames on the PC.
- Send only final frames to the device.

The device should not need to understand presets, media URLs, web UI state, or NZXT CAM APIs.

## Render Paths

Normal designer preview flow:

- `nzxt-esc` posts frames to `/api/v1/designer/frame`.
- `pc-agent/agent.py` can forward designer frames to RawUSB.

Direct USB renderer flow:

- `pc-agent/designer_renderer.py --usb-direct` captures the real designer surface and sends JPEG frames over RawUSB.
- `pc-agent/direct_media_renderer.py` uses ffmpeg for smoother direct media playback and sends frames over RawUSB.

Useful script:

```powershell
.\scripts\run_direct_media_renderer.ps1
```

## Sensors

Sensor values come from our own PC agent stack, not from NZXT CAM device impersonation.

Allowed sources:

- LibreHardwareMonitor / local sensor bridge.
- WMI.
- NVIDIA/Windows APIs.
- Existing `pc-agent/telemetry.py` pipeline.

Designer metric names should map through our tolerant metric layer, for example:

- CPU load
- CPU temperature
- GPU load
- GPU temperature
- RAM usage
- ping/network values when available

Missing sensors should degrade to neutral values or hide/fallback in the preset. They should not break rendering.

## Idle Behavior

When no SignalRGB or `nxzt-esc` RawUSB stream is active, the firmware stays in boot idle animation. It should not wait forever on a blank screen.

When a stream starts:

- SignalRGB or `nxzt-esc` owns the visible output.
- The firmware prioritizes receiving and drawing frames smoothly.

When the stream stops:

- After the stream timeout, firmware returns to boot idle animation.

## Safety Rules

- Do not merge old production/app-detector display behavior into the lab stream path until it is rebuilt intentionally.
- Do not reintroduce CAM spoofing into `t-rgb-half-circle-rawusb`.
- Do not flash experimental firmware without explicitly saying which environment is being flashed.
- Preserve the lab smoothness path before changing protocol, frame timing, USB buffers, or display flush behavior.
