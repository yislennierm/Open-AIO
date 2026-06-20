#include <Arduino.h>
#include <esp_heap_caps.h>

#include "assets.h"
#include "config.h"
#include "display.h"
#include "network.h"
#include "protocol.h"

#if SIGNALRGB_RAWUSB_EXPERIMENT
#define RAWUSB_STREAM_ENABLED (!NZXT_CAM_HID_ONLY)
#include <USB.h>
#if RAWUSB_STREAM_ENABLED
#include <USBVendor.h>
#endif
#if NZXT_CAM_SPOOF
#include <USBHIDVendor.h>
#endif

#if RAWUSB_STREAM_ENABLED
static USBVendor rawUsb(64);
#endif
#if NZXT_CAM_SPOOF
static void sendNzxtHidResponse(const uint8_t *request, size_t len);
static void processNzxtHidQueue();
static USBHIDVendor nzxtHid(63, false);
#endif
#if RAWUSB_STREAM_ENABLED
extern "C" uint32_t tud_vendor_n_write_flush(uint8_t itf);
extern "C" uint32_t tud_vendor_n_available(uint8_t itf);
extern "C" uint32_t tud_vendor_n_read(uint8_t itf, void* buffer, uint32_t bufsize);

static constexpr uint8_t MICROSOFT_OS_VENDOR_CODE = 0x20;

struct DirectVendorStream {
  uint8_t itf;

  int available() {
    return static_cast<int>(tud_vendor_n_available(itf));
  }

  size_t read(uint8_t* buffer, size_t size) {
    return static_cast<size_t>(tud_vendor_n_read(itf, buffer, static_cast<uint32_t>(size)));
  }
};

static const uint8_t microsoftOsCompatIdDescriptor[] = {
    0x28, 0x00, 0x00, 0x00,  // dwLength
    0x00, 0x01,              // bcdVersion
    0x04, 0x00,              // wIndex: extended compat ID
    0x01,                    // bCount
    0x00, 0x00, 0x00, 0x00,
    0x00, 0x00, 0x00,
#if NZXT_CAM_SPOOF
    0x01,                    // vendor interface follows the HID control interface
#else
    0x00,                    // first interface
#endif
    0x01,
    'W', 'I', 'N', 'U', 'S', 'B', 0x00, 0x00,
    0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00,
    0x00, 0x00, 0x00, 0x00,
    0x00, 0x00
};
#endif

extern "C" uint16_t const *tud_descriptor_string_cb(uint8_t index, uint16_t) {
  static uint16_t descriptor[64];
#if RAWUSB_STREAM_ENABLED
  static const uint16_t msOsString[] = {
      0x0312, 'M', 'S', 'F', 'T', '1', '0', '0', MICROSOFT_OS_VENDOR_CODE
  };
#endif

  if (index == 0xEE) {
#if RAWUSB_STREAM_ENABLED && !NZXT_CAM_SPOOF
    return msOsString;
#else
    return nullptr;
#endif
  }

  const char *value = nullptr;
  if (index == 0) {
    descriptor[0] = (0x03 << 8) | 0x04;
    descriptor[1] = 0x0409;
    return descriptor;
  }
  if (index == 1) {
#if NZXT_CAM_SPOOF
    value = "NZXT";
#else
    value = "Open AIO";
#endif
  } else if (index == 2) {
#if NZXT_CAM_SPOOF
    value = "Kraken Elite RGB";
#else
    value = DEVICE_NAME;
#endif
  } else if (index == 3) {
    value = DEVICE_ID;
  } else if (index == 4) {
#if NZXT_CAM_SPOOF
    value = "NZXT HID";
#else
    value = "TinyUSB HID";
#endif
  } else if (index == 5) {
#if NZXT_CAM_SPOOF
    value = "NZXT LCD";
#else
    value = "TinyUSB Vendor";
#endif
  } else if (index == 6) {
#if NZXT_CAM_SPOOF
    value = "NZXT Composite";
#else
    value = "TinyUSB Device";
#endif
  } else {
    return nullptr;
  }

  size_t length = strlen(value);
  if (length > 63) {
    length = 63;
  }
  descriptor[0] = (0x03 << 8) | static_cast<uint16_t>((length * 2) + 2);
  for (size_t i = 0; i < length; i++) {
    descriptor[i + 1] = static_cast<uint8_t>(value[i]);
  }
  return descriptor;
}

#if RAWUSB_STREAM_ENABLED
static bool handleRawUsbControlRequest(uint8_t rhport, uint8_t stage, arduino_usb_control_request_t const *request) {
  if (stage != REQUEST_STAGE_SETUP || request->bmRequestDirection != REQUEST_DIRECTION_IN ||
      request->bmRequestType != REQUEST_TYPE_VENDOR || request->bRequest != MICROSOFT_OS_VENDOR_CODE ||
      request->wIndex != 0x0004) {
    return false;
  }
  return rawUsb.sendResponse(rhport, request, const_cast<uint8_t *>(microsoftOsCompatIdDescriptor),
                             sizeof(microsoftOsCompatIdDescriptor));
}
#endif

#if NZXT_CAM_SPOOF
static void sendNzxtHidResponse(const uint8_t *request, size_t len) {
  if (!request || len < 2) {
    return;
  }

  uint8_t response[63] = {};
  if (request[0] == 0x10 && request[1] == 0x01) {
    response[0] = 0x11;
    response[1] = 0x01;
    response[0x11] = 2;
    response[0x12] = 0;
    response[0x13] = 0;
    nzxtHid.write(response, sizeof(response));
  } else if (request[0] == 0x20 && request[1] == 0x03) {
    response[0] = 0x21;
    response[1] = 0x03;
    response[14] = 0;
    nzxtHid.write(response, sizeof(response));
  }
}

