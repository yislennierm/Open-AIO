import LCD from "@SignalRGB/lcd";
import Serial from "@SignalRGB/serial";

const DEVICE_NAME = "Open AIO"; // Keep in sync with firmware/src/config.h.
const DEVICE_IMAGE_URL = "https://assets.signalrgb.com/devices/default/misc/usb-drive-render.png";

export function Name() { return DEVICE_NAME; }
export function VendorId() { return 0x303A; }
export function ProductId() { return 0x1001; }
export function Publisher() { return "Local"; }
export function Size() { return [1, 1]; }
export function Type() { return "serial"; }
export function DeviceType() { return "lcd"; }
export function SubdeviceController() { return true; }
export function Validate(endpoint) { return endpoint.interface === 0; }
export function ImageUrl() { return DEVICE_IMAGE_URL; }
/* global
streamQuality:readonly
*/
export function ControllableParameters() {
  return [
    {
      property: "streamQuality",
      group: "lighting",
      label: "Stream Mode",
      description: "JPEG streams the SignalRGB LCD face compressed. Raw modes are lower resolution fallbacks. Local FX sends colors only and lets the ESP32 render its own animation.",
      type: "combobox",
      values: ["Direct JPEG", "Direct FPS", "Direct Fast", "Direct Balanced", "Direct Sharp", "Local FX"],
      default: "Direct JPEG",
    },
  ];
}

const LCD_WIDTH = 480;
const LCD_HEIGHT = 480;
const BAUD_RATE = 4000000;
const JPEG_QUALITY = 8;
const MAGIC = [0x53, 0x52, 0x47, 0x42]; // SRGB
const CMD_RECT = 0x01;
const CMD_RECT_SCALED = 0x03;
const CMD_FLUSH = 0x02;
const CMD_LOCAL = 0x04;
const CMD_JPEG = 0x05;
const SIGNALRGB_HEADER_SIZE = 20;

// Keep packet format changes in sync with Open_AIO_RawUSB.js and AGENT.md.

let initialized = false;
let previousFrame = null;
let pendingZones = [];
let frameId = 0;
let renderCount = 0;
let frameHasPendingFlush = false;
let statStartedAt = Date.now();
let statFlushes = 0;
let statBytes = 0;
let statZones = 0;
let statLastJpegBytes = 0;
let renderSeen = false;

export function Initialize() {
  device.setName(DEVICE_NAME);
  updateFrameRate();
  LCD.initialize({ width: LCD_WIDTH, height: LCD_HEIGHT, circularPreview: true });
  connect();
  device.log(DEVICE_NAME + " LCD initialized over serial");
}

export function Render() {
  if (!renderSeen) {
    renderSeen = true;
    console.log(DEVICE_NAME + " render started mode=" + streamQuality);
  }
  if (!initialized || !Serial.isConnected()) {
    connect();
    return;
  }
  sendFrame();
}

export function Shutdown() {
  if (Serial.isConnected()) {
    Serial.disconnect();
  }
  initialized = false;
  previousFrame = null;
  pendingZones = [];
  frameHasPendingFlush = false;
}

export function onstreamQualityChanged() {
  pendingZones = [];
  previousFrame = null;
  frameHasPendingFlush = false;
  updateFrameRate();
}

function updateFrameRate() {
  device.setFrameRateTarget(streamQuality === "Direct JPEG" ? 8 : 30);
}

function connect() {
  if (!Serial.isConnected()) {
    Serial.disconnect();
    console.log("Connecting to " + DEVICE_NAME + " at " + BAUD_RATE);
    Serial.connect({
      baudRate: BAUD_RATE,
      parity: "None",
      dataBits: 8,
      stopBits: "One",
    });
    if (!Serial.isConnected()) {
      console.log("Failed to connect to " + DEVICE_NAME);
      initialized = false;
      return false;
    }
  }

  console.log("Connected to " + DEVICE_NAME);
  initialized = true;
  return true;
}

