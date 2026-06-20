# Lab Rebuild Baseline

Status: active baseline as of 2026-06-19.

Primary direction document: `docs/RAWUSB_NXZT_ESC.md`.

We are rebuilding from the lab firmware because the production/app-detector merge regressed display sync, touch review behavior, and preset/app state behavior.

Current firmware direction:

- Use the lab RawUSB stream path as the source of truth.
- Keep only boot animation plus lab stream playback for now.
- Do not build from the old production/app-detector path until it is rebuilt from this baseline.
- Keep SignalRGB/nxzt-esc video smoothness as the first priority.
- Keep the local USB identity: `VID_303A PID_4004`, product `Open AIO`.
- Do not impersonate NZXT CAM, Kraken, or `VID_1E71`.

Active PlatformIO target:

- `t-rgb-half-circle-rawusb`
- This target now defines `NZXT_ESC_TEST_FIRMWARE=1`.
- It runs `renderBootAnimation()` once, then enters the lean RawUSB stream loop.

Dropped experiment:

- The NZXT CAM spoof route is abandoned for the active product.
- `nxzt-esc` is a PC-side renderer/sensor UI that sends frames through the same RawUSB protocol as SignalRGB.

Legacy/non-working area:

- The non-test `#else` path in `firmware/src/main.cpp` is retained only as reference.
- Treat app detector, icon review touch, Wi-Fi polling, and production preset/app-state logic as legacy until rebuilt intentionally.

Do not flash or compile without explicit user confirmation.
