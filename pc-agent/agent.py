from __future__ import annotations

import json
import logging
import msvcrt
import os
import subprocess
import time
from datetime import datetime, UTC
from logging.handlers import RotatingFileHandler
from pathlib import Path
from typing import Any

import requests

from foreground_app import get_foreground_window_info
from telemetry import apply_external_sensors, collect_telemetry, get_last_cpu_source, get_last_gpu_source
from usb_transport import UsbStateSender

logger = logging.getLogger("open-aio-agent")
CREATE_NO_WINDOW = 0x08000000 if os.name == "nt" else 0
_LOCK_FILE = None
DESIGNER_PREVIEW_RELEASE_GRACE_SECONDS = 3.0
DESIGNER_PREVIEW_STATS_INTERVAL_SECONDS = 5.0
DIRECT_USB_OWNER_TTL_SECONDS = 4.0


class ProcessPresenceCache:
    def __init__(self, names: list[str], ttl_seconds: float = 5.0) -> None:
        self._names = {name.lower() for name in names}
        self._ttl_seconds = ttl_seconds
        self._checked_at = 0.0
        self._present = False

    def is_present(self) -> bool:
        if not self._names:
            return False
        now = time.monotonic()
        if now - self._checked_at < self._ttl_seconds:
            return self._present
        self._checked_at = now
        try:
            result = subprocess.run(
                ["tasklist", "/FO", "CSV", "/NH"],
                check=False,
                capture_output=True,
                text=True,
                timeout=2.0,
                creationflags=CREATE_NO_WINDOW,
            )
            output = result.stdout.lower()
            self._present = any(f'"{name}"' in output for name in self._names)
        except Exception:
            self._present = False
        return self._present


def configure_logging(config: dict[str, Any]) -> None:
    level_name = str(config.get("log_level", "INFO")).upper()
    level = getattr(logging, level_name, logging.INFO)
    formatter = logging.Formatter("%(asctime)s %(levelname)s %(message)s")

    root = logging.getLogger()
    root.setLevel(level)
    root.handlers.clear()

    console = logging.StreamHandler()
    console.setFormatter(formatter)
    root.addHandler(console)

    log_file = config.get("log_file", "logs/agent.log")
    if log_file:
        path = Path(str(log_file))
        if not path.is_absolute():
            path = Path(__file__).resolve().parent / path
        path.parent.mkdir(parents=True, exist_ok=True)
        file_handler = RotatingFileHandler(path, maxBytes=512 * 1024, backupCount=3, encoding="utf-8")
        file_handler.setFormatter(formatter)
        root.addHandler(file_handler)


def load_config() -> dict[str, Any]:
    base = Path(__file__).resolve().parent
    path = base / "config.json"
    if not path.exists():
        path = base / "config.example.json"
    return json.loads(path.read_text(encoding="utf-8"))


def resolve_agent_path(path_value: str | None, default_name: str) -> Path:
    base = Path(__file__).resolve().parent
    raw = path_value or f"logs/{default_name}"
    path = Path(str(raw))
    if not path.is_absolute():
        path = base / path
    path.parent.mkdir(parents=True, exist_ok=True)
    return path


def write_status(path: Path, status: dict[str, Any]) -> None:
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(status, indent=2, sort_keys=True), encoding="utf-8")
    tmp.replace(path)


def post_review_decision(
    session: requests.Session,
    server_url: str,
    headers: dict[str, str],
    action: str,
    state: dict[str, Any],
) -> bool:
    process_name = str(state.get("review_process_name") or "")
    app_id = str(state.get("review_app_id") or "")
    if not process_name:
        return False
    endpoint = "approve-candidate" if action == "approve" else "reject-candidate"
    payload: dict[str, str] = {"process_name": process_name}
    if app_id:
        payload["app_id"] = app_id
    response = session.post(
        f"{server_url}/api/v1/apps/{endpoint}",
        json=payload,
        headers=headers,
        timeout=2.0,
    )
    response.raise_for_status()
    logger.info("review %s process=%s app=%s", action, process_name, app_id)
    return True


