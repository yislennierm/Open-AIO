# Open AIO

PC telemetry and active foreground app display for an ESP32-driven round TFT mounted on the decorative top of a CPU water-cooling block.

The project is split into three small pieces:

```text
Windows PC agent -> FastAPI local server -> ESP32 round TFT display
```

The PC agent stays lightweight. It collects telemetry and the active foreground process basename only. It does not extract icons, window titles, thumbnails, or process images. The server owns app mapping and asset preprocessing, and the ESP32 only consumes validated JSON and preprocessed RGB565 assets.

## Hardware Assumptions

- LilyGO T-RGB 2.1-inch half-circle board with ESP32-S3R8.
- 480x480 ST7701S RGB panel with FT3267 touch.
- Official LilyGO T-RGB Arduino display library.
- USB 5V power from a motherboard USB header or another proper USB 5V source.
- The display is mounted on a decorative top surface, bracket, magnets, or thin adhesive, not directly on a hot metal contact surface.

## Server Setup

```bash
cd server
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
cp config.example.json config.json
uvicorn app.main:app --host 0.0.0.0 --port 8000
```

The server reads `config.json` if present, otherwise `config.example.json`. The default API key is `change-me`; change it before using the project beyond a local MVP.

Preprocess an app logo:

```bash
cd server
python scripts/preprocess_asset.py path/to/logo.png steam --size 160
```

This creates `assets/apps/steam/logo_160x160.rgb565` and `assets/apps/steam/manifest.json`.

## PC Agent Setup

Windows:

```bat
scripts\setup_windows.ps1
scripts\start_tray.ps1
```

The tray icon is the normal Windows control surface. Right-click it to start, stop, restart, open logs, open logo review, check the device, or switch transport mode. See `docs/WINDOWS.md` for the full Windows bring-up path, including firewall, LAN IP, ESP32 config, transport modes, and autostart notes.

Linux/macOS:

```bash
cd pc-agent
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
cp config.example.json config.json
python agent.py
```

The agent posts process basename and telemetry every second by default. It never sends window titles. On Linux/X11, install `xdotool` for active process detection. On Sway/Wayland, install `swaymsg` and `jq`. Other Wayland desktops may report `unknown.exe` unless a desktop-specific foreground-process API is added.

## ESP32 Firmware Setup

```bash
cd firmware
pio run
pio run --target upload
pio device monitor
```

Before flashing, edit `firmware/src/config.h` with your Wi-Fi network, server URL, device name, device ID, and API key. The firmware is configured for the LilyGO T-RGB 2.1-inch half-circle board.

## SignalRGB LCD Streaming

The `signalrgb` folder contains local SignalRGB LCD plugins for the serial and RawUSB firmware builds. See `docs/SIGNALRGB.md` for plugin installation, driver setup, endpoint notes, and the RawUSB status/debug path.

## Native Sensors and Designer

The PC side is moving toward a native sensor bridge and browser-based display designer while keeping the current firmware screen stable. See `docs/ROADMAP.md`, `sensor-bridge/README.md`, and `docs/DESIGNER.md`.

## Security Notes

- All API calls require `X-API-Key`.
- The PC agent sends the executable basename only.
- Unknown processes map to the default app.
- Assets are served only from known app folders.
- ESP32 verifies asset SHA-256 before saving.
- Asset size is capped on both server and ESP32.
- The MVP is intended for local/LAN use. Use HTTPS or a tunnel with authentication before crossing trust boundaries.

## MVP Limitations

- Latest telemetry is stored in memory, so it resets when the server restarts.
- GPU telemetry is `null` in the default Windows agent.
- The server has a hardcoded process-to-app map.
- The default firmware display pin configuration is a starting point and must be adjusted for real hardware.
- No database, user management, web UI, or OTA firmware update flow is included in phase 1.
