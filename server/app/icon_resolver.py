from __future__ import annotations

import hashlib
import json
import os
import platform
import re
import shutil
import subprocess
import tempfile
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from PIL import Image

from .assets import APP_DISPLAY_NAMES, asset_root, normalize_process_name, process_to_app_id
from .config import SETTINGS

ASSET_SIZE = 160
STATE_FILE = "local_icon_state.json"


@dataclass(frozen=True)
class DesktopEntry:
    path: Path
    desktop_id: str
    name: str
    exec_name: str
    icon: str
    startup_wm_class: str


def app_id_from_process(process_name: str) -> str:
    mapped_app_id = process_to_app_id(process_name)
    if mapped_app_id != SETTINGS.default_app_id:
        return mapped_app_id

    stem = normalize_process_name(process_name)
    if stem.endswith(".exe"):
        stem = stem[:-4]
    stem = re.sub(r"[^a-z0-9_-]+", "-", stem.lower()).strip("-")
    return stem[:64] or "unknown"


def display_name_from_app_id(app_id: str) -> str:
    return APP_DISPLAY_NAMES.get(app_id, app_id.replace("_", " ").replace("-", " ").title())


def discover_or_queue_app(process_name: str) -> str | None:
    process_name = normalize_process_name(process_name)
    if process_name in {"unknown", "unknown.exe"}:
        return None
    app_id = app_id_from_process(process_name)
    state = _load_state()

    approved = state.get("approved_mappings", {})
    if process_name in approved:
        return str(approved[process_name])

    manifest_path = asset_root() / app_id / "manifest.json"
    pending_item = state.get("pending", {}).get(process_name, {})
    pending_status = str(pending_item.get("status", "")) if isinstance(pending_item, dict) else ""
    if manifest_path.exists() and pending_status not in {"needs_ai_search", "rejected_candidate"}:
        _record_pending(state, process_name, app_id, "existing_manifest", None)
        _save_state(state)
        return app_id

    rejected_sources = _rejected_sources_for_process(state, process_name)
    windows_app = _find_windows_app(process_name) if platform.system().lower() == "windows" else None
    if windows_app is not None:
        display_name = windows_app.get("name") or display_name_from_app_id(app_id)
        source_icon = windows_app.get("target")
        if source_icon and source_icon not in rejected_sources:
            try:
                _preprocess_windows_exe_icon(Path(source_icon), app_id, display_name)
            except Exception as exc:
                _record_pending(state, process_name, app_id, f"windows_icon_failed:{type(exc).__name__}", source_icon)
                _save_state(state)
            else:
                approved[process_name] = app_id
                state["approved_mappings"] = approved
                _record_pending(state, process_name, app_id, "auto_windows_icon", source_icon)
                _save_state(state)
                return app_id

    entry = _find_desktop_entry(process_name)
    icon_paths = _candidate_icon_paths(entry, app_id)
    display_name = entry.name if entry and entry.name else display_name_from_app_id(app_id)

    for icon_path in icon_paths:
        if str(icon_path) in rejected_sources:
            continue
        try:
            _preprocess_icon(icon_path, app_id, display_name)
        except Exception as exc:
            _record_pending(state, process_name, app_id, f"preprocess_failed:{type(exc).__name__}", str(icon_path))
            _save_state(state)
            continue

        approved[process_name] = app_id
        state["approved_mappings"] = approved
        _record_pending(state, process_name, app_id, "auto_local_icon", str(icon_path))
        _save_state(state)
        return app_id

    _record_pending(state, process_name, app_id, "needs_ai_search", None)
    _save_state(state)
    return None


def list_unknown_apps() -> list[dict[str, Any]]:
    state = _load_state()
    pending = state.get("pending", {})
    return sorted(pending.values(), key=lambda item: str(item.get("updated_at", "")), reverse=True)


def candidate_for_process(process_name: str) -> dict[str, Any] | None:
    process_name = normalize_process_name(process_name)
    if process_name in {"unknown", "unknown.exe"}:
        return None
    state = _load_state()
    item = state.get("pending", {}).get(process_name)
    if not isinstance(item, dict):
        return None
    status = str(item.get("status", ""))
    if status not in {"auto_local_icon", "auto_windows_icon", "existing_manifest", "web_candidate"}:
        return None
    app_id = str(item.get("app_id", ""))
    if not app_id or not (asset_root() / app_id / "manifest.json").exists():
        return None
    return item


