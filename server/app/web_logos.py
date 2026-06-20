from __future__ import annotations

import hashlib
import json
import re
import shutil
import subprocess
import tempfile
import urllib.error
import urllib.parse
import urllib.request
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from PIL import Image

from .assets import asset_root, normalize_process_name
from .config import SETTINGS
from .icon_resolver import app_id_from_process, display_name_from_app_id

ASSET_SIZE = 160
MAX_DOWNLOAD_BYTES = min(SETTINGS.max_asset_size_bytes, 512 * 1024)
ALLOWED_CONTENT_TYPES = {"image/png", "image/jpeg", "image/webp", "image/svg+xml"}


def task_list() -> list[dict[str, Any]]:
    state = _load_state()
    pending = state.get("pending", {})
    tasks: list[dict[str, Any]] = []
    for item in pending.values():
        if not isinstance(item, dict):
            continue
        status = str(item.get("status", ""))
        if status in {"needs_ai_search", "web_candidate", "rejected_candidate"}:
            tasks.append(item)
    return sorted(tasks, key=lambda item: str(item.get("updated_at", "")), reverse=True)


def try_web_logo(process_name: str, query: str | None = None) -> dict[str, Any]:
    process_name = normalize_process_name(process_name)
    state = _load_state()
    app_id = app_id_from_process(process_name)
    display_name = _display_name_for_process(state, process_name, app_id, query)
    rejected_sources = _rejected_sources(state, process_name)

    errors: list[str] = []
    for url in _candidate_urls(process_name, display_name, query):
        if url in rejected_sources:
            continue
        try:
            return import_logo_url(process_name, url, display_name)
        except ValueError as exc:
            errors.append(f"{url}: {exc}")

    _record_pending(state, process_name, app_id, "needs_ai_search", None, display_name, errors[-3:])
    _save_state(state)
    raise ValueError("no web logo candidate found")


def import_logo_url(process_name: str, url: str, display_name: str | None = None) -> dict[str, Any]:
    process_name = normalize_process_name(process_name)
    url = _validate_url(url)
    state = _load_state()
    if url in _rejected_sources(state, process_name):
        raise ValueError("source was already rejected")

    app_id = app_id_from_process(process_name)
    name = display_name or _display_name_for_process(state, process_name, app_id, None)
    with tempfile.TemporaryDirectory() as tmpdir:
        downloaded = Path(tmpdir) / "logo"
        image_path = _download_image(url, downloaded)
        rgb565 = _image_to_rgb565(image_path)

    output_dir = asset_root() / app_id
    output_dir.mkdir(parents=True, exist_ok=True)
    asset_file = "logo_160x160.rgb565"
    output_path = output_dir / asset_file
    output_path.write_bytes(rgb565)
    digest = hashlib.sha256(rgb565).hexdigest()
    manifest = {
        "app_id": app_id,
        "display_name": name,
        "asset_type": "rgb565",
        "asset_file": asset_file,
        "asset_width": ASSET_SIZE,
        "asset_height": ASSET_SIZE,
        "asset_hash": digest,
    }
    (output_dir / "manifest.json").write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")

    approved = state.get("approved_mappings", {})
    if isinstance(approved, dict):
        approved[process_name] = app_id
        state["approved_mappings"] = approved
    _record_pending(state, process_name, app_id, "web_candidate", url, name, [])
    _save_state(state)
    return _load_state().get("pending", {}).get(process_name, {})


def _candidate_urls(process_name: str, display_name: str, query: str | None) -> list[str]:
    slugs = _candidate_slugs(process_name, display_name, query)
    urls: list[str] = []
    for slug in slugs:
        urls.append(f"https://cdn.simpleicons.org/{urllib.parse.quote(slug)}/ffffff")
        urls.append(f"https://raw.githubusercontent.com/simple-icons/simple-icons/develop/icons/{urllib.parse.quote(slug)}.svg")
    return urls


def _candidate_slugs(process_name: str, display_name: str, query: str | None) -> list[str]:
    aliases = {
        "obs": ["obsstudio", "obs"],
        "obs64": ["obsstudio", "obs"],
        "steamwebhelper": ["steam"],
        "firefox-bin": ["firefoxbrowser", "firefox"],
        "code": ["visualstudiocode"],
        "discord": ["discord"],
        "spotify": ["spotify"],
        "vlc": ["vlcmediaplayer", "vlc"],
    }
    stem = process_name[:-4] if process_name.endswith(".exe") else process_name
    values: list[str] = []
    values.extend(aliases.get(stem, []))
    values.extend([query or "", display_name, stem])
    slugs: list[str] = []
    for value in values:
        slug = re.sub(r"[^a-z0-9]+", "", value.lower())
        if slug and slug not in slugs:
            slugs.append(slug)
    return slugs[:12]


