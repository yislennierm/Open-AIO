#pragma once

#include <Arduino.h>

bool connectWiFi();
void suspendWiFi();
void resumeWiFi();
bool isWiFiSuspended();
bool httpGetString(const String& path, String& body);
bool httpPostCandidateDecision(const String& path, const String& processName, const String& appId);
bool downloadAssetToFile(const String& path, const char* tmpPath, size_t maxBytes);