def approve_candidate(process_name: str, app_id: str | None = None) -> dict[str, Any]:
    process_name = normalize_process_name(process_name)
    state = _load_state()
    pending = state.get("pending", {})
    item = pending.get(process_name, {})
    selected_app_id = app_id or item.get("app_id") or app_id_from_process(process_name)
    if not isinstance(selected_app_id, str):
        selected_app_id = app_id_from_process(process_name)
    if not (asset_root() / selected_app_id / "manifest.json").exists():
        raise ValueError("candidate asset does not exist")
    approved = state.get("approved_mappings", {})
    approved[process_name] = selected_app_id
    state["approved_mappings"] = approved
    _record_pending(state, process_name, selected_app_id, "approved", item.get("source_icon"))
    _save_state(state)
    return pending.get(process_name, {})


def reject_candidate(process_name: str) -> dict[str, Any]:
    process_name = normalize_process_name(process_name)
    state = _load_state()
    approved = state.get("approved_mappings", {})
    if process_name in approved:
        del approved[process_name]
        state["approved_mappings"] = approved

    pending = state.get("pending", {})
    item = pending.get(process_name, {})
    if isinstance(item, dict):
        source_icon = item.get("source_icon")
        if isinstance(source_icon, str) and source_icon:
            rejected_sources = state.get("rejected_candidate_sources", {})
            values = rejected_sources.get(process_name, [])
            if not isinstance(values, list):
                values = []
            if source_icon not in values:
                values.append(source_icon)
            rejected_sources[process_name] = values
            state["rejected_candidate_sources"] = rejected_sources
    if process_name in pending:
        pending[process_name]["status"] = "rejected_candidate"
        pending[process_name]["updated_at"] = datetime.now(tz=UTC).isoformat()
    _save_state(state)
    discover_or_queue_app(process_name)
    return _load_state().get("pending", {}).get(process_name, {})


def _state_path() -> Path:
    return asset_root() / STATE_FILE


def _load_state() -> dict[str, Any]:
    path = _state_path()
    if not path.exists():
        return {"approved_mappings": {}, "rejected_processes": {}, "pending": {}}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return {"approved_mappings": {}, "rejected_processes": {}, "pending": {}}


