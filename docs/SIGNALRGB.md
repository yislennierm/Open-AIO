# SignalRGB, NZXT-ESC, and Firmware Streaming

This is the unified reference for ESP32 LCD streaming, the known-good
`t-rgb-nzxt-esc-test` firmware, and the production RawUSB firmware path.

## Firmware Builds

| Environment | Purpose | Transport | Notes |
| --- | --- | --- | --- |
| `t-rgb-half-circle` | Safer production fallback | USB CDC serial + Wi-Fi | Keeps rotated product display and Wi-Fi polling. |
| `t-rgb-half-circle-rawusb` | Production RawUSB build | RawUSB + USB CDC + Wi-Fi | Keeps product behavior, CAPP app-state, SignalRGB, and NZXT-ESC/designer JPEG streaming. Uses the smooth-video fast path. |
| `t-rgb-nzxt-esc-test` | Protected performance test firmware | RawUSB only | Known-good smooth playback reference. Do not casually refactor. |

Build and upload production RawUSB:

```powershell
cd firmware
pio run -e t-rgb-half-circle-rawusb --target upload
```

Build and upload the video-only test firmware:

```powershell
cd firmware
pio run -e t-rgb-nzxt-esc-test --target upload
```

## Known-Good Test Baseline

The test firmware is the reference for smooth SignalRGB/NZXT-ESC video playback.
It intentionally strips out product work so only the streaming hot path remains.

The important properties are:

- `NZXT_ESC_TEST_FIRMWARE=1`.
- `SIGNALRGB_VIDEO_FAST_PATH=1`.
- RawUSB vendor transport.
- RawUSB RX buffer size `131072`.
- `SIGNALRGB_MAX_PAYLOAD=131072`.
- stream read buffer `4096`.
- `DISPLAY_ROTATE_180=0`.
- direct panel framebuffer enabled.
- direct JPEG framebuffer decode enabled.
- `loop()` only drains RawUSB and yields.
- accepts the video-critical `SRGB` commands:
  - `0x03`: scaled RGB565 rectangle.
  - `0x05`: JPEG frame.

Do not migrate the test firmware by deleting its special behavior. It is the
performance baseline.

## Production RawUSB Migration

The production RawUSB firmware now opts into `SIGNALRGB_VIDEO_FAST_PATH=1`.
That brings the working parts of the test firmware into production while keeping
the product features:

- normal USB product name, `Open AIO`;
- Wi-Fi polling when no stream is active;
- cached logo/assets;
- app telemetry screen;
- touch review;
- `CAPP` USB app-state packets from the PC agent;
- SignalRGB local FX and JPEG streaming;
- NZXT-ESC/designer JPEG streaming from the PC renderer.

What was migrated:

- direct panel framebuffer fast path;
- direct full-size JPEG framebuffer decode;
- non-rotated video orientation so direct JPEG can actually activate;
- `4096` byte firmware stream read buffer;
- RawUSB stream draining before serial/Wi-Fi/product background work;
- stream timing/status packets remain available for diagnostics.

What must not be migrated into production:

- test firmware early return from `setup()`;
- test firmware permanent early return from `loop()`;
- disabling Wi-Fi globally;
- disabling `CAPP` app-state packets;
- rejecting `0x01`, `0x02`, or `0x04` production SignalRGB commands;
- renaming the production USB device to `NZXT ESC Test Display`.

## Rotation Rule

The smooth direct JPEG path depends on rotation being disabled in firmware:

```cpp
directPanelFrame &&
!directDecodeOffscreen &&
SIGNALRGB_DIRECT_JPEG_FRAMEBUFFER_DECODE &&
!DISPLAY_ROTATE_180 &&
jpegWidth == DISPLAY_WIDTH &&
jpegHeight == DISPLAY_HEIGHT
```

If `DISPLAY_ROTATE_180=1`, full-frame JPEG playback silently misses the direct
decode path and falls back to the slower path. That was one of the reasons the
test firmware existed.

For smooth video, rotate content on the PC side when needed. The direct media
renderer already exposes:

```powershell
python pc-agent\direct_media_renderer.py --rotate-180
```

## SignalRGB Plugins

| Plugin file | Firmware environment | VID:PID | Transport | Best use |
| --- | --- | --- | --- | --- |
| `signalrgb/Open_AIO.js` | `t-rgb-half-circle` | `303A:1001` | USB CDC serial at 4 Mbaud | Safer fallback, easier serial debugging. |
| `signalrgb/Open_AIO_RawUSB.js` | `t-rgb-half-circle-rawusb` | `303A:4004` | TinyUSB RawUSB bulk OUT/IN | Smooth full-resolution JPEG streaming. |

Install:

1. Flash the matching firmware.
2. Copy the matching plugin file into:

   ```text
   %USERPROFILE%\Documents\WhirlwindFX\Plugins
   ```

3. Restart SignalRGB.
4. Select `Open AIO`.

RawUSB modes:

- `Direct JPEG Max FPS`: lower JPEG quality, higher frame target.
- `Direct JPEG`: balanced JPEG quality.
- `Direct JPEG Low`: higher compression, lower frame target.
- `Local FX`: sends color summary and lets the ESP32 render animation locally.