static void processNzxtHidQueue() {
  uint8_t request[63] = {};
  while (nzxtHid.available() > 0) {
    size_t len = 0;
    while (len < sizeof(request) && nzxtHid.available() > 0) {
      int value = nzxtHid.read();
      if (value < 0) {
        break;
      }
      request[len++] = static_cast<uint8_t>(value);
    }
    sendNzxtHidResponse(request, len);
  }
}

#endif
#endif

static DisplayState currentState;
static uint32_t lastPollMs = 0;
static uint32_t lastTouchMs = 0;
static uint32_t lastTouchIdleDiagnosticMs = 0;
static uint32_t lastSignalRgbMs = 0;
static uint32_t lastSignalRgbRxMs = 0;
static uint32_t lastUsbAppStateMs = 0;
static uint32_t lastUsbAppRenderMs = 0;
static uint32_t lastDisplayAnimMs = 0;
static uint32_t lastBootIdleFrameMs = 0;
static uint32_t lastSignalRgbRejectLogMs = 0;
static bool currentOffline = true;
static uint8_t localBaseR = 0;
static uint8_t localBaseG = 160;
static uint8_t localBaseB = 255;
static uint8_t localAccentR = 118;
static uint8_t localAccentG = 255;
static uint8_t localAccentB = 0;
static uint8_t localEnergy = 96;
static bool localSignalMode = false;

static constexpr uint32_t SIGNALRGB_TIMEOUT_MS = 3000;
static constexpr uint32_t USB_APP_TIMEOUT_MS = 3000;
static constexpr uint32_t USB_REVIEW_RENDER_INTERVAL_MS = 5000;
static constexpr uint32_t BOOT_IDLE_FRAME_INTERVAL_MS = 33;
static constexpr uint32_t SIGNALRGB_MIN_RENDER_INTERVAL_MS_VALUE = SIGNALRGB_MIN_RENDER_INTERVAL_MS;
static constexpr size_t SIGNALRGB_HEADER_SIZE = 20;
static constexpr size_t SIGNALRGB_FULL_FRAME_BYTES = static_cast<size_t>(DISPLAY_WIDTH) * DISPLAY_HEIGHT * 2;
static constexpr size_t SIGNALRGB_MAX_PAYLOAD = SIGNALRGB_VIDEO_FAST_PATH ? SIGNALRGB_FULL_FRAME_BYTES : 131072;
static constexpr size_t SIGNALRGB_RAWUSB_RX_BUFFER = 32768;
static constexpr size_t USB_APP_MAX_PAYLOAD = 8192;
static constexpr uint8_t SIGNAL_STATUS_OK = 0x00;
static constexpr uint8_t SIGNAL_STATUS_BAD_MAGIC = 0x01;
static constexpr uint8_t SIGNAL_STATUS_BAD_COMMAND = 0x02;
static constexpr uint8_t SIGNAL_STATUS_BAD_LENGTH = 0x03;
static constexpr uint8_t SIGNAL_STATUS_BAD_CHECKSUM = 0x04;
static constexpr uint8_t SIGNAL_STATUS_RENDER_FAILED = 0x05;
static uint8_t signalHeader[SIGNALRGB_HEADER_SIZE];
static uint8_t signalStreamBuffer[SIGNALRGB_VIDEO_FAST_PATH ? 4096 : 512];
static uint8_t* signalPayload = nullptr;
static size_t signalHeaderLen = 0;
static size_t signalPayloadLen = 0;
static size_t signalExpectedPayloadLen = 0;
static uint32_t signalPayloadStartMs = 0;
static uint16_t signalPayloadChecksum = 0;
static uint8_t signalRectScale = 2;
static uint8_t signalRectCommand = 0;
static bool signalStatusRequested = false;
static bool signalDropPayload = false;
static uint32_t signalLastRenderMs = 0;
static enum {
  SIGNAL_WAIT_MAGIC,
  SIGNAL_READ_HEADER,
  SIGNAL_READ_PAYLOAD,
} signalParserState = SIGNAL_WAIT_MAGIC;
static enum {
  PROTOCOL_NONE,
  PROTOCOL_SIGNALRGB,
  PROTOCOL_APP_STATE,
} signalParserProtocol = PROTOCOL_NONE;

static bool signalRgbActive();
static bool usbAppStateActive();
static bool shouldRenderUsbAppState(const DisplayState& next);

static String statePath() {
  return String("/api/v1/device/") + DEVICE_ID + "/state";
}

static bool inCircle(int16_t x, int16_t y, int cx, int cy, int radius) {
  int dx = x - cx;
  int dy = y - cy;
  return (dx * dx + dy * dy) <= radius * radius;
}

static bool inRect(int16_t x, int16_t y, int left, int top, int right, int bottom) {
  return x >= left && x <= right && y >= top && y <= bottom;
}

static bool readReviewTouchRaw(int16_t& rawX, int16_t& rawY) {
  for (uint8_t attempt = 0; attempt < 6; attempt++) {
    if (readDisplayTouchRaw(rawX, rawY)) {
      return true;
    }
    delay(4);
  }
  return false;
}

static uint16_t readLe16(const uint8_t* data) {
  return static_cast<uint16_t>(data[0]) | (static_cast<uint16_t>(data[1]) << 8);
}

static uint32_t readLe32(const uint8_t* data) {
  return static_cast<uint32_t>(data[0]) |
         (static_cast<uint32_t>(data[1]) << 8) |
         (static_cast<uint32_t>(data[2]) << 16) |
         (static_cast<uint32_t>(data[3]) << 24);
}

static uint16_t checksum16(const uint8_t* data, size_t len) {
  uint32_t sum = 0;
  for (size_t i = 0; i < len; i++) {
    sum = (sum + data[i]) & 0xFFFF;
  }
  return static_cast<uint16_t>(sum);
}

static void addSignalPayloadChecksum(const uint8_t* data, size_t len) {
  uint32_t sum = signalPayloadChecksum;
  for (size_t i = 0; i < len; i++) {
    sum = (sum + data[i]) & 0xFFFF;
  }
  signalPayloadChecksum = static_cast<uint16_t>(sum);
}

