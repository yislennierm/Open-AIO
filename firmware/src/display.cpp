#include "display.h"

#include <LilyGo_RGBPanel.h>
#include <LittleFS.h>
#include <Arduino.h>
#include <JPEGDEC.h>
#include <esp_heap_caps.h>
#include <esp32s3/rom/cache.h>
#include <math.h>

#include "assets.h"
#include "config.h"

static LilyGo_RGBPanel panel;
static uint16_t* framebuffer = nullptr;
static uint16_t* panelFramebuffer = nullptr;
static uint16_t* rotatedFramebuffer = nullptr;
static uint16_t* signalLineBuffer = nullptr;
static uint32_t signalFpsWindowStartMs = 0;
static uint16_t signalFpsWindowFrames = 0;
static uint16_t signalFpsDisplay = 0;
static uint32_t signalLocalFrame = 0;
static uint32_t signalRxBytes = 0;
static uint32_t signalRxMs = 0;
static uint32_t signalDecodeMs = 0;
static uint32_t signalFlushMs = 0;
static uint32_t displayAnimLastMs = 0;
static float displayCpuLoad = NAN;
static float displayGpuLoad = NAN;
static float displayRamUsedPercent = NAN;
static float displayCpuTemp = NAN;
static float displayGpuTemp = NAN;
static JPEGDEC signalJpeg;
static int signalLastJpegWidth = 0;
static int signalLastJpegHeight = 0;

extern "C" int Cache_WriteBack_Addr(uint32_t addr, uint32_t size);

static constexpr uint16_t COLOR_BLACK = 0x0000;
static constexpr uint16_t COLOR_WHITE = 0xFFFF;
static constexpr uint16_t COLOR_CYAN = 0x07FF;
static constexpr uint16_t COLOR_DIM = 0x8410;
static constexpr uint16_t COLOR_TRACK = 0x2104;
static constexpr uint16_t COLOR_INTEL_BLUE = 0x045F;
static constexpr uint16_t COLOR_NVIDIA_GREEN = 0x76E0;
static constexpr uint16_t COLOR_RED = 0xF800;
static constexpr uint16_t COLOR_ORANGE = 0xFD20;
static constexpr uint16_t COLOR_PURPLE = 0x801F;
static constexpr uint16_t COLOR_GREEN = 0x07E0;
static constexpr uint16_t COLOR_DARK_CYAN = 0x0451;
static constexpr uint16_t COLOR_DARK_GREEN = 0x0320;
static constexpr uint16_t COLOR_DARK_RED = 0x6000;
static constexpr float ARC_START_DEG = 120.0f;
static constexpr float ARC_SWEEP_DEG = 300.0f;
static constexpr int LOGO_RENDER_SIZE = 188;
static constexpr int BOOT_LOGO_WIDTH = 320;
static constexpr int BOOT_LOGO_HEIGHT = 260;
static constexpr int SYSTEM_LOGO_WIDTH = 460;
static constexpr int SYSTEM_LOGO_HEIGHT = 460;

static uint16_t scaleRgb5658(uint16_t color, uint8_t brightness);
static uint16_t blendRgb565(uint16_t a, uint16_t b, uint8_t amount);

static void clearFrame(uint16_t color) {
  if (!framebuffer) {
    return;
  }
  for (size_t i = 0; i < static_cast<size_t>(DISPLAY_WIDTH) * DISPLAY_HEIGHT; i++) {
    framebuffer[i] = color;
  }
}

static void setPixel(int x, int y, uint16_t color) {
  if (!framebuffer || x < 0 || y < 0 || x >= DISPLAY_WIDTH || y >= DISPLAY_HEIGHT) {
    return;
  }
  framebuffer[y * DISPLAY_WIDTH + x] = color;
}

static void flushDisplay() {
  if (!framebuffer) {
    return;
  }
#if DISPLAY_ROTATE_180
  if (rotatedFramebuffer) {
    const size_t pixelCount = static_cast<size_t>(DISPLAY_WIDTH) * DISPLAY_HEIGHT;
    for (size_t i = 0; i < pixelCount; i++) {
      rotatedFramebuffer[pixelCount - 1 - i] = framebuffer[i];
    }
    panel.pushColors(0, 0, DISPLAY_WIDTH, DISPLAY_HEIGHT, rotatedFramebuffer);
    return;
  }
#endif
  panel.pushColors(0, 0, DISPLAY_WIDTH, DISPLAY_HEIGHT, framebuffer);
}

static void flushDisplayRaw() {
  if (!framebuffer) {
    return;
  }
  panel.pushColors(0, 0, DISPLAY_WIDTH, DISPLAY_HEIGHT, framebuffer);
}

static void fillRect(int x, int y, int w, int h, uint16_t color) {
  if (!framebuffer || w <= 0 || h <= 0) {
    return;
  }
  int x2 = min(DISPLAY_WIDTH, x + w);
  int y2 = min(DISPLAY_HEIGHT, y + h);
  x = max(0, x);
  y = max(0, y);
  for (int yy = y; yy < y2; yy++) {
    uint16_t* row = framebuffer + yy * DISPLAY_WIDTH;
    for (int xx = x; xx < x2; xx++) {
      row[xx] = color;
    }
  }
}

static void fillCircle(int cx, int cy, int r, uint16_t color) {
  int rr = r * r;
  for (int y = -r; y <= r; y++) {
    for (int x = -r; x <= r; x++) {
      if (x * x + y * y <= rr) {
        setPixel(cx + x, cy + y, color);
      }
    }
  }
}

static const uint8_t* glyphFor(char c) {
  static const uint8_t space[5] = {0, 0, 0, 0, 0};
  static const uint8_t dash[5] = {0x08, 0x08, 0x08, 0x08, 0x08};
  static const uint8_t dot[5] = {0, 0x60, 0x60, 0, 0};
  static const uint8_t pct[5] = {0x63, 0x13, 0x08, 0x64, 0x63};
  static const uint8_t colon[5] = {0, 0x36, 0x36, 0, 0};
  static const uint8_t digits[10][5] = {
      {0x3E, 0x51, 0x49, 0x45, 0x3E}, {0x00, 0x42, 0x7F, 0x40, 0x00},
      {0x42, 0x61, 0x51, 0x49, 0x46}, {0x21, 0x41, 0x45, 0x4B, 0x31},
      {0x18, 0x14, 0x12, 0x7F, 0x10}, {0x27, 0x45, 0x45, 0x45, 0x39},
      {0x3C, 0x4A, 0x49, 0x49, 0x30}, {0x01, 0x71, 0x09, 0x05, 0x03},
      {0x36, 0x49, 0x49, 0x49, 0x36}, {0x06, 0x49, 0x49, 0x29, 0x1E},
  };
  static const uint8_t letters[26][5] = {
      {0x7E, 0x11, 0x11, 0x11, 0x7E}, {0x7F, 0x49, 0x49, 0x49, 0x36},
      {0x3E, 0x41, 0x41, 0x41, 0x22}, {0x7F, 0x41, 0x41, 0x22, 0x1C},
      {0x7F, 0x49, 0x49, 0x49, 0x41}, {0x7F, 0x09, 0x09, 0x09, 0x01},
      {0x3E, 0x41, 0x49, 0x49, 0x7A}, {0x7F, 0x08, 0x08, 0x08, 0x7F},
      {0x00, 0x41, 0x7F, 0x41, 0x00}, {0x20, 0x40, 0x41, 0x3F, 0x01},
      {0x7F, 0x08, 0x14, 0x22, 0x41}, {0x7F, 0x40, 0x40, 0x40, 0x40},
      {0x7F, 0x02, 0x0C, 0x02, 0x7F}, {0x7F, 0x04, 0x08, 0x10, 0x7F},
      {0x3E, 0x41, 0x41, 0x41, 0x3E}, {0x7F, 0x09, 0x09, 0x09, 0x06},
      {0x3E, 0x41, 0x51, 0x21, 0x5E}, {0x7F, 0x09, 0x19, 0x29, 0x46},
      {0x46, 0x49, 0x49, 0x49, 0x31}, {0x01, 0x01, 0x7F, 0x01, 0x01},
      {0x3F, 0x40, 0x40, 0x40, 0x3F}, {0x1F, 0x20, 0x40, 0x20, 0x1F},
      {0x3F, 0x40, 0x38, 0x40, 0x3F}, {0x63, 0x14, 0x08, 0x14, 0x63},
      {0x07, 0x08, 0x70, 0x08, 0x07}, {0x61, 0x51, 0x49, 0x45, 0x43},
  };
  if (c >= 'a' && c <= 'z') {
    c = c - 'a' + 'A';
  }
  if (c >= 'A' && c <= 'Z') {
    return letters[c - 'A'];
  }
  if (c >= '0' && c <= '9') {
    return digits[c - '0'];
  }
  if (c == '-') {
    return dash;
  }
  if (c == '.') {
    return dot;
  }
  if (c == '%') {
    return pct;
  }
  if (c == ':') {
    return colon;
  }
  return space;
}

