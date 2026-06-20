#include "network.h"

#include <HTTPClient.h>
#include <LittleFS.h>
#include <WiFi.h>

#include "config.h"

static bool wifiSuspended = false;

static String makeUrl(const String& path) {
  if (path.startsWith("http://") || path.startsWith("https://")) {
    return path;
  }
  String base = SERVER_BASE_URL;
  if (path.startsWith("/")) {
    return base + path;
  }
  return base + "/" + path;
}

bool connectWiFi() {
  if (wifiSuspended) {
    return false;
  }
  if (WiFi.status() == WL_CONNECTED) {
    return true;
  }
  WiFi.mode(WIFI_STA);
  WiFi.begin(WIFI_SSID, WIFI_PASSWORD);
  Serial.print("Connecting Wi-Fi");
  uint32_t started = millis();
  while (WiFi.status() != WL_CONNECTED && millis() - started < 15000) {
    delay(250);
    Serial.print(".");
  }
  Serial.println();
  if (WiFi.status() == WL_CONNECTED) {
    Serial.print("Wi-Fi IP: ");
    Serial.println(WiFi.localIP());
    return true;
  }
  Serial.println("Wi-Fi connection failed");
  return false;
}

void suspendWiFi() {
  if (wifiSuspended) {
    return;
  }
  wifiSuspended = true;
  WiFi.disconnect(true);
  WiFi.mode(WIFI_OFF);
}

void resumeWiFi() {
  if (!wifiSuspended) {
    return;
  }
  wifiSuspended = false;
  WiFi.mode(WIFI_STA);
}

bool isWiFiSuspended() {
  return wifiSuspended;
}

bool httpGetString(const String& path, String& body) {
  if (WiFi.status() != WL_CONNECTED) {
    return false;
  }
  HTTPClient http;
  http.setTimeout(2500);
  http.begin(makeUrl(path));
  http.addHeader("X-API-Key", API_KEY);
  int code = http.GET();
  if (code != HTTP_CODE_OK) {
    Serial.printf("GET failed code=%d path=%s\n", code, path.c_str());
    http.end();
    return false;
  }
  body = http.getString();
  Serial.printf("GET ok path=%s bytes=%u\n", path.c_str(), static_cast<unsigned>(body.length()));
  http.end();
  return body.length() > 0 && body.length() < 8192;
}

static String jsonEscape(const String& value) {
  String escaped;
  escaped.reserve(value.length() + 8);
  for (size_t i = 0; i < value.length(); i++) {
    char c = value[i];
    if (c == '"' || c == '\\') {
      escaped += '\\';
      escaped += c;
    } else if (static_cast<uint8_t>(c) >= 0x20) {
      escaped += c;
    }
  }
  return escaped;
}

bool httpPostCandidateDecision(const String& path, const String& processName, const String& appId) {
  if (WiFi.status() != WL_CONNECTED || processName.length() == 0) {
    return false;
  }

  String payload = String("{\"process_name\":\"") + jsonEscape(processName) + "\"";
  if (appId.length() > 0) {
    payload += String(",\"app_id\":\"") + jsonEscape(appId) + "\"";
  }
  payload += "}";

  HTTPClient http;
  http.setTimeout(2500);
  http.begin(makeUrl(path));
  http.addHeader("X-API-Key", API_KEY);
  http.addHeader("Content-Type", "application/json");
  int code = http.POST(payload);
  http.end();

  bool ok = code >= 200 && code < 300;
  if (!ok) {
    Serial.printf("POST failed code=%d path=%s\n", code, path.c_str());
  }
  return ok;
}

bool downloadAssetToFile(const String& path, const char* tmpPath, size_t maxBytes) {
  if (WiFi.status() != WL_CONNECTED) {
    return false;
  }

  HTTPClient http;
  http.setTimeout(5000);
  http.begin(makeUrl(path));
  http.addHeader("X-API-Key", API_KEY);
  int code = http.GET();
  if (code != HTTP_CODE_OK) {
    Serial.printf("asset GET failed code=%d\n", code);
    http.end();
    return false;
  }

  int contentLength = http.getSize();
  if (contentLength <= 0 || static_cast<size_t>(contentLength) > maxBytes) {
    Serial.printf("asset length rejected: %d\n", contentLength);
    http.end();
    return false;
  }

  File file = LittleFS.open(tmpPath, "w");
  if (!file) {
    http.end();
    return false;
  }

  WiFiClient* stream = http.getStreamPtr();
  uint8_t buffer[1024];
  size_t total = 0;
  while (http.connected() && total < static_cast<size_t>(contentLength)) {
    size_t available = stream->available();
    if (available == 0) {
      delay(1);
      continue;
    }
    size_t toRead = min(available, sizeof(buffer));
    int readLen = stream->readBytes(buffer, toRead);
    if (readLen <= 0) {
      break;
    }
    total += static_cast<size_t>(readLen);
    if (total > maxBytes) {
      file.close();
      LittleFS.remove(tmpPath);
      http.end();
      return false;
    }
    file.write(buffer, readLen);
  }

  file.close();
  http.end();

  if (total != static_cast<size_t>(contentLength)) {
    LittleFS.remove(tmpPath);
    return false;
  }
  Serial.printf("asset downloaded bytes=%u\n", static_cast<unsigned>(total));
  return true;
}