def fetch_designer_frame(
    session: requests.Session,
    server_url: str,
    headers: dict[str, str],
    last_sequence: int,
    timeout: float = 0.25,
) -> tuple[int, bytes | None, bool]:
    response = session.get(
        f"{server_url}/api/v1/designer/frame",
        params={"since": last_sequence},
        headers=headers,
        timeout=timeout,
    )
    active = response.headers.get("X-Designer-Preview-Active") == "1"
    if response.status_code == 204:
        return last_sequence, None, active
    response.raise_for_status()
    sequence_header = response.headers.get("X-Frame-Sequence")
    sequence = int(sequence_header) if sequence_header else last_sequence + 1
    return sequence, response.content, True


def process_usb_review_events(
    usb_sender: UsbStateSender,
    session: requests.Session,
    server_url: str,
    headers: dict[str, str],
    review_state: dict[str, Any] | None,
    status: dict[str, Any],
) -> dict[str, Any] | None:
    review_actions, touch_events = usb_sender.read_review_usb_events()
    for touch in touch_events:
        logger.info(
            "review touch diagnostic result=%s raw=%d,%d logical=%d,%d candidate=%s",
            touch.result,
            touch.raw_x,
            touch.raw_y,
            touch.logical_x,
            touch.logical_y,
            str((review_state or {}).get("review_process_name") or ""),
        )
        status["review_touch"] = touch.result
    for review_action in review_actions:
        if not review_state:
            logger.warning("review %s ignored: no USB review candidate", review_action)
            status["review_error"] = "no USB review candidate"
            continue
        try:
            if post_review_decision(session, server_url, headers, review_action, review_state):
                status["review_action"] = review_action
                review_state = None
        except requests.RequestException as exc:
            logger.warning("review %s failed: %s", review_action, exc)
            status["review_error"] = str(exc)
    return review_state


def extract_review_state(state: dict[str, Any] | None) -> dict[str, Any] | None:
    if not state or not state.get("review_available"):
        return None
    process_name = str(state.get("review_process_name") or "")
    if not process_name:
        return None
    return {
        "review_process_name": process_name,
        "review_app_id": str(state.get("review_app_id") or ""),
        "review_display_name": str(state.get("review_display_name") or ""),
        "review_status": str(state.get("review_status") or ""),
    }


def write_designer_preview_status(
    status_path: Path,
    config: dict[str, Any],
    device_id: str,
    server_url: str,
    session: requests.Session,
    telemetry_url: str,
    headers: dict[str, str],
    usb_sender: UsbStateSender,
) -> None:
    try:
        active_process, active_window_title = get_foreground_window_info()
    except Exception:
        active_process, active_window_title = "unknown.exe", ""
    telemetry = apply_external_sensors(collect_telemetry(), config)
    payload = {"active_process": active_process, "active_window_title": active_window_title, **telemetry}
    response = session.post(telemetry_url, json=payload, headers=headers, timeout=2.0)
    response.raise_for_status()
    write_status(
        status_path,
        {
            "ok": True,
            "agent_pid": os.getpid(),
            "updated_at": datetime.now(tz=UTC).isoformat(),
            "device_id": device_id,
            "server_url": server_url,
            "server_status": "ok",
            "http_status": response.status_code,
            "usb_status": "designer_preview",
            "usb_error": usb_sender.last_error,
            "transport_mode": str(config.get("transport_mode", "auto")),
            "active_process": active_process,
            "active_window_title": active_window_title,
            "cpu_temp": payload.get("cpu_temp"),
            "gpu_temp": payload.get("gpu_temp"),
            "gpu_load": payload.get("gpu_load"),
            "ram_used_percent": payload.get("ram_used_percent"),
            "cpu_source": get_last_cpu_source(),
            "gpu_source": get_last_gpu_source(),
            "message": "designer preview owns USB; telemetry still live",
        },
    )


def write_direct_renderer_status(
    status_path: Path,
    config: dict[str, Any],
    device_id: str,
    server_url: str,
) -> None:
    try:
        active_process, active_window_title = get_foreground_window_info()
    except Exception:
        active_process, active_window_title = "unknown.exe", ""
    write_status(
        status_path,
        {
            "ok": True,
            "agent_pid": os.getpid(),
            "updated_at": datetime.now(tz=UTC).isoformat(),
            "device_id": device_id,
            "server_url": server_url,
            "server_status": "ok",
            "http_status": 200,
            "usb_status": "owned_by_designer_renderer",
            "usb_error": None,
            "transport_mode": str(config.get("transport_mode", "auto")),
            "active_process": active_process,
            "active_window_title": active_window_title,
            "message": "designer renderer owns USB for direct preview",
        },
    )