static int textWidth(const String& text, int scale) {
  return text.length() * 6 * scale;
}

static void drawText(const String& text, int x, int y, int scale, uint16_t color) {
  for (size_t i = 0; i < text.length(); i++) {
    const uint8_t* glyph = glyphFor(text[i]);
    for (int col = 0; col < 5; col++) {
      uint8_t bits = glyph[col];
      for (int row = 0; row < 7; row++) {
        if (bits & (1 << row)) {
          fillRect(x + (col * scale), y + (row * scale), scale, scale, color);
        }
      }
    }
    x += 6 * scale;
  }
}

static void signalSetPixel(int x, int y, uint16_t color) {
  if (!framebuffer || x < 0 || y < 0 || x >= DISPLAY_WIDTH || y >= DISPLAY_HEIGHT) {
    return;
  }
#if DISPLAY_ROTATE_180
  framebuffer[(DISPLAY_HEIGHT - 1 - y) * DISPLAY_WIDTH + (DISPLAY_WIDTH - 1 - x)] = color;
#else
  framebuffer[y * DISPLAY_WIDTH + x] = color;
#endif
}

static void signalFillRect(int x, int y, int w, int h, uint16_t color) {
  if (!framebuffer || w <= 0 || h <= 0) {
    return;
  }
  int x2 = min(DISPLAY_WIDTH, x + w);
  int y2 = min(DISPLAY_HEIGHT, y + h);
  x = max(0, x);
  y = max(0, y);
  for (int yy = y; yy < y2; yy++) {
    for (int xx = x; xx < x2; xx++) {
      signalSetPixel(xx, yy, color);
    }
  }
}

static void signalDrawText(const String& text, int x, int y, int scale, uint16_t color) {
  for (size_t i = 0; i < text.length(); i++) {
    const uint8_t* glyph = glyphFor(text[i]);
    for (int col = 0; col < 5; col++) {
      uint8_t bits = glyph[col];
      for (int row = 0; row < 7; row++) {
        if (bits & (1 << row)) {
          signalFillRect(x + (col * scale), y + (row * scale), scale, scale, color);
        }
      }
    }
    x += 6 * scale;
  }
}

static void drawCenteredText(const String& text, int y, int scale, uint16_t color) {
  int x = (DISPLAY_WIDTH - textWidth(text, scale)) / 2;
  drawText(text, max(0, x), y, scale, color);
}

static void drawCenteredTextInBox(const String& text, int x, int y, int w, int scale, uint16_t color) {
  int textX = x + ((w - textWidth(text, scale)) / 2);
  drawText(text, max(0, textX), y, scale, color);
}

static void drawSignalFpsOverlay() {
#if SIGNALRGB_FPS_OVERLAY
  uint32_t now = millis();
  if (signalFpsWindowStartMs == 0) {
    signalFpsWindowStartMs = now;
  }
  signalFpsWindowFrames++;
  uint32_t elapsed = now - signalFpsWindowStartMs;
  if (elapsed >= 1000) {
    signalFpsDisplay = static_cast<uint16_t>((signalFpsWindowFrames * 1000UL + (elapsed / 2)) / elapsed);
    signalFpsWindowFrames = 0;
    signalFpsWindowStartMs = now;
  }

  char text[10];
  snprintf(text, sizeof(text), "%u FPS", static_cast<unsigned>(signalFpsDisplay));
  constexpr int overlayW = 126;
  constexpr int overlayH = 32;
  constexpr int overlayX = (DISPLAY_WIDTH - overlayW) / 2;
  constexpr int overlayY = 26;
  signalFillRect(overlayX, overlayY, overlayW, overlayH, COLOR_BLACK);
  signalDrawText(String(text), overlayX + 12, overlayY + 7, 3, COLOR_GREEN);
#endif
}

static void drawJpegFpsOverlay() {
#if SIGNALRGB_FPS_OVERLAY
  uint32_t now = millis();
  if (signalFpsWindowStartMs == 0) {
    signalFpsWindowStartMs = now;
  }
  signalFpsWindowFrames++;
  uint32_t elapsed = now - signalFpsWindowStartMs;
  if (elapsed >= 1000) {
    signalFpsDisplay = static_cast<uint16_t>((signalFpsWindowFrames * 1000UL + (elapsed / 2)) / elapsed);
    signalFpsWindowFrames = 0;
    signalFpsWindowStartMs = now;
  }

  char line1[28];
  char line2[28];
  snprintf(line1, sizeof(line1), "%uF R%u D%u F%u",
           static_cast<unsigned>(signalFpsDisplay),
           static_cast<unsigned>(signalRxMs),
           static_cast<unsigned>(signalDecodeMs),
           static_cast<unsigned>(signalFlushMs));
  snprintf(line2, sizeof(line2), "%uK %dx%d",
           static_cast<unsigned>((signalRxBytes + 512) / 1024),
           signalLastJpegWidth,
           signalLastJpegHeight);
  constexpr int overlayW = 252;
  constexpr int overlayH = 48;
  constexpr int overlayX = (DISPLAY_WIDTH - overlayW) / 2;
  constexpr int overlayY = 26;
  fillRect(overlayX, overlayY, overlayW, overlayH, COLOR_BLACK);
  drawText(String(line1), overlayX + 8, overlayY + 6, 2, COLOR_GREEN);
  drawText(String(line2), overlayX + 8, overlayY + 27, 2, COLOR_DIM);
#endif
}

static float normalizedPercent(float value) {
  if (isnan(value)) {
    return 0.0f;
  }
  if (value < 0.0f) {
    return 0.0f;
  }
  if (value > 100.0f) {
    return 100.0f;
  }
  return value;
}

static void drawArc(int cx, int cy, int radius, int dotRadius, float startDeg, float sweepDeg, uint16_t color) {
  int steps = max(1, static_cast<int>(fabsf(sweepDeg)));
  float direction = sweepDeg >= 0.0f ? 1.0f : -1.0f;
  for (int i = 0; i <= steps; i++) {
    float deg = startDeg + (static_cast<float>(i) * direction);
    float rad = deg * 0.01745329252f;
    int x = cx + static_cast<int>(roundf(cosf(rad) * radius));
    int y = cy + static_cast<int>(roundf(sinf(rad) * radius));
    fillCircle(x, y, dotRadius, color);
  }
}

static void drawSolidUsageArc(int radius, float displayPercent, uint16_t color) {
  float percent = normalizedPercent(displayPercent);
  float sweep = ARC_SWEEP_DEG * (percent / 100.0f);
  drawArc(240, 240, radius, 7, ARC_START_DEG, sweep, color);
}

static void drawCpuUsageArc(float cpuLoad) {
  drawSolidUsageArc(224, cpuLoad, COLOR_INTEL_BLUE);
}

static void drawGpuUsageArc(float gpuLoad, float fallbackRamUsedPercent) {
  float percent = isnan(gpuLoad) ? normalizedPercent(fallbackRamUsedPercent) : normalizedPercent(gpuLoad);
  drawSolidUsageArc(204, percent, COLOR_NVIDIA_GREEN);
}

static void drawBootSweep(float progress, uint16_t color) {
  drawArc(240, 240, 224, 6, ARC_START_DEG, ARC_SWEEP_DEG, COLOR_TRACK);
  drawArc(240, 240, 204, 4, ARC_START_DEG, ARC_SWEEP_DEG, COLOR_TRACK);
  drawArc(240, 240, 224, 6, ARC_START_DEG, ARC_SWEEP_DEG * progress, color);
  drawArc(240, 240, 204, 4, ARC_START_DEG, ARC_SWEEP_DEG * progress, COLOR_DIM);
}

static void drawUsageArcs(float cpuLoad, float gpuLoad, float ramUsedPercent) {
  drawArc(240, 240, 224, 7, ARC_START_DEG, ARC_SWEEP_DEG, COLOR_TRACK);
  drawArc(240, 240, 204, 7, ARC_START_DEG, ARC_SWEEP_DEG, COLOR_TRACK);
  drawCpuUsageArc(cpuLoad);
  drawGpuUsageArc(gpuLoad, ramUsedPercent);
}

