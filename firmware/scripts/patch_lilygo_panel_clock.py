from pathlib import Path

Import("env")

project_dir = Path(env["PROJECT_DIR"])
pioenv = env["PIOENV"]
utilities_h = (
    project_dir
    / ".pio"
    / "libdeps"
    / pioenv
    / "LilyGo-T-RGB"
    / "src"
    / "utilities.h"
)

if utilities_h.exists():
    text = utilities_h.read_text(encoding="utf-8")
    text = text.replace(
        "#define RGB_MAX_PIXEL_CLOCK_HZ  (12000000UL)",
        "#define RGB_MAX_PIXEL_CLOCK_HZ  (8000000UL)",
    )
    text = text.replace(
        "#define RGB_MAX_PIXEL_CLOCK_HZ  (16000000UL)",
        "#define RGB_MAX_PIXEL_CLOCK_HZ  (8000000UL)",
    )
    utilities_h.write_text(text, encoding="utf-8")
