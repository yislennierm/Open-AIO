#pragma once

#include <Arduino.h>

#include "protocol.h"

void initDisplay();
void renderBootAnimation();
void renderBootIdleAnimationFrame(uint32_t nowMs);
void renderDisplay(const DisplayState& state, bool offline);
bool readDisplayTouch(int16_t& x, int16_t& y);
bool readDisplayTouchRaw(int16_t& x, int16_t& y);
bool readDisplayTouchPressed();
void renderTouchFeedback(int16_t x, int16_t y, bool accepted);
bool drawSignalRgb565Rect(int x, int y, int width, int height, const uint8_t* data, size_t dataLen);
bool drawSignalRgb565RectScaled(int x, int y, int width, int height, int scale, const uint8_t* data, size_t dataLen);
void setSignalRxStats(uint32_t bytes, uint32_t rxMs);
void getSignalTimingStats(uint32_t& rxMs, uint32_t& decodeMs, uint32_t& flushMs);
bool drawSignalJpegFrame(const uint8_t* data, size_t dataLen);
int signalJpegWidth();
int signalJpegHeight();
void renderSignalStatus(const String& text, uint16_t color);
void flushSignalRgbFrame();
void renderSignalRgbLocalFrame(uint8_t baseR, uint8_t baseG, uint8_t baseB, uint8_t accentR, uint8_t accentG, uint8_t accentB, uint8_t energy);
