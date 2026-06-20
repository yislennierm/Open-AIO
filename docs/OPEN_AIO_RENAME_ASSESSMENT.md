# Open AIO Rename Assessment

Goal: user-facing project, firmware, driver, desktop app, and USB display names should become **Open AIO** without breaking the working RawUSB stream path, SignalRGB compatibility, or Electron/NZXT-ESC renderer flow.

## Rename Rule

Use **Open AIO** for user-visible names.

Keep stable protocol and compatibility identifiers unless we intentionally migrate them:

- USB VID/PID: keep `303A:4004` for the working RawUSB firmware.
- RawUSB packet magic: keep `SRGB`.
- Local API key: keep as configured.
- NZXT-ESC upstream/dist naming: do not globally rewrite upstream internal names. We adapt it, but it remains the NZXT-ESC UI codebase.
- Existing persisted storage prefixes such as `nzxt-esc-dev:` should stay unless a migration script is written.

## Already Open AIO

- `firmware/src/config.h` now uses `DEVICE_NAME "Open AIO"`.
- `windows/driver/open-aio-winusb.inf` shows `DeviceName="Open AIO"` for `VID_303A&PID_4004`.

## Safe Immediate Renames

These are display labels and docs. They should not change protocol behavior.

- Electron window/title/tray labels now use `Open AIO`.
- Electron package description now uses `Open AIO`.
- SignalRGB plugin user-visible names now use `Open AIO`.
- README/docs headings now use `Open AIO` where not describing legacy paths.
- Windows task display names should use `Open AIO` for new installs.
- Python logger names may use `open-aio-agent.*` later for logs only.

## Rename With Migration

These can break existing saved state or installed integrations if changed without a bridge.

- `DEVICE_ID` / `device_id` currently `cooler-display-01`.
  - Recommendation: keep it for now.
  - Later migration: support alias `open-aio-01` while still accepting `cooler-display-01` until all configs are updated.
- Electron app ID `com.cooler-display.electron`.
  - Recommendation: keep until packaging.
  - Later migration: packaged app should use something like `io.openaio.desktop`; it may create a new Windows app identity.
- Electron persistent partition `persist:cooler-display`.
  - Recommendation: keep for now so presets/storage remain visible.
  - Later migration: copy old partition data to `persist:open-aio` before switching.
- LocalStorage keys `cooler-display:electron` and `cooler-display:electron-renderer`.
  - Safe to rename only if the bridge reads both old and new keys.
- Folder/file names now use Open AIO naming where they are owned by this project.

## Do Not Rename Blindly

- `nzxt-esc-live/dist/**`
  - This is the adapted NZXT-ESC v6.05.11 build. Upstream labels, asset names, and storage prefixes are part of how presets and UI work.
- `nzxt-esc-gallery/**`
  - Preset metadata may say `NZXT-ESC-DEV`; this belongs to gallery import/export compatibility.
- Archived folders under `_archive_cleanup_*`.
- Logs and generated browser profiles under `logs/`.
- USB VID/PID `303A:4004`.
  - Changing this requires driver INF update, reinstall, SignalRGB plugin update, PC agent update, and firmware flash.

## Recommended Implementation Order

1. Add central brand constants for owned code:
- Electron: `APP_NAME = "Open AIO"`, `APP_ID = "com.openaio.desktop"` only when packaging is ready.
   - Python/server docs: `PROJECT_NAME = "Open AIO"` where needed.
   - Firmware: `DEVICE_NAME "Open AIO"`.
2. Apply safe display-label renames in Electron, SignalRGB, docs, and driver display strings.
3. Keep `device_id: cooler-display-01`, `persist:cooler-display`, and `com.cooler-display.electron` during the first rename pass.
4. Build/test:
   - Electron launches and starts one server plus one agent.
   - `http://127.0.0.1:8000/api/cam/status` is healthy.
   - SignalRGB still detects `303A:4004`.
   - Device Manager shows `Open AIO` for the RawUSB device.
   - USB frame stream remains `designer_preview` with `failed=0`.
5. Only after packaging, plan the second migration:
   - app ID / install directory / executable name,
   - persistent partition migration,
   - optional `device_id` alias.

## Current Best First Patch

Rename user-facing owned labels only:

- Electron title/tray/menu now uses `Open AIO`.
- SignalRGB visible names now use `Open AIO`.
- Firmware `DEVICE_NAME` now uses `Open AIO`.
- Docs/readme display references.

Do not change VID/PID, packet protocol, `device_id`, Electron partition, NZXT-ESC dist storage keys, or upstream gallery metadata in the first pass.
