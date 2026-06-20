from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from pydantic import BaseModel, Field


class Settings(BaseModel):
    api_key: str = "change-me"
    asset_base_path: str = "assets/apps"
    default_app_id: str = "default"
    max_asset_size_bytes: int = Field(default=131072, ge=1)


def load_settings() -> Settings:
    root = Path(__file__).resolve().parents[1]
    config_path = root / "config.json"
    if not config_path.exists():
        config_path = root / "config.example.json"

    data: dict[str, Any] = {}
    if config_path.exists():
        data = json.loads(config_path.read_text(encoding="utf-8"))
    return Settings(**data)


SETTINGS = load_settings()
SERVER_ROOT = Path(__file__).resolve().parents[1]

