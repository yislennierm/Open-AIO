#pragma once

#include <Arduino.h>

#include "protocol.h"

bool initAssetStore();
String cachedAssetHash();
bool hasCachedAsset();
bool updateCachedAsset(const DisplayState& state);
const char* cachedAssetPath();

