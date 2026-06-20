from __future__ import annotations

import json
import msvcrt
import os
import subprocess
import sys
import threading
import time
import webbrowser
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import psutil
import pystray
import requests
from PIL import Image, ImageDraw
from pystray import Menu, MenuItem


ROOT = Path(__file__).resolve().parents[1]
SERVER_DIR = ROOT / "server"
AGENT_DIR = ROOT / "pc-agent"
DESKTOP_DIR = ROOT / "desktop-app"
LOG_DIR = ROOT / "logs"
SERVER_PYTHON = SERVER_DIR / ".venv" / "Scripts" / "python.exe"
AGENT_PYTHON = AGENT_DIR / ".venv" / "Scripts" / "python.exe"
AGENT_PYTHONW = AGENT_DIR / ".venv" / "Scripts" / "pythonw.exe"
SENSOR_BRIDGE_EXE = ROOT / "sensor-bridge" / "bin" / "Release" / "net10.0" / "SensorBridge.exe"
SENSOR_OUTPUT = AGENT_DIR / "logs" / "native_sensors.json"
SERVER_CONFIG = SERVER_DIR / "config.json"
AGENT_CONFIG = AGENT_DIR / "config.json"
AGENT_STATUS = AGENT_DIR / "logs" / "status.json"
DESIGNER_FRAME_PROOF = AGENT_DIR / "logs" / "designer_last_sent.jpg"
STREAM_SUPERVISOR = DESKTOP_DIR / "stream_supervisor.py"
ELECTRON_DIR = ROOT / "electron-app"
ELECTRON_EXE = ELECTRON_DIR / "node_modules" / "electron" / "dist" / "electron.exe"
SERVER_URL = "http://127.0.0.1:8000"
SENSOR_TASK_NAME = "Open AIO Sensor Bridge"
RENDERER_FPS = "30"
RENDERER_QUALITY = "18"
RENDERER_STALE_SECONDS = 5.0
CREATE_NO_WINDOW = 0x08000000 if os.name == "nt" else 0
_LOCK_FILE = None
STREAM_ONLY_MODE = True
EDGE_PATHS = (
    Path(r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe"),
    Path(r"C:\Program Files\Microsoft\Edge\Application\msedge.exe"),
)


@dataclass
class RuntimeStatus:
    server_running: bool = False
    agent_running: bool = False
    server_health: bool = False
    sensor_bridge_running: bool = False
    sensor_task_installed: bool = False
    renderer_running: bool = False
    designer_preview_active: bool = False
    renderer_frame_age_seconds: float | None = None
    signalrgb_running: bool = False
    usb_device: str = "unknown"
    agent_status: str = "unknown"
    transport_mode: str = "auto"
    active_process: str = ""
    updated_at: str = ""

    @property
    def color(self) -> str:
        if not self.server_running and not self.agent_running:
            return "red"
        if self.usb_owned_by_signalrgb:
            return "purple"
        if self.renderer_running and self.agent_status in {"designer_preview", "owned_by_designer_renderer"}:
            return "green" if self.designer_preview_active else "yellow"
        if self.renderer_running and self.agent_status == "owned_by_designer_renderer":
            age = self.renderer_frame_age_seconds
            return "green" if age is not None and age <= RENDERER_STALE_SECONDS else "yellow"
        if self.server_health and self.agent_running and self.agent_status == "ok":
            return "green"
        if self.server_health and self.agent_running and self.agent_status in {"missing", "disabled"}:
            return "yellow"
        return "red"

    @property
    def usb_owned_by_signalrgb(self) -> bool:
        return self.agent_status == "owned_by_signalrgb" or self.signalrgb_running


class CoolerTray:
    def __init__(self) -> None:
        enforce_stream_only_config()
        self.status = RuntimeStatus()
        self._stop_event = threading.Event()
        self.icon = pystray.Icon(
            "open-aio",
            self._make_icon("red"),
            "Open AIO: starting",
            menu=self._make_menu(),
        )

    def run(self) -> None:
        threading.Thread(target=self._status_loop, daemon=True).start()
        threading.Thread(target=self._stream_watch_loop, daemon=True).start()
        self.icon.run()

    def _make_menu(self) -> Menu:
        stream_items = (
            MenuItem("Stream Mode: RawUSB", lambda _: None, enabled=lambda _: False),
            MenuItem("Transport: Auto", lambda _: self.set_transport_mode("auto"), checked=lambda _: self.status.transport_mode == "auto"),
            MenuItem("Transport: USB Only", lambda _: self.set_transport_mode("usb_only"), checked=lambda _: self.status.transport_mode == "usb_only"),
        )
        transport_items = (
            MenuItem("Transport: Auto", lambda _: self.set_transport_mode("auto"), checked=lambda _: self.status.transport_mode == "auto"),
            MenuItem("Transport: USB Only", lambda _: self.set_transport_mode("usb_only"), checked=lambda _: self.status.transport_mode == "usb_only"),
            MenuItem("Transport: WiFi Only", lambda _: self.set_transport_mode("wifi_only"), checked=lambda _: self.status.transport_mode == "wifi_only"),
        )
        utility_items = (
            MenuItem("Open CAM Control", self.open_cam_control, enabled=lambda _: self.status.server_health),
            MenuItem("Open Electron Designer", self.open_designer, enabled=lambda _: self.status.server_health),
            MenuItem("Start Electron ESC", self.start_esc_stream, enabled=lambda _: self.status.server_health and not self.status.signalrgb_running),
            MenuItem("Restart Electron ESC", self.restart_esc_stream, enabled=lambda _: self.status.server_health),
            MenuItem("Stop Electron ESC", self.stop_esc_stream, enabled=lambda _: self.status.renderer_running),
            MenuItem("Open Logs", self.open_logs),
            MenuItem("Check Device", self.refresh_now),
        ) if STREAM_ONLY_MODE else (
            MenuItem("Open CAM Control", self.open_cam_control, enabled=lambda _: self.status.server_health),
            MenuItem("Open Logo Review", self.open_review, enabled=lambda _: self.status.server_health),
            MenuItem("Open Designer", self.open_designer, enabled=lambda _: self.status.server_health),
            MenuItem("Start ESC Stream", self.start_esc_stream, enabled=lambda _: self.status.server_health),
            MenuItem("Restart ESC Stream", self.restart_esc_stream, enabled=lambda _: self.status.server_health),
            MenuItem("Stop ESC Stream", self.stop_esc_stream, enabled=lambda _: self.status.renderer_running),
            MenuItem("Open Logs", self.open_logs),
            MenuItem("Check Device", self.refresh_now),
        )
        return Menu(
            MenuItem("Start", self.start_app, enabled=lambda _: not self.status.server_running or not self.status.agent_running),
            MenuItem("Stop", self.stop_app, enabled=lambda _: self.status.server_running or self.status.agent_running),
            MenuItem("Restart", self.restart_app),
            Menu.SEPARATOR,
            MenuItem("Restart Server", self.restart_server),
            MenuItem("Restart Agent", self.restart_agent),
            MenuItem("Restart Sensor Bridge", self.restart_sensor_bridge),
            MenuItem("Start Sensor Bridge as Admin", self.start_sensor_bridge_admin),
            MenuItem("Install Sensor Startup Task", self.install_sensor_task, enabled=lambda _: not self.status.sensor_task_installed),
            MenuItem("Remove Sensor Startup Task", self.remove_sensor_task, enabled=lambda _: self.status.sensor_task_installed),
            Menu.SEPARATOR,
            *utility_items,
            Menu.SEPARATOR,
            *(stream_items if STREAM_ONLY_MODE else transport_items),
            Menu.SEPARATOR,
            MenuItem("Install Startup Task", self.install_startup_shortcut),
            MenuItem("Remove Startup Task", self.remove_startup_shortcut),
            Menu.SEPARATOR,
            MenuItem("Exit", self.exit),
        )

    def _status_loop(self) -> None:
        while not self._stop_event.is_set():
            self.refresh_status()
            time.sleep(2.0)

    def _stream_watch_loop(self) -> None:
        while not self._stop_event.is_set():
            time.sleep(3.0)
            try:
                self.ensure_esc_stream()
            except Exception:
                pass

    def refresh_now(self, _: Any = None) -> None:
        self.refresh_status()

    def refresh_status(self) -> None:
        enforce_stream_only_config()
        server_running = bool(find_processes("uvicorn app.main:app"))
        agent_running = bool(find_processes("pc-agent", "agent.py"))
        sensor_bridge_running = bool(find_processes("SensorBridge.exe", "--watch"))
        renderer_running = electron_renderer_running()
        sensor_task_installed = scheduled_task_exists(SENSOR_TASK_NAME)
        server_health = check_server_health()
        cam_status = read_cam_status() if server_health else {}
        agent_data = read_json(AGENT_STATUS)
        signalrgb_running = any(
            (proc.info.get("name") or "").lower() in {"signalrgb.exe", "signalrgb", "signal-x64.exe"}
            for proc in psutil.process_iter(["name"])
        )
        self.status = RuntimeStatus(
            server_running=server_running,
            agent_running=agent_running,
            server_health=server_health,
            sensor_bridge_running=sensor_bridge_running,
            sensor_task_installed=sensor_task_installed,
            renderer_running=renderer_running,
            designer_preview_active=bool(cam_status.get("designer_preview_active")),
            renderer_frame_age_seconds=frame_age_seconds(DESIGNER_FRAME_PROOF),
            signalrgb_running=signalrgb_running,
            usb_device=detect_usb_device(),
            agent_status=str(agent_data.get("usb_status", "unknown")),
            transport_mode=read_transport_mode(),
            active_process=str(agent_data.get("active_process", "")),
            updated_at=str(agent_data.get("updated_at", "")),
        )
        self.icon.icon = self._make_icon(self.status.color)
        self.icon.title = self._tooltip()
        self.icon.update_menu()

    def _tooltip(self) -> str:
        if not self.status.server_running and not self.status.agent_running:
            return "Open AIO Stream: stopped" if STREAM_ONLY_MODE else "Open AIO: stopped"
        parts = ["Open AIO Stream"] if STREAM_ONLY_MODE else ["Open AIO"]
        parts.append("server ok" if self.status.server_health else "server down")
        parts.append("agent ok" if self.status.agent_running else "agent down")
        sensor_text = "sensors ok" if self.status.sensor_bridge_running else "sensors off"
        if self.status.sensor_task_installed:
            sensor_text += "/startup"
        parts.append(sensor_text)
        if self.status.signalrgb_running:
            parts.append("signalrgb")
        elif self.status.renderer_running:
            parts.append("electron esc live" if self.status.designer_preview_active else "electron esc idle")
        parts.append(f"usb {self.status.agent_status}")
        if self.status.usb_device != "unknown":
            parts.append(self.status.usb_device)
        if self.status.active_process and not STREAM_ONLY_MODE:
            parts.append(self.status.active_process)
        return " | ".join(parts)[:127]

    def _make_icon(self, color_name: str) -> Image.Image:
        colors = {
            "green": (39, 197, 96),
            "yellow": (245, 190, 48),
            "red": (226, 65, 65),
            "purple": (156, 99, 255),
        }
        accent = colors.get(color_name, colors["red"])
        image = Image.new("RGBA", (64, 64), (16, 16, 18, 255))
        draw = ImageDraw.Draw(image)
        draw.ellipse((6, 6, 58, 58), fill=(28, 30, 34), outline=accent, width=5)
        draw.arc((14, 14, 50, 50), 125, 420, fill=accent, width=6)
        draw.ellipse((26, 26, 38, 38), fill=accent)
        return image

    def start_app(self, _: Any = None) -> None:
        ensure_log_dir()
        if not check_prereqs():
            return
        if not find_processes("uvicorn app.main:app"):
            start_hidden(
                SERVER_PYTHON,
                ["-m", "uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"],
                SERVER_DIR,
                LOG_DIR / "server.stdout.log",
                LOG_DIR / "server.stderr.log",
            )
        if not find_processes("pc-agent", "agent.py"):
            start_hidden(
                AGENT_PYTHON,
                ["agent.py"],
                AGENT_DIR,
                LOG_DIR / "agent.stdout.log",
                LOG_DIR / "agent.stderr.log",
            )
        if STREAM_ONLY_MODE:
            start_electron_renderer()
        time.sleep(1.0)
        self.refresh_status()

    def stop_app(self, _: Any = None) -> None:
        stop_stream_supervisor()
        stop_designer_renderer()
        stop_electron_renderer()
        stop_agent()
        stop_matching("uvicorn app.main:app")
        time.sleep(0.8)
        self.refresh_status()

    def restart_app(self, _: Any = None) -> None:
        self.stop_app()
        self.start_app()

    def restart_server(self, _: Any = None) -> None:
        stop_matching("uvicorn app.main:app")
        time.sleep(0.5)
        ensure_log_dir()
        start_hidden(
            SERVER_PYTHON,
            ["-m", "uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"],
            SERVER_DIR,
            LOG_DIR / "server.stdout.log",
            LOG_DIR / "server.stderr.log",
        )
        time.sleep(1.0)
        self.refresh_status()

    def restart_sensor_bridge(self, _: Any = None) -> None:
        stop_matching("SensorBridge.exe", "--watch")
        time.sleep(0.5)
        ensure_log_dir()
        if scheduled_task_exists(SENSOR_TASK_NAME):
            run_scheduled_task(SENSOR_TASK_NAME)
        else:
            start_sensor_bridge()
        time.sleep(1.0)
        self.refresh_status()

    def start_sensor_bridge_admin(self, _: Any = None) -> None:
        stop_matching("SensorBridge.exe", "--watch")
        subprocess.Popen(
            [
                "powershell.exe",
                "-NoProfile",
                "-ExecutionPolicy",
                "Bypass",
                "-File",
                str(ROOT / "scripts" / "start_sensor_bridge_admin.ps1"),
            ],
            cwd=str(ROOT),
            creationflags=CREATE_NO_WINDOW,
            close_fds=True,
        )
        time.sleep(1.0)
        self.refresh_status()

    def restart_agent(self, _: Any = None) -> None:
        stop_agent()
        time.sleep(0.5)
        ensure_log_dir()
        start_hidden(
            AGENT_PYTHON,
            ["agent.py"],
            AGENT_DIR,
            LOG_DIR / "agent.stdout.log",
            LOG_DIR / "agent.stderr.log",
        )
        time.sleep(1.0)
        self.refresh_status()

    def ensure_esc_stream(self) -> None:
        if not STREAM_ONLY_MODE:
            return
        if not self.status.server_health or not self.status.agent_running:
            return
        start_electron_renderer()

    def start_esc_stream(self, _: Any = None) -> None:
        start_electron_renderer()
        time.sleep(1.0)
        self.refresh_status()

    def restart_esc_stream(self, _: Any = None) -> None:
        stop_stream_supervisor()
        stop_designer_renderer()
        stop_electron_renderer()
        time.sleep(0.5)
        start_electron_renderer()
        time.sleep(1.0)
        self.refresh_status()

    def stop_esc_stream(self, _: Any = None) -> None:
        stop_stream_supervisor()
        stop_designer_renderer()
        stop_electron_renderer()
        time.sleep(0.5)
        self.refresh_status()

    def install_sensor_task(self, _: Any = None) -> None:
        run_script(ROOT / "scripts" / "install_sensor_bridge_task_admin.ps1")
        time.sleep(1.0)
        self.refresh_status()

    def remove_sensor_task(self, _: Any = None) -> None:
        run_script(ROOT / "scripts" / "remove_sensor_bridge_task.ps1")
        time.sleep(1.0)
        self.refresh_status()

    def open_review(self, _: Any = None) -> None:
        webbrowser.open(f"{SERVER_URL}/review")

    def open_designer(self, _: Any = None) -> None:
        start_electron_renderer()

    def open_cam_control(self, _: Any = None) -> None:
        open_app_window(f"{SERVER_URL}/cam")

    def open_logs(self, _: Any = None) -> None:
        ensure_log_dir()
        os.startfile(LOG_DIR) if os.name == "nt" else subprocess.Popen(["xdg-open", str(LOG_DIR)])

    def set_transport_mode(self, mode: str) -> None:
        update_agent_config({"transport_mode": mode})
        self.status.transport_mode = mode
        self.restart_agent()

    def install_startup_shortcut(self, _: Any = None) -> None:
        run_script(ROOT / "scripts" / "install_tray_task.ps1")

    def remove_startup_shortcut(self, _: Any = None) -> None:
        run_script(ROOT / "scripts" / "remove_tray_task.ps1")

    def exit(self, _: Any = None) -> None:
        self._stop_event.set()
        self.icon.stop()


def ensure_log_dir() -> None:
    LOG_DIR.mkdir(parents=True, exist_ok=True)


def acquire_single_instance_lock() -> bool:
    global _LOCK_FILE
    ensure_log_dir()
    lock_path = LOG_DIR / "tray.lock"
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


def check_prereqs() -> bool:
    return SERVER_PYTHON.exists() and AGENT_PYTHON.exists()


def start_hidden(executable: Path, args: list[str], cwd: Path, stdout_path: Path, stderr_path: Path) -> subprocess.Popen[Any]:
    stdout = stdout_path.open("ab")
    stderr = stderr_path.open("ab")
    return subprocess.Popen(
        [str(executable), *args],
        cwd=str(cwd),
        stdout=stdout,
        stderr=stderr,
        creationflags=CREATE_NO_WINDOW,
        close_fds=True,
    )


def read_cam_status() -> dict[str, Any]:
    try:
        response = requests.get(f"{SERVER_URL}/api/cam/status", timeout=0.8)
        response.raise_for_status()
        payload = response.json()
    except (requests.RequestException, ValueError):
        return {}
    return payload if isinstance(payload, dict) else {}


def frame_age_seconds(path: Path) -> float | None:
    try:
        stat = path.stat()
    except OSError:
        return None
    return max(0.0, time.time() - stat.st_mtime)


def designer_renderer_running() -> bool:
    return bool(find_processes("designer_renderer.py"))


def electron_renderer_running() -> bool:
    return bool(find_processes("electron-app", "electron.exe"))


def start_electron_renderer(restart: bool = False) -> None:
    ensure_log_dir()
    if restart:
        stop_electron_renderer()
        time.sleep(0.5)
    if electron_renderer_running():
        # Launching a second instance activates the existing Electron window.
        if ELECTRON_EXE.exists():
            subprocess.Popen(
                [str(ELECTRON_EXE), "."],
                cwd=str(ELECTRON_DIR),
                creationflags=CREATE_NO_WINDOW,
                close_fds=True,
            )
        return
    if not ELECTRON_EXE.exists():
        return
    env = os.environ.copy()
    env.pop("ELECTRON_RUN_AS_NODE", None)
    subprocess.Popen(
        [str(ELECTRON_EXE), "."],
        cwd=str(ELECTRON_DIR),
        env=env,
        creationflags=CREATE_NO_WINDOW,
        close_fds=True,
    )


def stop_electron_renderer() -> None:
    stop_matching("electron-app", "electron.exe")


def start_designer_renderer(restart: bool = False) -> None:
    ensure_log_dir()
    if restart:
        stop_designer_renderer()
        time.sleep(0.5)
    if designer_renderer_running():
        return
    python = AGENT_PYTHONW if AGENT_PYTHONW.exists() else AGENT_PYTHON
    if not python.exists():
        return
    start_hidden(
        python,
        [
            "designer_renderer.py",
            "--fps",
            RENDERER_FPS,
            "--quality",
            RENDERER_QUALITY,
            "--usb-direct",
            "--status-every",
            "0",
        ],
        AGENT_DIR,
        LOG_DIR / "designer_renderer.stdout.log",
        LOG_DIR / "designer_renderer.stderr.log",
    )


def stop_designer_renderer() -> None:
    stop_matching("designer_renderer.py")


def start_stream_supervisor() -> None:
    ensure_log_dir()
    if find_processes("stream_supervisor.py"):
        return
    python = DESKTOP_DIR / ".venv" / "Scripts" / "pythonw.exe"
    if not python.exists():
        python = DESKTOP_DIR / ".venv" / "Scripts" / "python.exe"
    if not python.exists() or not STREAM_SUPERVISOR.exists():
        return
    start_hidden(
        python,
        ["stream_supervisor.py"],
        DESKTOP_DIR,
        LOG_DIR / "stream_supervisor.stdout.log",
        LOG_DIR / "stream_supervisor.stderr.log",
    )


def stop_stream_supervisor() -> None:
    stop_matching("stream_supervisor.py")


def open_app_window(url: str) -> None:
    profile_dir = LOG_DIR / "cam-edge-profile"
    profile_dir.mkdir(parents=True, exist_ok=True)
    for edge_path in EDGE_PATHS:
        if edge_path.exists():
            subprocess.Popen(
                [
                    str(edge_path),
                    f"--app={url}",
                    "--new-window",
                    f"--user-data-dir={profile_dir}",
                    "--disable-features=msEdgeSmartScreenProtection",
                ],
                cwd=str(ROOT),
                creationflags=CREATE_NO_WINDOW,
                close_fds=True,
            )
            return
    webbrowser.open(url)


def start_sensor_bridge() -> None:
    if not SENSOR_BRIDGE_EXE.exists():
        return
    start_hidden(
        SENSOR_BRIDGE_EXE,
        [
            "--watch",
            "--output",
            str(SENSOR_OUTPUT),
            "--interval-ms",
            "1000",
            "--cpu-sensor-id",
            "/intelcpu/0/temperature/1",
        ],
        SENSOR_BRIDGE_EXE.parent,
        LOG_DIR / "sensor-bridge.stdout.log",
        LOG_DIR / "sensor-bridge.stderr.log",
    )


def run_script(path: Path) -> None:
    subprocess.Popen(
        [
            "powershell.exe",
            "-NoProfile",
            "-ExecutionPolicy",
            "Bypass",
            "-File",
            str(path),
        ],
        cwd=str(ROOT),
        creationflags=CREATE_NO_WINDOW,
        close_fds=True,
    )


def process_text(proc: psutil.Process) -> str:
    try:
        name = proc.name()
        cmdline = " ".join(proc.cmdline())
        cwd = proc.cwd()
    except (psutil.NoSuchProcess, psutil.AccessDenied):
        return ""
    return f"{name} {cmdline} {cwd}".lower()


def find_processes(*needles: str) -> list[psutil.Process]:
    lowered = [needle.lower() for needle in needles]
    matches: list[psutil.Process] = []
    current = os.getpid()
    for proc in psutil.process_iter(["pid", "name", "cmdline"]):
        if proc.info.get("pid") == current:
            continue
        text = process_text(proc)
        if text and all(needle in text for needle in lowered):
            matches.append(proc)
    return matches


def stop_matching(*needles: str) -> None:
    processes = find_processes(*needles)
    for proc in processes:
        try:
            proc.terminate()
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            pass
    gone, alive = psutil.wait_procs(processes, timeout=2.0)
    for proc in alive:
        try:
            proc.kill()
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            pass


def stop_agent() -> None:
    roots = find_processes("pc-agent", "agent.py")
    related: dict[int, psutil.Process] = {proc.pid: proc for proc in roots}
    for root in roots:
        try:
            for child in root.children(recursive=True):
                if "agent.py" in process_text(child):
                    related[child.pid] = child
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            pass
    for proc in list(related.values()):
        try:
            proc.terminate()
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            pass
    gone, alive = psutil.wait_procs(list(related.values()), timeout=2.0)
    for proc in alive:
        try:
            proc.kill()
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            pass


def scheduled_task_exists(name: str) -> bool:
    if os.name != "nt":
        return False
    try:
        result = subprocess.run(
            ["powershell.exe", "-NoProfile", "-ExecutionPolicy", "Bypass", "-Command", f"if (Get-ScheduledTask -TaskName '{name}' -ErrorAction SilentlyContinue) {{ 'yes' }}"],
            capture_output=True,
            text=True,
            timeout=1.0,
            creationflags=CREATE_NO_WINDOW,
        )
    except (OSError, subprocess.SubprocessError):
        return False
    return result.returncode == 0 and "yes" in result.stdout.lower()


def run_scheduled_task(name: str) -> None:
    if os.name != "nt":
        return
    subprocess.Popen(
        ["powershell.exe", "-NoProfile", "-ExecutionPolicy", "Bypass", "-Command", f"Start-ScheduledTask -TaskName '{name}'"],
        cwd=str(ROOT),
        creationflags=CREATE_NO_WINDOW,
        close_fds=True,
    )


def check_server_health() -> bool:
    try:
        response = requests.get(f"{SERVER_URL}/health", timeout=0.5)
        return response.ok and bool(response.json().get("ok"))
    except requests.RequestException:
        return False


def read_json(path: Path) -> dict[str, Any]:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}


