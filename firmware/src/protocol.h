#pragma once

#include <Arduino.h>

struct DisplayState {
  String deviceId;
  String appId;
  String displayName;
  String assetType;
  String assetUrl;
  String assetHash;
  int assetWidth = 0;
  int assetHeight = 0;
  float cpuTemp = NAN;
  float gpuTemp = NAN;
  float cpuLoad = 0.0f;
  float gpuLoad = NAN;
  float ramUsedPercent = 0.0f;
  String updatedAt;
  String localTime;
  String localDate;
  bool reviewAvailable = false;
  String reviewProcessName;
  String reviewAppId;
  String reviewDisplayName;
  String reviewStatus;
  bool valid = false;
};

bool parseDisplayState(const String& json, DisplayState& out);
