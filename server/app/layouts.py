from __future__ import annotations

import json
import re
from copy import deepcopy
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from .config import SERVER_ROOT

LAYOUT_DIR = SERVER_ROOT / "layouts"
LAYOUT_ID_RE = re.compile(r"^[a-z0-9][a-z0-9_-]{0,63}$")


DEFAULT_LAYOUT: dict[str, Any] = {
    "version": 1,
    "id": "classic",
    "name": "Classic",
    "updated_at": None,
    "canvas": {"width": 480, "height": 480, "shape": "circle", "background": "#05070a"},
    "elements": [
        {
            "id": "cpu_arc",
            "type": "arc_metric",
            "metric": "cpu_load",
            "x": 240,
            "y": 240,
            "radius": 224,
            "width": 12,
            "start_deg": 122,
            "sweep_deg": 296,
            "color": "#027bff",
            "track_color": "#132033",
            "z": 10,
        },
        {
            "id": "gpu_arc",
            "type": "arc_metric",
            "metric": "gpu_load",
            "x": 240,
            "y": 240,
            "radius": 202,
            "width": 12,
            "start_deg": 122,
            "sweep_deg": 296,
            "color": "#76ff00",
            "track_color": "#1a2a14",
            "z": 11,
        },
        {
            "id": "app_logo",
            "type": "app_logo",
            "x": 150,
            "y": 96,
            "width": 180,
            "height": 180,
            "opacity": 1,
            "z": 20,
        },
        {
            "id": "app_name",
            "type": "text",
            "text": "{display_name}",
            "x": 80,
            "y": 284,
            "width": 320,
            "height": 34,
            "font_size": 24,
            "align": "center",
            "color": "#f4f7fb",
            "z": 30,
        },
        {
            "id": "cpu_temp",
            "type": "metric_text",
            "metric": "cpu_temp",
            "x": 64,
            "y": 328,
            "width": 150,
            "height": 46,
            "font_size": 34,
            "align": "center",
            "color": "#027bff",
            "suffix": "C",
            "z": 31,
        },
        {
            "id": "gpu_temp",
            "type": "metric_text",
            "metric": "gpu_temp",
            "x": 266,
            "y": 328,
            "width": 150,
            "height": 46,
            "font_size": 34,
            "align": "center",
            "color": "#76ff00",
            "suffix": "C",
            "z": 32,
        },
        {
            "id": "clock",
            "type": "text",
            "text": "{local_time}  {local_date}",
            "x": 146,
            "y": 388,
            "width": 188,
            "height": 26,
            "font_size": 18,
            "align": "center",
            "color": "#d9e2ec",
            "z": 33,
        },
    ],
}


def ensure_layout_dir() -> None:
    LAYOUT_DIR.mkdir(parents=True, exist_ok=True)
    classic_path = layout_path("classic")
    if not classic_path.exists():
        initial = deepcopy(DEFAULT_LAYOUT)
        initial["updated_at"] = datetime.now(tz=UTC).isoformat()
        classic_path.write_text(json.dumps(initial, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def layout_path(layout_id: str) -> Path:
    return LAYOUT_DIR / f"{layout_id}.json"


def normalize_layout_id(value: str) -> str:
    layout_id = value.strip().lower().replace(" ", "-")
    if not LAYOUT_ID_RE.match(layout_id):
        raise ValueError("layout id must use lowercase letters, numbers, dash, or underscore")
    return layout_id


def list_layouts() -> list[dict[str, Any]]:
    ensure_layout_dir()
    items: list[dict[str, Any]] = []
    for path in sorted(LAYOUT_DIR.glob("*.json")):
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        items.append(
            {
                "id": str(data.get("id") or path.stem),
                "name": str(data.get("name") or path.stem),
                "updated_at": data.get("updated_at"),
                "element_count": len(data.get("elements", [])) if isinstance(data.get("elements"), list) else 0,
            }
        )
    return items


def get_layout(layout_id: str) -> dict[str, Any]:
    ensure_layout_dir()
    normalized = normalize_layout_id(layout_id)
    path = layout_path(normalized)
    if not path.exists():
        if normalized == "classic":
            return deepcopy(DEFAULT_LAYOUT)
        raise FileNotFoundError(normalized)
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise ValueError("layout must be a JSON object")
    data["id"] = normalized
    return data


def save_layout(layout_id: str, layout: dict[str, Any]) -> dict[str, Any]:
    ensure_layout_dir()
    normalized = normalize_layout_id(layout_id)
    if not isinstance(layout, dict):
        raise ValueError("layout must be a JSON object")
    saved = deepcopy(layout)
    saved["id"] = normalized
    saved.setdefault("version", 1)
    saved.setdefault("name", normalized)
    saved.setdefault("canvas", {"width": 480, "height": 480, "shape": "circle", "background": "#05070a"})
    elements = saved.get("elements")
    if not isinstance(elements, list):
        raise ValueError("layout elements must be a list")
    if not all(isinstance(element, dict) for element in elements):
        raise ValueError("layout elements must be JSON objects")
    saved["updated_at"] = datetime.now(tz=UTC).isoformat()
    LAYOUT_DIR.mkdir(parents=True, exist_ok=True)
    layout_path(normalized).write_text(json.dumps(saved, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return saved
