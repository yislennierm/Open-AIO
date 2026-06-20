#include "protocol.h"

#include <ArduinoJson.h>

#include "config.h"

static float readNullableFloat(JsonVariantConst value) {
  if (value.isNull()) {
    return NAN;
  }
  return value.as<float>();
}

bool parseDisplayState(const String& json, DisplayState& out) {
  JsonDocument doc;
  DeserializationError err = deserializeJson(doc, json);
  if (err) {
    Serial.printf("JSON parse failed: %s\n", err.c_str());
    return false;
  }

  const char* appId = doc["app_id"] | "";
  const char* displayName = doc["display_name"] | "";
  const char* assetType = doc["asset_type"] | "";
  const char* assetUrl = doc["asset_url"] | "";
  const char* assetHash = doc["asset_hash"] | "";

  int width = doc["asset_width"] | 0;
  int height = doc["asset_height"] | 0;

  if (strlen(appId) == 0 || strlen(displayName) == 0 || strlen(assetUrl) == 0 || strlen(assetHash) != 64) {
    return false;
  }
  if (strcmp(assetType, "rgb565") != 0) {
    return false;
  }
  if (width != ASSET_WIDTH || height != ASSET_HEIGHT) {
    return false;
  }

  out.deviceId = doc["device_id"] | "";
  out.appId = appId;
  out.displayName = displayName;
  out.assetType = assetType;
  out.assetUrl = assetUrl;
  out.assetHash = assetHash;
  out.assetWidth = width;
  out.assetHeight = height;
  out.cpuTemp = readNullableFloat(doc["cpu_temp"]);
  out.gpuTemp = readNullableFloat(doc["gpu_temp"]);
  out.cpuLoad = doc["cpu_load"] | 0.0f;
  out.gpuLoad = readNullableFloat(doc["gpu_load"]);
  out.ramUsedPercent = doc["ram_used_percent"] | 0.0f;
  out.updatedAt = doc["updated_at"] | "";
  out.localTime = doc["local_time"] | "";
  out.localDate = doc["local_date"] | "";
  out.reviewAvailable = doc["review_available"] | false;
  out.reviewProcessName = doc["review_process_name"] | "";
  out.reviewAppId = doc["review_app_id"] | "";
  out.reviewDisplayName = doc["review_display_name"] | "";
  out.reviewStatus = doc["review_status"] | "";
  if (out.reviewAvailable && (out.reviewProcessName.length() == 0 || out.reviewAppId.length() == 0)) {
    out.reviewAvailable = false;
  }
  out.valid = true;
  return true;
}