static float animatedValue(float current, float target, float maxUnitsPerSecond, uint32_t elapsedMs) {
  if (isnan(target)) {
    return NAN;
  }
  if (isnan(current)) {
    return target;
  }
  float delta = target - current;
  float maxStep = maxUnitsPerSecond * (static_cast<float>(elapsedMs) / 1000.0f);
  maxStep = max(0.2f, min(maxStep, maxUnitsPerSecond * 0.12f));
  if (fabsf(delta) <= maxStep) {
    return target;
  }
  return current + (delta > 0.0f ? maxStep : -maxStep);
}

static float smoothPercentValue(float current, float target, uint32_t elapsedMs) {
  if (isnan(target)) {
    return NAN;
  }
  if (isnan(current)) {
    return target;
  }

  float dt = min(0.12f, max(0.001f, static_cast<float>(elapsedMs) / 1000.0f));
  float alpha = 1.0f - expf(-dt * 4.2f);
  float next = current + ((target - current) * alpha);
  if (fabsf(target - next) < 0.15f) {
    return target;
  }
  return max(0.0f, min(100.0f, next));
}

static String formatTemp(float value) {
  if (isnan(value)) {
    return "--*";
  }
  char buf[12];
  snprintf(buf, sizeof(buf), "%.0f*", value);
  return String(buf);
}

static int tempGlyphWidth(char c) {
  if (c == '.') {
    return 10;
  }
  if (c == '*') {
    return 14;
  }
  if (c == ' ') {
    return 8;
  }
  return 30;
}

static int tempTextWidth(const String& text) {
  int width = 0;
  for (size_t i = 0; i < text.length(); i++) {
    width += tempGlyphWidth(text[i]);
  }
  return max(0, width - 2);
}

static void fillRoundRect(int x, int y, int w, int h, int r, uint16_t color) {
  fillRect(x + r, y, w - (r * 2), h, color);
  fillRect(x, y + r, w, h - (r * 2), color);
  fillCircle(x + r, y + r, r, color);
  fillCircle(x + w - r - 1, y + r, r, color);
  fillCircle(x + r, y + h - r - 1, r, color);
  fillCircle(x + w - r - 1, y + h - r - 1, r, color);
}

static void drawTempSegment(int x, int y, int segment, uint16_t color) {
  constexpr int W = 26;
  constexpr int H = 42;
  constexpr int T = 5;
  constexpr int R = 2;
  switch (segment) {
    case 0:
      fillRoundRect(x + T, y, W - (T * 2), T, R, color);
      break;
    case 1:
      fillRoundRect(x + W - T, y + T, T, (H / 2) - T, R, color);
      break;
    case 2:
      fillRoundRect(x + W - T, y + (H / 2), T, (H / 2) - T, R, color);
      break;
    case 3:
      fillRoundRect(x + T, y + H - T, W - (T * 2), T, R, color);
      break;
    case 4:
      fillRoundRect(x, y + (H / 2), T, (H / 2) - T, R, color);
      break;
    case 5:
      fillRoundRect(x, y + T, T, (H / 2) - T, R, color);
      break;
    case 6:
      fillRoundRect(x + T, y + (H / 2) - (T / 2), W - (T * 2), T, R, color);
      break;
  }
}

static uint8_t tempSegmentMask(char c) {
  switch (c) {
    case '0':
      return 0b00111111;
    case '1':
      return 0b00000110;
    case '2':
      return 0b01011011;
    case '3':
      return 0b01001111;
    case '4':
      return 0b01100110;
    case '5':
      return 0b01101101;
    case '6':
      return 0b01111101;
    case '7':
      return 0b00000111;
    case '8':
      return 0b01111111;
    case '9':
      return 0b01101111;
    case '-':
      return 0b01000000;
    default:
      return 0;
  }
}

static void drawTempGlyph(char c, int x, int y, uint16_t color) {
  if (c == '.') {
    fillCircle(x + 4, y + 38, 3, color);
    return;
  }
  if (c == '*') {
    fillCircle(x + 6, y + 5, 6, color);
    fillCircle(x + 6, y + 5, 3, COLOR_BLACK);
    return;
  }
  uint8_t mask = tempSegmentMask(c);
  drawTempSegment(x + 1, y + 1, 6, COLOR_TRACK);
  for (int segment = 0; segment < 7; segment++) {
    if (mask & (1 << segment)) {
      drawTempSegment(x, y, segment, color);
    }
  }
}

static void drawTempValue(const String& text, int boxX, int y, int boxW, uint16_t color) {
  int x = boxX + ((boxW - tempTextWidth(text)) / 2);
  for (size_t i = 0; i < text.length(); i++) {
    drawTempGlyph(text[i], x, y, color);
    x += tempGlyphWidth(text[i]);
  }
}

static void drawClockDate(const DisplayState& state) {
  String timeText = state.localTime;
  String dateText = state.localDate;

  if (timeText.length() == 0 && state.updatedAt.length() >= 16) {
    timeText = state.updatedAt.substring(11, 16);
  }
  if (dateText.length() == 0 && state.updatedAt.length() >= 10) {
    dateText = state.updatedAt.substring(5, 10);
  }

  if (timeText.length() > 5) {
    timeText = timeText.substring(0, 5);
  }
  if (dateText.length() > 8) {
    dateText = dateText.substring(0, 8);
  }
  dateText.toUpperCase();

  if (timeText.length() > 0) {
    drawCenteredText(timeText, 386, 3, COLOR_WHITE);
  }
  if (dateText.length() > 0) {
    drawCenteredText(dateText, 416, 2, COLOR_DIM);
  }
}

void initDisplay() {
  framebuffer = static_cast<uint16_t*>(heap_caps_malloc(
      static_cast<size_t>(DISPLAY_WIDTH) * DISPLAY_HEIGHT * sizeof(uint16_t),
      MALLOC_CAP_SPIRAM | MALLOC_CAP_8BIT));
  if (!framebuffer) {
    Serial.println("display framebuffer allocation failed");
    return;
  }
  signalLineBuffer = static_cast<uint16_t*>(heap_caps_malloc(
      static_cast<size_t>(DISPLAY_WIDTH) * sizeof(uint16_t),
      MALLOC_CAP_INTERNAL | MALLOC_CAP_8BIT));
  if (!signalLineBuffer) {
    signalLineBuffer = static_cast<uint16_t*>(heap_caps_malloc(
        static_cast<size_t>(DISPLAY_WIDTH) * sizeof(uint16_t),
        MALLOC_CAP_SPIRAM | MALLOC_CAP_8BIT));
  }
#if DISPLAY_ROTATE_180
  rotatedFramebuffer = static_cast<uint16_t*>(heap_caps_malloc(
      static_cast<size_t>(DISPLAY_WIDTH) * DISPLAY_HEIGHT * sizeof(uint16_t),
      MALLOC_CAP_SPIRAM | MALLOC_CAP_8BIT));
  if (!rotatedFramebuffer) {
    Serial.println("display rotated framebuffer allocation failed");
  }
#endif

  bool ok = panel.begin(LILYGO_T_RGB_2_1_INCHES_HALF_CIRCLE);
  if (!ok) {
    Serial.println("T-RGB panel init failed");
    return;
  }
  Serial.print("Touch: ");
  Serial.println(panel.getTouchModelName());
#if SIGNALRGB_DIRECT_FRAMEBUFFER && HAS_LILYGO_PANEL_FRAMEBUFFER
  panelFramebuffer = panel.getFrameBuffer();
#else
  panelFramebuffer = nullptr;
#endif
  Serial.print("Panel framebuffer: ");
  Serial.println(panelFramebuffer ? "direct" : "unavailable");
  panel.setBrightness(16);
  clearFrame(COLOR_BLACK);
  flushDisplay();
}

static bool drawRgb565Asset(const char* path, int x0, int y0, int width, int height) {
  File file = LittleFS.open(path, "r");
  if (!file) {
    return false;
  }
  if (file.size() != static_cast<size_t>(width) * height * 2) {
    file.close();
    return false;
  }

  uint8_t raw[SYSTEM_LOGO_WIDTH * 2];
  const int rowBytes = width * 2;
  if (rowBytes > static_cast<int>(sizeof(raw))) {
    file.close();
    return false;
  }
  for (int y = 0; y < height; y++) {
    size_t readLen = file.read(raw, rowBytes);
    if (readLen != static_cast<size_t>(rowBytes)) {
      file.close();
      return false;
    }
    for (int x = 0; x < width; x++) {
      uint16_t color = static_cast<uint16_t>(raw[x * 2]) | (static_cast<uint16_t>(raw[x * 2 + 1]) << 8);
      setPixel(x0 + x, y0 + y, color);
    }
  }
  file.close();
  return true;
}

