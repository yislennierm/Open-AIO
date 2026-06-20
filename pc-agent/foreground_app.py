from __future__ import annotations

import ctypes
import os
import platform
import shutil
import subprocess
from ctypes import wintypes

import psutil

CREATE_NO_WINDOW = 0x08000000 if platform.system().lower() == "windows" else 0


def _basename(value: str | None) -> str:
    if not value:
        return "unknown.exe"
    return os.path.basename(value.replace("\\", "/")) or "unknown.exe"


def _run_command(args: list[str]) -> str | None:
    try:
        result = subprocess.run(
            args,
            capture_output=True,
            text=True,
            timeout=0.5,
            check=False,
            creationflags=CREATE_NO_WINDOW,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    if result.returncode != 0:
        return None
    return result.stdout.strip()


def _process_name_from_pid(pid: int) -> str:
    try:
        proc = psutil.Process(pid)
        exe = proc.exe()
        if exe:
            return _basename(exe)
        return proc.name() or "unknown.exe"
    except (psutil.Error, OSError):
        return "unknown.exe"


def _windows_foreground_window_info() -> tuple[str, str]:
    try:
        user32 = ctypes.WinDLL("user32", use_last_error=True)
        kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    except Exception:
        return "unknown.exe", ""

    process_query_limited_information = 0x1000
    max_path = 260
    max_title = 512

    user32.GetForegroundWindow.restype = wintypes.HWND
    user32.GetWindowThreadProcessId.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.DWORD)]
    user32.GetWindowThreadProcessId.restype = wintypes.DWORD
    user32.GetWindowTextLengthW.argtypes = [wintypes.HWND]
    user32.GetWindowTextLengthW.restype = ctypes.c_int
    user32.GetWindowTextW.argtypes = [wintypes.HWND, wintypes.LPWSTR, ctypes.c_int]
    user32.GetWindowTextW.restype = ctypes.c_int
    kernel32.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
    kernel32.OpenProcess.restype = wintypes.HANDLE
    kernel32.QueryFullProcessImageNameW.argtypes = [
        wintypes.HANDLE,
        wintypes.DWORD,
        wintypes.LPWSTR,
        ctypes.POINTER(wintypes.DWORD),
    ]
    kernel32.QueryFullProcessImageNameW.restype = wintypes.BOOL
    kernel32.CloseHandle.argtypes = [wintypes.HANDLE]
    kernel32.CloseHandle.restype = wintypes.BOOL

    try:
        hwnd = user32.GetForegroundWindow()
        if not hwnd:
            return "unknown.exe", ""

        title = ""
        title_len = user32.GetWindowTextLengthW(hwnd)
        if title_len > 0:
            title_buffer = ctypes.create_unicode_buffer(min(title_len + 1, max_title))
            user32.GetWindowTextW(hwnd, title_buffer, len(title_buffer))
            title = title_buffer.value.strip()

        pid = wintypes.DWORD()
        user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
        if pid.value == 0:
            return "unknown.exe", title

        handle = kernel32.OpenProcess(process_query_limited_information, False, pid.value)
        if not handle:
            return "unknown.exe", title

        try:
            buffer = ctypes.create_unicode_buffer(max_path)
            size = wintypes.DWORD(max_path)
            if not kernel32.QueryFullProcessImageNameW(handle, 0, buffer, ctypes.byref(size)):
                return _process_name_from_pid(pid.value), title
            return _basename(buffer.value), title
        finally:
            kernel32.CloseHandle(handle)
    except Exception:
        return "unknown.exe", ""


def _windows_foreground_process_name() -> str:
    process_name, _title = _windows_foreground_window_info()
    return process_name


def _linux_x11_foreground_process_name() -> str:
    name = _linux_x11_xdotool_process_name()
    if name != "unknown.exe":
        return name
    return _linux_x11_wmctrl_process_name()


def _linux_x11_xdotool_process_name() -> str:
    if not shutil.which("xdotool"):
        return "unknown.exe"
    window_id = _run_command(["xdotool", "getactivewindow"])
    if not window_id:
        return "unknown.exe"
    pid_text = _run_command(["xdotool", "getwindowpid", window_id])
    if not pid_text or not pid_text.isdigit():
        return "unknown.exe"
    return _process_name_from_pid(int(pid_text))


def _linux_x11_wmctrl_process_name() -> str:
    if not shutil.which("xprop") or not shutil.which("wmctrl"):
        return "unknown.exe"

    active = _run_command(["xprop", "-root", "_NET_ACTIVE_WINDOW"])
    if not active or "#" not in active:
        return "unknown.exe"
    active_id = active.rsplit("#", 1)[-1].strip().lower()
    if not active_id.startswith("0x"):
        return "unknown.exe"
    active_id = "0x" + active_id[2:].lstrip("0")

    windows = _run_command(["wmctrl", "-lp"])
    if not windows:
        return "unknown.exe"
    for line in windows.splitlines():
        parts = line.split(None, 4)
        if len(parts) < 3:
            continue
        window_id = "0x" + parts[0].lower()[2:].lstrip("0")
        if window_id == active_id and parts[2].isdigit():
            if _is_linux_mint_desktop_window(parts):
                return "linuxmint-desktop"
            return _process_name_from_pid(int(parts[2]))
    return "unknown.exe"


def _is_linux_mint_desktop_window(wmctrl_parts: list[str]) -> bool:
    if len(wmctrl_parts) < 5:
        return False
    desktop = os.environ.get("XDG_CURRENT_DESKTOP", "").lower()
    title = wmctrl_parts[4].lower()
    return "cinnamon" in desktop and ("nemo-desktop" in title or title.endswith(" desktop"))


def _linux_wayland_foreground_process_name() -> str:
    swaymsg = shutil.which("swaymsg")
    jq = shutil.which("jq")
    if not swaymsg or not jq:
        return "unknown.exe"
    pid_text = _run_command(
        [
            "sh",
            "-c",
            "swaymsg -t get_tree | jq -r '.. | objects | select(.focused == true) | .pid // empty' | head -n 1",
        ]
    )
    if not pid_text or not pid_text.isdigit():
        return "unknown.exe"
    return _process_name_from_pid(int(pid_text))


def _linux_foreground_process_name() -> str:
    session_type = os.environ.get("XDG_SESSION_TYPE", "").lower()
    if session_type == "x11":
        return _linux_x11_foreground_process_name()
    if session_type == "wayland":
        name = _linux_wayland_foreground_process_name()
        if name != "unknown.exe":
            return name
    name = _linux_x11_foreground_process_name()
    if name != "unknown.exe":
        return name
    return _linux_wayland_foreground_process_name()


def _macos_foreground_process_name() -> str:
    if not shutil.which("osascript"):
        return "unknown.exe"
    app_name = _run_command(
        [
            "osascript",
            "-e",
            'tell application "System Events" to get name of first application process whose frontmost is true',
        ]
    )
    if not app_name:
        return "unknown.exe"
    return _basename(app_name)


def get_foreground_process_name() -> str:
    system = platform.system().lower()
    if system == "windows":
        return _windows_foreground_process_name()
    if system == "linux":
        return _linux_foreground_process_name()
    if system == "darwin":
        return _macos_foreground_process_name()
    return "unknown.exe"


def get_foreground_window_info() -> tuple[str, str]:
    system = platform.system().lower()
    if system == "windows":
        return _windows_foreground_window_info()
    return get_foreground_process_name(), ""