class DirectUsbOwner:
    def __init__(self) -> None:
        self._path = Path(__file__).resolve().parent / "logs" / "designer-usb-owner.json"

    def is_active(self) -> bool:
        try:
            payload = json.loads(self._path.read_text(encoding="utf-8"))
            updated_at = float(payload.get("updated_at") or 0.0)
            ttl = float(payload.get("ttl_seconds") or DIRECT_USB_OWNER_TTL_SECONDS)
        except (OSError, ValueError, TypeError, json.JSONDecodeError):
            return False
        return time.time() - updated_at <= max(1.0, ttl)


class DesignerPreviewStats:
    def __init__(self) -> None:
        self.reset(time.monotonic())

    def reset(self, now: float) -> None:
        self.started_at = now
        self.sent = 0
        self.failed = 0
        self.bytes_sent = 0
        self.write_seconds = 0.0

    def record(self, frame: bytes, ok: bool, write_seconds: float) -> None:
        if ok:
            self.sent += 1
            self.bytes_sent += len(frame)
            self.write_seconds += write_seconds
        else:
            self.failed += 1

    def maybe_log(self, now: float, usb_sender: UsbStateSender) -> None:
        elapsed = now - self.started_at
        if elapsed < DESIGNER_PREVIEW_STATS_INTERVAL_SECONDS:
            return
        total = self.sent + self.failed
        sent_fps = self.sent / elapsed if elapsed > 0 else 0.0
        avg_kb = (self.bytes_sent / self.sent / 1024.0) if self.sent else 0.0
        avg_write_ms = (self.write_seconds / self.sent * 1000.0) if self.sent else 0.0
        logger.info(
            "designer preview usb stats sent=%d failed=%d total=%d sent_fps=%.2f avg_jpeg_kb=%.1f avg_usb_write_ms=%.1f status=%s error=%s",
            self.sent,
            self.failed,
            total,
            sent_fps,
            avg_kb,
            avg_write_ms,
            usb_sender.last_status,
            usb_sender.last_error,
        )
        self.reset(now)


def acquire_single_instance_lock() -> bool:
    global _LOCK_FILE
    lock_path = Path(__file__).resolve().parent / "logs" / "agent.lock"
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    _LOCK_FILE = lock_path.open("a+b")
    try:
        _LOCK_FILE.seek(0)
        msvcrt.locking(_LOCK_FILE.fileno(), msvcrt.LK_NBLCK, 1)
    except OSError:
        _LOCK_FILE.close()
        _LOCK_FILE = None
        return False
    _LOCK_FILE.seek(0)
    _LOCK_FILE.truncate()
    _LOCK_FILE.write(str(os.getpid()).encode("ascii"))
    _LOCK_FILE.flush()
    return True