static float smoothStep(float value) {
  if (value < 0.0f) {
    value = 0.0f;
  }
  if (value > 1.0f) {
    value = 1.0f;
  }
  return value * value * (3.0f - (2.0f * value));
}

static uint16_t scaleRgb565(uint16_t color, float brightness) {
  if (brightness >= 0.99f) {
    return color;
  }
  if (brightness < 0.0f) {
    brightness = 0.0f;
  }
  uint8_t r = (color >> 11) & 0x1F;
  uint8_t g = (color >> 5) & 0x3F;
  uint8_t b = color & 0x1F;
  r = static_cast<uint8_t>(static_cast<float>(r) * brightness);
  g = static_cast<uint8_t>(static_cast<float>(g) * brightness);
  b = static_cast<uint8_t>(static_cast<float>(b) * brightness);
  return static_cast<uint16_t>((r << 11) | (g << 5) | b);
}

static uint16_t scaleRgb5658(uint16_t color, uint8_t brightness) {
  if (brightness >= 252) {
    return color;
  }
  uint16_t r = (color >> 11) & 0x1F;
  uint16_t g = (color >> 5) & 0x3F;
  uint16_t b = color & 0x1F;
  r = (r * brightness) >> 8;
  g = (g * brightness) >> 8;
  b = (b * brightness) >> 8;
  return static_cast<uint16_t>((r << 11) | (g << 5) | b);
}

static uint16_t rgb888ToRgb565(uint8_t r, uint8_t g, uint8_t b) {
  return static_cast<uint16_t>(((r & 0xF8) << 8) | ((g & 0xFC) << 3) | (b >> 3));
}

static uint16_t blendRgb565(uint16_t a, uint16_t b, uint8_t amount) {
  uint16_t inv = 255 - amount;
  uint16_t ar = (a >> 11) & 0x1F;
  uint16_t ag = (a >> 5) & 0x3F;
  uint16_t ab = a & 0x1F;
  uint16_t br = (b >> 11) & 0x1F;
  uint16_t bg = (b >> 5) & 0x3F;
  uint16_t bb = b & 0x1F;
  uint16_t r = ((ar * inv) + (br * amount)) / 255;
  uint16_t g = ((ag * inv) + (bg * amount)) / 255;
  uint16_t blue = ((ab * inv) + (bb * amount)) / 255;
  return static_cast<uint16_t>((r << 11) | (g << 5) | blue);
}

static uint16_t* loadRgb565AssetToPsram(const char* path, int width, int height) {
  File file = LittleFS.open(path, "r");
  if (!file) {
    return nullptr;
  }
  size_t byteLen = static_cast<size_t>(width) * height * sizeof(uint16_t);
  if (file.size() != byteLen) {
    file.close();
    return nullptr;
  }

  uint16_t* pixels = static_cast<uint16_t*>(heap_caps_malloc(byteLen, MALLOC_CAP_SPIRAM | MALLOC_CAP_8BIT));
  if (!pixels) {
    file.close();
    return nullptr;
  }

  size_t readLen = file.read(reinterpret_cast<uint8_t*>(pixels), byteLen);
  file.close();
  if (readLen != byteLen) {
    heap_caps_free(pixels);
    return nullptr;
  }
  return pixels;
}

static uint8_t* loadAlphaAssetToPsram(const char* path, int width, int height) {
  File file = LittleFS.open(path, "r");
  if (!file) {
    return nullptr;
  }
  size_t byteLen = static_cast<size_t>(width) * height;
  if (file.size() != byteLen) {
    file.close();
    return nullptr;
  }

  uint8_t* alpha = static_cast<uint8_t*>(heap_caps_malloc(byteLen, MALLOC_CAP_SPIRAM | MALLOC_CAP_8BIT));
  if (!alpha) {
    file.close();
    return nullptr;
  }

  size_t readLen = file.read(alpha, byteLen);
  file.close();
  if (readLen != byteLen) {
    heap_caps_free(alpha);
    return nullptr;
  }
  return alpha;
}

static bool drawScaledRgb565Pixels(
    const uint16_t* pixels,
    int srcWidth,
    int srcHeight,
    int dstWidth,
    int dstHeight,
    uint8_t brightness) {
  if (!framebuffer || !pixels || dstWidth <= 0 || dstHeight <= 0) {
    return false;
  }

  const int x0 = (DISPLAY_WIDTH - dstWidth) / 2;
  const int y0 = (DISPLAY_HEIGHT - dstHeight) / 2;
  for (int y = 0; y < dstHeight; y++) {
    int srcY = (y * srcHeight) / dstHeight;
    const uint16_t* srcRow = pixels + static_cast<size_t>(srcY) * srcWidth;
    uint16_t* dstRow = framebuffer + static_cast<size_t>(y0 + y) * DISPLAY_WIDTH + x0;
    for (int x = 0; x < dstWidth; x++) {
      int srcX = (x * srcWidth) / dstWidth;
      dstRow[x] = scaleRgb5658(srcRow[srcX], brightness);
    }
  }
  return true;
}

static bool drawScaledMaskedRgb565Pixels(
    const uint16_t* pixels,
    const uint8_t* alpha,
    int srcWidth,
    int srcHeight,
    int dstWidth,
    int dstHeight,
    uint8_t brightness) {
  if (!framebuffer || !pixels || !alpha || dstWidth <= 0 || dstHeight <= 0) {
    return false;
  }

  const int x0 = (DISPLAY_WIDTH - dstWidth) / 2;
  const int y0 = (DISPLAY_HEIGHT - dstHeight) / 2;
  for (int y = 0; y < dstHeight; y++) {
    int srcY = (y * srcHeight) / dstHeight;
    const uint16_t* srcRow = pixels + static_cast<size_t>(srcY) * srcWidth;
    const uint8_t* alphaRow = alpha + static_cast<size_t>(srcY) * srcWidth;
    uint16_t* dstRow = framebuffer + static_cast<size_t>(y0 + y) * DISPLAY_WIDTH + x0;
    for (int x = 0; x < dstWidth; x++) {
      int srcX = (x * srcWidth) / dstWidth;
      if (alphaRow[srcX] >= 16) {
        dstRow[x] = scaleRgb5658(srcRow[srcX], brightness);
      }
    }
  }
  return true;
}

static bool drawScaledRgb565Asset(const char* path, int srcWidth, int srcHeight, int dstWidth, int dstHeight, float brightness) {
  File file = LittleFS.open(path, "r");
  if (!file) {
    return false;
  }
  if (file.size() != static_cast<size_t>(srcWidth) * srcHeight * 2) {
    file.close();
    return false;
  }

  uint8_t raw[SYSTEM_LOGO_WIDTH * 2];
  const int rowBytes = srcWidth * 2;
  if (rowBytes > static_cast<int>(sizeof(raw)) || dstWidth <= 0 || dstHeight <= 0) {
    file.close();
    return false;
  }

  const int x0 = (DISPLAY_WIDTH - dstWidth) / 2;
  const int y0 = (DISPLAY_HEIGHT - dstHeight) / 2;
  int lastSrcY = -1;
  for (int y = 0; y < dstHeight; y++) {
    int srcY = (y * srcHeight) / dstHeight;
    if (srcY != lastSrcY) {
      file.seek(static_cast<uint32_t>(srcY * rowBytes));
      size_t readLen = file.read(raw, rowBytes);
      if (readLen != static_cast<size_t>(rowBytes)) {
        file.close();
        return false;
      }
      lastSrcY = srcY;
    }
    for (int x = 0; x < dstWidth; x++) {
      int srcX = (x * srcWidth) / dstWidth;
      uint16_t color = static_cast<uint16_t>(raw[srcX * 2]) | (static_cast<uint16_t>(raw[srcX * 2 + 1]) << 8);
      setPixel(x0 + x, y0 + y, scaleRgb565(color, brightness));
    }
  }
  file.close();
  return true;
}