static void noteSignalRgbRx() {
  lastSignalRgbRxMs = millis();
}

static void sendSignalRgbStatus(uint8_t status, uint8_t command, uint16_t detail) {
#if SIGNALRGB_RAWUSB_EXPERIMENT && RAWUSB_STREAM_ENABLED
  if (!rawUsb.mounted()) {
    return;
  }
  uint32_t rxMs = 0;
  uint32_t decodeMs = 0;
  uint32_t flushMs = 0;
  getSignalTimingStats(rxMs, decodeMs, flushMs);
  uint32_t now = millis();
  uint8_t response[] = {
      'S', 'R', 'S', 'P',
      status,
      command,
      static_cast<uint8_t>(detail & 0xFF),
      static_cast<uint8_t>((detail >> 8) & 0xFF),
      static_cast<uint8_t>(now & 0xFF),
      static_cast<uint8_t>((now >> 8) & 0xFF),
      static_cast<uint8_t>((now >> 16) & 0xFF),
      static_cast<uint8_t>((now >> 24) & 0xFF),
      static_cast<uint8_t>(rxMs & 0xFF),
      static_cast<uint8_t>((rxMs >> 8) & 0xFF),
      static_cast<uint8_t>(decodeMs & 0xFF),
      static_cast<uint8_t>((decodeMs >> 8) & 0xFF),
      static_cast<uint8_t>(flushMs & 0xFF),
      static_cast<uint8_t>((flushMs >> 8) & 0xFF),
  };
  rawUsb.write(response, sizeof(response));
  tud_vendor_n_write_flush(0);
#else
  (void)status;
  (void)command;
  (void)detail;
#endif
}

static bool sendUsbReviewDecision(bool approve) {
#if SIGNALRGB_RAWUSB_EXPERIMENT && RAWUSB_STREAM_ENABLED
  if (!rawUsb.mounted()) {
    return false;
  }
  uint8_t event[] = {
      'C', 'R', 'E', 'V',
      static_cast<uint8_t>(approve ? 0x01 : 0x02),
      0,
      static_cast<uint8_t>(millis() & 0xFF),
      static_cast<uint8_t>((millis() >> 8) & 0xFF),
      static_cast<uint8_t>((millis() >> 16) & 0xFF),
      static_cast<uint8_t>((millis() >> 24) & 0xFF),
  };
  size_t written = rawUsb.write(event, sizeof(event));
  tud_vendor_n_write_flush(0);
  return written == sizeof(event);
#else
  (void)approve;
  return false;
#endif
}

static void sendUsbReviewTouchDiagnostic(uint8_t result, int16_t rawX, int16_t rawY, int16_t logicalX, int16_t logicalY) {
#if SIGNALRGB_RAWUSB_EXPERIMENT && RAWUSB_STREAM_ENABLED
  if (!rawUsb.mounted()) {
    return;
  }
  uint8_t event[] = {
      'C', 'T', 'C', 'H',
      result,
      0,
      static_cast<uint8_t>(rawX & 0xFF),
      static_cast<uint8_t>((rawX >> 8) & 0xFF),
      static_cast<uint8_t>(rawY & 0xFF),
      static_cast<uint8_t>((rawY >> 8) & 0xFF),
      static_cast<uint8_t>(logicalX & 0xFF),
      static_cast<uint8_t>((logicalX >> 8) & 0xFF),
      static_cast<uint8_t>(logicalY & 0xFF),
      static_cast<uint8_t>((logicalY >> 8) & 0xFF),
  };
  rawUsb.write(event, sizeof(event));
  tud_vendor_n_write_flush(0);
#else
  (void)result;
  (void)rawX;
  (void)rawY;
  (void)logicalX;
  (void)logicalY;
#endif
}

static void resetSignalParser() {
  signalHeaderLen = 0;
  signalPayloadLen = 0;
  signalExpectedPayloadLen = 0;
  signalPayloadStartMs = 0;
  signalPayloadChecksum = 0;
  signalRectScale = 2;
  signalRectCommand = 0;
  signalStatusRequested = false;
  signalDropPayload = false;
  signalParserState = SIGNAL_WAIT_MAGIC;
  signalParserProtocol = PROTOCOL_NONE;
}

