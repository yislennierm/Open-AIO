# Codebase Cleanup Map

## Active Runtime

- `firmware/` - ESP32-S3 LilyGO T-RGB firmware. Keep RawUSB frame streaming compatible with SignalRGB and the Electron renderer.
- `server/` - FastAPI server. Serves `nzxt-esc-live/dist`, gallery media, sensor/CAM shim APIs, preset storage, preview thumbnails, and the designer frame queue.
- `pc-agent/agent.py` - Current PC agent. Collects sensors and forwards Electron designer frames to the device over RawUSB.
- `electron-app/` - Current supported NZXT-ESC desktop renderer and launcher. It owns the visible editor window, hidden 480x480 render window, thumbnail capture, frame posting, and starts the FastAPI server / PC agent when they are not already healthy.
- Stream orientation/color inversion is handled in Electron's hidden render window through the tray `Stream Transform` menu. Do not invert in firmware unless the raw device protocol itself changes.
- `nzxt-esc-live/dist/` - Served NZXT-ESC v6.05.11 runtime with local bridge patches.
- `nzxt-esc-gallery/` - Preset source cloned from the gallery repo.
- `signalrgb/` - SignalRGB plugins, especially the RawUSB plugin.
- `drivers/open-aio-winusb/` - WinUSB driver files for the real RawUSB device ID.
- `scripts/start_electron.ps1` - Preferred launcher. Starts Electron, which then checks/starts the server and PC agent.
- `scripts/run_server.ps1`, `scripts/run_agent.ps1`, `scripts/setup_windows.ps1`, and RawUSB driver repair scripts - Keep for setup, repair, and direct debugging.

## Preferred Launch Flow

1. Start `scripts/start_electron.ps1`.
2. Electron checks `http://127.0.0.1:8000/api/cam/status`.
3. If the server is missing, Electron starts `server/.venv/Scripts/python.exe -m uvicorn app.main:app --host 0.0.0.0 --port 8000`.
4. If the PC agent is not healthy, Electron starts `pc-agent/.venv/Scripts/python.exe agent.py`.
5. Electron opens the NZXT-ESC editor and keeps one hidden 480x480 renderer posting frames to the server.
6. The PC agent sends those frames to the device over the same RawUSB path SignalRGB uses.

Electron only stops backend processes that Electron started itself. It does not kill a manually started server or agent.

## Archived In `_archive_cleanup_20260620-120632`

- `_unused_esc_copies/` - duplicate and experimental ESC copies.
- `drivers/nzxt-spoof-winusb/` - CAM spoofing route; intentionally dropped.
- `nzxt-esc/`, `nzxt-esc-upstream/` - confusing local Git dirs. Recreate cleanly when setting up the long-term fork/upstream flow.
- `pc-agent/designer_renderer.py`, `pc-agent/direct_media_renderer.py`, `pc-agent/sensor_cache_bridge.py` - legacy Python/Playwright/direct render paths. Electron is the supported path.
- `desktop-app/stream_supervisor.py` - legacy supervisor for the old Python renderer.
- old sensor-bridge/direct-render scripts - archived to reduce launcher confusion.

`sensor-bridge/` was left in place because Windows had a locked build output. Treat it as inactive unless we intentionally revive that path.

## Removed

- Root `tmp_*` screenshots, HTML probes, and render-debug images.

## NZXT-ESC Update Plan

1. Recreate a clean `nzxt-esc-upstream/` clone from `mrgogo7/nzxt-esc` when we are ready to formalize updates.
2. Track our local changes as a small patch set or fork branch, not as manual edits scattered across duplicate dist folders.
3. Build or copy the supported runtime into `nzxt-esc-live/dist/`; the server only mounts this folder.
4. Keep `nzxt-esc-gallery/` as a clean preset source. Preset updates should be a simple `git pull` plus server cache refresh.
5. Preserve the device contract: ESC renders on the PC, Electron captures 480x480 frames, the server queues frames, `pc-agent` sends RawUSB, and firmware receives the same `SRGB` frame protocol SignalRGB uses.