Serial modes:

- `Direct JPEG`: full 480x480 SignalRGB LCD preview as JPEG.
- `Direct FPS`, `Direct Fast`, `Direct Balanced`, `Direct Sharp`: RGB565 rectangle modes.
- `Local FX`: local animation mode.

## RawUSB Driver

The RawUSB firmware advertises `VID:PID 303A:4004` and a WinUSB-compatible vendor
interface. If SignalRGB or the PC agent cannot open the device:

```powershell
.\scripts\install_rawusb_winusb_driver.ps1
```

If Windows cached the wrong driver:

```powershell
.\scripts\repair_rawusb_winusb_driver.ps1
```

## Packet Protocol

`SRGB` packets are used by SignalRGB and NZXT-ESC/designer JPEG streams.

Header: 20 bytes, little-endian.

| Offset | Size | Field |
| --- | ---: | --- |
| 0 | 4 | Magic: `SRGB` |
| 4 | 1 | Command |
| 5 | 1 | Scale or command-specific value |
| 6 | 2 | Payload checksum, unsigned sum of payload bytes |
| 8 | 2 | X coordinate for rectangle commands |
| 10 | 2 | Y coordinate for rectangle commands |
| 12 | 2 | Width for rectangle commands |
| 14 | 2 | Height for rectangle commands |
| 16 | 4 | Payload length |

Commands:

| Command | Name | Payload |
| ---: | --- | --- |
| `0x01` | RGB565 rectangle | `width * height * 2`, scale 2 |
| `0x02` | Flush | no payload |
| `0x03` | Scaled RGB565 rectangle | `width * height * 2`, scale in header byte 5 |
| `0x04` | Local FX | 8 bytes: base RGB, accent RGB, energy, reserved |
| `0x05` | JPEG frame | JPEG bytes for a full 480x480 LCD preview |

`CAPP` packets are used by the PC agent for production app-state/telemetry:

- magic: `CAPP`;
- command `0x01`;
- payload: compact JSON state;
- max payload: `8192` bytes.

The production RawUSB firmware must continue accepting both `SRGB` and `CAPP`.

## Status Packets

RawUSB status packets are optional device-to-host replies on the bulk IN endpoint.
The SignalRGB RawUSB plugin only polls them when `Log Device Status` is enabled.

Status packet format:

| Offset | Size | Field |
| --- | ---: | --- |
| 0 | 4 | Magic: `SRSP` |
| 4 | 1 | Status code |
| 5 | 1 | Command that produced the status |
| 6 | 2 | Detail, usually payload length or checksum |
| 8 | 4 | Device `millis()` timestamp |
| 12 | 2 | Last RX ms |
| 14 | 2 | Last JPEG decode ms |
| 16 | 2 | Last flush ms |

Status codes:

| Code | Name |
| ---: | --- |
| `0x00` | OK |
| `0x01` | BAD_MAGIC |
| `0x02` | BAD_COMMAND |
| `0x03` | BAD_LENGTH |
| `0x04` | BAD_CHECKSUM |
| `0x05` | RENDER_FAILED |

## NZXT-ESC / Designer Streaming

The adapted/newer NZXT-ESC UI is served by the local server at:

```text
http://127.0.0.1:8000/designer-app/
```

Designer preview streaming is PC-rendered. The Python renderer captures a 480x480
JPEG preview and sends it to the ESP32 as an `SRGB 0x05` JPEG packet through
`pc-agent/usb_transport.py`.

Relevant commands:

```powershell
python pc-agent\designer_renderer.py --usb-direct
python pc-agent\direct_media_renderer.py --transport jpeg
```

Use `--rotate-180` on the PC renderer if the physical installation requires
rotation. Do not re-enable firmware rotation for the RawUSB smooth-video build
unless you intentionally accept the slower JPEG path.

## Endpoint Notes

The firmware uses TinyUSB's vendor interface, normally:

- OUT: `0x01`;
- IN: `0x81`.

The RawUSB plugin probes OUT endpoints `0x01` to `0x04` and IN endpoints `0x81`
to `0x84` after failures, then remembers the working endpoint.

## Acceptance Checklist

Before calling production streaming good:

- SignalRGB RawUSB `Direct JPEG Max FPS` remains smooth.
- SignalRGB RawUSB balanced `Direct JPEG` remains smooth.
- NZXT-ESC/designer USB-direct JPEG preview remains smooth.
- No periodic hitch appears from Wi-Fi polling or telemetry redraw.
- No stutter appears while the app/server is running in the background.
- Device status packets still work when `Log Device Status` is enabled.
- Normal app telemetry display resumes after SignalRGB or designer streaming stops.
- `CAPP` USB app-state packets still update the display outside video streaming.
- Logo review touch actions still work outside video streaming.
- A full power cycle returns to normal production behavior.

## Developer Docs

SignalRGB plugin references:

- Plugin metadata exports: <https://docs.signalrgb.com/developer/plugins/plugin-exports/>
- Raw USB and serial communication: <https://docs.signalrgb.com/developer/plugins/advanced-communication/>
- User controls: <https://docs.signalrgb.com/developer/plugins/user-controls/>
- Device images: <https://docs.signalrgb.com/developer/plugins/device-images/>
