from __future__ import annotations

import argparse
from pathlib import Path

from PIL import Image, ImageOps


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


def force_visible_pixels_white(image: Image.Image) -> Image.Image:
    pixels = image.load()
    for y in range(image.height):
        for x in range(image.width):
            r, g, b, a = pixels[x, y]
            if a > 0 and (r > 16 or g > 16 or b > 16):
                pixels[x, y] = (255, 255, 255, a)
    return image


def dark_logo_to_white_on_black(image: Image.Image) -> Image.Image:
    pixels = image.load()
    for y in range(image.height):
        for x in range(image.width):
            r, g, b, a = pixels[x, y]
            if a == 0:
                pixels[x, y] = (0, 0, 0, 255)
                continue
            luminance = (r * 299 + g * 587 + b * 114) // 1000
            pixels[x, y] = (255, 255, 255, 255) if luminance < 160 else (0, 0, 0, 255)
    return image


def non_white_logo_to_white_on_black(image: Image.Image) -> Image.Image:
    pixels = image.load()
    for y in range(image.height):
        for x in range(image.width):
            r, g, b, a = pixels[x, y]
            if a == 0:
                pixels[x, y] = (0, 0, 0, 255)
                continue
            max_channel = max(r, g, b)
            min_channel = min(r, g, b)
            saturation = max_channel - min_channel
            is_white_background = r > 222 and g > 222 and b > 222 and saturation < 36
            pixels[x, y] = (0, 0, 0, 255) if is_white_background else (255, 255, 255, 255)
    return image


def preprocess(
    input_path: Path,
    output_path: Path,
    width: int,
    height: int,
    rotate: int,
    force_white: bool,
    dark_to_white: bool,
    non_white_to_white: bool,
    alpha_mask_path: Path | None,
) -> None:
    with Image.open(input_path) as source:
        image = source.convert("RGBA")
        if non_white_to_white:
            image = non_white_logo_to_white_on_black(image)
        elif dark_to_white:
            image = dark_logo_to_white_on_black(image)
        elif force_white:
            image = force_visible_pixels_white(image)
        if rotate:
            image = image.rotate(rotate, expand=True)

        image = ImageOps.contain(image, (width, height), Image.Resampling.LANCZOS)
        canvas = Image.new("RGBA", (width, height), (0, 0, 0, 0))
        x = (width - image.width) // 2
        y = (height - image.height) // 2
        canvas.alpha_composite(image, (x, y))
        rgb_canvas = Image.new("RGBA", (width, height), (0, 0, 0, 255))
        rgb_canvas.alpha_composite(canvas)
        rgb565 = rgb888_to_rgb565_le(rgb_canvas.convert("RGB").tobytes())
        alpha = canvas.getchannel("A").tobytes()

    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_bytes(rgb565)
    if alpha_mask_path is not None:
        alpha_mask_path.parent.mkdir(parents=True, exist_ok=True)
        alpha_mask_path.write_bytes(alpha)


def main() -> None:
    parser = argparse.ArgumentParser(description="Convert a boot logo into RGB565 little-endian data.")
    parser.add_argument("input_image", type=Path)
    parser.add_argument("output_image", type=Path)
    parser.add_argument("--width", type=int, default=240)
    parser.add_argument("--height", type=int, default=200)
    parser.add_argument("--rotate", type=int, default=0)
    parser.add_argument("--force-white", action="store_true")
    parser.add_argument("--dark-to-white", action="store_true")
    parser.add_argument("--non-white-to-white", action="store_true")
    parser.add_argument("--alpha-mask", type=Path)
    args = parser.parse_args()
    preprocess(
        args.input_image,
        args.output_image,
        args.width,
        args.height,
        args.rotate,
        args.force_white,
        args.dark_to_white,
        args.non_white_to_white,
        args.alpha_mask,
    )


if __name__ == "__main__":
    main()
