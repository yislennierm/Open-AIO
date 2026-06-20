from __future__ import annotations

import argparse
import hashlib
import json
import re
from pathlib import Path

from PIL import Image


def sanitize_app_id(app_id: str) -> str:
    normalized = app_id.strip().lower()
    if not re.fullmatch(r"[a-z0-9_-]{1,64}", normalized):
        raise ValueError("app ID must match [a-z0-9_-]{1,64}")
    return normalized


def display_name_from_app_id(app_id: str) -> str:
    return app_id.replace("_", " ").replace("-", " ").title()


def center_crop_square(image: Image.Image) -> Image.Image:
    width, height = image.size
    side = min(width, height)
    left = (width - side) // 2
    top = (height - side) // 2
    return image.crop((left, top, left + side, top + side))


def rgb888_to_rgb565_le(data: bytes) -> bytes:
    output = bytearray()
    for index in range(0, len(data), 3):
        r = data[index]
        g = data[index + 1]
        b = data[index + 2]
        value = ((r & 0xF8) << 8) | ((g & 0xFC) << 3) | (b >> 3)
        output.append(value & 0xFF)
        output.append((value >> 8) & 0xFF)
    return bytes(output)


def preprocess(input_path: Path, app_id: str, size: int, asset_base: Path) -> Path:
    app_id = sanitize_app_id(app_id)
    if size <= 0 or size > 240:
        raise ValueError("size must be between 1 and 240")

    output_dir = asset_base / app_id
    output_dir.mkdir(parents=True, exist_ok=True)
    asset_file = f"logo_{size}x{size}.rgb565"
    output_path = output_dir / asset_file

    with Image.open(input_path) as image:
        prepared = center_crop_square(image.convert("RGB")).resize((size, size), Image.Resampling.LANCZOS)
        rgb565 = rgb888_to_rgb565_le(prepared.tobytes())

    output_path.write_bytes(rgb565)
    digest = hashlib.sha256(rgb565).hexdigest()
    manifest = {
        "app_id": app_id,
        "display_name": display_name_from_app_id(app_id),
        "asset_type": "rgb565",
        "asset_file": asset_file,
        "asset_width": size,
        "asset_height": size,
        "asset_hash": digest,
    }
    (output_dir / "manifest.json").write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    return output_path


def main() -> None:
    parser = argparse.ArgumentParser(description="Preprocess an image into ESP32-ready RGB565 little-endian asset data.")
    parser.add_argument("input_image", type=Path)
    parser.add_argument("app_id")
    parser.add_argument("--size", type=int, default=160)
    parser.add_argument("--asset-base", type=Path, default=Path(__file__).resolve().parents[1] / "assets" / "apps")
    args = parser.parse_args()

    output = preprocess(args.input_image, args.app_id, args.size, args.asset_base)
    print(output)


if __name__ == "__main__":
    main()
