from __future__ import annotations

import logging
import base64
import json
import time
import urllib.error
import urllib.request
from contextlib import asynccontextmanager
from datetime import datetime
from threading import Lock
from urllib.parse import quote

from fastapi import Depends, FastAPI, HTTPException, Request, Response, status
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles

from .assets import asset_root, asset_url_for_manifest, default_manifest, load_manifest, serve_app_asset
from .auth import require_api_key
from .icon_resolver import approve_candidate, candidate_for_process, list_unknown_apps, reject_candidate
from .layouts import get_layout as load_layout_preset
from .layouts import list_layouts, save_layout
from .models import (
    CandidateDecision,
    LayoutSaveRequest,
    LayoutSummary,
    LogoFetchRequest,
    LogoUrlImportRequest,
    StateResponse,
    TelemetryAck,
    TelemetryRequest,
    UnknownApp,
)
from .telemetry import get_latest, update_telemetry
from .web_logos import import_logo_url, task_list, try_web_logo
from .config import SERVER_ROOT
from .designer_frames import get_frame_after, is_active as is_designer_preview_active, put_frame, set_preview_active
from .designer_state import get_storage_snapshot, put_storage_snapshot

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")
logger = logging.getLogger("open-aio-server")
AGENT_STATUS_PATH = SERVER_ROOT.parent / "pc-agent" / "logs" / "status.json"
PRESET_PREVIEWS_PATH = SERVER_ROOT / "preset_previews.json"
_PRESET_PREVIEWS_LOCK = Lock()


@asynccontextmanager
async def lifespan(app_: FastAPI):
    default_manifest()
    yield


app = FastAPI(title="Open AIO Server", version="0.1.0", lifespan=lifespan)


@app.middleware("http")
async def no_cache_designer_assets(request: Request, call_next):
    response = await call_next(request)
    if request.url.path.startswith(("/designer-app", "/nzxt-esc", "/assets")):
        response.headers["Cache-Control"] = "no-store, no-cache, must-revalidate, max-age=0"
        response.headers["Pragma"] = "no-cache"
        response.headers["Expires"] = "0"
    return response

DESIGNER_DIST = SERVER_ROOT.parent / "nzxt-esc-live" / "dist"
if not DESIGNER_DIST.exists():
    raise RuntimeError(f"required NZXT-ESC live dist is missing: {DESIGNER_DIST}")
if DESIGNER_DIST.exists():
    app.mount("/nzxt-esc", StaticFiles(directory=DESIGNER_DIST, html=True), name="nzxt-esc")
    live_assets = DESIGNER_DIST / "assets"
    if live_assets.exists():
        app.mount("/assets", StaticFiles(directory=live_assets), name="designer-assets")
        app.mount("/designer-app/assets", StaticFiles(directory=live_assets), name="legacy-designer-assets")
    live_docs = DESIGNER_DIST / "docs"
    if live_docs.exists():
        app.mount("/docs", StaticFiles(directory=live_docs), name="designer-docs")

GALLERY_ROOT = SERVER_ROOT.parent / "nzxt-esc-gallery" / "presets"
if GALLERY_ROOT.exists():
    app.mount("/designer-gallery-assets", StaticFiles(directory=GALLERY_ROOT), name="designer-gallery-assets")

SUPPORTED_GALLERY_ELEMENT_TYPES = {"text", "metric", "arc_graphic", "linear_graphic", "shape", "clock", "date"}
SUPPORTED_GALLERY_BACKGROUND_MEDIA_TYPES = {"image", "video", "url"}
GALLERY_API_CACHE = SERVER_ROOT.parent / "nzxt-esc-gallery" / "gallery-api-cache.json"
GALLERY_API_URL = "https://nzxt-esc-gallery-api.mrgogo7.workers.dev/api/gallery"


def _gallery_media_entry(media_id: str) -> tuple[dict[str, object], str] | None:
    if not GALLERY_ROOT.exists():
        return None
    for preset_dir in GALLERY_ROOT.iterdir():
        if not preset_dir.is_dir():
            continue
        preset_file = preset_dir / "ExportedPreset.json"
        if not preset_file.exists():
            continue
        try:
            data = json.loads(preset_file.read_text(encoding="utf-8"))
        except Exception:
            continue
        media = data.get("media") if isinstance(data, dict) else None
        if not isinstance(media, dict):
            continue
        entry = media.get(media_id)
        if isinstance(entry, dict) and isinstance(entry.get("data"), str):
            return entry, preset_dir.name
    return None


def _normalize_designer_storage_items(raw_items: object) -> object:
    if not isinstance(raw_items, dict):
        return raw_items
    items = dict(raw_items)
    presets_raw = items.get("nzxt-esc-dev:presets")
    if not isinstance(presets_raw, str) or not presets_raw:
        return items
    try:
        presets = json.loads(presets_raw)
    except json.JSONDecodeError:
        return items
    if not isinstance(presets, dict):
        return items

    active_id = items.get("nzxt-esc-dev:activePresetId")
    if isinstance(active_id, str) and active_id:
        items["nzxtActivePresetId"] = active_id

    changed = False
    for preset in presets.values():
        if not isinstance(preset, dict):
            continue
        background = preset.get("background")
        media_overlay = background.get("mediaOverlay") if isinstance(background, dict) else None
        if not isinstance(media_overlay, dict) or media_overlay.get("source") != "local":
            continue
        media = media_overlay.get("media")
        if not isinstance(media, dict) or media.get("type") != "local":
            continue
        media_id = str(media.get("mediaId") or "")
        if not media_id or _gallery_media_entry(media_id) is None:
            continue
        file_name = quote(str(media.get("fileName") or "media.bin"))
        media_overlay["source"] = "url"
        media_overlay["media"] = {
            "type": "url",
            "url": f"/api/designer/gallery-media/{quote(media_id)}/{file_name}",
            **({"intrinsic": media["intrinsic"]} if isinstance(media.get("intrinsic"), dict) else {}),
        }
        changed = True

    if changed:
        items["nzxt-esc-dev:presets"] = json.dumps(presets, separators=(",", ":"))
    return items


def _read_agent_status() -> dict[str, object]:
    try:
        payload = json.loads(AGENT_STATUS_PATH.read_text(encoding="utf-8"))
    except Exception:
        return {}
    return payload if isinstance(payload, dict) else {}


def _active_designer_preset(snapshot: dict[str, object]) -> tuple[str, str]:
    items = snapshot.get("items")
    if not isinstance(items, dict):
        return "", ""
    active_id = str(items.get("nzxt-esc-dev:activePresetId") or items.get("nzxtActivePresetId") or "")
    presets_raw = items.get("nzxt-esc-dev:presets")
    if not isinstance(presets_raw, str) or not active_id:
        return active_id, ""
    try:
        presets = json.loads(presets_raw)
    except json.JSONDecodeError:
        return active_id, ""
    preset = presets.get(active_id) if isinstance(presets, dict) else None
    name = preset.get("name") if isinstance(preset, dict) else ""
    return active_id, str(name or "")