function sendFrame() {
  if (streamQuality === "Direct JPEG") {
    const jpeg = LCD.getFrame({ format: "jpeg", quality: JPEG_QUALITY });
    const packet = packetWithPayload(CMD_JPEG, 0, jpeg);
    writePacket(packet);
    statBytes += packet.length;
    statLastJpegBytes = jpeg.length;
    statFlushes++;
    logStats();
    return;
  }

  const rgb = LCD.getFrame({ format: "RGB" });
  if (streamQuality === "Local FX") {
    const packet = localPacket(rgb);
    writePacket(packet);
    statBytes += packet.length;
    statFlushes++;
    logStats();
    return;
  }

  const scale = streamScale();
  const width = streamWidth();
  const height = streamHeight();
  const rgb565 = streamQuality === "Direct FPS" || streamQuality === "Direct Fast"
      ? sampleRgbToRgb565(rgb, scale, width, height)
      : downsampleRgbToRgb565(rgb, scale, width, height);
  renderCount++;

  if (pendingZones.length === 0) {
    const forceFullRefresh = previousFrame === null || renderCount % fullRefreshInterval() === 0;
    pendingZones = collectChangedZones(rgb565, width, height, forceFullRefresh);
  }

  let sent = 0;
  const maxZones = zonesPerRender();
  while (pendingZones.length > 0 && sent < maxZones) {
    const zone = pendingZones.shift();
    const packet = rectPacket(zone.x, zone.y, zone.w, zone.h, scale, width, rgb565);
    writePacket(packet);
    statBytes += packet.length;
    statZones++;
    updatePreviousZone(rgb565, width, zone.x, zone.y, zone.w, zone.h);
    frameHasPendingFlush = true;
    sent++;
  }

  if (frameHasPendingFlush && pendingZones.length === 0) {
    const packet = flushPacket();
    writePacket(packet);
    statBytes += packet.length;
    statFlushes++;
    frameHasPendingFlush = false;
  } else if (!frameHasPendingFlush && renderCount % 10 === 0) {
    const packet = flushPacket();
    writePacket(packet);
    statBytes += packet.length;
    statFlushes++;
  }

  if (previousFrame === null || previousFrame.length !== rgb565.length) {
    previousFrame = new Uint8Array(rgb565.length);
  }
  logStats();
}

function streamScale() {
  if (streamQuality === "Direct Sharp") return 4;
  if (streamQuality === "Direct Balanced") return 5;
  if (streamQuality === "Direct Fast") return 6;
  return 8;
}

function localPacket(rgb) {
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
  const payload = [r, g, b, accentR, accentG, accentB, energy, 0];
  return packetWithPayload(CMD_LOCAL, 0, payload);
}

