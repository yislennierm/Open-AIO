# Open AIO Agent Notes

This file is the working memory for future AI and developer sessions. Keep the public-facing overview and user instructions in `README.md`; keep process notes, decisions, migration rules, and session guardrails here.

## Current Direction

Open AIO is a USB-first display stack for the LilyGO T-RGB 2.8 inch 480x480 ESP32-S3R8 board. The active product direction is:

- Stable RawUSB lab firmware on the device.
- Boot animation while no stream is active.
- Smooth frame/video stream over USB.
- SignalRGB compatibility through the same RawUSB protocol.
- Electron desktop app as the preferred local control/render shell.
- Our own sensor path through local Windows APIs, WMI, LibreHardwareMonitor-compatible sources, NVIDIA/Windows APIs, and the current Python/agent layer.
- A native Open AIO core replacing performance-sensitive Python/PowerShell runtime paths over time.
- No NZXT CAM impersonation, no NZXT USB VID/PID, and no Kraken/CAM HID spoofing.

The device should be a fast frame receiver. Presets, video, browser state, media, and sensors are rendered or resolved on the PC side.

## Repository Modules

`firmware/`

ESP32-S3 firmware for the LilyGO T-RGB 2.8 inch 480x480 display. The source of truth is the RawUSB lab stream target:

```powershell
cd firmware
python -m platformio run -e t-rgb-half-circle-rawusb
python -m platformio run -e t-rgb-half-circle-rawusb -t upload --upload-port COM4
```

Important active flags and identity:

- `USB_VID=0x303A`
- `USB_PID=0x4004`
- `SIGNALRGB_RAWUSB_EXPERIMENT=1`
- `SIGNALRGB_VIDEO_FAST_PATH=1`
- `NZXT_ESC_TEST_FIRMWARE=1`
- USB product string: `Open AIO`

Do not reintroduce the older app-detector display path into this firmware unless it is rebuilt intentionally around the lab stream timing. Preserve the smooth streaming path first.

`electron-app/`

Preferred desktop shell. It owns the app window, tray, local render supervision, stream transforms, backend start/status, SignalRGB plugin deployment, and launcher behavior. Future desktop UX work should happen here first.

`nzxt-esc-live/`

Our local maintained ESC fork/custom copy. Treat it as Open AIO's adapted version of NZXT-ESC v6.05.11 behavior, not as a disposable generated folder. It should stay visually close to the upstream/live ESC UI while adding only the compatibility layers needed for Open AIO:

- 480x480 circular render mode.
- Local sensor shim.
- Local storage/render synchronization.
- RawUSB frame bridge support.
- No dependency on NZXT CAM being installed or running.

Do not replace this with older ESC builds or old local experiments. If upstream ESC is refreshed, compare carefully and port the Open AIO shims forward.

`nzxt-esc-gallery/`

Preset gallery module. Keep it separate from the ESC runtime so presets can be refreshed from upstream/user sources without overwriting our ESC fork. The gallery should contain preset packs, thumbnails, and importable preset data. Avoid storing personal local edits here unless they are meant to be shared.

`pc-agent/`

Python agent and RawUSB transport. It gathers sensor data, provides tolerant sensor naming/mapping, and sends frames to the device. `pc-agent/usb_transport.py` is the shared transport family used by SignalRGB and the Electron/ESC rendering path.

`native/open-aio-core/`

Rust/N-API native core scaffold. The first migration target is RawUSB JPEG frame delivery using the same `SRGB` protocol as the Python transport. Keep it isolated until it builds and measures cleanly, then wire Electron to prefer native USB with Python as fallback. Later migration targets are sensor collection, status, and packaging.

`server/`

Local FastAPI server. It serves the ESC UI, gallery, sensor bridge endpoints, designer/frame endpoints, and helper APIs.

`signalrgb/`

SignalRGB RawUSB plugin for Open AIO. Keep only the active RawUSB plugin here unless a second firmware path is intentionally restored. The supported plugin is `Open_AIO_Display.js`; it should appear in SignalRGB as `Open AIO Display` and target VID/PID `303A:4004`.

Deploy it from Electron with:

```text
Open AIO -> Deploy SignalRGB Plugin
```

For manual development deployment, use:

```powershell
.\scripts\deploy_signalrgb_plugin.ps1
```

That script copies the plugin into SignalRGB's persistent user plugin directory under `Documents\WhirlwindFX\Plugins`.

`drivers/` and `windows/driver/`

WinUSB driver metadata for the Open AIO RawUSB device. Keep device naming user-facing as Open AIO.

`scripts/`

Windows setup, launch, driver, SignalRGB deployment, and repair helper scripts. Prefer these over ad hoc commands when they already cover the workflow.