def _download_image(url: str, output_path: Path) -> Path:
    request = urllib.request.Request(url, headers={"User-Agent": "open-aio/0.1"})
    try:
        with urllib.request.urlopen(request, timeout=8) as response:
            content_type = response.headers.get_content_type()
            if content_type not in ALLOWED_CONTENT_TYPES:
                raise ValueError(f"unsupported content type {content_type}")
            data = response.read(MAX_DOWNLOAD_BYTES + 1)
    except urllib.error.URLError as exc:
        raise ValueError(f"download failed: {exc}") from exc
    if len(data) == 0:
        raise ValueError("empty image")
    if len(data) > MAX_DOWNLOAD_BYTES:
        raise ValueError("image too large")

    suffix = ".svg" if b"<svg" in data[:512].lower() or url.lower().endswith(".svg") else ".img"
    output = output_path.with_suffix(suffix)
    output.write_bytes(data)
    if suffix == ".svg":
        png = output_path.with_suffix(".png")
        _convert_svg(output, png)
        return png
    return output


def _validate_url(url: str) -> str:
    parsed = urllib.parse.urlparse(url)
    if parsed.scheme != "https" or not parsed.netloc:
        raise ValueError("logo URL must be HTTPS")
    if len(url) > 2048:
        raise ValueError("logo URL is too long")
    return url


def _convert_svg(input_path: Path, output_path: Path) -> None:
    converter = shutil.which("convert") or shutil.which("magick")
    if converter is not None:
        try:
            subprocess.run(
                [converter, str(input_path), "-background", "none", "-resize", "256x256", str(output_path)],
                check=True,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
        except subprocess.CalledProcessError as exc:
            raise ValueError("SVG conversion failed") from exc
        return
    inkscape = shutil.which("inkscape")
    if inkscape is None:
        raise ValueError("no SVG converter available")
    try:
        subprocess.run(
            [inkscape, str(input_path), "--export-type=png", f"--export-filename={output_path}", "-w", "256", "-h", "256"],
            check=True,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
    except subprocess.CalledProcessError as exc:
        raise ValueError("SVG conversion failed") from exc


def _image_to_rgb565(image_path: Path) -> bytes:
    with Image.open(image_path) as image:
        if image.width < 16 or image.height < 16 or image.width > 4096 or image.height > 4096:
            raise ValueError("image dimensions rejected")
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


def _display_name_for_process(state: dict[str, Any], process_name: str, app_id: str, query: str | None) -> str:
    if query:
        return query.strip()[:64]
    pending = state.get("pending", {})
    item = pending.get(process_name, {}) if isinstance(pending, dict) else {}
    if isinstance(item, dict):
        value = item.get("display_name")
        if isinstance(value, str) and value:
            return value[:64]
    return display_name_from_app_id(app_id)


def _record_pending(
    state: dict[str, Any],
    process_name: str,
    app_id: str,
    status: str,
    source_icon: str | None,
    display_name: str,
    errors: list[str],
) -> None:
    pending = state.get("pending", {})
    pending[process_name] = {
        "process_name": process_name,
        "app_id": app_id,
        "display_name": display_name,
        "status": status,
        "source_icon": source_icon,
        "errors": errors,
        "updated_at": datetime.now(tz=UTC).isoformat(),
    }
    state["pending"] = pending


def _rejected_sources(state: dict[str, Any], process_name: str) -> set[str]:
    rejected = state.get("rejected_candidate_sources", {})
    values = rejected.get(process_name, []) if isinstance(rejected, dict) else []
    if not isinstance(values, list):
        return set()
    return {str(value) for value in values}


def _load_state() -> dict[str, Any]:
    path = asset_root() / "local_icon_state.json"
    if not path.exists():
        return {"approved_mappings": {}, "rejected_candidate_sources": {}, "pending": {}}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return {"approved_mappings": {}, "rejected_candidate_sources": {}, "pending": {}}


def _save_state(state: dict[str, Any]) -> None:
    path = asset_root() / "local_icon_state.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(state, indent=2, sort_keys=True) + "\n", encoding="utf-8")
