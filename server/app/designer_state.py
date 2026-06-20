from __future__ import annotations

import json
import time
from pathlib import Path
from threading import Lock
from typing import Any

from .config import SERVER_ROOT


_LOCK = Lock()
_ITEMS: dict[str, str] = {}
_UPDATED_AT = 0.0
_MAX_KEYS = 80
_MAX_VALUE_BYTES = 512 * 1024
_STATE_PATH = SERVER_ROOT / "designer_storage.json"


def _load_state() -> None:
    global _ITEMS, _UPDATED_AT
    try:
        payload = json.loads(_STATE_PATH.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return
    except Exception:
        return
    if not isinstance(payload, dict):
        return
    items = payload.get("items")
    if not isinstance(items, dict):
        return
    try:
        _ITEMS = _clean_items(items)
        _UPDATED_AT = float(payload.get("updated_at") or 0.0)
    except Exception:
        _ITEMS = {}
        _UPDATED_AT = 0.0


def _save_state() -> None:
    _STATE_PATH.parent.mkdir(parents=True, exist_ok=True)
    tmp = _STATE_PATH.with_suffix(f".{time.time_ns()}.tmp")
    tmp.write_text(
        json.dumps({"items": _ITEMS, "updated_at": _UPDATED_AT}, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    tmp.replace(_STATE_PATH)


def _clean_items(raw_items: Any) -> dict[str, str]:
    if not isinstance(raw_items, dict):
        raise ValueError("items must be an object")

    cleaned: dict[str, str] = {}
    for raw_key, raw_value in raw_items.items():
        key = str(raw_key).strip()
        if not key:
            continue
        if len(cleaned) >= _MAX_KEYS:
            raise ValueError(f"too many storage keys; max is {_MAX_KEYS}")
        if raw_value is None:
            value = ""
        elif isinstance(raw_value, str):
            value = raw_value
        else:
            value = str(raw_value)
        if len(value.encode("utf-8")) > _MAX_VALUE_BYTES:
            raise ValueError(f"storage value is too large: {key}")
        cleaned[key[:160]] = value
    return cleaned


def _preset_ids(items: dict[str, str]) -> set[str]:
    raw = items.get("nzxt-esc-dev:presets")
    if not raw:
        return set()
    try:
        presets = json.loads(raw)
    except Exception:
        return set()
    if not isinstance(presets, dict):
        return set()
    return {str(key) for key in presets.keys()}


def put_storage_snapshot(raw_items: Any) -> dict[str, object]:
    global _ITEMS, _UPDATED_AT
    items = _clean_items(raw_items)
    with _LOCK:
        has_existing_presets = "nzxt-esc-dev:presets" in _ITEMS and "nzxt-esc-dev:activePresetId" in _ITEMS
        has_next_presets = "nzxt-esc-dev:presets" in items and "nzxt-esc-dev:activePresetId" in items
        if has_existing_presets and not has_next_presets:
            items = {**_ITEMS, **items}
        elif has_existing_presets and has_next_presets:
            if len(items) < len(_ITEMS):
                items = {**_ITEMS, **items}
        _ITEMS = items
        _UPDATED_AT = time.time()
        _save_state()
        return {
            "ok": True,
            "count": len(_ITEMS),
            "updated_at": _UPDATED_AT,
        }


def get_storage_snapshot() -> dict[str, object]:
    with _LOCK:
        return {
            "ok": True,
            "items": dict(_ITEMS),
            "updated_at": _UPDATED_AT,
        }


_load_state()