def _normalized_storage_snapshot() -> dict[str, object]:
    snapshot = get_storage_snapshot()
    snapshot["items"] = _normalize_designer_storage_items(snapshot.get("items"))
    return snapshot


def _read_preset_previews() -> dict[str, str]:
    try:
      payload = json.loads(PRESET_PREVIEWS_PATH.read_text(encoding="utf-8"))
    except Exception:
      return {}
    if not isinstance(payload, dict):
      return {}
    items = payload.get("items")
    if not isinstance(items, dict):
      return {}
    previews: dict[str, str] = {}
    for raw_key, raw_value in items.items():
      key = str(raw_key)
      value = str(raw_value)
      if not key or not value.startswith("data:image/"):
        continue
      if len(value.encode("utf-8")) > 1024 * 1024:
        continue
      previews[key[:160]] = value
    return previews


def _write_preset_previews(items: dict[str, str]) -> None:
    PRESET_PREVIEWS_PATH.write_text(
        json.dumps({"items": items, "updated_at": time.time()}, ensure_ascii=False),
        encoding="utf-8",
    )


def _fallback_gallery_items() -> list[dict[str, object]]:
    if not GALLERY_ROOT.exists():
        return []
    items: list[dict[str, object]] = []
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    for preset_dir in sorted((item for item in GALLERY_ROOT.iterdir() if item.is_dir()), key=lambda item: item.name.lower()):
        preset_file = preset_dir / "ExportedPreset.json"
        if not preset_file.exists():
            continue
        try:
            data = json.loads(preset_file.read_text(encoding="utf-8"))
            preset = data.get("preset") if isinstance(data, dict) else {}
            items.append({
                "id": preset_dir.name,
                "name": str(preset.get("name") or preset_dir.name),
                "description": "",
                "author": "",
                "contact": None,
                "tags": [],
                "downloads": 0,
                "created_at": now,
                "updated_at": now,
                "is_active": 1,
            })
        except Exception as exc:
            logger.warning("failed to read gallery preset metadata %s: %s", preset_file, exc)
    return items


def _load_gallery_api_items() -> list[dict[str, object]]:
    if GALLERY_API_CACHE.exists():
        try:
            cached = json.loads(GALLERY_API_CACHE.read_text(encoding="utf-8"))
            if isinstance(cached, dict) and isinstance(cached.get("data"), list):
                return cached["data"]
        except Exception as exc:
            logger.warning("failed to read gallery api cache: %s", exc)

    try:
        request = urllib.request.Request(GALLERY_API_URL, headers={"Accept": "application/json"})
        with urllib.request.urlopen(request, timeout=5) as response:
            payload = json.loads(response.read().decode("utf-8"))
        if isinstance(payload, dict) and payload.get("success") and isinstance(payload.get("data"), list):
            try:
                GALLERY_API_CACHE.parent.mkdir(parents=True, exist_ok=True)
                GALLERY_API_CACHE.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
            except Exception as exc:
                logger.warning("failed to write gallery api cache: %s", exc)
            return payload["data"]
    except Exception as exc:
        logger.warning("failed to fetch gallery api, using local fallback: %s", exc)

    return _fallback_gallery_items()


def _load_gallery_preset_envelope(preset_id: str) -> dict[str, object] | None:
    if not GALLERY_ROOT.exists():
        return None
    preset_file = GALLERY_ROOT / preset_id / "ExportedPreset.json"
    if not preset_file.exists():
        return None
    try:
        payload = json.loads(preset_file.read_text(encoding="utf-8"))
    except Exception as exc:
        logger.warning("failed to read gallery preset %s: %s", preset_file, exc)
        return None
    return payload if isinstance(payload, dict) else None


def _number_value(value: object, fallback: float) -> float:
    return value if isinstance(value, (int, float)) and not isinstance(value, bool) else fallback


def _string_value(value: object, fallback: str) -> str:
    return value if isinstance(value, str) and value else fallback


def _normalized_to_lcd(value: object) -> int:
    return round(_number_value(value, 0) * 250)


def _normalize_angle(value: object) -> float | None:
    if not isinstance(value, (int, float)) or isinstance(value, bool):
        return None
    normalized = float(value) % 360
    return None if normalized == 0 else normalized


def _map_gallery_metric(value: object) -> str:
    metric_map = {
        "cpu_temp": "cpuTemp",
        "cpu_load": "cpuLoad",
        "cpu_frequency": "cpuClock",
        "cpu_clock": "cpuClock",
        "cpu_power": "cpuPower",
        "ram_usage": "ramUsage",
        "memory_usage": "ramUsage",
        "ssd_temp": "ssdTemp",
        "liquid_temp": "liquidTemp",
        "gpu_temp": "gpuTemp",
        "gpu_load": "gpuLoad",
        "gpu_frequency": "gpuClock",
        "gpu_clock": "gpuClock",
    }
    return metric_map.get(str(value), "cpuTemp")