def _save_state(state: dict[str, Any]) -> None:
    path = _state_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(state, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def _record_pending(state: dict[str, Any], process_name: str, app_id: str, status: str, source_icon: str | None) -> None:
    pending = state.get("pending", {})
    pending[process_name] = {
        "process_name": process_name,
        "app_id": app_id,
        "display_name": display_name_from_app_id(app_id),
        "status": status,
        "source_icon": source_icon,
        "updated_at": datetime.now(tz=UTC).isoformat(),
    }
    state["pending"] = pending


def _rejected_sources_for_process(state: dict[str, Any], process_name: str) -> set[str]:
    rejected = state.get("rejected_candidate_sources", {})
    values = rejected.get(process_name, []) if isinstance(rejected, dict) else []
    if not isinstance(values, list):
        return set()
    return {str(value) for value in values}


def _desktop_dirs() -> list[Path]:
    home = Path.home()
    return [
        home / ".local/share/applications",
        Path("/usr/share/applications"),
    ]


def _read_desktop_entries() -> list[DesktopEntry]:
    entries: list[DesktopEntry] = []
    for directory in _desktop_dirs():
        if not directory.exists():
            continue
        for path in directory.glob("*.desktop"):
            data = _parse_desktop_file(path)
            if not data or data.get("NoDisplay", "").lower() == "true":
                continue
            icon = data.get("Icon", "")
            name = data.get("Name", path.stem)
            exec_value = data.get("Exec", "")
            entries.append(
                DesktopEntry(
                    path=path,
                    desktop_id=path.stem.lower(),
                    name=name,
                    exec_name=_exec_basename(exec_value),
                    icon=icon,
                    startup_wm_class=data.get("StartupWMClass", "").lower(),
                )
            )
    return entries


def _parse_desktop_file(path: Path) -> dict[str, str]:
    result: dict[str, str] = {}
    try:
        for raw in path.read_text(encoding="utf-8", errors="replace").splitlines():
            line = raw.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, value = line.split("=", 1)
            if "[" in key:
                continue
            result[key] = value.strip()
    except OSError:
        return {}
    return result


def _exec_basename(exec_value: str) -> str:
    if not exec_value:
        return ""
    token = exec_value.split()[0]
    return os.path.basename(token).lower()


def _find_desktop_entry(process_name: str) -> DesktopEntry | None:
    normalized = normalize_process_name(process_name)
    stem = normalized[:-4] if normalized.endswith(".exe") else normalized
    entries = _read_desktop_entries()
    for entry in entries:
        candidates = {
            entry.desktop_id,
            entry.exec_name,
            entry.startup_wm_class,
            entry.icon.lower(),
            entry.name.lower().replace(" ", "-"),
        }
        if normalized in candidates or stem in candidates:
            return entry
    for entry in entries:
        if stem and (stem in entry.desktop_id or stem in entry.exec_name or stem in entry.icon.lower()):
            return entry
    return None


def _icon_dirs() -> list[Path]:
    home = Path.home()
    return [
        home / ".local/share/icons",
        home / ".icons",
        Path("/usr/share/icons"),
        Path("/usr/share/pixmaps"),
    ]


def _resolve_icon_path(icon_name: str) -> Path | None:
    if not icon_name:
        return None
    path = Path(icon_name)
    if path.is_absolute() and path.exists() and path.is_file():
        return path
    candidates: list[Path] = []
    names = [icon_name]
    if not Path(icon_name).suffix:
        names.extend([f"{icon_name}.png", f"{icon_name}.svg", f"{icon_name}.xpm"])
    for directory in _icon_dirs():
        if not directory.exists():
            continue
        for name in names:
            candidates.extend(directory.rglob(name))
    return _best_icon_candidate(candidates)


def _candidate_icon_paths(entry: DesktopEntry | None, app_id: str) -> list[Path]:
    names: list[str] = [app_id]
    if entry is not None:
        names.extend([entry.icon, entry.desktop_id, entry.exec_name, entry.startup_wm_class])
    paths: list[Path] = []
    for name in names:
        paths.extend(_resolve_icon_paths(name))
    seen: set[str] = set()
    unique: list[Path] = []
    for path in sorted(paths, key=_icon_score, reverse=True):
        key = str(path)
        if key not in seen:
            seen.add(key)
            unique.append(path)
    return unique


def _powershell_command() -> str | None:
    return shutil.which("pwsh") or shutil.which("powershell")


def _find_windows_start_menu_app(process_name: str) -> dict[str, str] | None:
    powershell = _powershell_command()
    if powershell is None:
        return None

    stem = process_name[:-4] if process_name.endswith(".exe") else process_name
    script = r"""
$ProcessName = $env:COOLER_PROCESS_NAME
$Stem = $env:COOLER_PROCESS_STEM
$ErrorActionPreference = 'SilentlyContinue'
$shell = New-Object -ComObject WScript.Shell
$dirs = @(
  [Environment]::GetFolderPath('CommonPrograms'),
  [Environment]::GetFolderPath('Programs')
) | Where-Object { $_ -and (Test-Path $_) }

$items = foreach ($dir in $dirs) {
  Get-ChildItem -LiteralPath $dir -Recurse -Filter *.lnk | ForEach-Object {
    $shortcut = $shell.CreateShortcut($_.FullName)
    $target = $shortcut.TargetPath
    if ($target) {
      $leaf = [IO.Path]::GetFileName($target).ToLowerInvariant()
      $targetStem = [IO.Path]::GetFileNameWithoutExtension($target).ToLowerInvariant()
      if ($leaf -eq $ProcessName -or $targetStem -eq $Stem) {
        [pscustomobject]@{
          name = [IO.Path]::GetFileNameWithoutExtension($_.Name)
          target = $target
          shortcut = $_.FullName
        }
      }
    }
  }
}

$items | Select-Object -First 1 | ConvertTo-Json -Compress
"""
    try:
        result = subprocess.run(
            [powershell, "-NoProfile", "-ExecutionPolicy", "Bypass", "-Command", script],
            capture_output=True,
            text=True,
            timeout=4.0,
            check=False,
            env={**os.environ, "COOLER_PROCESS_NAME": process_name, "COOLER_PROCESS_STEM": stem},
        )
    except (OSError, subprocess.SubprocessError):
        return None
    if result.returncode != 0 or not result.stdout.strip():
        return None
    try:
        item = json.loads(result.stdout)
    except json.JSONDecodeError:
        return None
    if not isinstance(item, dict):
        return None
    target = item.get("target")
    if not isinstance(target, str) or not target:
        return None
    return {
        "name": str(item.get("name") or display_name_from_app_id(app_id_from_process(process_name))),
        "target": target,
        "shortcut": str(item.get("shortcut") or ""),
    }


def _find_windows_running_process_app(process_name: str) -> dict[str, str] | None:
    powershell = _powershell_command()
    if powershell is None:
        return None

    stem = process_name[:-4] if process_name.endswith(".exe") else process_name
    script = r"""
$Stem = $env:COOLER_PROCESS_STEM
$ErrorActionPreference = 'SilentlyContinue'
Get-Process -Name $Stem |
  Where-Object { $_.Path -and (Test-Path -LiteralPath $_.Path) } |
  Select-Object -First 1 @{Name='name';Expression={$_.ProcessName}}, @{Name='target';Expression={$_.Path}} |
  ConvertTo-Json -Compress
"""
    try:
        result = subprocess.run(
            [powershell, "-NoProfile", "-ExecutionPolicy", "Bypass", "-Command", script],
            capture_output=True,
            text=True,
            timeout=4.0,
            check=False,
            env={**os.environ, "COOLER_PROCESS_STEM": stem},
        )
    except (OSError, subprocess.SubprocessError):
        return None
    if result.returncode != 0 or not result.stdout.strip():
        return None
    try:
        item = json.loads(result.stdout)
    except json.JSONDecodeError:
        return None
    if not isinstance(item, dict):
        return None
    target = item.get("target")
    if not isinstance(target, str) or not target:
        return None
    return {
        "name": str(item.get("name") or display_name_from_app_id(app_id_from_process(process_name))),
        "target": target,
        "shortcut": "",
    }


def _find_windows_app(process_name: str) -> dict[str, str] | None:
    return _find_windows_start_menu_app(process_name) or _find_windows_running_process_app(process_name)


def _preprocess_windows_exe_icon(exe_path: Path, app_id: str, display_name: str) -> None:
    powershell = _powershell_command()
    if powershell is None:
        raise RuntimeError("PowerShell is not available")
    if not exe_path.exists() or not exe_path.is_file():
        raise RuntimeError("executable does not exist")
    with tempfile.TemporaryDirectory() as tmpdir:
        png_path = Path(tmpdir) / "associated-icon.png"
        script = r"""
$Target = $env:COOLER_ICON_TARGET
$Output = $env:COOLER_ICON_OUTPUT
$ErrorActionPreference = 'Stop'
Add-Type -AssemblyName System.Drawing
$icon = [System.Drawing.Icon]::ExtractAssociatedIcon($Target)
if ($null -eq $icon) { throw 'no associated icon' }
$bitmap = $icon.ToBitmap()
$bitmap.Save($Output, [System.Drawing.Imaging.ImageFormat]::Png)
$bitmap.Dispose()
$icon.Dispose()
"""
        result = subprocess.run(
            [powershell, "-NoProfile", "-ExecutionPolicy", "Bypass", "-Command", script],
            capture_output=True,
            text=True,
            timeout=5.0,
            check=False,
            env={**os.environ, "COOLER_ICON_TARGET": str(exe_path), "COOLER_ICON_OUTPUT": str(png_path)},
        )
        if result.returncode != 0 or not png_path.exists():
            raise RuntimeError("associated icon extraction failed")
        rgb565 = _image_to_rgb565(png_path)
    output_dir = asset_root() / app_id
    output_dir.mkdir(parents=True, exist_ok=True)
    asset_file = f"logo_{ASSET_SIZE}x{ASSET_SIZE}.rgb565"
    output_path = output_dir / asset_file
    output_path.write_bytes(rgb565)
    digest = hashlib.sha256(rgb565).hexdigest()
    manifest = {
        "app_id": app_id,
        "display_name": display_name,
        "asset_type": "rgb565",
        "asset_file": asset_file,
        "asset_width": ASSET_SIZE,
        "asset_height": ASSET_SIZE,
        "asset_hash": digest,
    }
    (output_dir / "manifest.json").write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")


def _resolve_icon_paths(icon_name: str) -> list[Path]:
    if not icon_name:
        return []
    path = Path(icon_name)
    if path.is_absolute() and path.exists() and path.is_file():
        return [path]
    candidates: list[Path] = []
    names = [icon_name]
    if not Path(icon_name).suffix:
        names.extend([f"{icon_name}.png", f"{icon_name}.svg", f"{icon_name}.xpm"])
    for directory in _icon_dirs():
        if not directory.exists():
            continue
        for name in names:
            candidates.extend(directory.rglob(name))
    return [path for path in candidates if path.is_file() and path.suffix.lower() in {".png", ".svg", ".xpm"}]


def _best_icon_candidate(candidates: list[Path]) -> Path | None:
    files = [path for path in candidates if path.is_file() and path.suffix.lower() in {".png", ".svg", ".xpm"}]
    if not files:
        return None
    files.sort(key=_icon_score, reverse=True)
    return files[0]


def _icon_score(path: Path) -> tuple[int, int, int]:
    text = str(path).lower()
    size_score = 0
    for part in path.parts:
        match = re.search(r"(\d+)(?:x\d+)?", part)
        if match:
            size_score = max(size_score, int(match.group(1)))
    exact_theme = 1 if any(theme in text for theme in ("mint-l", "mint-y", "hicolor", "papirus")) else 0
    ext_score = 2 if path.suffix.lower() == ".png" else 1
    return (size_score, exact_theme, ext_score)


def _preprocess_icon(icon_path: Path, app_id: str, display_name: str) -> None:
    with tempfile.TemporaryDirectory() as tmpdir:
        source = icon_path
        if icon_path.suffix.lower() == ".svg":
            source = Path(tmpdir) / "icon.png"
            _convert_svg(icon_path, source)
        rgb565 = _image_to_rgb565(source)
    output_dir = asset_root() / app_id
    output_dir.mkdir(parents=True, exist_ok=True)
    asset_file = f"logo_{ASSET_SIZE}x{ASSET_SIZE}.rgb565"
    output_path = output_dir / asset_file
    output_path.write_bytes(rgb565)
    digest = hashlib.sha256(rgb565).hexdigest()
    manifest = {
        "app_id": app_id,
        "display_name": display_name,
        "asset_type": "rgb565",
        "asset_file": asset_file,
        "asset_width": ASSET_SIZE,
        "asset_height": ASSET_SIZE,
        "asset_hash": digest,
    }
    (output_dir / "manifest.json").write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")


def _convert_svg(input_path: Path, output_path: Path) -> None:
    converter = shutil.which("convert") or shutil.which("magick")
    if converter is not None:
        subprocess.run(
            [converter, str(input_path), "-background", "none", "-resize", "256x256", str(output_path)],
            check=True,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        return
    inkscape = shutil.which("inkscape")
    if inkscape is None:
        raise RuntimeError("no SVG converter available")
    subprocess.run(
        [inkscape, str(input_path), "--export-type=png", f"--export-filename={output_path}", "-w", "256", "-h", "256"],
        check=True,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )


def _image_to_rgb565(image_path: Path) -> bytes:
    with Image.open(image_path) as image:
        rgba = image.convert("RGBA")
        background = Image.new("RGBA", rgba.size, (16, 16, 18, 255))
        composed = Image.alpha_composite(background, rgba).convert("RGB")
        width, height = composed.size
        side = min(width, height)
        left = (width - side) // 2
        top = (height - side) // 2
        prepared = composed.crop((left, top, left + side, top + side)).resize((ASSET_SIZE, ASSET_SIZE), Image.Resampling.LANCZOS)
        data = prepared.tobytes()
    out = bytearray()
    for index in range(0, len(data), 3):
        r = data[index]
        g = data[index + 1]
        b = data[index + 2]
        value = ((r & 0xF8) << 8) | ((g & 0xFC) << 3) | (b >> 3)
        out.append(value & 0xFF)
        out.append((value >> 8) & 0xFF)
    return bytes(out)
