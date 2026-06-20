import LCD from "@SignalRGB/lcd";

const DEVICE_NAME = "Open AIO";
const DEVICE_IMAGE_URL = "https://assets.signalrgb.com/devices/default/misc/usb-drive-render.png";

export function Name() { return DEVICE_NAME; }
export function VendorId() { return 0x303A; }
export function ProductId() { return 0x4004; }
export function Publisher() { return "Local"; }
export function Size() { return [1, 1]; }
export function Type() { return "rawusb"; }
export function DeviceType() { return "lcd"; }
export function SubdeviceController() { return true; }
export function Validate(endpoint) { return endpoint.interface === 0; }
export function ImageUrl() { return DEVICE_IMAGE_URL; }
/* global
streamQuality:readonly
logDeviceStatus:readonly
*/
export function ControllableParameters() {
  return [
    {
      property: "streamQuality",
      group: "lighting",
      label: "Stream Mode",
      description: "Raw USB bulk transfer test for full-resolution JPEG LCD streaming.",
      type: "combobox",
      values: ["Direct JPEG Max FPS", "Direct JPEG", "Direct JPEG Low", "Local FX"],
      default: "Direct JPEG",
    },
    {
      property: "logDeviceStatus",
      group: "lighting",
      label: "Log Device Status",
      description: "Polls the Raw USB IN endpoint and logs firmware ACK/status packets for debugging.",
      type: "boolean",
      default: false,
    },
  ];
}

const LCD_WIDTH = 480;
const LCD_HEIGHT = 480;
const MAGIC = [0x53, 0x52, 0x47, 0x42]; // SRGB
const CMD_LOCAL = 0x04;
const CMD_JPEG = 0x05;

// Keep packet format changes in sync with Open_AIO.js and AGENT.md.
const BULK_OUT_ENDPOINTS = [0x01, 0x02, 0x03, 0x04];
const BULK_IN_ENDPOINTS = [0x81, 0x82, 0x83, 0x84];
const BULK_CHUNK_SIZE = 16384;
const BULK_TIMEOUT_MS = 500;
const STATUS_TIMEOUT_MS = 10;
const RETRY_BACKOFF_MS = 1000;

let selectedEndpoint = 0x01;
let selectedInEndpoint = 0x81;
let renderSeen = false;
let suspendedUntil = 0;
let writeFailureCount = 0;
let lastStatusPoll = 0;

export function Initialize() {
  device.setName(DEVICE_NAME);
  updateFrameRate();
  LCD.initialize({ width: LCD_WIDTH, height: LCD_HEIGHT, circularPreview: true });
  device.log(DEVICE_NAME + " LCD initialized over raw USB");
}

export function Render() {
  if (!renderSeen) {
    renderSeen = true;
    console.log(DEVICE_NAME + " render started mode=" + streamQuality);
  }
  if (Date.now() < suspendedUntil) {
    return;
  }
  try {
    sendFrame();
  } catch (error) {
    writeFailureCount++;
    suspendedUntil = Date.now() + RETRY_BACKOFF_MS;
    selectedEndpoint = 0x01;
    selectedInEndpoint = 0x81;
    if (writeFailureCount === 1 || writeFailureCount % 10 === 0) {
      console.log(DEVICE_NAME + " raw USB write failed; retrying (" + writeFailureCount + ")");
    }
  }
}

export function Shutdown() {}

export function onstreamQualityChanged() {
  updateFrameRate();
}

function updateFrameRate() {
  if (streamQuality === "Direct JPEG Max FPS") {
    device.setFrameRateTarget(24);
  } else if (streamQuality === "Direct JPEG") {
    device.setFrameRateTarget(16);
  } else {
    device.setFrameRateTarget(12);
  }
}

function sendFrame() {
  if (streamQuality === "Local FX") {
    const rgb = LCD.getFrame({ format: "RGB" });
    const payload = localPayload(rgb);
    writePayload(CMD_LOCAL, 0, payload);
    return;
  }

  const quality = streamQuality === "Direct JPEG Max FPS" ? 3 : (streamQuality === "Direct JPEG Low" ? 6 : 10);
  const jpeg = LCD.getFrame({ format: "jpeg", quality });
  writePayload(CMD_JPEG, 0, jpeg);
}

function writePayload(command, scale, payload) {
  if (!writeChunk(packetHeader(command, scale, payload))) {
    return false;
  }
  for (let offset = 0; offset < payload.length; offset += BULK_CHUNK_SIZE) {
    if (!writeChunk(payload.slice(offset, offset + BULK_CHUNK_SIZE))) {
      return false;
    }
  }
  writeFailureCount = 0;
  pollDeviceStatus();
  return true;
}