def read_transport_mode() -> str:
    config = read_json(AGENT_CONFIG)
    mode = str(config.get("transport_mode", "auto"))
    return mode if mode in {"auto", "usb_only", "wifi_only"} else "auto"


def enforce_stream_only_config() -> None:
    if STREAM_ONLY_MODE and read_transport_mode() == "wifi_only":
        update_agent_config({"transport_mode": "auto"})


def update_agent_config(updates: dict[str, Any]) -> None:
    config = read_json(AGENT_CONFIG)
    if not config:
        config = read_json(AGENT_DIR / "config.example.json")
    config.update(updates)
    AGENT_CONFIG.write_text(json.dumps(config, indent=2) + "\n", encoding="utf-8")


def detect_usb_device() -> str:
    if os.name != "nt":
        return "unknown"
    script = r"""
$items = Get-PnpDevice -PresentOnly -ErrorAction SilentlyContinue |
  Where-Object { $_.InstanceId -match 'VID_303A&PID_(4004|1001)' } |
  Select-Object -First 4 FriendlyName,InstanceId
$items | ConvertTo-Json -Compress
"""
    try:
        result = subprocess.run(
            ["powershell.exe", "-NoProfile", "-ExecutionPolicy", "Bypass", "-Command", script],
            capture_output=True,
            text=True,
            timeout=1.5,
            creationflags=CREATE_NO_WINDOW,
        )
    except (OSError, subprocess.SubprocessError):
        return "unknown"
    if result.returncode != 0 or not result.stdout.strip():
        return "missing"
    try:
        data = json.loads(result.stdout)
    except json.JSONDecodeError:
        return "unknown"
    items = data if isinstance(data, list) else [data]
    text = " ".join(str(item.get("InstanceId", "")) for item in items if isinstance(item, dict))
    if "PID_4004" in text:
        return "Open AIO"
    if "PID_1001" in text:
        return "bootloader"
    return "unknown"


def main() -> int:
    if not check_prereqs():
        print("Missing server or agent virtual environment. Run scripts\\setup_windows.ps1 first.", file=sys.stderr)
        return 1
    if not acquire_single_instance_lock():
        print("Open AIO tray is already running.", file=sys.stderr)
        return 0
    CoolerTray().run()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