static bool drawMaskedRgb565Asset(const char* imagePath, const char* maskPath, int x0, int y0, int width, int height) {
  File image = LittleFS.open(imagePath, "r");
  File mask = LittleFS.open(maskPath, "r");
  if (!image || !mask) {
    if (image) {
      image.close();
    }
    if (mask) {
      mask.close();
    }
    return false;
  }
  if (image.size() != static_cast<size_t>(width) * height * 2 || mask.size() != static_cast<size_t>(width) * height) {
    image.close();
    mask.close();
    return false;
  }

  uint8_t raw[SYSTEM_LOGO_WIDTH * 2];
  uint8_t alpha[SYSTEM_LOGO_WIDTH];
  const int rowBytes = width * 2;
  if (rowBytes > static_cast<int>(sizeof(raw)) || width > static_cast<int>(sizeof(alpha))) {
    image.close();
    mask.close();
    return false;
  }

  for (int y = 0; y < height; y++) {
    size_t imageReadLen = image.read(raw, rowBytes);
    size_t maskReadLen = mask.read(alpha, width);
    if (imageReadLen != static_cast<size_t>(rowBytes) || maskReadLen != static_cast<size_t>(width)) {
      image.close();
      mask.close();
      return false;
    }
    for (int x = 0; x < width; x++) {
      if (alpha[x] < 16) {
        continue;
      }
      uint16_t color = static_cast<uint16_t>(raw[x * 2]) | (static_cast<uint16_t>(raw[x * 2 + 1]) << 8);
      setPixel(x0 + x, y0 + y, color);
    }
  }

  image.close();
  mask.close();
  return true;
}

static bool drawScaledMaskedRgb565Asset(
    const char* imagePath,
    const char* maskPath,
    int srcWidth,
    int srcHeight,
    int dstWidth,
    int dstHeight,
    float brightness) {
  File image = LittleFS.open(imagePath, "r");
  File mask = LittleFS.open(maskPath, "r");
  if (!image || !mask) {
    if (image) {
      image.close();
    }
    if (mask) {
      mask.close();
    }
    return false;
  }
  if (image.size() != static_cast<size_t>(srcWidth) * srcHeight * 2 || mask.size() != static_cast<size_t>(srcWidth) * srcHeight) {
    image.close();
    mask.close();
    return false;
  }

  uint8_t raw[SYSTEM_LOGO_WIDTH * 2];
  uint8_t alpha[SYSTEM_LOGO_WIDTH];
  const int rowBytes = srcWidth * 2;
  if (rowBytes > static_cast<int>(sizeof(raw)) || srcWidth > static_cast<int>(sizeof(alpha)) || dstWidth <= 0 || dstHeight <= 0) {
    image.close();
    mask.close();
    return false;
  }

  const int x0 = (DISPLAY_WIDTH - dstWidth) / 2;
  const int y0 = (DISPLAY_HEIGHT - dstHeight) / 2;
  int lastSrcY = -1;
  for (int y = 0; y < dstHeight; y++) {
    int srcY = (y * srcHeight) / dstHeight;
    if (srcY != lastSrcY) {
      image.seek(static_cast<uint32_t>(srcY * rowBytes));
      mask.seek(static_cast<uint32_t>(srcY * srcWidth));
      size_t imageReadLen = image.read(raw, rowBytes);
      size_t maskReadLen = mask.read(alpha, srcWidth);
      if (imageReadLen != static_cast<size_t>(rowBytes) || maskReadLen != static_cast<size_t>(srcWidth)) {
        image.close();
        mask.close();
        return false;
      }
      lastSrcY = srcY;
    }
    for (int x = 0; x < dstWidth; x++) {
      int srcX = (x * srcWidth) / dstWidth;
      if (alpha[srcX] < 16) {
        continue;
      }
      uint16_t pixel = static_cast<uint16_t>(raw[srcX * 2]) | (static_cast<uint16_t>(raw[srcX * 2 + 1]) << 8);
      setPixel(x0 + x, y0 + y, scaleRgb565(pixel, brightness));
    }
  }

  image.close();
  mask.close();
  return true;
}

static void drawBootShaderFrame(float progress) {
  clearFrame(COLOR_BLACK);

  const float eased = smoothStep(progress);
  const float spin = progress * 360.0f;
  const int tile = 8;
  for (int y = 0; y < DISPLAY_HEIGHT; y += tile) {
    for (int x = 0; x < DISPLAY_WIDTH; x += tile) {
      float dx = static_cast<float>(x + (tile / 2) - 240);
      float dy = static_cast<float>(y + (tile / 2) - 240);
      float dist = sqrtf((dx * dx) + (dy * dy));
      if (dist > 239.0f) {
        continue;
      }
      float wave = sinf((dist * 0.055f) - (progress * 9.0f));
      float angle = atan2f(dy, dx) + (progress * 4.0f);
      float spokes = sinf(angle * 6.0f);
      uint8_t amount = static_cast<uint8_t>(max(0.0f, min(1.0f, (wave + spokes + 2.0f) * 0.18f * eased)) * 120.0f);
      uint16_t base = blendRgb565(COLOR_BLACK, COLOR_DARK_CYAN, amount);
      if (amount > 8) {
        fillRect(x, y, tile, tile, base);
      }
    }
  }

  drawArc(240, 240, 224, 4, ARC_START_DEG, ARC_SWEEP_DEG, COLOR_TRACK);
  drawArc(240, 240, 224, 5, ARC_START_DEG + spin, 84.0f + (90.0f * eased), COLOR_INTEL_BLUE);
  drawArc(240, 240, 204, 4, ARC_START_DEG - (spin * 1.25f), -(70.0f + (110.0f * eased)), COLOR_NVIDIA_GREEN);
  drawArc(240, 240, 176, 3, spin * 0.7f, 50.0f + (80.0f * sinf(progress * 3.14159f)), COLOR_WHITE);

  int pulse = static_cast<int>(42.0f + (24.0f * sinf(progress * 3.14159f)));
  fillCircle(240, 240, pulse + 30, COLOR_DARK_CYAN);
  fillCircle(240, 240, pulse + 14, COLOR_BLACK);
  fillCircle(240, 240, pulse, blendRgb565(COLOR_INTEL_BLUE, COLOR_NVIDIA_GREEN, static_cast<uint8_t>(eased * 255.0f)));
  fillCircle(240, 240, max(8, pulse - 18), COLOR_BLACK);

  drawCenteredText("AIO DISPLAY", 214, 3, blendRgb565(COLOR_DIM, COLOR_WHITE, static_cast<uint8_t>(eased * 255.0f)));
  flushDisplay();
}

static void drawBootShaderBackdrop(float progress, uint16_t accent) {
  clearFrame(COLOR_BLACK);

  const float spin = progress * 360.0f;
  drawArc(240, 240, 224, 3, ARC_START_DEG, ARC_SWEEP_DEG, COLOR_TRACK);
  drawArc(240, 240, 224, 5, ARC_START_DEG + spin, 96.0f, accent);
  drawArc(240, 240, 204, 4, ARC_START_DEG - (spin * 1.18f), -84.0f, COLOR_DIM);
  drawArc(240, 240, 176, 3, spin * 0.64f, 62.0f, blendRgb565(accent, COLOR_WHITE, 72));

  for (int i = 0; i < 18; i++) {
    float phase = (static_cast<float>(i) / 18.0f) * 360.0f;
    float rad = (phase + (spin * (i % 2 == 0 ? 1.0f : -0.72f))) * 0.01745329252f;
    int radius = 72 + ((i * 19) % 132);
    int x = 240 + static_cast<int>(cosf(rad) * radius);
    int y = 240 + static_cast<int>(sinf(rad) * radius);
    uint8_t mix = static_cast<uint8_t>(72 + ((i * 17) % 120));
    fillCircle(x, y, 2 + (i % 3), blendRgb565(accent, COLOR_WHITE, mix));
  }
}

