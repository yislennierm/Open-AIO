from pathlib import Path

Import("env")

project_dir = Path(env["PROJECT_DIR"])
pioenv = env["PIOENV"]
panel_dir = project_dir / ".pio" / "libdeps" / pioenv / "LilyGo-T-RGB" / "src"
panel_h = panel_dir / "LilyGo_RGBPanel.h"
panel_cpp = panel_dir / "LilyGo_RGBPanel.cpp"

if panel_h.exists():
    text = panel_h.read_text(encoding="utf-8")
    if "getFrameBuffer()" not in text:
        marker = "    void pushColors(uint16_t x, uint16_t y, uint16_t width, uint16_t hight, uint16_t *data);\n"
        replacement = marker + "\n    uint16_t *getFrameBuffer();\n"
        if marker in text:
            panel_h.write_text(text.replace(marker, replacement, 1), encoding="utf-8")

if panel_cpp.exists():
    text = panel_cpp.read_text(encoding="utf-8")
    include_marker = '#include "LilyGo_RGBPanel.h"\n'
    internal_struct = include_marker + """
#include <esp_intr_alloc.h>
#include <esp_lcd_panel_interface.h>
#include <esp_pm.h>
#include <hal/lcd_hal.h>

struct LilyGoPatchedRgbPanel {
    esp_lcd_panel_t base;
    int panel_id;
    lcd_hal_context_t hal;
    size_t data_width;
    size_t sram_trans_align;
    size_t psram_trans_align;
    int disp_gpio_num;
    intr_handle_t intr;
    esp_pm_lock_handle_t pm_lock;
    size_t num_dma_nodes;
    uint8_t *fb;
};
"""
    if include_marker in text and "struct LilyGoPatchedRgbPanel" not in text:
        text = text.replace(include_marker, internal_struct, 1)
    if "struct LilyGoPatchedRgbPanel" in text and "#include <hal/lcd_hal.h>" not in text:
        text = text.replace("#include <esp_pm.h>\n", "#include <esp_pm.h>\n#include <hal/lcd_hal.h>\n", 1)
    if "size_t data_width;\n    int disp_gpio_num;" in text:
        text = text.replace(
            "size_t data_width;\n    int disp_gpio_num;",
            "size_t data_width;\n    size_t sram_trans_align;\n    size_t psram_trans_align;\n    int disp_gpio_num;",
            1,
        )

    old_get_framebuffer = """uint16_t *LilyGo_RGBPanel::getFrameBuffer()
{
    if (!_panelDrv) {
        return nullptr;
    }
    void *fb = nullptr;
    if (esp_lcd_rgb_panel_get_frame_buffer(_panelDrv, 1, &fb) != ESP_OK) {
        return nullptr;
    }
    return static_cast<uint16_t *>(fb);
}
"""
    new_get_framebuffer = """uint16_t *LilyGo_RGBPanel::getFrameBuffer()
{
    if (!_panelDrv) {
        return nullptr;
    }
    return reinterpret_cast<uint16_t *>(reinterpret_cast<LilyGoPatchedRgbPanel *>(_panelDrv)->fb);
}
"""
    if old_get_framebuffer in text:
        text = text.replace(old_get_framebuffer, new_get_framebuffer, 1)

    if "LilyGo_RGBPanel::getFrameBuffer()" not in text:
        marker = """void LilyGo_RGBPanel::pushColors(uint16_t x, uint16_t y, uint16_t width, uint16_t hight, uint16_t *data)
{
    assert(_panelDrv);
    esp_lcd_panel_draw_bitmap(_panelDrv, x, y, width, hight, data);
}
"""
        replacement = marker + "\n" + new_get_framebuffer
        if marker in text:
            text = text.replace(marker, replacement, 1)

    panel_cpp.write_text(text, encoding="utf-8")