function packetWithPayload(command, scale, payload) {
  const body = Array.from(payload);
  const payloadLength = body.length;
  const checksum = checksum16(body);
  const packet = MAGIC.concat([
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
  return packet.concat(body);
}

function writePacket(packet) {
  const chunkSize = 4096;
  for (let offset = 0; offset < packet.length; offset += chunkSize) {
    Serial.write(packet.slice(offset, offset + chunkSize));
    if (packet.length > chunkSize && offset > 0 && offset % 16384 === 0) {
      device.pause(1);
    }
  }
}

function streamWidth() {
  return Math.floor(LCD_WIDTH / streamScale());
}

function streamHeight() {
  return Math.floor(LCD_HEIGHT / streamScale());
}

function zoneWidth() {
  if (streamQuality === "Direct Sharp") return 30;
  if (streamQuality === "Direct Balanced") return 32;
  if (streamQuality === "Direct Fast") return 40;
  return 60;
}

function zoneHeight() {
  if (streamQuality === "Direct Sharp") return 20;
  if (streamQuality === "Direct Balanced") return 32;
  if (streamQuality === "Direct Fast") return 40;
  return 30;
}

function zonesPerRender() {
  if (streamQuality === "Direct Sharp") return 8;
  if (streamQuality === "Direct Balanced") return 9;
  if (streamQuality === "Direct Fast") return 4;
  return 2;
}

function fullRefreshInterval() {
  if (streamQuality === "Direct Sharp") return 240;
  if (streamQuality === "Direct Balanced") return 180;
  if (streamQuality === "Direct Fast") return 120;
  return 60;
}

function logStats() {
  const now = Date.now();
  const elapsed = now - statStartedAt;
  if (elapsed < 30000) return;
  const seconds = elapsed / 1000;
  const fps = statFlushes / seconds;
  const kbps = (statBytes / 1024) / seconds;
  console.log(
      DEVICE_NAME + " stream " + streamQuality +
      " flush_fps=" + fps.toFixed(1) +
      " zones/s=" + (statZones / seconds).toFixed(1) +
      " KB/s=" + kbps.toFixed(1) +
      (statLastJpegBytes > 0 ? " jpeg_bytes=" + statLastJpegBytes : ""));
  statStartedAt = now;
  statFlushes = 0;
  statBytes = 0;
  statZones = 0;
}

function rgbToRgb565(rgb) {
  const out = [];
  for (let i = 0; i < rgb.length; i += 3) {
    const r = rgb[i];
    const g = rgb[i + 1];
    const b = rgb[i + 2];
    const value = ((r & 0xF8) << 8) | ((g & 0xFC) << 3) | (b >> 3);
    out.push(value & 0xFF);
    out.push((value >> 8) & 0xFF);
  }
  return out;
}

function sampleRgbToRgb565(rgb, scale, width, height) {
  const out = [];
  const offset = Math.floor(scale / 2);
  for (let y = 0; y < height; y++) {
    const srcY = Math.min(LCD_HEIGHT - 1, (y * scale) + offset);
    for (let x = 0; x < width; x++) {
      const srcX = Math.min(LCD_WIDTH - 1, (x * scale) + offset);
      const index = ((srcY * LCD_WIDTH) + srcX) * 3;
      const r = rgb[index];
      const g = rgb[index + 1];
      const b = rgb[index + 2];
      const value = ((r & 0xF8) << 8) | ((g & 0xFC) << 3) | (b >> 3);
      out.push(value & 0xFF);
      out.push((value >> 8) & 0xFF);
    }
  }
  return out;
}

function downsampleRgbToRgb565(rgb, scale, width, height) {
  const out = [];
  const sampleCount = scale * scale;
  for (let y = 0; y < height; y++) {
    for (let x = 0; x < width; x++) {
      let r = 0;
      let g = 0;
      let b = 0;
      const srcX = x * scale;
      const srcY = y * scale;
      for (let yy = 0; yy < scale; yy++) {
        for (let xx = 0; xx < scale; xx++) {
          const index = (((srcY + yy) * LCD_WIDTH) + srcX + xx) * 3;
          r += rgb[index];
          g += rgb[index + 1];
          b += rgb[index + 2];
        }
      }
      r = Math.floor(r / sampleCount);
      g = Math.floor(g / sampleCount);
      b = Math.floor(b / sampleCount);
      const value = ((r & 0xF8) << 8) | ((g & 0xFC) << 3) | (b >> 3);
      out.push(value & 0xFF);
      out.push((value >> 8) & 0xFF);
    }
  }
  return out;
}

function zoneChanged(current, previous, frameWidth, x, y, w, h) {
  for (let yy = 0; yy < h; yy++) {
    const row = y + yy;
    for (let xx = 0; xx < w; xx++) {
      const col = x + xx;
      const index = ((row * frameWidth) + col) * 2;
      if (current[index] !== previous[index] || current[index + 1] !== previous[index + 1]) {
        return true;
      }
    }
  }
  return false;
}

function collectChangedZones(frame, frameWidth, frameHeight, force) {
  const zones = [];
  const zw = zoneWidth();
  const zh = zoneHeight();
  for (let y = 0; y < frameHeight; y += zh) {
    for (let x = 0; x < frameWidth; x += zw) {
      const w = Math.min(zw, frameWidth - x);
      const h = Math.min(zh, frameHeight - y);
      if (force || previousFrame === null || previousFrame.length !== frame.length ||
          zoneChanged(frame, previousFrame, frameWidth, x, y, w, h)) {
        zones.push({ x, y, w, h });
      }
    }
  }
  return zones;
}

function updatePreviousZone(frame, frameWidth, x, y, w, h) {
  if (previousFrame === null || previousFrame.length !== frame.length) {
    previousFrame = new Uint8Array(frame.length);
  }
  for (let yy = 0; yy < h; yy++) {
    const row = y + yy;
    for (let xx = 0; xx < w; xx++) {
      const col = x + xx;
      const index = ((row * frameWidth) + col) * 2;
      previousFrame[index] = frame[index];
      previousFrame[index + 1] = frame[index + 1];
    }
  }
}

function rectPacket(x, y, w, h, scale, frameWidth, frame) {
  const payload = [];
  for (let yy = 0; yy < h; yy++) {
    const row = y + yy;
    for (let xx = 0; xx < w; xx++) {
      const col = x + xx;
      const index = ((row * frameWidth) + col) * 2;
      payload.push(frame[index]);
      payload.push(frame[index + 1]);
    }
  }

  const payloadLength = payload.length;
  const checksum = checksum16(payload);
  const packet = MAGIC.concat([
    CMD_RECT_SCALED,
    scale & 0xFF,
    checksum & 0xFF, (checksum >> 8) & 0xFF,
    x & 0xFF, (x >> 8) & 0xFF,
    y & 0xFF, (y >> 8) & 0xFF,
    w & 0xFF, (w >> 8) & 0xFF,
    h & 0xFF, (h >> 8) & 0xFF,
    payloadLength & 0xFF,
    (payloadLength >> 8) & 0xFF,
    (payloadLength >> 16) & 0xFF,
    (payloadLength >> 24) & 0xFF,
  ]);

  return packet.concat(payload);
}

function flushPacket() {
  frameId = (frameId + 1) & 0xFF;
  return MAGIC.concat([CMD_FLUSH, frameId & 0xFF, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0]);
}

function checksum16(values) {
  let sum = 0;
  for (let i = 0; i < values.length; i++) {
    sum = (sum + values[i]) & 0xFFFF;
  }
  return sum;
}