static void handleSignalHeader() {
#if NZXT_ESC_TEST_FIRMWARE
  if (signalParserProtocol != PROTOCOL_SIGNALRGB ||
      signalHeader[0] != 'S' || signalHeader[1] != 'R' || signalHeader[2] != 'G' || signalHeader[3] != 'B') {
    sendSignalRgbStatus(SIGNAL_STATUS_BAD_MAGIC, 0, 0);
    resetSignalParser();
    return;
  }

  uint8_t command = signalHeader[4];
  signalStatusRequested = (signalHeader[5] & 0x80) != 0;
  if (command == 0x02) {
    flushSignalRgbFrame();
    lastSignalRgbMs = millis();
    signalLastRenderMs = lastSignalRgbMs;
    sendSignalRgbStatus(SIGNAL_STATUS_OK, command, 0);
    resetSignalParser();
    return;
  }

  if (command != 0x01 && command != 0x03 && command != 0x05 && command != 0x06 && command != 0x07 && command != 0x08) {
    sendSignalRgbStatus(SIGNAL_STATUS_BAD_COMMAND, command, 0);
    resetSignalParser();
    return;
  }

  if (command == 0x01 || command == 0x03) {
    uint8_t scale = signalHeader[5] & 0x7F;
    if (command == 0x01) {
      scale = 1;
    }
    uint16_t x = readLe16(signalHeader + 8);
    uint16_t y = readLe16(signalHeader + 10);
    uint16_t width = readLe16(signalHeader + 12);
    uint16_t height = readLe16(signalHeader + 14);
    signalExpectedPayloadLen = readLe32(signalHeader + 16);
    size_t expectedRectBytes = static_cast<size_t>(width) * height * 2;
    if (scale == 0 || width == 0 || height == 0 ||
        static_cast<uint32_t>(x + width) * scale > DISPLAY_WIDTH ||
        static_cast<uint32_t>(y + height) * scale > DISPLAY_HEIGHT ||
        signalExpectedPayloadLen != expectedRectBytes ||
        signalExpectedPayloadLen > SIGNALRGB_MAX_PAYLOAD ||
        !signalPayload) {
      sendSignalRgbStatus(SIGNAL_STATUS_BAD_LENGTH, command, static_cast<uint16_t>(min(signalExpectedPayloadLen, static_cast<size_t>(0xFFFF))));
      resetSignalParser();
      return;
    }
    signalRectScale = scale;
    signalRectCommand = command;
    signalPayloadLen = 0;
    signalPayloadChecksum = 0;
    signalPayloadStartMs = millis();
    signalParserState = SIGNAL_READ_PAYLOAD;
    return;
  }

  signalExpectedPayloadLen = readLe32(signalHeader + 16);
  if (command == 0x06 && signalExpectedPayloadLen != SIGNALRGB_FULL_FRAME_BYTES) {
    sendSignalRgbStatus(SIGNAL_STATUS_BAD_LENGTH, command, static_cast<uint16_t>(min(signalExpectedPayloadLen, static_cast<size_t>(0xFFFF))));
    resetSignalParser();
    return;
  }
  if (signalExpectedPayloadLen == 0 ||
      signalExpectedPayloadLen > SIGNALRGB_MAX_PAYLOAD ||
      (command != 0x08 && !signalPayload)) {
    sendSignalRgbStatus(SIGNAL_STATUS_BAD_LENGTH, command, static_cast<uint16_t>(min(signalExpectedPayloadLen, static_cast<size_t>(0xFFFF))));
    resetSignalParser();
    return;
  }
  signalRectCommand = command;
  signalDropPayload = command != 0x07 &&
                      command != 0x08 &&
                      signalLastRenderMs != 0 &&
                      millis() - signalLastRenderMs < SIGNALRGB_MIN_RENDER_INTERVAL_MS_VALUE;
  signalPayloadLen = 0;
  signalPayloadChecksum = 0;
  signalPayloadStartMs = millis();
  signalParserState = SIGNAL_READ_PAYLOAD;
  return;
#else
  if (signalParserProtocol == PROTOCOL_APP_STATE) {
    uint8_t command = signalHeader[4];
    signalExpectedPayloadLen = readLe32(signalHeader + 16);
    if (command != 0x01 || signalExpectedPayloadLen == 0 ||
        signalExpectedPayloadLen > USB_APP_MAX_PAYLOAD || !signalPayload) {
      sendSignalRgbStatus(SIGNAL_STATUS_BAD_LENGTH, command, static_cast<uint16_t>(min(signalExpectedPayloadLen, static_cast<size_t>(0xFFFF))));
      resetSignalParser();
      return;
    }
    signalRectCommand = command;
    signalPayloadLen = 0;
    signalPayloadChecksum = 0;
    signalPayloadStartMs = millis();
    signalParserState = SIGNAL_READ_PAYLOAD;
    return;
  }

  if (signalParserProtocol != PROTOCOL_SIGNALRGB ||
      signalHeader[0] != 'S' || signalHeader[1] != 'R' || signalHeader[2] != 'G' || signalHeader[3] != 'B') {
    sendSignalRgbStatus(SIGNAL_STATUS_BAD_MAGIC, 0, 0);
    resetSignalParser();
    return;
  }

  uint8_t command = signalHeader[4];
  if (command == 0x02) {
    flushSignalRgbFrame();
    lastSignalRgbMs = millis();
    sendSignalRgbStatus(SIGNAL_STATUS_OK, command, 0);
    resetSignalParser();
    return;
  }
  if (command != 0x01 && command != 0x03 && command != 0x04 && command != 0x05) {
    sendSignalRgbStatus(SIGNAL_STATUS_BAD_COMMAND, command, 0);
    resetSignalParser();
    return;
  }

  if (command == 0x04 || command == 0x05) {
    signalExpectedPayloadLen = readLe32(signalHeader + 16);
    if ((command == 0x04 && signalExpectedPayloadLen != 8) ||
        (command == 0x05 && signalExpectedPayloadLen == 0) ||
        signalExpectedPayloadLen > SIGNALRGB_MAX_PAYLOAD ||
        !signalPayload) {
      sendSignalRgbStatus(SIGNAL_STATUS_BAD_LENGTH, command, static_cast<uint16_t>(min(signalExpectedPayloadLen, static_cast<size_t>(0xFFFF))));
      resetSignalParser();
      return;
    }
    signalRectCommand = command;
    signalPayloadLen = 0;
    signalPayloadChecksum = 0;
    signalPayloadStartMs = millis();
    signalParserState = SIGNAL_READ_PAYLOAD;
    return;
  }

  uint8_t scale = command == 0x03 ? signalHeader[5] : 2;
  uint16_t x = readLe16(signalHeader + 8);
  uint16_t y = readLe16(signalHeader + 10);
  uint16_t width = readLe16(signalHeader + 12);
  uint16_t height = readLe16(signalHeader + 14);
  signalExpectedPayloadLen = readLe32(signalHeader + 16);
  size_t expectedRectBytes = static_cast<size_t>(width) * height * 2;
  if (scale == 0 || width == 0 || height == 0 ||
      static_cast<uint32_t>(x + width) * scale > DISPLAY_WIDTH ||
      static_cast<uint32_t>(y + height) * scale > DISPLAY_HEIGHT ||
      signalExpectedPayloadLen != expectedRectBytes || signalExpectedPayloadLen > SIGNALRGB_MAX_PAYLOAD) {
    sendSignalRgbStatus(SIGNAL_STATUS_BAD_LENGTH, command, static_cast<uint16_t>(min(signalExpectedPayloadLen, static_cast<size_t>(0xFFFF))));
    resetSignalParser();
    return;
  }
  signalRectScale = scale;
  signalRectCommand = command;
  signalPayloadLen = 0;
  signalPayloadChecksum = 0;
  signalPayloadStartMs = millis();
  signalParserState = SIGNAL_READ_PAYLOAD;
#endif
}

