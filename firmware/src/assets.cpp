#include "assets.h"

#include <LittleFS.h>
#include <mbedtls/sha256.h>

#include "config.h"
#include "network.h"

static const char* ASSET_PATH = "/logo.rgb565";
static const char* TMP_PATH = "/logo.tmp";
static const char* HASH_PATH = "/asset.hash";

bool initAssetStore() {
  if (LittleFS.begin(true)) {
    return true;
  }
  Serial.println("LittleFS mount failed");
  return false;
}

const char* cachedAssetPath() {
  return ASSET_PATH;
}

bool hasCachedAsset() {
  File file = LittleFS.open(ASSET_PATH, "r");
  if (!file) {
    return false;
  }
  size_t expected = ASSET_WIDTH * ASSET_HEIGHT * 2;
  bool ok = file.size() == expected;
  file.close();
  return ok;
}

String cachedAssetHash() {
  File file = LittleFS.open(HASH_PATH, "r");
  if (!file) {
    return "";
  }
  String hash = file.readString();
  file.close();
  hash.trim();
  return hash;
}

static String sha256File(const char* path) {
  File file = LittleFS.open(path, "r");
  if (!file) {
    return "";
  }

  mbedtls_sha256_context ctx;
  mbedtls_sha256_init(&ctx);
  mbedtls_sha256_starts(&ctx, 0);

  uint8_t buffer[1024];
  while (file.available()) {
    size_t readLen = file.read(buffer, sizeof(buffer));
    if (readLen > 0) {
      mbedtls_sha256_update(&ctx, buffer, readLen);
    }
  }
  file.close();

  uint8_t digest[32];
  mbedtls_sha256_finish(&ctx, digest);
  mbedtls_sha256_free(&ctx);

  char hex[65];
  for (int i = 0; i < 32; i++) {
    snprintf(hex + (i * 2), 3, "%02x", digest[i]);
  }
  hex[64] = '\0';
  return String(hex);
}

bool updateCachedAsset(const DisplayState& state) {
  if (!state.valid || state.assetHash.length() != 64) {
    return false;
  }
  if (cachedAssetHash() == state.assetHash && hasCachedAsset()) {
    return true;
  }

  LittleFS.remove(TMP_PATH);
  size_t expectedSize = static_cast<size_t>(state.assetWidth) * static_cast<size_t>(state.assetHeight) * 2;
  if (expectedSize == 0 || expectedSize > MAX_ASSET_SIZE_BYTES) {
    return false;
  }
  if (!downloadAssetToFile(state.assetUrl, TMP_PATH, MAX_ASSET_SIZE_BYTES)) {
    return false;
  }

  File tmp = LittleFS.open(TMP_PATH, "r");
  if (!tmp) {
    return false;
  }
  size_t tmpSize = tmp.size();
  tmp.close();
  if (tmpSize != expectedSize) {
    LittleFS.remove(TMP_PATH);
    return false;
  }

  String actualHash = sha256File(TMP_PATH);
  if (!actualHash.equalsIgnoreCase(state.assetHash)) {
    Serial.println("asset hash mismatch");
    LittleFS.remove(TMP_PATH);
    return false;
  }

  LittleFS.remove(ASSET_PATH);
  if (!LittleFS.rename(TMP_PATH, ASSET_PATH)) {
    LittleFS.remove(TMP_PATH);
    return false;
  }

  File hashFile = LittleFS.open(HASH_PATH, "w");
  if (!hashFile) {
    return false;
  }
  hashFile.print(state.assetHash);
  hashFile.close();
  return true;
}