def _convert_gallery_element(element: object) -> dict[str, object] | None:
    if not isinstance(element, dict):
        return None
    config = element.get("config") if isinstance(element.get("config"), dict) else {}
    transform = element.get("transform") if isinstance(element.get("transform"), dict) else {}
    element_type = str(element.get("elementType") or "")
    base: dict[str, object] = {
        "id": _string_value(element.get("id"), f"gallery-{int(time.time() * 1000)}"),
        "x": _normalized_to_lcd(transform.get("x")),
        "y": _normalized_to_lcd(transform.get("y")),
        "zIndex": int(_number_value(element.get("typeSeq"), 0)),
    }
    angle = _normalize_angle(transform.get("rotateDeg"))
    if angle is not None:
        base["angle"] = angle

    if element_type == "text":
        return {
            **base,
            "type": "text",
            "data": {
                "text": _string_value(config.get("content"), "Text"),
                "textColor": _string_value(config.get("color"), "#ffffff"),
                "textSize": _number_value(config.get("fontSize"), 45),
            },
        }
    if element_type == "metric":
        return {
            **base,
            "type": "metric",
            "data": {
                "metric": _map_gallery_metric(config.get("metricType")),
                "numberColor": _string_value(config.get("color"), "#ffffff"),
                "numberSize": _number_value(config.get("fontSize"), 80),
                "textColor": "transparent",
                "textSize": 0,
                "showLabel": False,
            },
        }
    if element_type == "arc_graphic":
        return {
            **base,
            "type": "arc_graphic",
            "data": {
                "sourceMetric": _map_gallery_metric(config.get("sourceMetric")),
                "strokeWidth": _number_value(config.get("strokeWidth"), 24),
                "totalAngle": _number_value(config.get("totalAngle"), 234),
                "size": _number_value(config.get("size"), 180),
                "strokeColor": _string_value(config.get("strokeColor"), "rgba(255, 255, 255, 1)"),
                "trackEnabled": config.get("trackEnabled") is not False,
                "trackColor": _string_value(config.get("trackColor"), "rgba(255, 255, 255, 0.18)"),
                "hotspotColor": _string_value(config.get("hotspotColor"), "#ffffff"),
            },
        }
    if element_type == "shape":
        return {
            **base,
            "type": "shape",
            "data": {
                "width": _number_value(config.get("width"), 120),
                "height": _number_value(config.get("height"), 60),
                "radius": _number_value(config.get("radius"), 0),
                "fillColor": _string_value(config.get("fillColor"), "rgba(255, 255, 255, 0.18)"),
                "borderColor": _string_value(config.get("borderColor"), "transparent"),
                "borderWidth": _number_value(config.get("borderWidth"), 0),
            },
        }
    if element_type == "linear_graphic":
        return {
            **base,
            "type": "linear_graphic",
            "data": {
                "sourceMetric": _map_gallery_metric(config.get("sourceMetric")),
                "width": _number_value(config.get("width"), 240),
                "height": _number_value(config.get("height"), 32),
                "radius": _number_value(config.get("radius"), 0),
                "fillColor": _string_value(config.get("fillColor"), "rgba(255, 255, 255, 1)"),
                "outlineColor": _string_value(config.get("outlineColor"), "transparent"),
                "outlineWidth": _number_value(config.get("outlineWidth"), 0),
            },
        }
    if element_type == "clock":
        time_format = _string_value(config.get("timeFormat"), "hh:mm")
        return {
            **base,
            "type": "clock",
            "data": {
                "format": "HH:mm:ss" if "ss" in time_format else "HH:mm",
                "mode": "12h" if _string_value(config.get("timeSystem"), "24") == "12" else "24h",
                "fontSize": _number_value(config.get("fontSize"), 45),
                "color": _string_value(config.get("color"), "#ffffff"),
                "font": "digital" if "digit" in _string_value(config.get("fontFamily"), "").lower() else "default",
            },
        }
    if element_type == "date":
        return {
            **base,
            "type": "date",
            "data": {
                "format": _string_value(config.get("formatString"), _string_value(config.get("formatPreset"), "YYYY-MM-DD")),
                "fontSize": _number_value(config.get("fontSize"), 45),
                "color": _string_value(config.get("color"), "#ffffff"),
            },
        }
    return None


def _convert_gallery_preset_to_v6(envelope: dict[str, object], stored_preset_id: str, name: str) -> dict[str, object]:
    preset = envelope.get("preset") if isinstance(envelope.get("preset"), dict) else {}
    background = preset.get("background") if isinstance(preset.get("background"), dict) else {}
    background_base = background.get("base") if isinstance(background.get("base"), dict) else {}
    media_overlay = background.get("mediaOverlay") if isinstance(background.get("mediaOverlay"), dict) else {}
    media = media_overlay.get("media") if isinstance(media_overlay.get("media"), dict) else {}
    transform = media_overlay.get("transform") if isinstance(media_overlay.get("transform"), dict) else {}
    overlay = preset.get("overlay") if isinstance(preset.get("overlay"), dict) else {}

    media_url = _string_value(media.get("url"), "")
    if not media_url and background_base.get("sourceType") != "color":
        media_url = _string_value(background_base.get("url"), "")
    elements = [
        converted
        for converted in (_convert_gallery_element(element) for element in overlay.get("elements", []) if isinstance(overlay.get("elements"), list))
        if converted is not None
    ]
    now = datetime.now().astimezone().isoformat()
    return {
        "id": stored_preset_id,
        "name": name,
        "preset": {
            "schemaVersion": 3,
            "exportedAt": _string_value(envelope.get("exportedAt"), now),
            "appVersion": _string_value((envelope.get("app") or {}).get("version") if isinstance(envelope.get("app"), dict) else None, "gallery"),
            "presetName": name,
            "background": {
                "url": media_url,
                "settings": {
                    "scale": _number_value(transform.get("scale"), 1) * _number_value(transform.get("autoScale"), 1),
                    "x": _number_value(transform.get("offsetX"), 0),
                    "y": _number_value(transform.get("offsetY"), 0),
                    "fit": "cover",
                    "align": "center",
                    "loop": True,
                    "autoplay": True,
                    "mute": True,
                    "resolution": "640x640",
                    "backgroundColor": _string_value(background_base.get("color"), "#000000"),
                },
                "source": {"type": "remote", "url": media_url},
            },
            "overlay": {
                "mode": "custom" if elements and overlay.get("enabled") is not False else "none",
                "elements": elements,
                "zOrder": [str(element["id"]) for element in elements],
            },
            "misc": {
                "showGuide": False,
                "importedFrom": "gallery-preset",
                "sourceGalleryId": preset.get("sourceGalleryId") or preset.get("id"),
            },
        },
        "isDefault": False,
        "createdAt": now,
        "updatedAt": now,
    }


def _activate_gallery_preset_for_renderer(preset_id: str) -> str | None:
    envelope = _load_gallery_preset_envelope(preset_id)
    preset = envelope.get("preset") if isinstance(envelope, dict) else None
    if not isinstance(preset, dict):
        return None

    name = str(preset.get("name") or preset_id)
    renderer_preset_id = f"gallery-{preset_id}"
    renderer_preset = dict(preset)
    renderer_preset["id"] = renderer_preset_id
    renderer_preset["name"] = name
    renderer_preset["sourceGalleryId"] = preset_id

    snapshot = get_storage_snapshot()
    items = snapshot.get("items")
    if not isinstance(items, dict):
        items = {}
    items = {str(key): str(value) for key, value in items.items()}

    try:
        presets = json.loads(items.get("nzxt-esc-dev:presets", "{}"))
    except Exception:
        presets = {}
    if not isinstance(presets, dict):
        presets = {}
    presets[renderer_preset_id] = renderer_preset

    try:
        order = json.loads(items.get("nzxt-esc-dev:presetOrder", "[]"))
    except Exception:
        order = []
    if not isinstance(order, list):
        order = []
    order = [str(item) for item in order if str(item) != renderer_preset_id]
    order.append(renderer_preset_id)

    items["nzxt-esc-dev:presets"] = json.dumps(presets, separators=(",", ":"))
    items["nzxt-esc-dev:presetOrder"] = json.dumps(order, separators=(",", ":"))
    items["nzxt-esc-dev:activePresetId"] = renderer_preset_id

    try:
        manager_presets = json.loads(items.get("nzxtPresets", "[]"))
    except Exception:
        manager_presets = []
    if not isinstance(manager_presets, list):
        manager_presets = []
    stored_preset = _convert_gallery_preset_to_v6(envelope, renderer_preset_id, name)
    manager_presets = [
        existing
        for existing in manager_presets
        if not (isinstance(existing, dict) and existing.get("id") == renderer_preset_id)
    ]
    manager_presets.append(stored_preset)
    items["nzxtPresets"] = json.dumps(manager_presets, separators=(",", ":"))
    items["nzxtActivePresetId"] = renderer_preset_id

    put_storage_snapshot(items)
    return renderer_preset_id