static void handleSignalPayload() {
  uint16_t expectedChecksum = readLe16(signalHeader + 6);
  uint16_t actualChecksum = signalPayloadChecksum;
  if (actualChecksum != expectedChecksum) {
    if (millis() - lastSignalRgbRejectLogMs > 1000) {
      lastSignalRgbRejectLogMs = millis();
      Serial.printf("SignalRGB rect checksum rejected expected=%u actual=%u len=%u x=%u y=%u w=%u h=%u\n",
                    expectedChecksum,
                    actualChecksum,
                    static_cast<unsigned>(signalExpectedPayloadLen),
                    readLe16(signalHeader + 8),
                    readLe16(signalHeader + 10),
                    readLe16(signalHeader + 12),
                    readLe16(signalHeader + 14));
    }
    sendSignalRgbStatus(SIGNAL_STATUS_BAD_CHECKSUM, signalRectCommand, actualChecksum);
    resetSignalParser();
    return;
  }

#if NZXT_ESC_TEST_FIRMWARE
  setSignalRxStats(static_cast<uint32_t>(signalExpectedPayloadLen), millis() - signalPayloadStartMs);
  if (signalDropPayload) {
    resetSignalParser();
    return;
  }
  bool drawn = false;
  if (signalRectCommand == 0x01 || signalRectCommand == 0x03) {
    uint16_t x = readLe16(signalHeader + 8);
    uint16_t y = readLe16(signalHeader + 10);
    uint16_t width = readLe16(signalHeader + 12);
    uint16_t height = readLe16(signalHeader + 14);
    drawn = drawSignalRgb565RectScaled(x, y, width, height, signalRectScale, signalPayload, signalExpectedPayloadLen);
  } else if (signalRectCommand == 0x06) {
    drawn = drawSignalRgb565Frame(signalPayload, signalExpectedPayloadLen);
    if (drawn) {
      flushSignalRgbFrame();
    }
  } else if (signalRectCommand == 0x07) {
    drawn = true;
  } else {
    drawn = drawSignalJpegFrame(signalPayload, signalExpectedPayloadLen);
  }
  if (signalStatusRequested || !drawn) {
    sendSignalRgbStatus(drawn ? SIGNAL_STATUS_OK : SIGNAL_STATUS_RENDER_FAILED,
                        signalRectCommand,
                        static_cast<uint16_t>(min(signalExpectedPayloadLen, static_cast<size_t>(0xFFFF))));
  }
  if (drawn) {
    lastSignalRgbMs = millis();
    signalLastRenderMs = lastSignalRgbMs;
  }
  resetSignalParser();
  return;
#else
  if (signalParserProtocol == PROTOCOL_APP_STATE) {
    String body;
    body.reserve(signalExpectedPayloadLen + 1);
    for (size_t i = 0; i < signalExpectedPayloadLen; i++) {
      body += static_cast<char>(signalPayload[i]);
    }

    DisplayState next;
    if (parseDisplayState(body, next)) {
      bool renderState = shouldRenderUsbAppState(next);
      if (cachedAssetHash() != next.assetHash || !hasCachedAsset()) {
        resumeWiFi();
        if (connectWiFi()) {
          updateCachedAsset(next);
        }
        suspendWiFi();
      }
      currentState = next;
      lastUsbAppStateMs = millis();
      lastPollMs = lastUsbAppStateMs;
      if (renderState) {
        lastUsbAppRenderMs = millis();
        renderDisplay(currentState, false);
      }
      Serial.printf("usb state ok app=%s cpu=%.1f ram=%.1f\n",
                    currentState.appId.c_str(),
                    currentState.cpuLoad,
                    currentState.ramUsedPercent);
      sendSignalRgbStatus(SIGNAL_STATUS_OK, signalRectCommand, static_cast<uint16_t>(min(signalExpectedPayloadLen, static_cast<size_t>(0xFFFF))));
    } else {
      Serial.println("usb state JSON rejected");
      sendSignalRgbStatus(SIGNAL_STATUS_BAD_LENGTH, signalRectCommand, static_cast<uint16_t>(min(signalExpectedPayloadLen, static_cast<size_t>(0xFFFF))));
    }
    resetSignalParser();
    return;
  }

  uint16_t x = readLe16(signalHeader + 8);
  uint16_t y = readLe16(signalHeader + 10);
  uint16_t width = readLe16(signalHeader + 12);
  uint16_t height = readLe16(signalHeader + 14);
  bool drawn = false;
  if (signalRectCommand == 0x04) {
    localBaseR = signalPayload[0];
    localBaseG = signalPayload[1];
    localBaseB = signalPayload[2];
    localAccentR = signalPayload[3];
    localAccentG = signalPayload[4];
    localAccentB = signalPayload[5];
    localEnergy = signalPayload[6];
    localSignalMode = true;
    renderSignalRgbLocalFrame(localBaseR, localBaseG, localBaseB, localAccentR, localAccentG, localAccentB, localEnergy);
    drawn = true;
  } else if (signalRectCommand == 0x05) {
    setSignalRxStats(static_cast<uint32_t>(signalExpectedPayloadLen), millis() - signalPayloadStartMs);
    drawn = drawSignalJpegFrame(signalPayload, signalExpectedPayloadLen);
    localSignalMode = false;
  } else {
    drawn = signalRectCommand == 0x03
        ? drawSignalRgb565RectScaled(x, y, width, height, signalRectScale, signalPayload, signalExpectedPayloadLen)
        : drawSignalRgb565Rect(x, y, width, height, signalPayload, signalExpectedPayloadLen);
    localSignalMode = false;
  }
  if (drawn) {
    lastSignalRgbMs = millis();
    sendSignalRgbStatus(SIGNAL_STATUS_OK, signalRectCommand, static_cast<uint16_t>(min(signalExpectedPayloadLen, static_cast<size_t>(0xFFFF))));
  } else {
    sendSignalRgbStatus(SIGNAL_STATUS_RENDER_FAILED, signalRectCommand, static_cast<uint16_t>(min(signalExpectedPayloadLen, static_cast<size_t>(0xFFFF))));
  }
  resetSignalParser();
#endif
}