static void drawBootLogoLayer(const uint16_t* pixels, const char* assetPath, int srcWidth, int srcHeight, float opacity) {
  if (opacity <= 0.01f) {
    return;
  }

  int drawWidth = srcWidth;
  int drawHeight = srcHeight;
  if (drawWidth > 360 || drawHeight > 300) {
    float scale = min(360.0f / static_cast<float>(drawWidth), 300.0f / static_cast<float>(drawHeight));
    drawWidth = static_cast<int>(static_cast<float>(drawWidth) * scale);
    drawHeight = static_cast<int>(static_cast<float>(drawHeight) * scale);
  }

  uint8_t brightness = static_cast<uint8_t>(max(0.0f, min(1.0f, opacity)) * 255.0f);
  if (pixels) {
    const int x0 = (DISPLAY_WIDTH - drawWidth) / 2;
    const int y0 = (DISPLAY_HEIGHT - drawHeight) / 2;
    for (int y = 0; y < drawHeight; y++) {
      int srcY = (y * srcHeight) / drawHeight;
      const uint16_t* srcRow = pixels + static_cast<size_t>(srcY) * srcWidth;
      for (int x = 0; x < drawWidth; x++) {
        int srcX = (x * srcWidth) / drawWidth;
        uint16_t color = srcRow[srcX];
        uint8_t r = (color >> 11) & 0x1F;
        uint8_t g = (color >> 5) & 0x3F;
        uint8_t b = color & 0x1F;
        if (r <= 1 && g <= 2 && b <= 1) {
          continue;
        }
        setPixel(x0 + x, y0 + y, scaleRgb5658(color, brightness));
      }
    }
    return;
  }

  File file = LittleFS.open(assetPath, "r");
  if (!file) {
    return;
  }
  if (file.size() != static_cast<size_t>(srcWidth) * srcHeight * 2) {
    file.close();
    return;
  }

  uint8_t raw[SYSTEM_LOGO_WIDTH * 2];
  const int rowBytes = srcWidth * 2;
  if (rowBytes > static_cast<int>(sizeof(raw))) {
    file.close();
    return;
  }

  const int x0 = (DISPLAY_WIDTH - drawWidth) / 2;
  const int y0 = (DISPLAY_HEIGHT - drawHeight) / 2;
  int lastSrcY = -1;
  for (int y = 0; y < drawHeight; y++) {
    int srcY = (y * srcHeight) / drawHeight;
    if (srcY != lastSrcY) {
      file.seek(static_cast<uint32_t>(srcY * rowBytes));
      size_t readLen = file.read(raw, rowBytes);
      if (readLen != static_cast<size_t>(rowBytes)) {
        break;
      }
      lastSrcY = srcY;
    }
    for (int x = 0; x < drawWidth; x++) {
      int srcX = (x * srcWidth) / drawWidth;
      uint16_t color = static_cast<uint16_t>(raw[srcX * 2]) | (static_cast<uint16_t>(raw[srcX * 2 + 1]) << 8);
      uint8_t r = (color >> 11) & 0x1F;
      uint8_t g = (color >> 5) & 0x3F;
      uint8_t b = color & 0x1F;
      if (r <= 1 && g <= 2 && b <= 1) {
        continue;
      }
      setPixel(x0 + x, y0 + y, scaleRgb5658(color, brightness));
    }
  }
  file.close();
}

static void drawBootSystemLogoLayer(const uint16_t* pixels, const uint8_t* alpha, float opacity) {
  if (opacity <= 0.01f) {
    return;
  }
  uint8_t brightness = static_cast<uint8_t>(max(0.0f, min(1.0f, opacity)) * 255.0f);
  if (pixels && alpha) {
    drawScaledMaskedRgb565Pixels(pixels, alpha, SYSTEM_LOGO_WIDTH, SYSTEM_LOGO_HEIGHT, 360, 360, brightness);
  } else {
    drawScaledMaskedRgb565Asset("/boot/system.rgb565", "/boot/system.alpha", SYSTEM_LOGO_WIDTH, SYSTEM_LOGO_HEIGHT, 360, 360, opacity);
  }
}

void renderBootAnimation() {
  if (!framebuffer) {
    return;
  }

  struct BootPart {
    const char* assetPath;
    uint16_t color;
  };

  static const BootPart parts[] = {
      {"/boot/astral.rgb565", COLOR_CYAN},
      {"/boot/rog.rgb565", COLOR_RED},
      {"/boot/tuf.rgb565", COLOR_ORANGE},
      {"/boot/corsair.rgb565", COLOR_WHITE},
  };

  const size_t partCount = sizeof(parts) / sizeof(parts[0]);
  uint16_t* bootPixels[partCount] = {};
  for (size_t part = 0; part < partCount; part++) {
    bootPixels[part] = loadRgb565AssetToPsram(parts[part].assetPath, BOOT_LOGO_WIDTH, BOOT_LOGO_HEIGHT);
  }
  uint16_t* systemPixels = loadRgb565AssetToPsram("/boot/system.rgb565", SYSTEM_LOGO_WIDTH, SYSTEM_LOGO_HEIGHT);
  uint8_t* systemAlpha = loadAlphaAssetToPsram("/boot/system.alpha", SYSTEM_LOGO_WIDTH, SYSTEM_LOGO_HEIGHT);

  const int frames = 84;
  const int logoCount = static_cast<int>(partCount) + 1;
  for (int frame = 0; frame <= frames; frame++) {
    float progress = static_cast<float>(frame) / static_cast<float>(frames);
    float position = progress * static_cast<float>(logoCount);
    int active = min(logoCount - 1, static_cast<int>(floorf(position)));
    float phase = position - static_cast<float>(active);
    float fadeOut = active == logoCount - 1 ? 1.0f : 1.0f - smoothStep(max(0.0f, (phase - 0.58f) / 0.42f));
    float fadeIn = active == 0 ? smoothStep(min(1.0f, phase / 0.28f)) : 1.0f;

    uint16_t accent = active < static_cast<int>(partCount) ? parts[active].color : COLOR_PURPLE;
    drawBootShaderBackdrop(progress, accent);

    if (active < static_cast<int>(partCount)) {
      drawBootLogoLayer(bootPixels[active], parts[active].assetPath, BOOT_LOGO_WIDTH, BOOT_LOGO_HEIGHT, fadeIn * fadeOut);
    } else {
      drawBootSystemLogoLayer(systemPixels, systemAlpha, fadeIn);
    }

    if (phase > 0.58f && active + 1 < logoCount) {
      float nextOpacity = smoothStep((phase - 0.58f) / 0.42f);
      int next = active + 1;
      if (next < static_cast<int>(partCount)) {
        drawBootLogoLayer(bootPixels[next], parts[next].assetPath, BOOT_LOGO_WIDTH, BOOT_LOGO_HEIGHT, nextOpacity);
      } else {
        drawBootSystemLogoLayer(systemPixels, systemAlpha, nextOpacity);
      }
    }

    flushDisplay();
    delay(8);
  }

  for (size_t part = 0; part < partCount; part++) {
    if (bootPixels[part]) {
      heap_caps_free(bootPixels[part]);
    }
  }
  if (systemPixels) {
    heap_caps_free(systemPixels);
  }
  if (systemAlpha) {
    heap_caps_free(systemAlpha);
  }
}

void renderBootIdleAnimationFrame(uint32_t nowMs) {
  const uint32_t cycleMs = 2400;
  float progress = static_cast<float>(nowMs % cycleMs) / static_cast<float>(cycleMs);
  drawBootShaderFrame(progress);
}

bool readDisplayTouchRaw(int16_t& x, int16_t& y) {
  int16_t xs[1] = {0};
  int16_t ys[1] = {0};
  uint8_t touched = panel.getPoint(xs, ys, 1);
  if (!touched) {
    return false;
  }
  x = xs[0];
  y = ys[0];
  return x >= 0 && y >= 0 && x < DISPLAY_WIDTH && y < DISPLAY_HEIGHT;
}

bool readDisplayTouchPressed() {
  return panel.isPressed();
}

bool readDisplayTouch(int16_t& x, int16_t& y) {
  if (!readDisplayTouchRaw(x, y)) {
    return false;
  }
#if DISPLAY_ROTATE_180
  x = DISPLAY_WIDTH - 1 - x;
  y = DISPLAY_HEIGHT - 1 - y;
#endif
  return x >= 0 && y >= 0 && x < DISPLAY_WIDTH && y < DISPLAY_HEIGHT;
}

void renderTouchFeedback(int16_t x, int16_t y, bool accepted) {
  if (!framebuffer) {
    return;
  }
  uint16_t color = accepted ? COLOR_GREEN : COLOR_RED;
  fillCircle(x, y, 18, COLOR_BLACK);
  fillCircle(x, y, 12, color);
  drawCenteredText(accepted ? "TAP" : "MISS", 440, 2, color);
  flushDisplay();
}

static void drawLogo() {
  const int x0 = (DISPLAY_WIDTH - LOGO_RENDER_SIZE) / 2;
  const int y0 = 104;

  if (!hasCachedAsset()) {
    fillCircle(DISPLAY_WIDTH / 2, y0 + LOGO_RENDER_SIZE / 2, 90, COLOR_DARK_CYAN);
    fillCircle(DISPLAY_WIDTH / 2, y0 + LOGO_RENDER_SIZE / 2, 64, COLOR_BLACK);
    fillCircle(DISPLAY_WIDTH / 2, y0 + LOGO_RENDER_SIZE / 2, 34, COLOR_CYAN);
    return;
  }

  File file = LittleFS.open(cachedAssetPath(), "r");
  if (!file) {
    return;
  }
  uint8_t raw[ASSET_WIDTH * 2];
  for (int y = 0; y < LOGO_RENDER_SIZE; y++) {
    int srcY = (y * ASSET_HEIGHT) / LOGO_RENDER_SIZE;
    file.seek(static_cast<uint32_t>(srcY * ASSET_WIDTH * 2));
    size_t readLen = file.read(raw, sizeof(raw));
    if (readLen != sizeof(raw)) {
      break;
    }
    for (int x = 0; x < LOGO_RENDER_SIZE; x++) {
      int srcX = (x * ASSET_WIDTH) / LOGO_RENDER_SIZE;
      uint16_t color = static_cast<uint16_t>(raw[srcX * 2]) | (static_cast<uint16_t>(raw[srcX * 2 + 1]) << 8);
      setPixel(x0 + x, y0 + y, color);
    }
  }
  file.close();
}