@app.get("/health")
def health() -> dict[str, object]:
    return {
        "ok": True,
        "service": "open-aio-server",
        "version": app.version,
        "time": datetime.now().astimezone().isoformat(),
    }


@app.get("/api/cam/status")
def cam_status() -> dict[str, object]:
    storage = get_storage_snapshot()
    active_id, preset_name = _active_designer_preset(storage)
    agent = _read_agent_status()
    render_url = (
        f"/nzxt-esc/?kraken=1&mockLcd=480&mockShape=circle&presetId={quote(active_id)}"
        if active_id
        else "/nzxt-esc/?kraken=1&mockLcd=480&mockShape=circle"
    )
    return {
        "ok": True,
        "designer_preview_active": is_designer_preview_active(),
        "active_preset_id": active_id,
        "active_preset_name": preset_name,
        "render_url": render_url,
        "agent": {
            "ok": bool(agent.get("ok")),
            "usb_status": agent.get("usb_status", "unknown"),
            "usb_error": agent.get("usb_error"),
            "transport_mode": agent.get("transport_mode", "unknown"),
            "active_process": agent.get("active_process", ""),
            "active_window_title": agent.get("active_window_title", ""),
            "gpu_temp": agent.get("gpu_temp"),
            "gpu_load": agent.get("gpu_load"),
            "cpu_temp": agent.get("cpu_temp"),
            "ram_used_percent": agent.get("ram_used_percent"),
            "updated_at": agent.get("updated_at", ""),
        },
        "updated_at": time.time(),
    }


@app.get("/cam", response_class=HTMLResponse)
def cam_page() -> HTMLResponse:
    return HTMLResponse(
        """
<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width,initial-scale=1">
  <title>Cooler CAM Control</title>
  <style>
    :root { color-scheme: dark; --bg: #0f1115; --panel: #171a20; --line: #2a2f39; --text: #f4f7fb; --muted: #9aa4b2; --ok: #27c560; --warn: #f5be30; --bad: #e24141; }
    * { box-sizing: border-box; }
    body { margin: 0; font-family: Segoe UI, system-ui, sans-serif; background: var(--bg); color: var(--text); }
    header { height: 54px; display: flex; align-items: center; justify-content: space-between; padding: 0 18px; border-bottom: 1px solid var(--line); background: #11141a; }
    h1 { font-size: 16px; margin: 0; font-weight: 650; letter-spacing: 0; }
    main { max-width: 1040px; margin: 0 auto; padding: 18px; display: grid; grid-template-columns: minmax(0, 1fr) 320px; gap: 16px; }
    section { border-top: 1px solid var(--line); padding-top: 14px; margin-top: 14px; }
    section:first-child { border-top: 0; padding-top: 0; margin-top: 0; }
    h2 { font-size: 13px; color: var(--muted); text-transform: uppercase; margin: 0 0 10px; font-weight: 650; letter-spacing: .08em; }
    .panel { background: var(--panel); border: 1px solid var(--line); border-radius: 8px; padding: 14px; }
    .grid { display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 10px; }
    .metric { min-height: 62px; border: 1px solid var(--line); border-radius: 8px; padding: 10px; background: #12161d; }
    .label { color: var(--muted); font-size: 12px; margin-bottom: 5px; }
    .value { font-size: 18px; font-weight: 650; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
    .small { font-size: 13px; color: var(--muted); overflow-wrap: anywhere; }
    .status { display: inline-flex; align-items: center; gap: 8px; font-size: 13px; color: var(--muted); }
    .dot { width: 10px; height: 10px; border-radius: 50%; background: var(--bad); }
    .dot.ok { background: var(--ok); }
    .dot.warn { background: var(--warn); }
    .actions { display: flex; flex-wrap: wrap; gap: 8px; }
    button, a.button { appearance: none; border: 1px solid var(--line); background: #202631; color: var(--text); border-radius: 7px; padding: 9px 11px; font: inherit; text-decoration: none; cursor: pointer; }
    button.primary, a.primary { background: #12304d; border-color: #245987; }
    iframe { width: 100%; aspect-ratio: 1 / 1; border: 1px solid var(--line); border-radius: 8px; background: #000; }
    @media (max-width: 820px) { main { grid-template-columns: 1fr; } .grid { grid-template-columns: 1fr; } }
  </style>
</head>
<body>
  <header>
    <h1>Cooler CAM Control</h1>
    <div class="status"><span id="topDot" class="dot"></span><span id="topStatus">checking</span></div>
  </header>
  <main>
    <div class="panel">
      <section>
        <h2>Stream</h2>
        <div class="grid">
          <div class="metric"><div class="label">USB</div><div class="value" id="usb">unknown</div></div>
          <div class="metric"><div class="label">Browser Preview</div><div class="value" id="preview">unknown</div></div>
          <div class="metric"><div class="label">Transport</div><div class="value" id="transport">unknown</div></div>
          <div class="metric"><div class="label">Active Preset</div><div class="value" id="preset">none</div></div>
        </div>
      </section>
      <section>
        <h2>Controls</h2>
        <div class="actions">
          <a class="button primary" href="/designer" target="_blank">Open Editor</a>
          <a class="button" id="renderLink" href="/nzxt-esc/?kraken=1&mockLcd=480&mockShape=circle" target="_blank">Open 480 Render</a>
          <button id="refreshBtn">Refresh</button>
        </div>
      </section>
      <section>
        <h2>Sensors</h2>
        <div class="grid">
          <div class="metric"><div class="label">GPU</div><div class="value" id="gpu">-</div></div>
          <div class="metric"><div class="label">CPU</div><div class="value" id="cpu">-</div></div>
          <div class="metric"><div class="label">RAM</div><div class="value" id="ram">-</div></div>
          <div class="metric"><div class="label">Foreground</div><div class="value" id="foreground">-</div></div>
        </div>
      </section>
      <section>
        <h2>State</h2>
        <div class="small" id="detail">-</div>
      </section>
    </div>
    <aside class="panel">
      <h2>Render Surface</h2>
      <iframe id="renderFrame" src="/nzxt-esc/?kraken=1&mockLcd=480&mockShape=circle" title="480 render preview"></iframe>
    </aside>
  </main>
  <script>
    const $ = (id) => document.getElementById(id);
    function text(value, fallback = "-") {
      return value === null || value === undefined || value === "" ? fallback : String(value);
    }
    async function refresh() {
      try {
        const res = await fetch("/api/cam/status", { cache: "no-store" });
        const data = await res.json();
        const agent = data.agent || {};
        const usb = text(agent.usb_status, "unknown");
        $("usb").textContent = usb;
        $("preview").textContent = data.designer_preview_active ? "live" : "idle";
        $("transport").textContent = text(agent.transport_mode, "unknown");
        $("preset").textContent = data.active_preset_name ? `${data.active_preset_name}` : text(data.active_preset_id, "none");
        $("gpu").textContent = `${text(agent.gpu_temp)} C / ${text(agent.gpu_load)}%`;
        $("cpu").textContent = agent.cpu_temp === null || agent.cpu_temp === undefined ? "not available" : `${agent.cpu_temp} C`;
        $("ram").textContent = `${text(agent.ram_used_percent)}%`;
        $("foreground").textContent = text(agent.active_process, "-");
        $("detail").textContent = `${text(agent.active_window_title)} · updated ${text(agent.updated_at)}`;
        $("renderLink").href = data.render_url;
        if ($("renderFrame").dataset.src !== data.render_url) {
          $("renderFrame").dataset.src = data.render_url;
          $("renderFrame").src = data.render_url;
        }
        const healthy = usb === "designer_preview" || usb === "ok" || usb === "owned_by_signalrgb";
        $("topDot").className = `dot ${healthy ? "ok" : "warn"}`;
        $("topStatus").textContent = data.designer_preview_active ? "preview live" : `usb ${usb}`;
      } catch (err) {
        $("topDot").className = "dot";
        $("topStatus").textContent = err.message || String(err);
      }
    }
    $("refreshBtn").addEventListener("click", refresh);
    refresh();
    setInterval(refresh, 1000);
  </script>
</body>
</html>
        """
    )


