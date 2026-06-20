from __future__ import annotations

import hashlib
import json
import os
import re
from pathlib import Path
from typing import Any

from fastapi import HTTPException, status
from fastapi.responses import FileResponse

from .config import SERVER_ROOT, SETTINGS


UNKNOWN_APP_ID = "unknown"

PROCESS_APP_MAP: dict[str, str] = {
    "steam.exe": "steam",
    "steam": "steam",
    "steamwebhelper": "steam",
    "steam-runtime-launcher-service": "steam",
    "chrome.exe": "chrome",
    "chrome": "chrome",
    "google-chrome": "chrome",
    "google-chrome-stable": "chrome",
    "chromium": "chrome",
    "firefox.exe": "firefox",
    "firefox": "firefox",
    "firefox-bin": "firefox",
    "dota2.exe": "dota2",
    "dota2": "dota2",
    "code.exe": "vscode",
    "code": "vscode",
    "codium": "vscode",
    "obs64.exe": "obs",
    "obs": "obs",
    "obs-studio": "obs",
    "discord.exe": "discord",
    "discord": "discord",
    "microsoft.media.player.exe": "media-player",
    "wmplayer.exe": "media-player",
    "explorer.exe": "windows",
    "applicationframehost.exe": "windows",
    "dwm.exe": "windows",
    "searchhost.exe": "windows",
    "shellexperiencehost.exe": "windows",
    "shellhost.exe": "windows",
    "startmenuexperiencehost.exe": "windows",
    "textinputhost.exe": "windows",
    "cmd.exe": "command-prompt",
    "powershell.exe": "powershell",
    "windowsterminal.exe": "terminal",
    "gnome-terminal": "terminal",
    "gnome-terminal-server": "terminal",
    "konsole": "terminal",
    "alacritty": "terminal",
    "kitty": "terminal",
    "wezterm-gui": "terminal",
    "nemo": "files",
    "linuxmint-desktop": "linuxmint",
    "nemo-desktop": "linuxmint",
    "xed": "editor",
    "xreader": "reader",
    "pix": "photos",
    "celluloid": "video",
    "cinnamon-settings": "settings",
    "libreoffice": "libreoffice",
    "soffice.bin": "libreoffice",
}


KNOWN_APP_IDS = set(PROCESS_APP_MAP.values()) | {SETTINGS.default_app_id, UNKNOWN_APP_ID}

APP_DISPLAY_NAMES: dict[str, str] = {
    "steam": "Steam",
    "chrome": "Chrome",
    "firefox": "Firefox",
    "dota2": "Dota 2",
    "vscode": "VS Code",
    "obs": "OBS",
    "discord": "Discord",
    "windows": "Windows 11",
    "terminal": "Terminal",
    "command-prompt": "Command Prompt",
    "powershell": "PowerShell",
    "files": "Files",
    "linuxmint": "Linux Mint",
    "editor": "Editor",
    "reader": "Reader",
    "photos": "Photos",
    "video": "Video",
    "settings": "Settings",
    "libreoffice": "LibreOffice",
    "file-explorer": "File Explorer",
    "media-player": "Media Player",
    UNKNOWN_APP_ID: "Unknown",
    SETTINGS.default_app_id: "Default",
}


def normalize_process_name(active_process: str) -> str:
    clean = active_process.replace("\\", "/")
    return os.path.basename(clean).strip().lower() or "unknown.exe"


def process_to_app_id(active_process: str) -> str:
    return PROCESS_APP_MAP.get(normalize_process_name(active_process), SETTINGS.default_app_id)


def is_known_app_id(app_id: str) -> bool:
    if app_id in KNOWN_APP_IDS:
        return True
    if not re_fullmatch_app_id(app_id):
        return False
    return (asset_root() / app_id / "manifest.json").exists()


def re_fullmatch_app_id(app_id: str) -> bool:
    return bool(re.fullmatch(r"[a-z0-9_-]{1,64}", app_id))


def asset_root() -> Path:
    return (SERVER_ROOT / SETTINGS.asset_base_path).resolve()


def has_app_manifest(app_id: str) -> bool:
    if not re_fullmatch_app_id(app_id):
        return False
    return (asset_root() / app_id / "manifest.json").exists()


