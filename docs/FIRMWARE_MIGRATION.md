# Firmware Migration Notes

This file is the source of truth for keeping the smooth lab/test video path while preserving the production app detector, boot animation, icons, and HTTP/NZXT behavior.

## Firmware targets

- Production RawUSB target: `t-rgb-half-circle-rawusb`
- Lab/test target: `t-rgb-nzxt-esc-test`

The lab/test target is intentionally minimal. It boots straight into the RawUSB video receiver so SignalRGB playback can be tested without production app polling, Wi-Fi, boot animation, app detector rendering, or icon work in the loop.

The production RawUSB target must not use the lab/test boot path. Production must run:

- `initAssetStore()`
- `initDisplay()`
- `renderBootAnimation()`
- `connectWiFi()`
- normal app polling/rendering when no SignalRGB video stream is active

## Smooth video invariants

These settings are the video performance work that came from the lab/test firmware and must remain enabled in production RawUSB:

- `SIGNALRGB_RAWUSB_EXPERIMENT=1`
- `SIGNALRGB_VIDEO_FAST_PATH=1`
- `HAS_LILYGO_PANEL_FRAMEBUFFER=1`
- `DISPLAY_ROTATE_180=0` while the fast path is enabled
- `SIGNALRGB_DIRECT_FRAMEBUFFER=1` while the fast path is enabled
- `SIGNALRGB_DIRECT_JPEG_FRAMEBUFFER_DECODE=1` while the fast path is enabled
- `SIGNALRGB_FPS_OVERLAY=0`
- `SIGNALRGB_SERIAL_BAUD=4000000`
- RawUSB RX buffer size: `131072`
- SignalRGB payload buffer size: `131072`

For full-screen 480x480 JPEG frames, `drawSignalJpegFrame()` must decode directly into the LilyGo panel framebuffer. That avoids the old slow path where frames were decoded into an intermediate buffer and then copied/flushed again.

## Production loop rule

Production RawUSB must process USB video first. If a SignalRGB frame or payload is currently active, it must immediately enter the fast stream branch:

- `processSignalRgbStream(rawUsb)`
- if `signalRgbActive()`: `suspendWiFi()`, `delay(0)`, and `return`

That branch must not do app polling, HTTP, serial fallback work, boot/app rendering, review touch work, overlays, or extra frame delays while video is active. This is the critical separation that keeps smooth playback from the lab/test firmware.

When no SignalRGB stream is active, production must continue with the app detector path:

- USB app-state handling
- serial fallback handling
- Wi-Fi resume
- HTTP app polling
- asset/icon cache updates
- `renderDisplay()`

## What changed on 2026-06-18

The production RawUSB setup had accidentally been included in the lab/test early-boot branch. That broke the original production behavior because `initAssetStore()`, `renderBootAnimation()`, `connectWiFi()`, and the app detector/icon path were bypassed.

The fix is:

- only `NZXT_ESC_TEST_FIRMWARE` uses the lean test setup and unconditional RawUSB loop
- production RawUSB uses the normal production setup
- production RawUSB uses the fast video branch only while `signalRgbActive()` is true

## Verification checklist

Before flashing production RawUSB:

1. Build `t-rgb-half-circle-rawusb`.
2. Build `t-rgb-nzxt-esc-test`.
3. Confirm production setup contains `initAssetStore()`, `renderBootAnimation()`, and `connectWiFi()`.
4. Confirm production loop has no unconditional `SIGNALRGB_VIDEO_FAST_PATH` return before app handling.
5. Confirm active SignalRGB video takes the fast branch with `suspendWiFi()`, `delay(0)`, and `return`.
6. Confirm `drawSignalJpegFrame()` uses direct framebuffer decode for 480x480 JPEG frames when the fast path is enabled.