static void processSignalRgbByte(uint8_t value) {
    if (signalParserState == SIGNAL_WAIT_MAGIC) {
      const char signalMagic[] = {'S', 'R', 'G', 'B'};
      const char appMagic[] = {'C', 'A', 'P', 'P'};

      if (signalHeaderLen == 0) {
        if (value == 'S') {
          signalParserProtocol = PROTOCOL_SIGNALRGB;
        } else if (value == 'C') {
          signalParserProtocol = PROTOCOL_APP_STATE;
        } else {
          return;
        }
        signalHeader[signalHeaderLen++] = value;
        if (signalParserProtocol == PROTOCOL_SIGNALRGB) {
          noteSignalRgbRx();
        }
        return;
      }

      const char* magic = signalParserProtocol == PROTOCOL_APP_STATE ? appMagic : signalMagic;
      if (value == static_cast<uint8_t>(magic[signalHeaderLen])) {
        signalHeader[signalHeaderLen++] = value;
        if (signalParserProtocol == PROTOCOL_SIGNALRGB) {
          noteSignalRgbRx();
        }
        if (signalHeaderLen == 4) {
          signalParserState = SIGNAL_READ_HEADER;
        }
      } else {
        resetSignalParser();
        if (value == 'S' || value == 'C') {
          processSignalRgbByte(value);
        }
      }
      return;
    }

    if (signalParserState == SIGNAL_READ_HEADER) {
      if (signalParserProtocol == PROTOCOL_SIGNALRGB) {
        noteSignalRgbRx();
      }
      signalHeader[signalHeaderLen++] = value;
      if (signalHeaderLen == SIGNALRGB_HEADER_SIZE) {
        handleSignalHeader();
      }
      return;
    }

    if (signalParserState == SIGNAL_READ_PAYLOAD) {
      if (signalParserProtocol == PROTOCOL_SIGNALRGB) {
        noteSignalRgbRx();
      }
      signalPayload[signalPayloadLen++] = value;
      signalPayloadChecksum = static_cast<uint16_t>((signalPayloadChecksum + value) & 0xFFFF);
      if (signalPayloadLen == signalExpectedPayloadLen) {
        handleSignalPayload();
      }
    }
}

template <typename StreamType>
static void processSignalRgbStream(StreamType& stream) {
#if SIGNALRGB_VIDEO_FAST_PATH
  uint8_t* buffer = signalStreamBuffer;
#else
  uint8_t* buffer = signalStreamBuffer;
#endif
  while (stream.available() > 0) {
    if (signalParserState == SIGNAL_READ_PAYLOAD && signalRectCommand == 0x08 && signalPayloadLen < signalExpectedPayloadLen) {
      noteSignalRgbRx();
      size_t remaining = signalExpectedPayloadLen - signalPayloadLen;
      size_t toRead = min(remaining, sizeof(signalStreamBuffer));
      int available = stream.available();
      if (available > 0) {
        toRead = min(toRead, static_cast<size_t>(available));
      }
      size_t readLen = stream.read(buffer, toRead);
      if (readLen == 0) {
        break;
      }
      signalPayloadLen += readLen;
      if (signalPayloadLen == signalExpectedPayloadLen) {
        setSignalRxStats(static_cast<uint32_t>(signalExpectedPayloadLen), millis() - signalPayloadStartMs);
        if (signalStatusRequested) {
          sendSignalRgbStatus(SIGNAL_STATUS_OK, signalRectCommand,
                              static_cast<uint16_t>(min(signalExpectedPayloadLen, static_cast<size_t>(0xFFFF))));
        }
        resetSignalParser();
      }
      continue;
    }

    if (signalParserState == SIGNAL_READ_PAYLOAD && signalPayload && signalPayloadLen < signalExpectedPayloadLen) {
      noteSignalRgbRx();
      size_t remaining = signalExpectedPayloadLen - signalPayloadLen;
      size_t toRead = min(remaining, sizeof(signalStreamBuffer));
      int available = stream.available();
      if (available > 0) {
        toRead = min(toRead, static_cast<size_t>(available));
      }
      size_t readLen = stream.read(signalPayload + signalPayloadLen, toRead);
      if (readLen == 0) {
        break;
      }
      addSignalPayloadChecksum(signalPayload + signalPayloadLen, readLen);
      signalPayloadLen += readLen;
      if (signalPayloadLen == signalExpectedPayloadLen) {
        handleSignalPayload();
      }
      continue;
    }

    size_t readLen = stream.read(buffer, min(sizeof(signalStreamBuffer), static_cast<size_t>(stream.available())));
    if (readLen == 0) {
      break;
    }
    for (size_t i = 0; i < readLen; i++) {
      processSignalRgbByte(buffer[i]);
    }
  }
}

static void processSignalRgbSerial() {
  processSignalRgbStream(Serial);
}

#if SIGNALRGB_RAWUSB_EXPERIMENT && RAWUSB_STREAM_ENABLED
extern "C" bool open_aio_vendor_rx_cb(uint8_t itf) {
  DirectVendorStream stream{itf};
  processSignalRgbStream(stream);
  return true;
}
#endif