void renderDisplay(const DisplayState& state, bool offline) {
  if (!framebuffer) {
    return;
  }
  uint32_t now = millis();
  if (displayAnimLastMs == 0) {
    displayAnimLastMs = now;
  }
  uint32_t elapsed = now - displayAnimLastMs;
  displayAnimLastMs = now;

  displayCpuLoad = smoothPercentValue(displayCpuLoad, state.cpuLoad, elapsed);
  displayGpuLoad = smoothPercentValue(displayGpuLoad, state.gpuLoad, elapsed);
  displayRamUsedPercent = smoothPercentValue(displayRamUsedPercent, state.ramUsedPercent, elapsed);
  displayCpuTemp = animatedValue(displayCpuTemp, state.cpuTemp, 10.0f, elapsed);
  displayGpuTemp = animatedValue(displayGpuTemp, state.gpuTemp, 8.0f, elapsed);

  clearFrame(COLOR_BLACK);

  String title = state.displayName.length() > 0 ? state.displayName : "Default";
  if (title.length() > 18) {
    title = title.substring(0, 18);
  }
  title.toUpperCase();

  drawUsageArcs(displayCpuLoad, displayGpuLoad, displayRamUsedPercent);
  drawCenteredText(title, 68, 4, COLOR_WHITE);
  drawLogo();
  if (!state.reviewAvailable) {
    drawTempValue(formatTemp(displayCpuTemp), 70, 326, 168, COLOR_INTEL_BLUE);
    drawTempValue(formatTemp(displayGpuTemp), 242, 326, 168, COLOR_NVIDIA_GREEN);
  }
  if (state.reviewAvailable) {
    drawCenteredText("REVIEW", 400, 2, COLOR_DIM);
    fillCircle(150, 410, 38, COLOR_DARK_GREEN);
    fillCircle(150, 410, 30, COLOR_GREEN);
    drawText("A", 141, 400, 3, COLOR_BLACK);

    fillCircle(330, 410, 38, COLOR_DARK_RED);
    fillCircle(330, 410, 30, COLOR_RED);
    drawText("R", 321, 400, 3, COLOR_WHITE);
  } else {
    drawClockDate(state);
  }
  fillCircle(438, 56, 9, offline ? COLOR_RED : COLOR_GREEN);

  flushDisplay();
}

bool drawSignalRgb565Rect(int x, int y, int width, int height, const uint8_t* data, size_t dataLen) {
  if (!framebuffer || !data || width <= 0 || height <= 0 || dataLen != static_cast<size_t>(width) * height * 2) {
    return false;
  }
  if (x < 0 || y < 0 || x + width > 240 || y + height > 240) {
    return false;
  }

  for (int sy = 0; sy < height; sy++) {
#if DISPLAY_ROTATE_180
    const uint8_t* src = data + (static_cast<size_t>(sy) * width * 2);
    for (int sx = 0; sx < width; sx++) {
      uint16_t color = static_cast<uint16_t>(src[0]) | (static_cast<uint16_t>(src[1]) << 8);
      int dstX = (x + sx) * 2;
      int dstY = (y + sy) * 2;
      for (int yy = 0; yy < 2; yy++) {
        uint16_t* row = framebuffer + (DISPLAY_HEIGHT - 1 - (dstY + yy)) * DISPLAY_WIDTH;
        row[DISPLAY_WIDTH - 1 - dstX] = color;
        row[DISPLAY_WIDTH - 2 - dstX] = color;
      }
      src += 2;
    }
#else
    uint16_t* row0 = framebuffer + ((y + sy) * 2) * DISPLAY_WIDTH + (x * 2);
    uint16_t* row1 = row0 + DISPLAY_WIDTH;
    const uint8_t* src = data + (static_cast<size_t>(sy) * width * 2);
    for (int sx = 0; sx < width; sx++) {
      uint16_t color = static_cast<uint16_t>(src[0]) | (static_cast<uint16_t>(src[1]) << 8);
      int dx = sx * 2;
      row0[dx] = color;
      row0[dx + 1] = color;
      row1[dx] = color;
      row1[dx + 1] = color;
      src += 2;
    }
#endif
  }
  return true;
}

bool drawSignalRgb565RectScaled(int x, int y, int width, int height, int scale, const uint8_t* data, size_t dataLen) {
  if (!framebuffer || !data || width <= 0 || height <= 0 || scale <= 0 ||
      dataLen != static_cast<size_t>(width) * height * 2) {
    return false;
  }
  if (x < 0 || y < 0 || (x + width) * scale > DISPLAY_WIDTH || (y + height) * scale > DISPLAY_HEIGHT) {
    return false;
  }

  if (signalLineBuffer) {
    const int dstX = x * scale;
    const int dstWidth = width * scale;
    for (int sy = 0; sy < height; sy++) {
      const uint8_t* src = data + (static_cast<size_t>(sy) * width * 2);
#if DISPLAY_ROTATE_180
      int out = DISPLAY_WIDTH - 1 - dstX;
      for (int sx = 0; sx < width; sx++) {
        uint16_t color = static_cast<uint16_t>(src[0]) | (static_cast<uint16_t>(src[1]) << 8);
        for (int xx = 0; xx < scale; xx++) {
          signalLineBuffer[out--] = color;
        }
        src += 2;
      }
      const int copyX = DISPLAY_WIDTH - dstX - dstWidth;
#else
      int out = dstX;
      for (int sx = 0; sx < width; sx++) {
        uint16_t color = static_cast<uint16_t>(src[0]) | (static_cast<uint16_t>(src[1]) << 8);
        for (int xx = 0; xx < scale; xx++) {
          signalLineBuffer[out++] = color;
        }
        src += 2;
      }
      const int copyX = dstX;
#endif
      const int dstY = (y + sy) * scale;
      for (int yy = 0; yy < scale; yy++) {
#if DISPLAY_ROTATE_180
        uint16_t* row = framebuffer + (DISPLAY_HEIGHT - 1 - (dstY + yy)) * DISPLAY_WIDTH + copyX;
#else
        uint16_t* row = framebuffer + (dstY + yy) * DISPLAY_WIDTH + copyX;
#endif
        memcpy(row, signalLineBuffer + copyX, static_cast<size_t>(dstWidth) * sizeof(uint16_t));
      }
    }
    return true;
  }

  for (int sy = 0; sy < height; sy++) {
    const uint8_t* src = data + (static_cast<size_t>(sy) * width * 2);
    int dstY = (y + sy) * scale;
    for (int sx = 0; sx < width; sx++) {
      uint16_t color = static_cast<uint16_t>(src[0]) | (static_cast<uint16_t>(src[1]) << 8);
      int dstX = (x + sx) * scale;
      for (int yy = 0; yy < scale; yy++) {
#if DISPLAY_ROTATE_180
        uint16_t* row = framebuffer + (DISPLAY_HEIGHT - 1 - (dstY + yy)) * DISPLAY_WIDTH;
        for (int xx = 0; xx < scale; xx++) {
          row[DISPLAY_WIDTH - 1 - (dstX + xx)] = color;
        }
#else
        uint16_t* row = framebuffer + (dstY + yy) * DISPLAY_WIDTH + dstX;
        for (int xx = 0; xx < scale; xx++) {
          row[xx] = color;
        }
#endif
      }
      src += 2;
    }
  }
  return true;
}

void flushSignalRgbFrame() {
  if (!framebuffer) {
    return;
  }
  drawSignalFpsOverlay();
#if DISPLAY_ROTATE_180
  flushDisplayRaw();
#else
  flushDisplay();
#endif
}