@app.get("/designer-app/{path:path}")
def legacy_designer_app_redirect(path: str = "") -> RedirectResponse:
    target = f"/nzxt-esc/{path}" if path else "/nzxt-esc/config.html"
    return RedirectResponse(url=target)


@app.get("/api/v1/designer/gallery")
def get_designer_gallery() -> dict[str, object]:
    items: list[dict[str, object]] = []
    if not GALLERY_ROOT.exists():
        return {"ok": True, "items": items}

    for preset_dir in sorted((item for item in GALLERY_ROOT.iterdir() if item.is_dir()), key=lambda item: item.name.lower()):
        preset_file = preset_dir / "ExportedPreset.json"
        if not preset_file.exists():
            continue
        try:
            data = json.loads(preset_file.read_text(encoding="utf-8"))
            preset = data.get("preset") if isinstance(data, dict) else {}
            overlay = preset.get("overlay") if isinstance(preset, dict) else {}
            elements = overlay.get("elements") if isinstance(overlay, dict) else []
            background = preset.get("background") if isinstance(preset, dict) else {}
            media_overlay = background.get("mediaOverlay") if isinstance(background, dict) else {}
            media = media_overlay.get("media") if isinstance(media_overlay, dict) else {}
            media_type = str(media.get("type") or "") if isinstance(media, dict) else ""
            media_url = str(media.get("url") or "") if isinstance(media, dict) else ""
            element_types = sorted({
                str(element.get("elementType"))
                for element in elements
                if isinstance(element, dict) and element.get("elementType")
            })
            unsupported = [element_type for element_type in element_types if element_type not in SUPPORTED_GALLERY_ELEMENT_TYPES]
            background_issues: list[str] = []
            if media_type and media_type not in SUPPORTED_GALLERY_BACKGROUND_MEDIA_TYPES:
                background_issues.append(f"background:{media_type}")
            if media_type and not media_url:
                background_issues.append("background:missing-url")
            thumb_name = "Thumb.png"
            if not (preset_dir / thumb_name).exists():
                thumbs = sorted(preset_dir.glob("Thumb*.png"))
                thumb_name = thumbs[0].name if thumbs else ""
            items.append({
                "id": preset_dir.name,
                "name": str(preset.get("name") or preset_dir.name),
                "thumbUrl": f"/designer-gallery-assets/{preset_dir.name}/{thumb_name}" if thumb_name else None,
                "presetUrl": f"/designer-gallery-assets/{preset_dir.name}/ExportedPreset.json",
                "elementCount": len(elements) if isinstance(elements, list) else 0,
                "elementTypes": element_types,
                "unsupportedTypes": unsupported,
                "backgroundMediaType": media_type or None,
                "hasBackgroundAnimation": bool(media_url),
                "backgroundIssues": background_issues,
                "fullySupported": len(unsupported) == 0 and len(background_issues) == 0,
            })
        except Exception as exc:
            logger.warning("failed to read gallery preset %s: %s", preset_file, exc)

    return {"ok": True, "items": items}


@app.get("/api/gallery")
def get_nzxt_esc_gallery() -> dict[str, object]:
    available_ids = {item.name for item in GALLERY_ROOT.iterdir() if item.is_dir()} if GALLERY_ROOT.exists() else set()
    items = [
        item for item in _load_gallery_api_items()
        if str(item.get("id") or "") in available_ids
    ]
    if not items:
        items = _fallback_gallery_items()
    return {"success": True, "data": items}


@app.post("/api/gallery/{preset_id}/download")
def post_nzxt_esc_gallery_download(preset_id: str) -> dict[str, object]:
    downloads = 0
    for item in _load_gallery_api_items():
        if item.get("id") == preset_id:
            try:
                downloads = int(item.get("downloads") or 0) + 1
            except Exception:
                downloads = 1
            break
    renderer_preset_id = _activate_gallery_preset_for_renderer(preset_id)
    return {"success": True, "downloads": downloads, "activePresetId": renderer_preset_id}


@app.get("/api/designer/gallery-media/{media_id}")
def get_designer_gallery_media(media_id: str) -> Response:
    return _designer_gallery_media_response(media_id)


@app.get("/api/designer/gallery-media/{media_id}/{file_name}")
def get_designer_gallery_media_named(media_id: str, file_name: str) -> Response:
    return _designer_gallery_media_response(media_id)


def _designer_gallery_media_response(media_id: str) -> Response:
    resolved = _gallery_media_entry(media_id)
    if resolved is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="gallery media not found")
    entry, preset_id = resolved
    data = entry.get("data")
    file_type = str(entry.get("fileType") or "application/octet-stream")
    try:
        body = base64.b64decode(str(data), validate=True)
    except Exception as exc:
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="invalid gallery media data") from exc
    response = Response(content=body, media_type=file_type)
    response.headers["Cache-Control"] = "public, max-age=86400"
    response.headers["X-Gallery-Preset-ID"] = preset_id
    if entry.get("fileName"):
        response.headers["Content-Disposition"] = f'inline; filename="{entry["fileName"]}"'
    return response


@app.post("/api/v1/device/{device_id}/telemetry", response_model=TelemetryAck, dependencies=[Depends(require_api_key)])
def post_telemetry(device_id: str, payload: TelemetryRequest) -> TelemetryAck:
    record = update_telemetry(device_id, payload)
    logger.info("telemetry device=%s app=%s process=%s", device_id, record.app_id, record.active_process)
    return TelemetryAck(ok=True, device_id=device_id, app_id=record.app_id)


