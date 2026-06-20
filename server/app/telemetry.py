from __future__ import annotations

from datetime import UTC, datetime

from .assets import UNKNOWN_APP_ID, has_app_manifest, normalize_process_name, process_to_app_id
from .config import SETTINGS
from .icon_resolver import discover_or_queue_app
from .models import TelemetryRecord, TelemetryRequest
from .web_logos import try_web_logo


_latest_by_device: dict[str, TelemetryRecord] = {}
UNKNOWN_PROCESS_GRACE_SECONDS = 20.0


def _is_file_explorer_window(process_name: str, window_title: str) -> bool:
    title = window_title.strip().lower()
    if process_name != "explorer.exe" or not title:
        return False
    return title not in {"program manager", "start", "search"}


def _app_id_from_window_context(process_name: str, window_title: str) -> str | None:
    title = window_title.strip().lower()
    if not title:
        return None
    if process_name == "applicationframehost.exe" and "media player" in title:
        return "media-player"
    if process_name == "windowsterminal.exe":
        if "command prompt" in title or title == "cmd" or title.startswith("cmd "):
            return "command-prompt"
        if "powershell" in title or "windows powershell" in title:
            return "powershell"
    return None


def update_telemetry(device_id: str, payload: TelemetryRequest) -> TelemetryRecord:
    now = datetime.now(tz=UTC)
    previous = _latest_by_device.get(device_id)
    process_name = normalize_process_name(payload.active_process)
    app_id = process_to_app_id(payload.active_process)
    contextual_app_id = _app_id_from_window_context(process_name, payload.active_window_title)
    if contextual_app_id is not None:
        app_id = contextual_app_id
    elif _is_file_explorer_window(process_name, payload.active_window_title):
        app_id = "file-explorer"
    if (
        process_name in {"unknown", "unknown.exe"}
        and previous is not None
        and previous.app_id != SETTINGS.default_app_id
        and (now - previous.updated_at).total_seconds() <= UNKNOWN_PROCESS_GRACE_SECONDS
    ):
        app_id = previous.app_id
    if app_id == SETTINGS.default_app_id:
        if process_name in {"unknown", "unknown.exe"}:
            app_id = SETTINGS.default_app_id
        else:
            app_id = discover_or_queue_app(payload.active_process) or UNKNOWN_APP_ID
    elif not has_app_manifest(app_id):
        discovered = discover_or_queue_app(payload.active_process)
        if discovered is not None:
            app_id = discovered
        if not has_app_manifest(app_id):
            try:
                try_web_logo(process_name)
            except ValueError:
                pass
    record = TelemetryRecord(
        **payload.model_dump(),
        device_id=device_id,
        app_id=app_id,
        updated_at=now,
    )
    _latest_by_device[device_id] = record
    return record


def get_latest(device_id: str) -> TelemetryRecord:
    record = _latest_by_device.get(device_id)
    if record is not None:
        return record
    return TelemetryRecord(
        device_id=device_id,
        active_process="unknown.exe",
        app_id="default",
        cpu_temp=None,
        gpu_temp=None,
        cpu_load=0.0,
        gpu_load=None,
        ram_used_percent=0.0,
        ram_total_mb=None,
        ssd_temp=None,
        updated_at=datetime.now(tz=UTC),
    )