static int signalJpegDrawCallback(JPEGDRAW* draw) {
  if (!framebuffer || !draw || !draw->pPixels) {
    return 0;
  }

  const int x0 = max(0, draw->x);
  const int y0 = max(0, draw->y);
  const int x1 = min(DISPLAY_WIDTH, draw->x + draw->iWidth);
  const int y1 = min(DISPLAY_HEIGHT, draw->y + draw->iHeight);
  if (x0 >= x1 || y0 >= y1) {
    return 1;
  }

  const uint16_t* src = reinterpret_cast<const uint16_t*>(draw->pPixels);
  for (int y = y0; y < y1; y++) {
    const int srcY = y - draw->y;
    const int srcX = x0 - draw->x;
#if DISPLAY_ROTATE_180
    uint16_t* dst = framebuffer + (static_cast<size_t>(DISPLAY_HEIGHT - 1 - y) * DISPLAY_WIDTH);
    const uint16_t* srcRow = src + (static_cast<size_t>(srcY) * draw->iWidth) + srcX;
    for (int x = x0; x < x1; x++) {
      dst[DISPLAY_WIDTH - 1 - x] = *srcRow++;
    }
#else
    uint16_t* dst = framebuffer + (static_cast<size_t>(y) * DISPLAY_WIDTH) + x0;
    memcpy(dst, src + (static_cast<size_t>(srcY) * draw->iWidth) + srcX,
           static_cast<size_t>(x1 - x0) * sizeof(uint16_t));
#endif
  }
  return 1;
}

bool drawSignalJpegFrame(const uint8_t* data, size_t dataLen) {
  if (!framebuffer || !data || dataLen < 4) {
    return false;
  }

  uint16_t* appFramebuffer = framebuffer;
  const bool directPanelFrame = SIGNALRGB_DIRECT_FRAMEBUFFER && panelFramebuffer != nullptr;
  const bool directDecodeOffscreen = directPanelFrame && SIGNALRGB_DIRECT_DECODE_OFFSCREEN;
  if (directPanelFrame && !directDecodeOffscreen) {
    framebuffer = panelFramebuffer;
  }

  if (!signalJpeg.openRAM(const_cast<uint8_t*>(data), static_cast<int>(dataLen), signalJpegDrawCallback)) {
    clearFrame(COLOR_BLACK);
    drawCenteredText("JPEG OPEN", 214, 3, COLOR_RED);
    if (!directPanelFrame) {
      flushDisplay();
    }
    framebuffer = appFramebuffer;
    return false;
  }

  const int jpegWidth = signalJpeg.getWidth();
  const int jpegHeight = signalJpeg.getHeight();
  signalLastJpegWidth = jpegWidth;
  signalLastJpegHeight = jpegHeight;
  const int x = max(0, (DISPLAY_WIDTH - jpegWidth) / 2);
  const int y = max(0, (DISPLAY_HEIGHT - jpegHeight) / 2);
  const bool directJpegFramebufferDecode =
      directPanelFrame &&
      !directDecodeOffscreen &&
      SIGNALRGB_DIRECT_JPEG_FRAMEBUFFER_DECODE &&
      !DISPLAY_ROTATE_180 &&
      jpegWidth == DISPLAY_WIDTH &&
      jpegHeight == DISPLAY_HEIGHT;
  if (directJpegFramebufferDecode) {
    signalJpeg.setFramebuffer(framebuffer);
  }
  signalJpeg.setPixelType(RGB565_LITTLE_ENDIAN);
  signalJpeg.setMaxOutputSize(DISPLAY_WIDTH / 16);
  if (jpegWidth < DISPLAY_WIDTH || jpegHeight < DISPLAY_HEIGHT) {
    clearFrame(COLOR_BLACK);
  }
  const uint32_t decodeStartedMs = millis();
  const int result = signalJpeg.decode(x, y, 0);
  signalDecodeMs = millis() - decodeStartedMs;
  signalJpeg.close();
  if (result == 0) {
    clearFrame(COLOR_BLACK);
    drawCenteredText("JPEG DECODE", 214, 3, COLOR_RED);
    if (!directPanelFrame) {
      flushDisplay();
    }
    framebuffer = appFramebuffer;
    return false;
  }

  const uint32_t flushStartedMs = millis();
  if (directPanelFrame) {
#if SIGNALRGB_DIRECT_FPS_OVERLAY
    drawJpegFpsOverlay();
#endif
    if (directDecodeOffscreen) {
      memcpy(panelFramebuffer, appFramebuffer,
             static_cast<size_t>(DISPLAY_WIDTH) * DISPLAY_HEIGHT * sizeof(uint16_t));
    }
#if SIGNALRGB_DIRECT_CACHE_WRITEBACK
    Cache_WriteBack_Addr(reinterpret_cast<uint32_t>(directDecodeOffscreen ? panelFramebuffer : framebuffer),
                         static_cast<uint32_t>(DISPLAY_WIDTH * DISPLAY_HEIGHT * sizeof(uint16_t)));
#endif
    signalFlushMs = millis() - flushStartedMs;
    framebuffer = appFramebuffer;
    return true;
  }
  drawJpegFpsOverlay();
#if DISPLAY_ROTATE_180
  flushDisplayRaw();
#else
  flushDisplay();
#endif
  signalFlushMs = millis() - flushStartedMs;
  framebuffer = appFramebuffer;
  return true;
}

void setSignalRxStats(uint32_t bytes, uint32_t rxMs) {
  signalRxBytes = bytes;
  signalRxMs = rxMs;
}

void getSignalTimingStats(uint32_t& rxMs, uint32_t& decodeMs, uint32_t& flushMs) {
  rxMs = signalRxMs;
  decodeMs = signalDecodeMs;
  flushMs = signalFlushMs;
}

int signalJpegWidth() {
  return signalLastJpegWidth;
}

int signalJpegHeight() {
  return signalLastJpegHeight;
}

void renderSignalStatus(const String& text, uint16_t color) {
  if (!framebuffer) {
    return;
  }
  constexpr int boxW = 168;
  constexpr int boxH = 28;
  constexpr int boxX = (DISPLAY_WIDTH - boxW) / 2;
  constexpr int boxY = DISPLAY_HEIGHT - 58;
  fillRect(boxX, boxY, boxW, boxH, COLOR_BLACK);
  int x = boxX + ((boxW - textWidth(text, 2)) / 2);
  drawText(text, max(0, x), boxY + 7, 2, color);
  flushDisplay();
}

void renderSignalRgbLocalFrame(
    uint8_t baseR,
    uint8_t baseG,
    uint8_t baseB,
    uint8_t accentR,
    uint8_t accentG,
    uint8_t accentB,
    uint8_t energy) {
  if (!framebuffer) {
    return;
  }

  uint16_t base = rgb888ToRgb565(baseR, baseG, baseB);
  uint16_t accent = rgb888ToRgb565(accentR, accentG, accentB);
  uint16_t bg = scaleRgb5658(base, 28);
  uint16_t track = blendRgb565(COLOR_TRACK, bg, 96);
  uint8_t pulse = static_cast<uint8_t>(72 + ((static_cast<uint16_t>(energy) * 120) / 255));
  uint16_t glow = blendRgb565(base, accent, pulse);

  clearFrame(COLOR_BLACK);
  fillCircle(240, 240, 224, bg);
  fillCircle(240, 240, 188, COLOR_BLACK);

  float t = static_cast<float>(signalLocalFrame % 360);
  float sweep = 90.0f + (static_cast<float>(energy) * 0.75f);
  drawArc(240, 240, 220, 5, t, sweep, glow);
  drawArc(240, 240, 198, 4, 360.0f - (t * 1.35f), sweep * 0.72f, accent);
  drawArc(240, 240, 174, 3, t * 1.85f, 60.0f + (static_cast<float>(energy) * 0.35f), blendRgb565(base, COLOR_WHITE, 64));
  drawArc(240, 240, 224, 2, ARC_START_DEG, ARC_SWEEP_DEG, track);

  for (int i = 0; i < 6; i++) {
    float deg = t * (1.4f + (i * 0.08f)) + (i * 60.0f);
    float rad = deg * 0.01745329252f;
    int radius = 62 + (i * 20);
    int dot = 6 + ((energy + i * 17) / 70);
    int x = 240 + static_cast<int>(roundf(cosf(rad) * radius));
    int y = 240 + static_cast<int>(roundf(sinf(rad) * radius));
    fillCircle(x, y, dot, (i % 2) ? accent : glow);
  }

  int coreRadius = 36 + (energy / 10);
  fillCircle(240, 240, coreRadius + 18, scaleRgb5658(accent, 72));
  fillCircle(240, 240, coreRadius, glow);
  fillCircle(240, 240, max(8, coreRadius - 18), blendRgb565(glow, COLOR_WHITE, 72));

  signalLocalFrame += 5 + (energy / 42);
  flushDisplay();
}