@app.get("/api/v1/device/{device_id}/state", response_model=StateResponse, dependencies=[Depends(require_api_key)])
def get_state(device_id: str) -> StateResponse:
    record = get_latest(device_id)
    manifest = load_manifest(record.app_id)
    review = candidate_for_process(record.active_process)
    local_now = datetime.now().astimezone()
    return StateResponse(
        device_id=device_id,
        app_id=str(manifest["app_id"]),
        display_name=str(manifest["display_name"]),
        asset_type=str(manifest["asset_type"]),
        asset_url=asset_url_for_manifest(manifest),
        asset_hash=str(manifest["asset_hash"]),
        asset_width=int(manifest["asset_width"]),
        asset_height=int(manifest["asset_height"]),
        cpu_temp=record.cpu_temp,
        gpu_temp=record.gpu_temp,
        cpu_load=record.cpu_load,
        gpu_load=record.gpu_load,
        ram_used_percent=record.ram_used_percent,
        ram_total_mb=record.ram_total_mb,
        ssd_temp=record.ssd_temp,
        cpu_frequency=record.cpu_frequency,
        gpu_frequency=record.gpu_frequency,
        cpu_power=record.cpu_power,
        gpu_power=record.gpu_power,
        gpu_fan_speed=record.gpu_fan_speed,
        updated_at=record.updated_at,
        local_time=local_now.strftime("%H:%M"),
        local_date=local_now.strftime("%d %b").upper(),
        review_available=review is not None,
        review_process_name=str(review["process_name"]) if review else None,
        review_app_id=str(review["app_id"]) if review else None,
        review_display_name=str(review["display_name"]) if review else None,
        review_status=str(review["status"]) if review else None,
    )


def _nzxt_monitoring_payload(device_id: str) -> dict[str, object]:
    record = get_latest(device_id)
    ram_total_mb = record.ram_total_mb if record.ram_total_mb and record.ram_total_mb > 0 else 32768.0
    ram_used_mb = ram_total_mb * max(0.0, min(100.0, record.ram_used_percent)) / 100.0
    cpu_load = max(0.0, min(100.0, record.cpu_load)) / 100.0
    gpu_load = None if record.gpu_load is None else max(0.0, min(100.0, record.gpu_load)) / 100.0
    cpu_power = record.cpu_power
    if cpu_power is None:
        cpu_power = round(cpu_load * 120.0, 1)
    liquid_temp = record.gpu_temp if record.gpu_temp is not None else record.cpu_temp
    if liquid_temp is None:
        liquid_temp = 30.0
    return {
        "cpus": [
            {
                "name": "CPU",
                "temperature": record.cpu_temp,
                "load": cpu_load,
                "frequency": record.cpu_frequency,
                "maxFrequency": 5500,
                "power": cpu_power,
                "tdp": 120,
            }
        ],
        "gpus": [
            {
                "name": "GPU",
                "temperature": record.gpu_temp,
                "load": gpu_load,
                "frequency": record.gpu_frequency,
                "maxFrequency": 3000,
                "power": record.gpu_power,
                "fanSpeed": record.gpu_fan_speed,
                "maxFanSpeed": 3000,
            }
        ],
        "ram": {
            "inUse": round(ram_used_mb),
            "totalSize": round(ram_total_mb),
            "usedPercent": record.ram_used_percent,
        },
        "storage": [
            {
                "name": "SSD",
                "temperature": record.ssd_temp,
            }
        ],
        "ssd": {
            "temperature": record.ssd_temp,
        },
        "kraken": {
            "liquidTemperature": liquid_temp,
        },
        "updatedAt": record.updated_at.isoformat(),
        "source": "open-aio-agent",
    }


@app.get("/api/nzxt/v1/monitoring")
def get_local_nzxt_monitoring(device_id: str = "cooler-display-01") -> dict[str, object]:
    return {"ok": True, "data": _nzxt_monitoring_payload(device_id)}


@app.get("/api/v1/assets/apps/{app_id}/{asset_file}", dependencies=[Depends(require_api_key)])
def get_asset(app_id: str, asset_file: str):
    return serve_app_asset(app_id, asset_file)


@app.get("/api/v1/unknown-apps", response_model=list[UnknownApp], dependencies=[Depends(require_api_key)])
def get_unknown_apps() -> list[UnknownApp]:
    return [UnknownApp(**item) for item in list_unknown_apps()]


@app.post("/api/v1/apps/approve-candidate", dependencies=[Depends(require_api_key)])
def approve_app_candidate(payload: CandidateDecision) -> dict[str, object]:
    try:
        item = approve_candidate(payload.process_name, payload.app_id)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    return {"ok": True, "candidate": item}


@app.post("/api/v1/apps/reject-candidate", dependencies=[Depends(require_api_key)])
def reject_app_candidate(payload: CandidateDecision) -> dict[str, object]:
    item = reject_candidate(payload.process_name)
    if isinstance(item, dict) and item.get("status") == "needs_ai_search":
        try:
            item = try_web_logo(payload.process_name)
        except ValueError:
            pass
    return {"ok": True, "candidate": item}


@app.get("/api/v1/logo-tasks", response_model=list[UnknownApp], dependencies=[Depends(require_api_key)])
def get_logo_tasks() -> list[UnknownApp]:
    return [UnknownApp(**item) for item in task_list()]


@app.get("/api/v1/icon-library", dependencies=[Depends(require_api_key)])
def get_icon_library() -> list[dict[str, object]]:
    icons: list[dict[str, object]] = []
    for manifest_path in sorted(asset_root().glob("*/manifest.json")):
        try:
            manifest = load_manifest(manifest_path.parent.name)
        except Exception:
            continue
        asset_file = str(manifest.get("asset_file", ""))
        asset_path = manifest_path.parent / asset_file
        if not asset_file or not asset_path.exists():
            continue
        icons.append(
            {
                "process_name": "",
                "app_id": str(manifest["app_id"]),
                "display_name": str(manifest["display_name"]),
                "status": "library",
                "source_icon": None,
                "updated_at": "",
            }
        )
    return icons


@app.get("/api/v1/layouts", response_model=list[LayoutSummary], dependencies=[Depends(require_api_key)])
def get_layouts() -> list[LayoutSummary]:
    return [LayoutSummary(**item) for item in list_layouts()]


@app.get("/api/v1/layouts/{layout_id}", dependencies=[Depends(require_api_key)])
def get_layout_preset(layout_id: str) -> dict[str, object]:
    try:
        return {"ok": True, "layout": load_layout_preset(layout_id)}
    except FileNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="layout not found") from exc
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc


