# Open AIO

Open AIO is a USB-first display stack for a 480x480 round ESP32-S3 LCD inside a PC cooling/display build. It keeps the device firmware simple and fast: the PC renders complete frames, and the ESP32 receives those frames over RawUSB and displays them smoothly.

The current target hardware is the LilyGO T-RGB 2.8 inch Full Circle board:

- ESP32-S3R8
- 16 MB flash
- 8 MB OPI PSRAM
- 480x480 round RGB panel
- USB device mode for RawUSB streaming

The active product goal is:

```text
SignalRGB or Open AIO Electron app -> RawUSB frames -> ESP32-S3 display
```

No NZXT CAM spoofing is used. No NZXT USB IDs are used. Open AIO can use NZXT-ESC-style presets as a PC-side UI/rendering surface, but the hardware presents itself as Open AIO.

## What Is Included

`firmware/`

ESP32-S3 firmware for the RawUSB lab stream path. It shows the boot animation while idle and displays incoming frames when SignalRGB or the Open AIO desktop app is streaming.

`electron-app/`

The preferred Windows desktop shell. It launches and supervises the local server/render flow, provides the app/tray surface, and keeps the controlled renderer synchronized with the device stream.

`nzxt-esc-live/`

Open AIO's customized ESC runtime. Treat this as our maintained local fork/copy of the NZXT-ESC v6.05.11 experience, adapted for a 480x480 circular display, local sensors, and RawUSB streaming.

`nzxt-esc-gallery/`

Preset gallery module. This is kept separate from the ESC runtime so presets can be refreshed or imported without overwriting Open AIO's customized renderer.

`pc-agent/`

Python agent and RawUSB transport. It gathers local sensor data and sends rendered frames to the device.

`server/`

Local FastAPI server for ESC hosting, sensor shims, gallery data, and frame endpoints.

`signalrgb/`

SignalRGB plugin files for streaming to the Open AIO RawUSB firmware.

`drivers/`, `windows/driver/`, and `scripts/`

Windows WinUSB driver metadata plus helper scripts for setup, launch, repair, and development workflows.

## Quick Start

Install project dependencies:

```powershell
cd electron-app
npm install
```

Install Python dependencies:

```powershell
cd ..\server
python -m pip install -r requirements.txt
cd ..\pc-agent
python -m pip install -r requirements.txt
```

Launch the desktop app:

```powershell
cd ..
.\scripts\start_electron.ps1
```

The normal ESC surface is served locally at:

```text
http://127.0.0.1:8000/nzxt-esc/?kraken=1&mockLcd=480&mockShape=circle
```

Use the Electron app as the preferred control surface when testing live streaming, because it manages the render process more reliably than a normal browser tab.

## Firmware Build And Flash

The active firmware target is:

```powershell
cd firmware
python -m platformio run -e t-rgb-half-circle-rawusb
```

Flash when the board is in download mode:

```powershell
python -m platformio run -e t-rgb-half-circle-rawusb -t upload --upload-port COM4
```

The active USB identity is:

- VID: `0x303A`
- PID: `0x4004`
- Product: `Open AIO`

Secrets are not committed. If Wi-Fi mode is needed, create a local ignored file:

```cpp
// firmware/src/config.local.h
#pragma once

#define WIFI_SSID "YOUR_WIFI_SSID"
#define WIFI_PASSWORD "YOUR_WIFI_PASSWORD"
#define SERVER_BASE_URL "http://YOUR_PC_LAN_IP:8000"
```

The RawUSB streaming path does not require Wi-Fi.

## SignalRGB

Install the Open AIO plugin from `signalrgb/` into SignalRGB's user plugins folder, then select the Open AIO LCD device/plugin inside SignalRGB.

SignalRGB and the Open AIO Electron renderer share the same RawUSB firmware path. If SignalRGB is streaming, it owns the display. When no stream is active, the device returns to the boot animation.

## Presets And Gallery

The ESC runtime and gallery are intentionally separate:

- `nzxt-esc-live/` is the Open AIO ESC fork/custom runtime.
- `nzxt-esc-gallery/` is the preset gallery module.

This lets the project update or replace preset packs without losing the local renderer changes needed for 480x480 output, local sensor data, and RawUSB streaming.

When adding presets, keep shared presets in `nzxt-esc-gallery/`. Avoid committing personal local drafts unless they are meant to become part of the public gallery.

## Sensors

Open AIO does not depend on NZXT CAM for sensor values. Sensor values come from the local Open AIO stack:

- Windows APIs
- WMI
- GPU vendor APIs where available
- LibreHardwareMonitor-compatible paths where useful
- `pc-agent/telemetry.py`

Presets can ask for CAM-like sensor names; Open AIO maps those names to local equivalents when possible. Missing sensors should fall back gracefully instead of breaking a preset.

## Privacy

The public repo should only contain placeholder secrets:

- `YOUR_WIFI_SSID`
- `YOUR_WIFI_PASSWORD`
- `change-me`

Do not commit local config files, logs, Electron settings, app icon cache, generated designer storage, build output, or real Wi-Fi credentials.

## Documentation

This repository intentionally has only two Markdown files:

- `README.md`: project overview and human usage.
- `AGENT.md`: architecture notes, AI-session context, process rules, and future work.

Keep new documentation in one of those two files. When the project is documented or refreshed, both files should be reviewed, only the relevant file or files should change, and the clean GitHub tree should be pushed after the documentation checks pass.