static bool signalRgbActive() {
  return (lastSignalRgbMs != 0 && millis() - lastSignalRgbMs < SIGNALRGB_TIMEOUT_MS) ||
         (lastSignalRgbRxMs != 0 && millis() - lastSignalRgbRxMs < SIGNALRGB_TIMEOUT_MS);
}

static bool usbAppStateActive() {
  return lastUsbAppStateMs != 0 && millis() - lastUsbAppStateMs < USB_APP_TIMEOUT_MS;
}

static bool shouldRenderUsbAppState(const DisplayState& next) {
  if (!next.reviewAvailable) {
    return true;
  }
  if (!currentState.valid || !currentState.reviewAvailable) {
    return true;
  }
  if (currentState.appId != next.appId ||
      currentState.assetHash != next.assetHash ||
      currentState.reviewProcessName != next.reviewProcessName ||
      currentState.reviewAppId != next.reviewAppId ||
      currentState.reviewStatus != next.reviewStatus) {
    return true;
  }
  return lastUsbAppRenderMs == 0 || millis() - lastUsbAppRenderMs >= USB_REVIEW_RENDER_INTERVAL_MS;
}

static bool handleReviewTouch() {
  if (millis() - lastTouchMs < 700) {
    return false;
  }

  int16_t rawX = 0;
  int16_t rawY = 0;
  if (!readReviewTouchRaw(rawX, rawY)) {
    if (currentState.reviewAvailable && millis() - lastTouchIdleDiagnosticMs >= 2000) {
      lastTouchIdleDiagnosticMs = millis();
      sendUsbReviewTouchDiagnostic(readDisplayTouchPressed() ? 5 : 4, -1, -1, -1, -1);
    }
    return false;
  }
  lastTouchMs = millis();
  lastTouchIdleDiagnosticMs = millis();

  int16_t logicalX = rawX;
  int16_t logicalY = rawY;
#if DISPLAY_ROTATE_180
  logicalX = DISPLAY_WIDTH - 1 - rawX;
  logicalY = DISPLAY_HEIGHT - 1 - rawY;
#endif

  if (!currentState.reviewAvailable) {
    sendUsbReviewTouchDiagnostic(3, rawX, rawY, logicalX, logicalY);
    Serial.printf("touch ignored: no review raw=%d,%d logical=%d,%d\n", rawX, rawY, logicalX, logicalY);
    return true;
  }

  bool approveLogical = inCircle(logicalX, logicalY, 150, 410, 72) || inRect(logicalX, logicalY, 76, 336, 224, 479);
  bool rejectLogical = inCircle(logicalX, logicalY, 330, 410, 72) || inRect(logicalX, logicalY, 256, 336, 404, 479);
  bool approveRaw = inCircle(rawX, rawY, 150, 410, 72) || inRect(rawX, rawY, 76, 336, 224, 479);
  bool rejectRaw = inCircle(rawX, rawY, 330, 410, 72) || inRect(rawX, rawY, 256, 336, 404, 479);
  bool approve = approveLogical || approveRaw;
  bool reject = !approve && (rejectLogical || rejectRaw);

  if (!approve && !reject) {
    renderTouchFeedback(logicalX, logicalY, false);
    sendUsbReviewTouchDiagnostic(0, rawX, rawY, logicalX, logicalY);
    Serial.printf("review touch miss raw=%d,%d logical=%d,%d\n", rawX, rawY, logicalX, logicalY);
    return true;
  }
  renderTouchFeedback(logicalX, logicalY, true);
  sendUsbReviewTouchDiagnostic(approve ? 1 : 2, rawX, rawY, logicalX, logicalY);
  Serial.printf("review touch raw=%d,%d logical=%d,%d action=%s\n",
                rawX,
                rawY,
                logicalX,
                logicalY,
                approve ? "approve" : "reject");
  if (sendUsbReviewDecision(approve)) {
    Serial.printf("review event queued over USB action=%s process=%s app=%s\n",
                  approve ? "approve" : "reject",
                  currentState.reviewProcessName.c_str(),
                  currentState.reviewAppId.c_str());
  }

  if (!connectWiFi()) {
    Serial.println("review touch ignored: Wi-Fi unavailable");
    return true;
  }

  String path = approve ? "/api/v1/apps/approve-candidate" : "/api/v1/apps/reject-candidate";
  bool ok = httpPostCandidateDecision(path, currentState.reviewProcessName, currentState.reviewAppId);
  if (ok) {
    Serial.printf("candidate %s process=%s app=%s\n",
                  approve ? "approved" : "rejected",
                  currentState.reviewProcessName.c_str(),
                  currentState.reviewAppId.c_str());
    currentState.reviewAvailable = false;
    renderDisplay(currentState, false);
    lastPollMs = 0;
  }
  return true;
}