@app.post("/api/v1/designer/frame", dependencies=[Depends(require_api_key)])
async def post_designer_frame(request: Request) -> dict[str, object]:
    content_type = request.headers.get("content-type", "").split(";", 1)[0].strip().lower()
    client_id = request.headers.get("x-designer-client-id")
    data = await request.body()
    try:
        frame = put_frame(data, content_type, client_id)
    except PermissionError as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    return {"ok": True, "sequence": frame.sequence, "bytes": len(frame.data)}


@app.get("/api/v1/designer/frame", dependencies=[Depends(require_api_key)])
def get_designer_frame(since: int = 0) -> Response:
    frame = get_frame_after(since)
    if frame is None:
        return Response(
            status_code=status.HTTP_204_NO_CONTENT,
            headers={"X-Designer-Preview-Active": "1" if is_designer_preview_active() else "0"},
        )
    return Response(
        content=frame.data,
        media_type=frame.content_type,
        headers={
            "X-Frame-Sequence": str(frame.sequence),
            "X-Designer-Preview-Active": "1",
        },
    )


@app.get("/api/v1/designer/status", dependencies=[Depends(require_api_key)])
def get_designer_status() -> dict[str, object]:
    return {"ok": True, "active": is_designer_preview_active()}


@app.post("/api/v1/designer/preview-active", dependencies=[Depends(require_api_key)])
async def post_designer_preview_active(request: Request) -> dict[str, object]:
    try:
        payload = await request.json()
    except Exception:
        payload = {}
    active = bool(payload.get("active"))
    client_id = str(payload.get("client_id") or request.headers.get("x-designer-client-id") or "")
    try:
        return {"ok": True, "active": set_preview_active(active, client_id)}
    except PermissionError as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc


@app.post("/api/v1/designer/client-log", dependencies=[Depends(require_api_key)])
async def post_designer_client_log(request: Request) -> dict[str, object]:
    try:
        payload = await request.json()
    except Exception:
        payload = {"message": (await request.body()).decode("utf-8", errors="replace")}
    level = str(payload.get("level") or "info").lower()
    message = str(payload.get("message") or "")
    details = str(payload.get("details") or "")
    url = str(payload.get("url") or "")
    log_message = "designer-ui level=%s message=%s details=%s url=%s"
    if level == "error":
        logger.error(log_message, level, message, details, url)
    elif level == "warning":
        logger.warning(log_message, level, message, details, url)
    else:
        logger.info(log_message, level, message, details, url)
    return {"ok": True}


@app.post("/api/v1/designer/storage", dependencies=[Depends(require_api_key)])
async def post_designer_storage(request: Request) -> dict[str, object]:
    try:
        payload = await request.json()
        return put_storage_snapshot(_normalize_designer_storage_items(payload.get("items")))
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc


@app.get("/api/v1/designer/storage", dependencies=[Depends(require_api_key)])
def get_designer_storage() -> dict[str, object]:
    return _normalized_storage_snapshot()


@app.post("/api/designer/storage")
async def post_local_designer_storage(request: Request) -> dict[str, object]:
    try:
        payload = await request.json()
        return put_storage_snapshot(_normalize_designer_storage_items(payload.get("items")))
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc


@app.get("/api/designer/storage")
def get_local_designer_storage() -> dict[str, object]:
    return _normalized_storage_snapshot()


@app.post("/api/designer/preset-previews")
async def post_local_preset_previews(request: Request) -> dict[str, object]:
    payload = await request.json()
    raw_items = payload.get("items") if isinstance(payload, dict) else None
    if not isinstance(raw_items, dict):
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="items must be an object")
    cleaned: dict[str, str] = {}
    for raw_key, raw_value in raw_items.items():
        key = str(raw_key).strip()
        value = str(raw_value)
        if not key or not value.startswith("data:image/"):
            continue
        if len(value.encode("utf-8")) > 1024 * 1024:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=f"preview too large: {key}")
        cleaned[key[:160]] = value
    with _PRESET_PREVIEWS_LOCK:
        items = _read_preset_previews()
        items.update(cleaned)
        _write_preset_previews(items)
    return {"ok": True, "count": len(cleaned)}


@app.get("/api/designer/preset-previews")
def get_local_preset_previews() -> dict[str, object]:
    with _PRESET_PREVIEWS_LOCK:
        return {"ok": True, "items": _read_preset_previews()}


@app.get("/api/v1/designer/media-proxy")
def proxy_designer_media(url: str) -> Response:
    if not (url.startswith("https://") or url.startswith("http://")):
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="only http(s) URLs are supported")
    request = urllib.request.Request(
        url,
        headers={
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) CoolerDisplayDesigner/0.1",
            "Accept": "image/avif,image/webp,image/apng,image/svg+xml,image/*,*/*;q=0.8",
        },
    )
    try:
        with urllib.request.urlopen(request, timeout=8) as upstream:
            content_type = upstream.headers.get("content-type", "application/octet-stream").split(";", 1)[0].lower()
            if not content_type.startswith("image/"):
                raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=f"not an image: {content_type}")
            max_bytes = 8 * 1024 * 1024
            data = upstream.read(max_bytes + 1)
            if len(data) > max_bytes:
                raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="image is too large")
    except urllib.error.URLError as exc:
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail=str(exc)) from exc
    return Response(
        content=data,
        media_type=content_type,
        headers={"Cache-Control": "public, max-age=300"},
    )


@app.post("/api/v1/layouts/{layout_id}", dependencies=[Depends(require_api_key)])
def save_layout_preset(layout_id: str, payload: LayoutSaveRequest) -> dict[str, object]:
    try:
        return {"ok": True, "layout": save_layout(layout_id, payload.layout)}
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc


@app.post("/api/v1/apps/fetch-logo", dependencies=[Depends(require_api_key)])
def fetch_logo_candidate(payload: LogoFetchRequest) -> dict[str, object]:
    try:
        item = try_web_logo(payload.process_name, payload.query)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    return {"ok": True, "candidate": item}


@app.post("/api/v1/apps/import-logo-url", dependencies=[Depends(require_api_key)])
def import_logo_candidate(payload: LogoUrlImportRequest) -> dict[str, object]:
    try:
        item = import_logo_url(payload.process_name, payload.url, payload.display_name)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    return {"ok": True, "candidate": item}