def safe_app_id(app_id: str) -> str:
    if not is_known_app_id(app_id):
        return SETTINGS.default_app_id
    return app_id


def default_manifest() -> dict[str, Any]:
    file_path = asset_root() / SETTINGS.default_app_id / "logo_160x160.rgb565"
    if not file_path.exists():
        create_default_asset(file_path)
    digest = hashlib.sha256(file_path.read_bytes()).hexdigest()
    return {
        "app_id": SETTINGS.default_app_id,
        "display_name": "Default",
        "asset_type": "rgb565",
        "asset_file": "logo_160x160.rgb565",
        "asset_width": 160,
        "asset_height": 160,
        "asset_hash": digest,
    }


def fallback_manifest_for_app(app_id: str) -> dict[str, Any]:
    manifest = default_manifest()
    safe_id = safe_app_id(app_id)
    manifest["app_id"] = safe_id
    manifest["display_name"] = APP_DISPLAY_NAMES.get(safe_id, safe_id.replace("_", " ").replace("-", " ").title())
    return manifest


def create_default_asset(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    width = 160
    height = 160
    pixels = bytearray()
    for y in range(height):
        for x in range(width):
            dx = x - width / 2
            dy = y - height / 2
            inside = (dx * dx + dy * dy) < 60 * 60
            if inside:
                r, g, b = 30, 190, 210
            else:
                r, g, b = 16, 16, 18
            value = ((r & 0xF8) << 8) | ((g & 0xFC) << 3) | (b >> 3)
            pixels.append(value & 0xFF)
            pixels.append((value >> 8) & 0xFF)
    path.write_bytes(bytes(pixels))
    digest = hashlib.sha256(path.read_bytes()).hexdigest()
    manifest = default_manifest_dict(digest)
    (path.parent / "manifest.json").write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")


def default_manifest_dict(digest: str) -> dict[str, Any]:
    return {
        "app_id": SETTINGS.default_app_id,
        "display_name": "Default",
        "asset_type": "rgb565",
        "asset_file": "logo_160x160.rgb565",
        "asset_width": 160,
        "asset_height": 160,
        "asset_hash": digest,
    }


def load_manifest(app_id: str) -> dict[str, Any]:
    app_id = safe_app_id(app_id)
    path = asset_root() / app_id / "manifest.json"
    if not path.exists() and app_id != SETTINGS.default_app_id:
        return fallback_manifest_for_app(app_id)
    if not path.exists():
        return default_manifest()

    try:
        manifest = json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return fallback_manifest_for_app(app_id)

    required = {"app_id", "display_name", "asset_type", "asset_file", "asset_width", "asset_height", "asset_hash"}
    if not required.issubset(manifest):
        return fallback_manifest_for_app(app_id)
    if not is_known_app_id(str(manifest["app_id"])):
        return fallback_manifest_for_app(app_id)
    return manifest


def asset_url_for_manifest(manifest: dict[str, Any]) -> str:
    app_id = safe_app_id(str(manifest["app_id"]))
    asset_file = os.path.basename(str(manifest["asset_file"]))
    return f"/api/v1/assets/apps/{app_id}/{asset_file}"


def serve_app_asset(app_id: str, asset_file: str) -> FileResponse:
    app_id = safe_app_id(app_id)
    safe_file = os.path.basename(asset_file)
    manifest = load_manifest(app_id)
    expected_file = os.path.basename(str(manifest["asset_file"]))

    if safe_file != expected_file:
        manifest = default_manifest()
        app_id = SETTINGS.default_app_id
        safe_file = os.path.basename(str(manifest["asset_file"]))

    path = (asset_root() / app_id / safe_file).resolve()
    root = asset_root().resolve()
    if root not in path.parents:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="invalid asset path")
    if not path.exists() or not path.is_file():
        manifest = default_manifest()
        path = asset_root() / SETTINGS.default_app_id / str(manifest["asset_file"])
    size = path.stat().st_size
    if size > SETTINGS.max_asset_size_bytes:
        raise HTTPException(status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE, detail="asset too large")
    return FileResponse(path, media_type="application/octet-stream")