function writeChunk(chunk) {
  try {
    device.bulk_transfer(selectedEndpoint, chunk, chunk.length, BULK_TIMEOUT_MS);
    return true;
  } catch (selectedError) {
    for (let i = 0; i < BULK_OUT_ENDPOINTS.length; i++) {
      const endpoint = BULK_OUT_ENDPOINTS[i];
      if (endpoint === selectedEndpoint) {
        continue;
      }
      try {
        device.bulk_transfer(endpoint, chunk, chunk.length, BULK_TIMEOUT_MS);
        selectedEndpoint = endpoint;
        console.log(DEVICE_NAME + " raw USB endpoint=0x" + endpoint.toString(16));
        return true;
      } catch (candidateError) {
      }
    }
    throw selectedError;
  }
}

function pollDeviceStatus() {
  if (!logDeviceStatus || Date.now() - lastStatusPoll < 1000) {
    return;
  }
  lastStatusPoll = Date.now();
  try {
    const response = device.bulk_transfer(selectedInEndpoint, [], 12, STATUS_TIMEOUT_MS);
    if (response && response.length >= 8) {
      logStatus(response);
    }
  } catch (selectedError) {
    for (let i = 0; i < BULK_IN_ENDPOINTS.length; i++) {
      const endpoint = BULK_IN_ENDPOINTS[i];
      if (endpoint === selectedInEndpoint) {
        continue;
      }
      try {
        const response = device.bulk_transfer(endpoint, [], 12, STATUS_TIMEOUT_MS);
        selectedInEndpoint = endpoint;
        console.log(DEVICE_NAME + " raw USB IN endpoint=0x" + endpoint.toString(16));
        if (response && response.length >= 8) {
          logStatus(response);
        }
        return;
      } catch (candidateError) {
      }
    }
  }
}

function logStatus(response) {
  if (response[0] !== 0x53 || response[1] !== 0x52 || response[2] !== 0x53 || response[3] !== 0x50) {
    return;
  }
  const status = statusName(response[4]);
  const command = "0x" + response[5].toString(16);
  const detail = response[6] | (response[7] << 8);
  if (response[4] !== 0x00) {
    console.log(DEVICE_NAME + " status=" + status + " command=" + command + " detail=" + detail);
  }
}

function statusName(value) {
  if (value === 0x00) return "OK";
  if (value === 0x01) return "BAD_MAGIC";
  if (value === 0x02) return "BAD_COMMAND";
  if (value === 0x03) return "BAD_LENGTH";
  if (value === 0x04) return "BAD_CHECKSUM";
  if (value === 0x05) return "RENDER_FAILED";
  return "UNKNOWN_" + value;
}

function localPayload(rgb) {
  let r = 0;
  let g = 0;
  let b = 0;
  let accentR = 0;
  let accentG = 0;
  let accentB = 0;
  let maxValue = -1;
  let minValue = 255;
  let maxDelta = 0;
  let samples = 0;
  const step = 24;

  for (let y = 0; y < LCD_HEIGHT; y += step) {
    for (let x = 0; x < LCD_WIDTH; x += step) {
      const index = ((y * LCD_WIDTH) + x) * 3;
      const sr = rgb[index];
      const sg = rgb[index + 1];
      const sb = rgb[index + 2];
      const value = Math.max(sr, sg, sb);
      const low = Math.min(sr, sg, sb);
      const delta = value - low;
      r += sr;
      g += sg;
      b += sb;
      maxValue = Math.max(maxValue, value);
      minValue = Math.min(minValue, low);
      if (delta > maxDelta || value > Math.max(accentR, accentG, accentB)) {
        maxDelta = delta;
        accentR = sr;
        accentG = sg;
        accentB = sb;
      }
      samples++;
    }
  }

  r = Math.floor(r / samples);
  g = Math.floor(g / samples);
  b = Math.floor(b / samples);
  if (maxDelta < 18) {
    accentR = Math.min(255, r + 72);
    accentG = Math.min(255, g + 72);
    accentB = Math.min(255, b + 72);
  }
  const energy = Math.max(32, Math.min(255, maxValue - minValue + 40));
  return [r, g, b, accentR, accentG, accentB, energy, 0];
}

function packetHeader(command, scale, payload) {
  const payloadLength = payload.length;
  const checksum = checksum16(payload);
  return MAGIC.concat([
    command,
    scale & 0xFF,
    checksum & 0xFF, (checksum >> 8) & 0xFF,
    0, 0,
    0, 0,
    0, 0,
    0, 0,
    payloadLength & 0xFF,
    (payloadLength >> 8) & 0xFF,
    (payloadLength >> 16) & 0xFF,
    (payloadLength >> 24) & 0xFF,
  ]);
}

function checksum16(values) {
  let sum = 0;
  for (let i = 0; i < values.length; i++) {
    sum = (sum + values[i]) & 0xFFFF;
  }
  return sum;
}