@app.get("/review", response_class=HTMLResponse)
def review_page() -> HTMLResponse:
    return HTMLResponse(
        """
<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>Open AIO Logo Review</title>
  <style>
    :root { color-scheme: dark; font-family: system-ui, sans-serif; background: #101012; color: #f4f4f5; }
    body { margin: 0; }
    main { max-width: 980px; margin: 0 auto; padding: 24px; }
    header { display: flex; gap: 12px; align-items: center; justify-content: space-between; margin-bottom: 20px; }
    input, button { font: inherit; border-radius: 6px; border: 1px solid #3f3f46; background: #18181b; color: #f4f4f5; padding: 8px 10px; }
    button { cursor: pointer; background: #27272a; min-height: 40px; }
    button:disabled { cursor: wait; opacity: .55; }
    button.ok { border-color: #22c55e; }
    button.bad { border-color: #ef4444; }
    .grid { display: grid; grid-template-columns: repeat(auto-fill, minmax(280px, 1fr)); gap: 14px; }
    .card { border: 1px solid #27272a; border-radius: 8px; padding: 14px; background: #18181b; }
    .row { display: flex; gap: 8px; align-items: center; flex-wrap: wrap; }
    .preview { width: 160px; height: 160px; background: #101012; border: 1px solid #27272a; image-rendering: pixelated; }
    .muted { color: #a1a1aa; font-size: 13px; overflow-wrap: anywhere; }
    .status { min-height: 20px; margin-top: 10px; color: #a1a1aa; font-size: 13px; overflow-wrap: anywhere; }
    .status.error { color: #fca5a5; }
    .grow { flex: 1; min-width: 160px; }
  </style>
</head>
<body>
<main>
  <header>
    <h1>Logo Review</h1>
    <div class="row">
      <input id="apiKey" value="change-me" aria-label="API key">
      <button onclick="load()">Refresh</button>
    </div>
  </header>
  <section class="grid" id="cards"></section>
</main>
<script>
const apiKey = document.getElementById('apiKey');
const cards = document.getElementById('cards');
let loading = false;
apiKey.value = localStorage.getItem('coolerApiKey') || apiKey.value;
apiKey.addEventListener('change', () => localStorage.setItem('coolerApiKey', apiKey.value));

async function api(path, options = {}) {
  const headers = {'X-API-Key': apiKey.value, ...(options.headers || {})};
  const res = await fetch(path, {...options, headers});
  if (!res.ok) throw new Error(await res.text());
  return res;
}

async function load() {
  if (loading) return;
  loading = true;
  localStorage.setItem('coolerApiKey', apiKey.value);
  try {
    const [unknown, tasks, library] = await Promise.all([
      api('/api/v1/unknown-apps').then(r => r.json()),
      api('/api/v1/logo-tasks').then(r => r.json()),
      api('/api/v1/icon-library').then(r => r.json()),
    ]);
    const merged = [...unknown, ...tasks, ...library].filter((item, index, arr) =>
      arr.findIndex(other => (other.process_name || `library:${other.app_id}`) === (item.process_name || `library:${item.app_id}`)) === index
    );
    cards.innerHTML = '';
    const elements = await Promise.all(merged.map(item => card(item)));
    for (const element of elements) cards.appendChild(element);
    if (!elements.length) cards.textContent = 'No icons found.';
  } catch (err) {
    cards.textContent = err.message;
  } finally {
    loading = false;
  }
}

async function card(item) {
  const el = document.createElement('article');
  el.className = 'card';
  const title = document.createElement('h2');
  title.textContent = item.display_name || item.app_id;
  const meta = document.createElement('p');
  meta.className = 'muted';
  meta.textContent = `${item.process_name} · ${item.status}`;
  const img = document.createElement('canvas');
  img.width = 160; img.height = 160; img.className = 'preview';
  await drawPreview(img, item);
  const url = document.createElement('input');
  url.className = 'grow';
  url.placeholder = 'https://... latest logo image/svg/png';
  const query = document.createElement('input');
  query.className = 'grow';
  query.placeholder = 'Search name override';
  query.value = item.display_name || '';
  const buttons = document.createElement('div');
  buttons.className = 'row';
  buttons.innerHTML = item.status === 'library'
    ? `<button>Refresh Preview</button>`
    : `
      <button class="ok">Approve</button>
      <button class="bad">Reject / Next</button>
      <button>Try Web</button>
      <button>Import URL</button>`;
  const status = document.createElement('div');
  status.className = 'status';
  if (item.status === 'library') {
    buttons.children[0].onclick = () => load();
  } else {
    buttons.children[0].onclick = () => decide(el, buttons, status, '/api/v1/apps/approve-candidate', item.process_name, item.app_id, true);
    buttons.children[1].onclick = () => decide(el, buttons, status, '/api/v1/apps/reject-candidate', item.process_name, item.app_id, true);
    buttons.children[2].onclick = () => fetchLogo(buttons, status, item.process_name, query.value);
    buttons.children[3].onclick = () => importUrl(buttons, status, item.process_name, url.value, query.value);
  }
  el.append(title, meta, img, document.createElement('br'), query, document.createElement('br'), url, document.createElement('br'), buttons, status);
  return el;
}

async function drawPreview(canvas, item) {
  try {
    const res = await api(`/api/v1/assets/apps/${item.app_id}/logo_160x160.rgb565`);
    const data = new Uint8Array(await res.arrayBuffer());
    const ctx = canvas.getContext('2d');
    const image = ctx.createImageData(160, 160);
    for (let i = 0, p = 0; i + 1 < data.length && p < image.data.length; i += 2, p += 4) {
      const v = data[i] | (data[i + 1] << 8);
      image.data[p] = v >> 8 & 0xf8;
      image.data[p + 1] = v >> 3 & 0xfc;
      image.data[p + 2] = v << 3 & 0xf8;
      image.data[p + 3] = 255;
    }
    ctx.putImageData(image, 0, 0);
  } catch {}
}

function setBusy(buttons, status, message) {
  status.className = 'status';
  status.textContent = message;
  for (const button of buttons.children) button.disabled = true;
}

function setError(buttons, status, err) {
  status.className = 'status error';
  status.textContent = err.message || String(err);
  for (const button of buttons.children) button.disabled = false;
}

async function decide(el, buttons, status, path, processName, appId, removeCard) {
  setBusy(buttons, status, 'Saving...');
  try {
    await api(path, {method: 'POST', headers: {'Content-Type': 'application/json'}, body: JSON.stringify({process_name: processName, app_id: appId})});
    status.textContent = 'Saved';
    if (removeCard) el.remove();
    window.setTimeout(load, 150);
  } catch (err) {
    setError(buttons, status, err);
  }
}

async function fetchLogo(buttons, status, processName, query) {
  setBusy(buttons, status, 'Searching...');
  try {
    await api('/api/v1/apps/fetch-logo', {method: 'POST', headers: {'Content-Type': 'application/json'}, body: JSON.stringify({process_name: processName, query})});
    status.textContent = 'Candidate updated';
    await load();
  } catch (err) {
    setError(buttons, status, err);
  }
}

async function importUrl(buttons, status, processName, url, displayName) {
  setBusy(buttons, status, 'Importing...');
  try {
    await api('/api/v1/apps/import-logo-url', {method: 'POST', headers: {'Content-Type': 'application/json'}, body: JSON.stringify({process_name: processName, url, display_name: displayName})});
    status.textContent = 'Imported';
    await load();
  } catch (err) {
    setError(buttons, status, err);
  }
}

load();
</script>
</body>
</html>
        """
    )


@app.get("/designer")
def designer_page() -> RedirectResponse:
    return RedirectResponse(url="/nzxt-esc/config.html")