void setup() {
#if NZXT_ESC_TEST_FIRMWARE
  setCpuFrequencyMhz(240);
  signalPayload = static_cast<uint8_t*>(heap_caps_malloc(SIGNALRGB_MAX_PAYLOAD, MALLOC_CAP_SPIRAM | MALLOC_CAP_8BIT));
  if (!signalPayload) {
    signalPayload = static_cast<uint8_t*>(heap_caps_malloc(SIGNALRGB_MAX_PAYLOAD, MALLOC_CAP_8BIT));
  }
#if SIGNALRGB_RAWUSB_EXPERIMENT && RAWUSB_STREAM_ENABLED
  rawUsb.setRxBufferSize(SIGNALRGB_RAWUSB_RX_BUFFER);
  USB.usbVersion(0x0210);
#if NZXT_CAM_SPOOF
  USB.usbClass(0xEF);
  USB.usbSubClass(0x02);
  USB.usbProtocol(0x01);
  USB.webUSB(false);
  USB.productName("Kraken Elite RGB");
  USB.manufacturerName("NZXT");
#else
  USB.webUSB(true);
  USB.webUSBURL("https://signalrgb.com");
  USB.productName(DEVICE_NAME);
  USB.manufacturerName("Local");
#endif
  rawUsb.onRequest(handleRawUsbControlRequest);
  rawUsb.begin();
#if NZXT_CAM_SPOOF
  nzxtHid.begin();
#endif
  USB.begin();
#elif SIGNALRGB_RAWUSB_EXPERIMENT && NZXT_CAM_SPOOF
  USB.usbVersion(0x0210);
  USB.usbClass(0x00);
  USB.usbSubClass(0x00);
  USB.usbProtocol(0x00);
  USB.webUSB(false);
  USB.productName("Kraken Elite RGB");
  USB.manufacturerName("NZXT");
  nzxtHid.begin();
  USB.begin();
#endif
  delay(150);
  initAssetStore();
  initDisplay();
  renderBootAnimation();
  return;
#else
  // LEGACY/NON-WORKING REBUILD AREA:
  // This production/app-detector path regressed the lab stream, display sync,
  // and touch review flow. Keep it as reference only until it is rebuilt
  // intentionally from the NZXT_ESC_TEST_FIRMWARE lab baseline.
  Serial.setRxBufferSize(131072);
  Serial.begin(SIGNALRGB_SERIAL_BAUD);
  signalPayload = static_cast<uint8_t*>(heap_caps_malloc(SIGNALRGB_MAX_PAYLOAD, MALLOC_CAP_SPIRAM | MALLOC_CAP_8BIT));
  if (!signalPayload) {
    signalPayload = static_cast<uint8_t*>(heap_caps_malloc(SIGNALRGB_MAX_PAYLOAD, MALLOC_CAP_8BIT));
  }
  if (!signalPayload) {
    Serial.println("SignalRGB payload buffer allocation failed");
  }
#if SIGNALRGB_RAWUSB_EXPERIMENT && RAWUSB_STREAM_ENABLED
  rawUsb.setRxBufferSize(SIGNALRGB_RAWUSB_RX_BUFFER);
  USB.usbVersion(0x0210);
  USB.webUSB(true);
  USB.webUSBURL("https://signalrgb.com");
  USB.productName(DEVICE_NAME);
  USB.manufacturerName("Local");
  rawUsb.onRequest(handleRawUsbControlRequest);
  rawUsb.begin();
  USB.begin();
#endif
  delay(200);
  Serial.printf("%s starting id=%s\n", DEVICE_NAME, DEVICE_ID);
  initAssetStore();
  initDisplay();
  renderBootAnimation();
  connectWiFi();
#endif
}

void loop() {
#if NZXT_ESC_TEST_FIRMWARE
#if SIGNALRGB_RAWUSB_EXPERIMENT && RAWUSB_STREAM_ENABLED
  processSignalRgbStream(rawUsb);
#if NZXT_CAM_SPOOF
  processNzxtHidQueue();
#endif
#endif
#if SIGNALRGB_RAWUSB_EXPERIMENT && NZXT_CAM_SPOOF && !RAWUSB_STREAM_ENABLED
  processNzxtHidQueue();
#endif
  if (!signalRgbActive() && signalParserState == SIGNAL_WAIT_MAGIC) {
    uint32_t now = millis();
    if (lastBootIdleFrameMs == 0 || now - lastBootIdleFrameMs >= BOOT_IDLE_FRAME_INTERVAL_MS) {
      lastBootIdleFrameMs = now;
      renderBootIdleAnimationFrame(now);
    }
  } else {
    lastBootIdleFrameMs = 0;
  }
  delay(0);
  return;
#else
  // See setup() legacy note: the active RawUSB target now builds the lab stream
  // path above. Do not use this branch as the source of truth.
#if SIGNALRGB_RAWUSB_EXPERIMENT && RAWUSB_STREAM_ENABLED
  processSignalRgbStream(rawUsb);
  if (signalRgbActive()) {
#if SIGNALRGB_VIDEO_FAST_PATH
    suspendWiFi();
    delay(0);
#else
    suspendWiFi();
    if (localSignalMode) {
      renderSignalRgbLocalFrame(localBaseR, localBaseG, localBaseB, localAccentR, localAccentG, localAccentB, localEnergy);
      delay(12);
    } else {
      delay(1);
    }
#endif
    return;
  }
#endif

  if (usbAppStateActive() && currentState.reviewAvailable) {
    bool touched = handleReviewTouch();
    if (touched) {
      delay(180);
      return;
    }
  }

  processSignalRgbSerial();

  if (signalRgbActive()) {
    suspendWiFi();
    if (localSignalMode) {
      renderSignalRgbLocalFrame(localBaseR, localBaseG, localBaseB, localAccentR, localAccentG, localAccentB, localEnergy);
      delay(12);
    } else {
      delay(1);
    }
    return;
  }
  localSignalMode = false;

  if (usbAppStateActive()) {
    suspendWiFi();
    bool touched = handleReviewTouch();
    if (touched) {
      delay(180);
      return;
    }
    delay(5);
    return;
  }

  resumeWiFi();

  handleReviewTouch();

  if (millis() - lastPollMs < POLL_INTERVAL_MS) {
    delay(20);
    return;
  }
  lastPollMs = millis();

  bool offline = true;
  if (connectWiFi()) {
    String body;
    if (httpGetString(statePath(), body)) {
      DisplayState next;
      if (parseDisplayState(body, next)) {
        updateCachedAsset(next);
        currentState = next;
        offline = false;
        Serial.printf("state ok app=%s cpu=%.1f ram=%.1f\n",
                      currentState.appId.c_str(),
                      currentState.cpuLoad,
                      currentState.ramUsedPercent);
      } else {
        Serial.println("state JSON rejected");
      }
    }
  }

  currentOffline = offline;
  lastDisplayAnimMs = millis();
  suspendWiFi();
  renderDisplay(currentState, offline);
#endif
}