def run_agent() -> None:
    config = load_config()
    configure_logging(config)
    status_path = resolve_agent_path(config.get("status_file"), "status.json")
    if not acquire_single_instance_lock():
        logger.warning("another agent instance is already running; exiting")
        write_status(
            status_path,
            {
                "ok": False,
                "agent_pid": os.getpid(),
                "updated_at": datetime.now(tz=UTC).isoformat(),
                "server_status": "not_started",
                "usb_status": "duplicate_agent",
                "transport_mode": str(config.get("transport_mode", "auto")),
                "message": "another agent instance is already running",
            },
        )
        return
    server_url = str(config["server_url"]).rstrip("/")
    device_id = str(config["device_id"])
    api_key = str(config["api_key"])
    interval = max(0.2, float(config.get("poll_interval_seconds", 1)))
    transport_mode = str(config.get("transport_mode", "auto")).strip().lower()
    if transport_mode not in {"auto", "usb_only", "wifi_only"}:
        transport_mode = "auto"
    url = f"{server_url}/api/v1/device/{device_id}/telemetry"
    state_url = f"{server_url}/api/v1/device/{device_id}/state"
    headers = {"X-API-Key": api_key}
    usb_sender = UsbStateSender()
    usb_owner_processes = [
        str(name)
        for name in config.get("usb_skip_when_processes_running", ["SignalRgb.exe"])
        if str(name).strip()
    ]
    usb_owner_cache = ProcessPresenceCache(usb_owner_processes)
    direct_usb_owner = DirectUsbOwner()

    logger.info("starting agent device=%s server=%s interval=%.2fs transport=%s", device_id, server_url, interval, transport_mode)
    session = requests.Session()
    last_usb_review_state: dict[str, Any] | None = None
    last_usb_review_state_at = 0.0
    last_designer_frame_sequence = 0
    last_designer_frame: bytes | None = None
    last_designer_frame_sent_at = 0.0
    designer_preview_stats = DesignerPreviewStats()

    while True:
        if transport_mode != "wifi_only" and direct_usb_owner.is_active():
            usb_sender.close()
            usb_sender.last_status = "owned_by_designer_renderer"
            usb_sender.last_error = None
            try:
                active_process, active_window_title = get_foreground_window_info()
            except Exception:
                active_process, active_window_title = "unknown.exe", ""
            try:
                telemetry = apply_external_sensors(collect_telemetry(), config)
                payload = {"active_process": active_process, "active_window_title": active_window_title, **telemetry}
                response = session.post(url, json=payload, headers=headers, timeout=2.0)
                response.raise_for_status()
                write_status(
                    status_path,
                    {
                        "ok": True,
                        "agent_pid": os.getpid(),
                        "updated_at": datetime.now(tz=UTC).isoformat(),
                        "device_id": device_id,
                        "server_url": server_url,
                        "server_status": "ok",
                        "http_status": response.status_code,
                        "usb_status": "owned_by_designer_renderer",
                        "usb_error": None,
                        "transport_mode": transport_mode,
                        "active_process": active_process,
                        "active_window_title": active_window_title,
                        "cpu_temp": payload.get("cpu_temp"),
                        "gpu_temp": payload.get("gpu_temp"),
                        "gpu_load": payload.get("gpu_load"),
                        "ram_used_percent": payload.get("ram_used_percent"),
                        "cpu_source": get_last_cpu_source(),
                        "gpu_source": get_last_gpu_source(),
                        "message": "designer renderer owns USB for direct preview",
                    },
                )
            except (OSError, requests.RequestException) as exc:
                logger.warning("direct renderer handoff status failed: %s", exc)
            time.sleep(0.5)
            continue

        if transport_mode != "wifi_only" and not usb_owner_cache.is_present():
            try:
                last_designer_frame_sequence, designer_frame, designer_active = fetch_designer_frame(
                    session,
                    server_url,
                    headers,
                    last_designer_frame_sequence,
                    timeout=0.2,
                )
            except requests.RequestException:
                designer_frame = None
                designer_active = False

            if designer_frame is not None:
                last_designer_frame = designer_frame
                usb_ok = usb_sender.send_signalrgb_jpeg(designer_frame)
                designer_preview_stats.record(designer_frame, usb_ok, usb_sender.last_write_seconds)
                designer_preview_stats.maybe_log(time.monotonic(), usb_sender)
                if usb_ok:
                    last_designer_frame_sent_at = time.monotonic()

            if designer_active:
                logger.info("designer preview active; keeping telemetry live while preview owns USB")
                last_status_write_at = 0.0
                designer_inactive_since: float | None = None
                while transport_mode != "wifi_only" and not usb_owner_cache.is_present():
                    now = time.monotonic()
                    if direct_usb_owner.is_active():
                        usb_sender.close()
                        usb_sender.last_status = "owned_by_designer_renderer"
                        usb_sender.last_error = None
                        if now - last_status_write_at >= 1.0:
                            try:
                                active_process, active_window_title = get_foreground_window_info()
                                telemetry = apply_external_sensors(collect_telemetry(), config)
                                payload = {"active_process": active_process, "active_window_title": active_window_title, **telemetry}
                                response = session.post(url, json=payload, headers=headers, timeout=2.0)
                                response.raise_for_status()
                                write_status(
                                    status_path,
                                    {
                                        "ok": True,
                                        "agent_pid": os.getpid(),
                                        "updated_at": datetime.now(tz=UTC).isoformat(),
                                        "device_id": device_id,
                                        "server_url": server_url,
                                        "server_status": "ok",
                                        "http_status": response.status_code,
                                        "usb_status": "owned_by_designer_renderer",
                                        "usb_error": None,
                                        "transport_mode": transport_mode,
                                        "active_process": active_process,
                                        "active_window_title": active_window_title,
                                        "cpu_temp": payload.get("cpu_temp"),
                                        "gpu_temp": payload.get("gpu_temp"),
                                        "gpu_load": payload.get("gpu_load"),
                                        "ram_used_percent": payload.get("ram_used_percent"),
                                        "cpu_source": get_last_cpu_source(),
                                        "gpu_source": get_last_gpu_source(),
                                        "message": "designer renderer owns USB for direct preview",
                                    },
                                )
                            except OSError as exc:
                                logger.warning("status write failed: %s", exc)
                            except requests.RequestException as exc:
                                logger.warning("direct renderer telemetry post failed: %s", exc)
                            last_status_write_at = now
                        time.sleep(0.2)
                        continue
                    if now - last_status_write_at >= 1.0:
                        try:
                            write_designer_preview_status(status_path, config, device_id, server_url, session, url, headers, usb_sender)
                        except OSError as exc:
                            logger.warning("status write failed: %s", exc)
                        last_status_write_at = now
                    designer_preview_stats.maybe_log(now, usb_sender)
                    try:
                        last_designer_frame_sequence, designer_frame, designer_active = fetch_designer_frame(
                            session,
                            server_url,
                            headers,
                            last_designer_frame_sequence,
                            timeout=0.15,
                        )
                        if designer_frame is not None:
                            last_designer_frame = designer_frame
                            usb_ok = usb_sender.send_signalrgb_jpeg(designer_frame)
                            designer_preview_stats.record(designer_frame, usb_ok, usb_sender.last_write_seconds)
                            if usb_ok:
                                last_designer_frame_sent_at = time.monotonic()
                            designer_inactive_since = None
                        elif designer_active:
                            designer_inactive_since = None
                        else:
                            if designer_inactive_since is None:
                                designer_inactive_since = time.monotonic()
                            if time.monotonic() - designer_inactive_since >= DESIGNER_PREVIEW_RELEASE_GRACE_SECONDS:
                                break
                    except requests.RequestException:
                        time.sleep(0.1)
                    time.sleep(0.005)
                logger.info("designer preview released; resuming telemetry")
                last_designer_frame = None
                last_designer_frame_sent_at = 0.0
                continue

        active_process, active_window_title = get_foreground_window_info()
        telemetry = apply_external_sensors(collect_telemetry(), config)
        payload = {"active_process": active_process, "active_window_title": active_window_title, **telemetry}
        status: dict[str, Any] = {
            "ok": False,
            "agent_pid": os.getpid(),
            "updated_at": datetime.now(tz=UTC).isoformat(),
            "device_id": device_id,
            "server_url": server_url,
            "server_status": "unknown",
            "http_status": None,
            "usb_status": "disabled" if transport_mode == "wifi_only" else "unknown",
            "usb_error": None,
            "transport_mode": transport_mode,
            "active_process": active_process,
            "active_window_title": active_window_title,
            "cpu_temp": payload.get("cpu_temp"),
            "gpu_temp": payload.get("gpu_temp"),
            "gpu_load": payload.get("gpu_load"),
            "ram_used_percent": payload.get("ram_used_percent"),
            "cpu_source": get_last_cpu_source(),
            "gpu_source": get_last_gpu_source(),
        }
        try:
            response = session.post(url, json=payload, headers=headers, timeout=2.0)
            response.raise_for_status()
            status["ok"] = True
            status["server_status"] = "ok"
            status["http_status"] = response.status_code
            usb_ok = False
            try:
                state_payload: dict[str, Any] | None = None
                if transport_mode == "wifi_only":
                    usb_sender.close()
                    usb_sender.last_status = "disabled"
                    usb_sender.last_error = None
                elif usb_owner_cache.is_present():
                    usb_sender.close()
                    usb_sender.last_status = "owned_by_signalrgb"
                    usb_sender.last_error = None
                else:
                    designer_frame: bytes | None = None
                    designer_active = False
                    try:
                        last_designer_frame_sequence, designer_frame, designer_active = fetch_designer_frame(
                            session,
                            server_url,
                            headers,
                            last_designer_frame_sequence,
                        )
                    except requests.RequestException:
                        designer_frame = None
                        designer_active = False
                    if designer_frame is not None:
                        last_designer_frame = designer_frame
                        usb_ok = usb_sender.send_signalrgb_jpeg(designer_frame)
                        designer_preview_stats.record(designer_frame, usb_ok, usb_sender.last_write_seconds)
                        designer_preview_stats.maybe_log(time.monotonic(), usb_sender)
                        if usb_ok:
                            last_designer_frame_sent_at = time.monotonic()
                            usb_sender.last_status = "designer_preview"
                        state_payload = None
                    elif designer_active:
                        usb_sender.last_status = "designer_preview"
                        usb_sender.last_error = None
                        state_payload = None
                    else:
                        last_designer_frame = None
                        last_designer_frame_sent_at = 0.0
                        state_payload = None
                    if designer_frame is None and not designer_active:
                        if last_usb_review_state and time.monotonic() - last_usb_review_state_at >= 30.0:
                            last_usb_review_state = None
                        if last_usb_review_state:
                            last_usb_review_state = process_usb_review_events(
                                usb_sender,
                                session,
                                server_url,
                                headers,
                                last_usb_review_state,
                                status,
                            )

                        state_response = session.get(state_url, headers=headers, timeout=1.0)
                        state_response.raise_for_status()
                        state_payload = state_response.json()
                        usb_ok = usb_sender.send_state(state_payload)
                        if usb_ok:
                            next_review_state = extract_review_state(state_payload)
                            if next_review_state:
                                last_usb_review_state = next_review_state
                                last_usb_review_state_at = time.monotonic()
                            else:
                                last_usb_review_state = None
                        last_usb_review_state = process_usb_review_events(
                            usb_sender,
                            session,
                            server_url,
                            headers,
                            extract_review_state(state_payload) or last_usb_review_state,
                            status,
                        )
            except requests.RequestException:
                usb_sender.last_status = "state_fetch_failed"
                usb_sender.last_error = "server state request failed"
            status["usb_status"] = "ok" if usb_ok else usb_sender.last_status
            status["usb_error"] = usb_sender.last_error
            logger.info(
                "posted process=%s title=%r status=%s usb=%s cpu_temp=%s gpu_temp=%s gpu_load=%s ram=%.1f cpu_source=%s gpu_source=%s",
                active_process,
                active_window_title,
                response.status_code,
                status["usb_status"],
                payload.get("cpu_temp"),
                payload.get("gpu_temp"),
                payload.get("gpu_load"),
                payload["ram_used_percent"],
                get_last_cpu_source(),
                get_last_gpu_source(),
            )
        except requests.RequestException as exc:
            status["ok"] = False
            status["server_status"] = "post_failed"
            status["message"] = str(exc)
            logger.warning("post failed: %s", exc)
        try:
            write_status(status_path, status)
        except OSError as exc:
            logger.warning("status write failed: %s", exc)
        sleep_until = time.monotonic() + interval
        while True:
            remaining = sleep_until - time.monotonic()
            if remaining <= 0:
                break
            if not last_usb_review_state or transport_mode == "wifi_only" or usb_owner_cache.is_present():
                if transport_mode == "wifi_only" or usb_owner_cache.is_present():
                    time.sleep(remaining)
                    break
                try:
                    last_designer_frame_sequence, designer_frame, designer_active = fetch_designer_frame(
                        session,
                        server_url,
                        headers,
                        last_designer_frame_sequence,
                        timeout=min(0.2, max(0.05, remaining)),
                    )
                    if designer_frame is not None:
                        last_designer_frame = designer_frame
                        usb_ok = usb_sender.send_signalrgb_jpeg(designer_frame)
                        designer_preview_stats.record(designer_frame, usb_ok, usb_sender.last_write_seconds)
                        designer_preview_stats.maybe_log(time.monotonic(), usb_sender)
                        if usb_ok:
                            last_designer_frame_sent_at = time.monotonic()
                            status["usb_status"] = "designer_preview"
                            status["usb_error"] = None
                            try:
                                write_status(status_path, status)
                            except OSError:
                                pass
                        time.sleep(min(0.005, max(0.0, remaining)))
                        continue
                    if designer_active:
                        status["usb_status"] = "designer_preview"
                        status["usb_error"] = None
                        try:
                            write_status(status_path, status)
                        except OSError:
                            pass
                        time.sleep(min(0.08, remaining))
                        continue
                    last_designer_frame = None
                    last_designer_frame_sent_at = 0.0
                except requests.RequestException:
                    pass
                time.sleep(min(0.08, remaining))
                continue
            try:
                last_usb_review_state = process_usb_review_events(
                    usb_sender,
                    session,
                    server_url,
                    headers,
                    last_usb_review_state,
                    status,
                )
            except requests.RequestException as exc:
                logger.warning("review event drain failed: %s", exc)
                break
            time.sleep(min(0.1, max(0.02, remaining)))


if __name__ == "__main__":
    run_agent()