Retired paths removed from the active tree:

- `desktop-app/`: old Python tray/control app. Electron is now the desktop app.
- `sensor-bridge/`: experimental C# sensor bridge. Reintroduce native helpers only with a clear active use case.

## RawUSB Protocol

The shared PC-to-device stream protocol uses the `SRGB` magic handled by the firmware lab path.

Current commands:

- `0x03`: RGB565 rectangle, scaled on device.
- `0x05`: JPEG frame.

Default transport details:

- VID: `0x303A`
- PID: `0x4004`
- OUT endpoint: `0x01`
- IN endpoint: `0x81`

Avoid adding USB write-back or acknowledgement traffic on the hot frame path unless it is measured and proven not to introduce burst/jump behavior.

The native core must preserve this protocol exactly while it replaces Python transport code. Any change to packet headers, chunking, endpoint usage, or acknowledgement behavior must be measured against SignalRGB compatibility and Electron preview smoothness.

## Rendering Rules

The browser/Electron side owns final frame rendering. The firmware receives complete frames and displays them as smoothly as possible.

Required behavior:

- Boot animation loops whenever there is no active stream.
- SignalRGB can take over the stream.
- Electron/ESC can take over the stream.
- Preset changes and overlay edits should update the live stream in real time.
- Sensor updates must not be confused with overlay updates; both must be observable.
- No duplicate renderer/streamer processes should survive preset changes.

The working render URL shape is generally:

```text
http://127.0.0.1:8000/nzxt-esc/?kraken=1&mockLcd=480&mockShape=circle
```

Electron may create a controlled renderer instead of relying on a normal browser tab. Prefer the controlled Electron renderer path when debugging real-time updates.

## Sensors

Sensor values must come from Open AIO's local agent path, not NZXT CAM.

Expected sensor categories:

- CPU load
- CPU temperature
- GPU load
- GPU temperature
- RAM usage
- Storage temperature/usage when available
- Network/ping values when available
- Fan/pump values only when a reliable local source exists

Sensor naming should be tolerant. Presets may ask for CAM-like names; the agent/server should map those to local equivalents when possible. Missing sensors should degrade gracefully with neutral values or hidden/fallback elements, not break rendering.

Do not require HWiNFO, NZXT CAM, or extra always-running services just to display a few basic sensors. Prefer built-in Windows APIs, WMI, GPU vendor APIs, and optional bridges only when needed.

## Privacy And Publishing

Never push the original local history that contained the Wi-Fi password. The GitHub repo was created from a fresh sanitized history. Treat `.publish/Open-AIO-clean` as the GitHub source unless the main working tree is rebuilt from that clean history.

Never commit:

- `firmware/src/config.local.h`
- Real Wi-Fi SSIDs/passwords
- `server/config.json`
- `pc-agent/config.json`
- Electron `settings.json`
- Logs
- Python bytecode
- PlatformIO build output
- Node modules
- Generated app icon cache
- Local designer storage/temp files

The repo should contain placeholders only:

- `YOUR_WIFI_SSID`
- `YOUR_WIFI_PASSWORD`
- `change-me`

## Documentation Rule

There should be exactly two Markdown files in the repo:

- `README.md`
- `AGENT.md`

When adding documentation, update one of those two files instead of creating another `.md` file. Keep the README useful for a new human user. Keep this file useful for future AI/developer sessions.

When the user says `document project`, treat it as an explicit instruction to:

- Review the current project state.
- Update `README.md` and/or `AGENT.md` only if something needs to be captured.
- Run the documentation and privacy checks.
- Commit and push the documentation update to GitHub from `.publish/Open-AIO-clean`, the sanitized source of truth.

## Verification Checklist

Before publishing changes:

```powershell
Get-ChildItem -Recurse -Filter *.md
rg -n --hidden "C:\\Users\\|WIFI_PASSWORD|WIFI_SSID|password|passwd|psk|secret|api[_-]?key" .
node --check electron-app/src/main.js
python -m py_compile server/app/main.py server/app/designer_page.py server/app/web_logos.py pc-agent/agent.py pc-agent/usb_transport.py
```

Broad text scans can hit base64 preset blobs. Investigate hits, but distinguish actual secrets from embedded preview image data.

## Open Work

- Keep SignalRGB smooth on the RawUSB lab path.
- Keep Electron/ESC live preview and device stream synchronized during preset edits.
- Formalize gallery refresh/import so upstream presets can be brought in without overwriting Open AIO changes.
- Build and validate `native/open-aio-core`, then move Electron USB frame delivery to native code with Python as fallback.
- Move sensors from Python to native Windows APIs only after native USB delivery is stable.
- Revisit app detector/icons later only after stream stability is protected.
