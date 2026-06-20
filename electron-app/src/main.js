const { app, BrowserWindow, Menu, Tray, nativeImage, shell, session } = require("electron");
const { spawn } = require("child_process");
const fs = require("fs");
const path = require("path");

const ROOT = path.resolve(__dirname, "..", "..");
const SERVER_URL = process.env.COOLER_SERVER_URL || "http://127.0.0.1:8000";
const API_KEY = process.env.COOLER_API_KEY || "change-me";
const CLIENT_ID = `edge-renderer-electron-${process.pid}`;
const FPS = Number(process.env.COOLER_ELECTRON_FPS || 30);
const JPEG_QUALITY = Math.max(1, Math.min(90, Number(process.env.COOLER_ELECTRON_QUALITY || 18)));
const USB_TRANSPORT_OVERRIDE = process.env.OPEN_AIO_USB_TRANSPORT;
const STREAM_FORMAT = ["rgb565-tiles", "rgb565-full"].includes(process.env.OPEN_AIO_STREAM_FORMAT)
  ? process.env.OPEN_AIO_STREAM_FORMAT
  : "jpeg";
const DEFAULT_USB_TRANSPORT = USB_TRANSPORT_OVERRIDE === "native" ? "native" : "python";
const RGB565_TILE_SIZE = 120;
const NATIVE_FAILURE_FALLBACK_THRESHOLD = STREAM_FORMAT.startsWith("rgb565-") ? Number.POSITIVE_INFINITY : 20;
const EDITOR_URL = `${SERVER_URL}/nzxt-esc/`;
const RENDER_URL = `${SERVER_URL}/nzxt-esc/?kraken=1&mockLcd=480&mockShape=circle&streamRenderer=1`;
const LIVE_PREVIEW_URL = `${SERVER_URL}/nzxt-esc/?kraken=1&mockLcd=480&mockShape=circle`;

let editorWindow = null;
let renderWindow = null;
let renderReady = false;
let tray = null;
let streaming = false;
let lastPostAt = 0;
let frameCount = 0;
let lastStatsAt = Date.now();
let posting = false;
let captureTimer = null;
let heartbeatTimer = null;
let thumbnailTimer = null;
let thumbnailRunning = false;
let streamTransform = "normal";
let usbTransport = DEFAULT_USB_TRANSPORT;
let streamTransformCssKey = null;
let nativeStream = null;
let nativeFrameCount = 0;
let nativeFailedCount = 0;
let nativeWriteMsTotal = 0;
let nativeConsecutiveFailures = 0;
let captureMsTotal = 0;
let encodeMsTotal = 0;
let deviceTimingSampleCount = 0;
let deviceRxMsTotal = 0;
let deviceDecodeMsTotal = 0;
let deviceFlushMsTotal = 0;
let previousRgb565Frame = null;
let rgb565BytesTotal = 0;
let rgb565TileCount = 0;
const LOG_DIR = path.join(ROOT, "logs");
const LOG_FILE = path.join(LOG_DIR, "electron-stream.log");
const SETTINGS_FILE = path.join(__dirname, "..", "settings.json");
const SERVER_DIR = path.join(ROOT, "server");
const SERVER_PYTHON = path.join(SERVER_DIR, ".venv", "Scripts", "python.exe");
const AGENT_DIR = path.join(ROOT, "pc-agent");
const AGENT_PYTHON = path.join(AGENT_DIR, ".venv", "Scripts", "python.exe");
const AGENT_STATUS_FILE = path.join(AGENT_DIR, "logs", "status.json");
const DIRECT_USB_OWNER_FILE = path.join(AGENT_DIR, "logs", "designer-usb-owner.json");
const NATIVE_SERVICE_EXE = path.join(ROOT, "native", "open-aio-core", "target", "release", "open-aio-service.exe");
const DEPLOY_SIGNALRGB_SCRIPT = path.join(ROOT, "scripts", "deploy_signalrgb_plugin.ps1");
const SIGNALRGB_PLUGIN_DIR = path.join(app.getPath("documents"), "WhirlwindFX", "Plugins");
const WEB_PARTITION = "persist:cooler-display";
const ICON_PATH = path.join(__dirname, "..", "assets", "open-aio.ico");
const ICON_PNG_BASE64 = "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";
let requestLoggingInstalled = false;
let managedServer = null;
let managedAgent = null;
let backendTimer = null;
let backendStatus = {
  server: "checking",
  agent: "checking",
  native: "checking",
  message: "Checking backend",
};
const STREAM_TRANSFORMS = {
  normal: { label: "Normal", css: "" },
  rotate180: { label: "Rotate 180", css: "body { transform: rotate(180deg) !important; }" },
  flipX: { label: "Mirror Left/Right", css: "body { transform: scaleX(-1) !important; }" },
  flipY: { label: "Flip Top/Bottom", css: "body { transform: scaleY(-1) !important; }" },
  invertColors: { label: "Invert Colors", css: "html { filter: invert(1) !important; }" },
};
const USB_TRANSPORTS = {
  python: { label: "Python Agent" },
  native: { label: "Native Helper" },
};
const TRANSPARENT_ICON_PNG_BASE64 = "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";
const SOLID_ICON_PNG_BASE64 = "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";

function log(...parts) {
  const line = `${new Date().toISOString()} ${parts.map((part) => {
    if (part instanceof Error) return part.stack || part.message;
    if (typeof part === "string") return part;
    try { return JSON.stringify(part); } catch { return String(part); }
  }).join(" ")}\n`;
  try {
    fs.mkdirSync(LOG_DIR, { recursive: true });
    fs.appendFileSync(LOG_FILE, line, "utf8");
  } catch {}
  console.log(...parts);
}

function loadSettings() {
  try {
    const settings = JSON.parse(fs.readFileSync(SETTINGS_FILE, "utf8"));
    if (settings && STREAM_TRANSFORMS[settings.streamTransform]) {
      streamTransform = settings.streamTransform;
    }
    if (!USB_TRANSPORT_OVERRIDE && settings && USB_TRANSPORTS[settings.usbTransport]) {
      usbTransport = settings.usbTransport;
    }
  } catch {}
}

function saveSettings() {
  try {
    fs.writeFileSync(SETTINGS_FILE, JSON.stringify({ streamTransform, usbTransport }, null, 2), "utf8");
  } catch (error) {
    log("[settings] save failed", error.message);
  }
}

async function applyStreamTransform() {
  if (!renderWindow || renderWindow.isDestroyed()) return;
  if (streamTransformCssKey) {
    try {
      await renderWindow.webContents.removeInsertedCSS(streamTransformCssKey);
    } catch {}
    streamTransformCssKey = null;
  }
  const transform = STREAM_TRANSFORMS[streamTransform] || STREAM_TRANSFORMS.normal;
  if (!transform.css) return;
  const css = `
    html, body {
      width: 480px !important;
      height: 480px !important;
      margin: 0 !important;
      overflow: hidden !important;
      background: #000 !important;
    }
    body {
      transform-origin: 50% 50% !important;
    }
    ${transform.css}
  `;
  streamTransformCssKey = await renderWindow.webContents.insertCSS(css);
  log("[electron-stream] stream transform applied", streamTransform);
}

function setStreamTransform(nextTransform) {
  if (!STREAM_TRANSFORMS[nextTransform]) return;
  streamTransform = nextTransform;
  saveSettings();
  buildMenu();
  applyStreamTransform().catch((error) => log("[electron-stream] transform failed", error.message));
}

function setUsbTransport(nextTransport) {
  if (!USB_TRANSPORTS[nextTransport]) return;
  usbTransport = nextTransport;
  nativeConsecutiveFailures = 0;
  saveSettings();
  if (nextTransport !== "native") {
    stopNativeStream();
    writeDirectUsbOwner(false);
  }
  buildMenu();
  log("[electron-stream] USB transport set", usbTransport);
}

function writeDirectUsbOwner(active) {
  try {
    fs.mkdirSync(path.dirname(DIRECT_USB_OWNER_FILE), { recursive: true });
    if (!active) {
      fs.rmSync(DIRECT_USB_OWNER_FILE, { force: true });
      return;
    }
    fs.writeFileSync(DIRECT_USB_OWNER_FILE, JSON.stringify({
      owner: "electron-native-helper",
      updated_at: Date.now() / 1000,
      ttl_seconds: 4,
    }, null, 2), "utf8");
  } catch (error) {
    log("[native-stream] owner heartbeat failed", error.message);
  }
}

function installRequestLogging() {
  if (requestLoggingInstalled) return;
  requestLoggingInstalled = true;
  const ses = session.fromPartition(WEB_PARTITION);
  ses.webRequest.onCompleted((details) => {
    if (details.statusCode >= 400) {
      log("[web-request]", details.statusCode, details.method, details.url);
    }
  });
  ses.webRequest.onErrorOccurred((details) => {
    if (details.error === "net::ERR_CACHE_MISS") return;
    if (details.url === "ws://localhost:27871/") return;
    log("[web-request-error]", details.error, details.method, details.url);
  });
}

function headers(extra = {}) {
  return {
    "X-API-Key": API_KEY,
    "X-Designer-Client-ID": CLIENT_ID,
    ...extra,
  };
}

function appendProcessLog(name) {
  fs.mkdirSync(LOG_DIR, { recursive: true });
  const file = path.join(LOG_DIR, name);
  return fs.createWriteStream(file, { flags: "a" });
}

async function fetchCamStatus(timeoutMs = 1200) {
  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(), timeoutMs);
  try {
    const response = await fetch(`${SERVER_URL}/api/cam/status`, {
      cache: "no-store",
      signal: controller.signal,
    });
    if (!response.ok) return null;
    const payload = await response.json();
    return payload && payload.ok ? payload : null;
  } catch {
    return null;
  } finally {
    clearTimeout(timer);
  }
}

async function waitForCamStatus(timeoutMs = 8000) {
  const started = Date.now();
  while (Date.now() - started < timeoutMs) {
    const status = await fetchCamStatus();
    if (status) return status;
    await wait(350);
  }
  return null;
}

function agentIsHealthy(status) {
  const agent = status && status.agent;
  if (!agent || !agent.ok) return false;
  const updatedAt = Date.parse(agent.updated_at || "");
  if (!Number.isFinite(updatedAt)) return false;
  if (Date.now() - updatedAt >= 15000) return false;
  return localAgentStatusIsLive();
}

function pidIsLive(pid) {
  const numericPid = Number(pid);
  if (!Number.isInteger(numericPid) || numericPid <= 0) return false;
  try {
    process.kill(numericPid, 0);
    return true;
  } catch {
    return false;
  }
}

function localAgentStatusIsLive() {
  try {
    const status = JSON.parse(fs.readFileSync(AGENT_STATUS_FILE, "utf8"));
    const updatedAt = Date.parse(status.updated_at || "");
    if (!Number.isFinite(updatedAt) || Date.now() - updatedAt >= 15000) return false;
    return pidIsLive(status.agent_pid);
  } catch {
    return false;
  }
}

function spawnManaged(label, exe, args, cwd, stdoutName, stderrName) {
  if (!fs.existsSync(exe)) {
    backendStatus.message = `${label} python missing: ${exe}`;
    log("[backend]", backendStatus.message);
    return null;
  }
  const child = spawn(exe, args, {
    cwd,
    windowsHide: true,
    stdio: ["ignore", "pipe", "pipe"],
  });
  child.stdout.pipe(appendProcessLog(stdoutName));
  child.stderr.pipe(appendProcessLog(stderrName));
  child.on("exit", (code, signal) => {
    log("[backend]", `${label} exited`, { code, signal });
    if (child === managedServer) managedServer = null;
    if (child === managedAgent) managedAgent = null;
    refreshBackendStatus();
  });
  child.on("error", (error) => {
    log("[backend]", `${label} spawn failed`, error);
  });
  log("[backend]", `${label} started`, { pid: child.pid });
  return child;
}

function runPowerShellScript(label, scriptPath, args = []) {
  return new Promise((resolve, reject) => {
    if (!fs.existsSync(scriptPath)) {
      reject(new Error(`${label} script missing: ${scriptPath}`));
      return;
    }
    const child = spawn("powershell.exe", [
      "-NoProfile",
      "-ExecutionPolicy",
      "Bypass",
      "-File",
      scriptPath,
      ...args,
    ], {
      cwd: ROOT,
      windowsHide: true,
      stdio: ["ignore", "pipe", "pipe"],
    });
    child.stdout.on("data", (chunk) => log(`[${label}]`, chunk.toString("utf8").trim()));
    child.stderr.on("data", (chunk) => log(`[${label}:error]`, chunk.toString("utf8").trim()));
    child.on("error", reject);
    child.on("exit", (code) => {
      if (code === 0) {
        resolve();
      } else {
        reject(new Error(`${label} exited with code ${code}`));
      }
    });
  });
}

function runNativeHelper(args = [], timeoutMs = 2000) {
  return new Promise((resolve) => {
    if (!fs.existsSync(NATIVE_SERVICE_EXE)) {
      resolve({ ok: false, status: "missing", error: `missing: ${NATIVE_SERVICE_EXE}` });
      return;
    }
    const child = spawn(NATIVE_SERVICE_EXE, args, {
      cwd: ROOT,
      windowsHide: true,
      stdio: ["ignore", "pipe", "pipe"],
    });
    let stdout = "";
    let stderr = "";
    const timer = setTimeout(() => {
      child.kill();
      resolve({ ok: false, status: "timeout", error: `timeout after ${timeoutMs}ms` });
    }, timeoutMs);
    child.stdout.on("data", (chunk) => { stdout += chunk.toString("utf8"); });
    child.stderr.on("data", (chunk) => { stderr += chunk.toString("utf8"); });
    child.on("error", (error) => {
      clearTimeout(timer);
      resolve({ ok: false, status: "spawn_failed", error: error.message });
    });
    child.on("exit", (code) => {
      clearTimeout(timer);
      const text = (stdout || stderr).trim();
      let payload = null;
      try {
        payload = text ? JSON.parse(text.split(/\r?\n/).at(-1)) : null;
      } catch {}
      resolve({
        ok: code === 0 && (!payload || payload.ok !== false),
        status: code === 0 ? "ok" : "failed",
        code,
        payload,
        stdout: stdout.trim(),
        stderr: stderr.trim(),
      });
    });
  });
}

async function refreshNativeHelperStatus() {
  const result = await runNativeHelper(["health"], 2000);
  backendStatus.native = result.ok ? "ok" : result.status || "missing";
  if (result.ok) {
    log("[native-helper] health ok");
  } else {
    log("[native-helper] health failed", result.error || result.stderr || result.status);
  }
  return result;
}

async function showNativeHelperHealth() {
  backendStatus.message = "Checking native helper";
  buildMenu();
  const result = await runNativeHelper(["protocol-info"], 2000);
  backendStatus.native = result.ok ? "ok" : result.status || "missing";
  backendStatus.message = result.ok
    ? `Native helper ok: ${result.stdout || "protocol-info"}`
    : `Native helper ${backendStatus.native}`;
  log("[native-helper] protocol-info", result);
  buildMenu();
}

async function deploySignalRgbPlugin() {
  try {
    backendStatus.message = "Deploying SignalRGB plugin";
    buildMenu();
    await runPowerShellScript("signalrgb-deploy", DEPLOY_SIGNALRGB_SCRIPT);
    backendStatus.message = "SignalRGB plugin deployed; restart SignalRGB";
    shell.openPath(SIGNALRGB_PLUGIN_DIR).catch(() => {});
  } catch (error) {
    backendStatus.message = `SignalRGB deploy failed: ${error.message}`;
    log("[signalrgb-deploy] failed", error);
  } finally {
    buildMenu();
  }
}

async function ensureServer() {
  const current = await fetchCamStatus();
  if (current) {
    backendStatus.server = "ok";
    return current;
  }
  backendStatus.server = "starting";
  backendStatus.message = "Starting FastAPI server";
  buildMenu();
  if (!managedServer) {
    managedServer = spawnManaged(
      "server",
      SERVER_PYTHON,
      ["-m", "uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"],
      SERVER_DIR,
      "electron-managed-server.stdout.log",
      "electron-managed-server.stderr.log",
    );
  }
  const started = await waitForCamStatus();
  backendStatus.server = started ? "ok" : "missing";
  return started;
}

async function ensureAgent(status) {
  if (agentIsHealthy(status)) {
    backendStatus.agent = "ok";
    return;
  }
  backendStatus.agent = "starting";
  backendStatus.message = "Starting PC agent";
  buildMenu();
  if (!managedAgent) {
    managedAgent = spawnManaged(
      "agent",
      AGENT_PYTHON,
      ["agent.py"],
      AGENT_DIR,
      "electron-managed-agent.stdout.log",
      "electron-managed-agent.stderr.log",
    );
  }
  const started = Date.now();
  while (Date.now() - started < 8000) {
    const next = await fetchCamStatus();
    if (agentIsHealthy(next)) {
      backendStatus.agent = "ok";
      return;
    }
    await wait(500);
  }
  backendStatus.agent = "starting";
}

async function ensureBackend() {
  backendStatus = { server: "checking", agent: "checking", native: "checking", message: "Checking backend" };
  buildMenu();
  await refreshNativeHelperStatus();
  const status = await ensureServer();
  if (status) {
    await ensureAgent(status);
  } else {
    backendStatus.agent = "unknown";
  }
  await refreshBackendStatus();
}

async function refreshBackendStatus() {
  const status = await fetchCamStatus();
  if (!status) {
    backendStatus.server = "missing";
    backendStatus.agent = "unknown";
    backendStatus.message = "Server unavailable";
  } else {
    const agentOk = agentIsHealthy(status);
    const usb = status.agent && status.agent.usb_status ? status.agent.usb_status : "unknown";
    backendStatus.server = "ok";
    backendStatus.agent = agentOk ? "ok" : "starting";
    backendStatus.message = agentOk ? `USB ${usb}` : "Agent not healthy yet";
    if (!agentOk && !managedAgent) {
      ensureAgent(status).catch((error) => log("[backend] agent recovery failed", error.message));
    }
  }
  buildMenu();
  return status;
}

async function restartManagedBackend() {
  if (managedAgent) {
    managedAgent.kill();
    managedAgent = null;
  }
  if (managedServer) {
    managedServer.kill();
    managedServer = null;
    await wait(1000);
  }
  await ensureBackend();
}

async function postPreviewActive(active) {
  writeDirectUsbOwner(active && usbTransport === "native");
  try {
    await fetch(`${SERVER_URL}/api/v1/designer/preview-active`, {
      method: "POST",
      headers: headers({ "Content-Type": "application/json" }),
      body: JSON.stringify({ active, client_id: CLIENT_ID }),
    });
  } catch (error) {
    log("[electron-stream] preview-active failed", error.message);
  }
}

async function postFrame(jpeg) {
  try {
    const response = await fetch(`${SERVER_URL}/api/v1/designer/frame`, {
      method: "POST",
      headers: headers({ "Content-Type": "image/jpeg" }),
      body: jpeg,
    });
    if (!response.ok) {
      log("[electron-stream] frame post failed", response.status, await response.text());
    }
  } catch (error) {
    log("[electron-stream] frame post error", error.message);
  }
}

function ensureNativeStream() {
  if (nativeStream && nativeStream.child && !nativeStream.exited) return nativeStream;
  if (!fs.existsSync(NATIVE_SERVICE_EXE)) {
    throw new Error(`native helper missing: ${NATIVE_SERVICE_EXE}`);
  }
  const child = spawn(NATIVE_SERVICE_EXE, ["stdio"], {
    cwd: ROOT,
    windowsHide: true,
    stdio: ["pipe", "pipe", "pipe"],
  });
  const stream = {
    child,
    exited: false,
    stdoutBuffer: "",
    pending: null,
  };
  child.stdout.on("data", (chunk) => {
    stream.stdoutBuffer += chunk.toString("utf8");
    while (stream.stdoutBuffer.includes("\n")) {
      const index = stream.stdoutBuffer.indexOf("\n");
      const line = stream.stdoutBuffer.slice(0, index).trim();
      stream.stdoutBuffer = stream.stdoutBuffer.slice(index + 1);
      if (!line) continue;
      let payload = null;
      try {
        payload = JSON.parse(line);
      } catch {
        payload = { ok: false, status: "bad_json", error: line };
      }
      const pending = stream.pending;
      stream.pending = null;
      if (pending) pending.resolve(payload);
    }
  });
  child.stderr.on("data", (chunk) => log("[native-stream:error]", chunk.toString("utf8").trim()));
  child.on("error", (error) => {
    stream.exited = true;
    if (stream.pending) {
      stream.pending.resolve({ ok: false, status: "spawn_failed", error: error.message });
      stream.pending = null;
    }
    log("[native-stream] spawn failed", error.message);
  });
  child.on("exit", (code, signal) => {
    stream.exited = true;
    if (stream.pending) {
      stream.pending.resolve({ ok: false, status: "exited", error: `native helper exited ${code ?? signal}` });
      stream.pending = null;
    }
    if (nativeStream === stream) nativeStream = null;
    log("[native-stream] exited", { code, signal });
  });
  nativeStream = stream;
  log("[native-stream] started", { pid: child.pid });
  return stream;
}

function stopNativeStream() {
  if (!nativeStream) return;
  try {
    nativeStream.child.stdin.end();
    nativeStream.child.kill();
  } catch {}
  nativeStream = null;
}

async function sendNativePacket(command, payload, flags = 0) {
  writeDirectUsbOwner(true);
  const stream = ensureNativeStream();
  if (stream.pending) {
    return { ok: false, status: "busy", error: "native frame already in flight" };
  }
  const header = Buffer.alloc(10);
  header.write("OAIO", 0, "ascii");
  header[4] = command;
  header[5] = flags;
  header.writeUInt32LE(payload.length, 6);
  const packet = payload.length ? Buffer.concat([header, Buffer.from(payload)]) : header;
  const resultPromise = new Promise((resolve) => {
    stream.pending = { resolve };
  });
  if (!stream.child.stdin.write(packet)) {
    await new Promise((resolve) => stream.child.stdin.once("drain", resolve));
  }
  return resultPromise;
}

async function sendNativeFrame(jpeg, sampleDeviceTiming = false) {
  return sendNativePacket(0x01, jpeg, sampleDeviceTiming ? 0x80 : 0x00);
}

async function sendNativeRgb565Rect(x, y, width, height, pixels) {
  const rectHeader = Buffer.alloc(8);
  rectHeader.writeUInt16LE(x, 0);
  rectHeader.writeUInt16LE(y, 2);
  rectHeader.writeUInt16LE(width, 4);
  rectHeader.writeUInt16LE(height, 6);
  return sendNativePacket(0x02, Buffer.concat([rectHeader, pixels]), 0x00);
}

async function sendNativeFlush() {
  return sendNativePacket(0x03, Buffer.alloc(0), 0x00);
}

async function sendNativeRgb565Frame(pixels) {
  return sendNativePacket(0x04, pixels, 0x80);
}

function bitmapToRgb565(bitmap, width, height) {
  const rgb565 = Buffer.alloc(width * height * 2);
  for (let i = 0, out = 0; i < bitmap.length && out < rgb565.length; i += 4, out += 2) {
    const b = bitmap[i];
    const g = bitmap[i + 1];
    const r = bitmap[i + 2];
    const value = ((r & 0xf8) << 8) | ((g & 0xfc) << 3) | (b >> 3);
    rgb565[out] = value & 0xff;
    rgb565[out + 1] = (value >> 8) & 0xff;
  }
  return rgb565;
}

function extractRgb565Tile(frame, width, x, y, tileWidth, tileHeight) {
  const tile = Buffer.alloc(tileWidth * tileHeight * 2);
  for (let row = 0; row < tileHeight; row += 1) {
    const sourceStart = ((y + row) * width + x) * 2;
    frame.copy(tile, row * tileWidth * 2, sourceStart, sourceStart + tileWidth * 2);
  }
  return tile;
}

function tileChanged(current, previous, width, x, y, tileWidth, tileHeight) {
  if (!previous) return true;
  for (let row = 0; row < tileHeight; row += 1) {
    const start = ((y + row) * width + x) * 2;
    const end = start + tileWidth * 2;
    if (current.compare(previous, start, end, start, end) !== 0) {
      return true;
    }
  }
  return false;
}

async function sendRgb565Tiles(image) {
  const width = 480;
  const height = 480;
  const rgb565 = bitmapToRgb565(image.toBitmap(), width, height);
  let sentTiles = 0;
  let sentBytes = 0;
  let failed = 0;
  let writeMs = 0;
  for (let y = 0; y < height; y += RGB565_TILE_SIZE) {
    for (let x = 0; x < width; x += RGB565_TILE_SIZE) {
      const tileWidth = Math.min(RGB565_TILE_SIZE, width - x);
      const tileHeight = Math.min(RGB565_TILE_SIZE, height - y);
      if (!tileChanged(rgb565, previousRgb565Frame, width, x, y, tileWidth, tileHeight)) {
        continue;
      }
      const tile = extractRgb565Tile(rgb565, width, x, y, tileWidth, tileHeight);
      const result = await sendNativeRgb565Rect(x, y, tileWidth, tileHeight, tile);
      if (result && result.ok) {
        sentTiles += 1;
        sentBytes += tile.length;
        writeMs += Number(result.writeMs || 0);
      } else {
        failed += 1;
        log("[native-stream] rgb565 tile failed", result);
      }
    }
  }
  if (sentTiles > 0) {
    const flush = await sendNativeFlush();
    if (flush && flush.ok) {
      writeMs += Number(flush.writeMs || 0);
    } else {
      failed += 1;
      log("[native-stream] rgb565 flush failed", flush);
    }
  }
  previousRgb565Frame = rgb565;
  return { ok: failed === 0, sentTiles, sentBytes, failed, writeMs };
}

async function sendRgb565FullFrame(image) {
  const rgb565 = bitmapToRgb565(image.toBitmap(), 480, 480);
  const result = await sendNativeRgb565Frame(rgb565);
  return {
    ok: Boolean(result && result.ok),
    sentBytes: rgb565.length,
    sentTiles: 1,
    failed: result && result.ok ? 0 : 1,
    writeMs: Number(result?.writeMs || 0),
  };
}

async function captureAndPostFrame() {
  if (!streaming || !renderReady || posting || !renderWindow || renderWindow.isDestroyed()) return;
  const now = Date.now();
  const minInterval = 1000 / FPS;
  if (now - lastPostAt < minInterval) return;
  lastPostAt = now;
  posting = true;
  try {
    const captureStarted = Date.now();
    const image = await renderWindow.webContents.capturePage({ x: 0, y: 0, width: 480, height: 480 });
    const captureMs = Date.now() - captureStarted;
    const encodeStarted = Date.now();
    const useRgb565 = usbTransport === "native" && STREAM_FORMAT.startsWith("rgb565-");
    const jpeg = useRgb565 ? null : image.resize({ width: 480, height: 480 }).toJPEG(JPEG_QUALITY);
    const encodeMs = Date.now() - encodeStarted;
    captureMsTotal += captureMs;
    encodeMsTotal += encodeMs;
    if (useRgb565) {
      const result = STREAM_FORMAT === "rgb565-full"
        ? await sendRgb565FullFrame(image)
        : await sendRgb565Tiles(image);
      if (result && result.ok) {
        nativeConsecutiveFailures = 0;
        nativeFrameCount += 1;
        nativeWriteMsTotal += Number(result.writeMs || 0);
        rgb565BytesTotal += Number(result.sentBytes || 0);
        rgb565TileCount += Number(result.sentTiles || 0);
      } else {
        nativeConsecutiveFailures += 1;
        nativeFailedCount += Number(result?.failed || 1);
        if (nativeConsecutiveFailures >= NATIVE_FAILURE_FALLBACK_THRESHOLD) {
          log("[native-stream] falling back to Python transport after repeated RGB565 failures");
          setUsbTransport("python");
        }
      }
    } else if (usbTransport === "native") {
      const sampleDeviceTiming = frameCount % Math.max(1, Math.round(FPS)) === 0;
      const result = await sendNativeFrame(jpeg, sampleDeviceTiming);
      if (result && result.ok) {
        nativeConsecutiveFailures = 0;
        nativeFrameCount += 1;
        nativeWriteMsTotal += Number(result.writeMs || 0);
        if (result.rxMs != null || result.decodeMs != null || result.flushMs != null) {
          deviceTimingSampleCount += 1;
          deviceRxMsTotal += Number(result.rxMs || 0);
          deviceDecodeMsTotal += Number(result.decodeMs || 0);
          deviceFlushMsTotal += Number(result.flushMs || 0);
        }
      } else {
        nativeConsecutiveFailures += 1;
        nativeFailedCount += 1;
        log("[native-stream] frame failed", result);
        if (nativeConsecutiveFailures >= NATIVE_FAILURE_FALLBACK_THRESHOLD) {
          log("[native-stream] falling back to Python transport after repeated native failures");
          setUsbTransport("python");
        }
      }
    } else {
      await postFrame(jpeg);
    }
    frameCount += 1;
    if (now - lastStatsAt >= 5000) {
      const fps = (frameCount * 1000) / (now - lastStatsAt);
      const nativeSuffix = usbTransport === "native"
        ? ` format=${STREAM_FORMAT} native_ok=${nativeFrameCount} native_failed=${nativeFailedCount} native_avg_write_ms=${nativeFrameCount ? (nativeWriteMsTotal / nativeFrameCount).toFixed(1) : "0.0"} rgb565_kb=${nativeFrameCount ? (rgb565BytesTotal / nativeFrameCount / 1024).toFixed(1) : "0.0"} rgb565_tiles=${nativeFrameCount ? (rgb565TileCount / nativeFrameCount).toFixed(1) : "0.0"} device_rx_ms=${deviceTimingSampleCount ? (deviceRxMsTotal / deviceTimingSampleCount).toFixed(1) : "n/a"} device_decode_ms=${deviceTimingSampleCount ? (deviceDecodeMsTotal / deviceTimingSampleCount).toFixed(1) : "n/a"} device_flush_ms=${deviceTimingSampleCount ? (deviceFlushMsTotal / deviceTimingSampleCount).toFixed(1) : "n/a"}`
        : "";
      log(`[electron-stream] transport=${usbTransport} fps=${fps.toFixed(1)} jpeg_kb=${jpeg ? (jpeg.length / 1024).toFixed(1) : "n/a"} capture_ms=${frameCount ? (captureMsTotal / frameCount).toFixed(1) : "0.0"} encode_ms=${frameCount ? (encodeMsTotal / frameCount).toFixed(1) : "0.0"}${nativeSuffix}`);
      frameCount = 0;
      nativeFrameCount = 0;
      nativeFailedCount = 0;
      nativeWriteMsTotal = 0;
      captureMsTotal = 0;
      encodeMsTotal = 0;
      deviceTimingSampleCount = 0;
      deviceRxMsTotal = 0;
      deviceDecodeMsTotal = 0;
      deviceFlushMsTotal = 0;
      rgb565BytesTotal = 0;
      rgb565TileCount = 0;
      lastStatsAt = now;
    }
  } catch (error) {
    log("[electron-stream] capture failed", error.message);
  } finally {
    posting = false;
  }
}

function buildMenu() {
  const backendLabel = `Backend: server ${backendStatus.server}, agent ${backendStatus.agent}, native ${backendStatus.native}`;
  const template = [
    {
      label: "Open AIO",
      submenu: [
        { label: backendLabel, enabled: false },
        { label: backendStatus.message || "Checking backend", enabled: false },
        { label: "Restart Managed Backend", click: restartManagedBackend },
        { label: "Check Native Helper", click: showNativeHelperHealth },
        { label: "Open Logs Folder", click: () => shell.openPath(LOG_DIR) },
        { type: "separator" },
        { label: "Open NZXT-ESC", click: showEditor },
        { label: "Open Status Page", click: () => shell.openExternal(`${SERVER_URL}/cam`) },
        { type: "separator" },
        { label: "Deploy SignalRGB Plugin", click: deploySignalRgbPlugin },
        { label: "Open SignalRGB Plugin Folder", click: () => shell.openPath(SIGNALRGB_PLUGIN_DIR) },
        { type: "separator" },
        { label: streaming ? "Stop Stream" : "Start Stream", click: () => setStreaming(!streaming) },
        {
          label: "USB Transport",
          submenu: Object.entries(USB_TRANSPORTS).map(([id, transport]) => ({
            label: transport.label,
            type: "radio",
            checked: usbTransport === id,
            click: () => setUsbTransport(id),
          })),
        },
        {
          label: "Stream Transform",
          submenu: Object.entries(STREAM_TRANSFORMS).map(([id, transform]) => ({
            label: transform.label,
            type: "radio",
            checked: streamTransform === id,
            click: () => setStreamTransform(id),
          })),
        },
        { type: "separator" },
        { label: "Open Live Preview", click: () => shell.openExternal(LIVE_PREVIEW_URL) },
        { type: "separator" },
        { label: "Quit", click: () => app.quit() },
      ],
    },
  ];
  const menu = Menu.buildFromTemplate(template);
  Menu.setApplicationMenu(menu);
  if (tray) {
    tray.setContextMenu(menu);
  }
}

function trayIcon(color = "#27c560") {
  return fs.existsSync(ICON_PATH) ? ICON_PATH : nativeImage.createFromDataURL(`data:image/png;base64,${ICON_PNG_BASE64}`);
}

function createTray() {
  tray = new Tray(trayIcon());
  tray.setToolTip("Open AIO");
  tray.on("click", showEditor);
  buildMenu();
}

function showEditor() {
  if (!editorWindow) {
    createEditorWindow();
  }
  editorWindow.show();
  editorWindow.focus();
}

function createEditorWindow() {
  editorWindow = new BrowserWindow({
    width: 1280,
    height: 900,
    minWidth: 960,
    minHeight: 720,
    show: false,
    title: "Open AIO - NZXT-ESC",
    icon: trayIcon(),
    backgroundColor: "#111111",
    webPreferences: {
      partition: WEB_PARTITION,
      contextIsolation: true,
      nodeIntegration: false,
      backgroundThrottling: false,
    },
  });

  editorWindow.loadURL(EDITOR_URL);
  editorWindow.on("close", (event) => {
    if (!app.isQuitting) {
      event.preventDefault();
      editorWindow.hide();
    }
  });
  editorWindow.webContents.on("did-finish-load", () => {
    editorWindow.webContents.executeJavaScript(`
      (() => {
        window.__coolerElectron = true;
        localStorage.setItem('cooler-display:electron', '1');
      })();
    `).catch(() => {});
    schedulePresetThumbnailRefresh();
  });
  editorWindow.webContents.on("console-message", (_event, level, message) => {
    if (level >= 2) log("[editor]", message);
  });
}

function wait(ms) {
  return new Promise((resolve) => setTimeout(resolve, ms));
}

function loadURL(window, url) {
  return new Promise((resolve) => {
    const done = () => {
      window.webContents.off("did-fail-load", done);
      resolve();
    };
    window.webContents.once("did-finish-load", done);
    window.webContents.once("did-fail-load", done);
    window.loadURL(url);
  });
}

async function readPresetPreviewTargets() {
  if (!editorWindow || editorWindow.isDestroyed()) return [];
  return editorWindow.webContents.executeJavaScript(`
    (() => {
      const prefix = 'nzxt-esc-dev:';
      const raw = localStorage.getItem(prefix + 'presets');
      if (!raw) return [];
      const presets = JSON.parse(raw);
      const order = JSON.parse(localStorage.getItem(prefix + 'presetOrder') || '[]');
      const ids = Array.isArray(order) && order.length ? order : Object.keys(presets || {});
      let changed = false;
      const targets = [];
      for (const id of ids) {
        const preset = presets && presets[id];
        if (!preset || typeof preset !== 'object') continue;
        if (!preset.previewImageId) {
          preset.previewImageId = 'preview_' + Date.now() + '_' + Math.random().toString(36).slice(2, 9);
          changed = true;
        }
        targets.push({ id, name: preset.name || id, previewImageId: preset.previewImageId });
      }
      if (changed) {
        localStorage.setItem(prefix + 'presets', JSON.stringify(presets));
        window.__coolerSyncDesignerStorage?.();
      }
      return targets;
    })();
  `);
}

async function storePresetPreview(mediaId, dataUrl) {
  if (!editorWindow || editorWindow.isDestroyed()) return;
  try {
    const response = await fetch(`${SERVER_URL}/api/designer/preset-previews`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ items: { [mediaId]: dataUrl } }),
    });
    if (!response.ok) {
      log("[preset-thumbnails] server preview upload failed", mediaId, response.status, await response.text());
    }
  } catch (error) {
    log("[preset-thumbnails] server preview upload error", mediaId, error.message);
  }
  await editorWindow.webContents.executeJavaScript(`
    (async () => {
      const mediaId = ${JSON.stringify(mediaId)};
      const dataUrl = ${JSON.stringify(dataUrl)};
      const blob = await fetch(dataUrl).then((response) => response.blob());
      const db = await new Promise((resolve, reject) => {
        const request = indexedDB.open('nzxt-esc-dev', 1);
        request.onupgradeneeded = () => {
          const db = request.result;
          if (!db.objectStoreNames.contains('localMedia')) {
            db.createObjectStore('localMedia', { keyPath: 'mediaId' }).createIndex('createdAt', 'createdAt', { unique: false });
          }
        };
        request.onsuccess = () => resolve(request.result);
        request.onerror = () => reject(request.error || new Error('preview database open failed'));
      });
      await new Promise((resolve, reject) => {
        const request = db.transaction(['localMedia'], 'readwrite').objectStore('localMedia').put({
          mediaId,
          blob,
          fileName: 'preview.png',
          fileType: 'image/png',
          fileSize: blob.size,
          createdAt: Date.now(),
        });
        request.onsuccess = () => resolve();
        request.onerror = () => reject(request.error || new Error('preview database write failed'));
      });
      db.close();
      window.dispatchEvent(new Event('presetPreviewImagesRepaired'));
      window.dispatchEvent(new Event('designerStorageSynced'));
    })();
  `);
}

async function refreshPresetThumbnails() {
  if (thumbnailRunning || !editorWindow || editorWindow.isDestroyed()) return;
  if (streaming) {
    log("[preset-thumbnails] skipped while streaming");
    return;
  }
  thumbnailRunning = true;
  let thumbnailWindow = null;
  try {
    const targets = await readPresetPreviewTargets();
    if (!Array.isArray(targets) || !targets.length) return;
    log("[preset-thumbnails] refreshing rendered previews", { count: targets.length });
    thumbnailWindow = new BrowserWindow({
      width: 480,
      height: 480,
      show: false,
      frame: false,
      resizable: false,
      useContentSize: true,
      webPreferences: {
        partition: WEB_PARTITION,
        contextIsolation: true,
        nodeIntegration: false,
        backgroundThrottling: false,
      },
    });
    thumbnailWindow.webContents.on("console-message", (_event, level, message) => {
      if (level >= 2) log("[preset-thumbnail-render]", message);
    });
    for (const target of targets) {
      if (streaming) break;
      if (!target || !target.id || !target.previewImageId) continue;
      const url = `${SERVER_URL}/nzxt-esc/?kraken=1&mockLcd=480&mockShape=circle&streamRenderer=1&presetId=${encodeURIComponent(target.id)}&thumbnail=1&_=${Date.now()}`;
      await loadURL(thumbnailWindow, url);
      await wait(1200);
      const image = await thumbnailWindow.webContents.capturePage({ x: 0, y: 0, width: 480, height: 480 });
      const dataUrl = image.resize({ width: 256, height: 256 }).toDataURL();
      await storePresetPreview(target.previewImageId, dataUrl);
    }
    log("[preset-thumbnails] refreshed rendered previews", { count: targets.length });
  } catch (error) {
    log("[preset-thumbnails] refresh failed", error);
  } finally {
    if (thumbnailWindow && !thumbnailWindow.isDestroyed()) thumbnailWindow.destroy();
    thumbnailRunning = false;
  }
}

function schedulePresetThumbnailRefresh(delay = 1500) {
  if (thumbnailTimer) clearTimeout(thumbnailTimer);
  thumbnailTimer = setTimeout(() => {
    thumbnailTimer = null;
    refreshPresetThumbnails();
  }, delay);
}

function createRenderWindow() {
  renderReady = false;
  renderWindow = new BrowserWindow({
    width: 480,
    height: 480,
    show: false,
    frame: false,
    resizable: false,
    icon: trayIcon(),
    useContentSize: true,
    webPreferences: {
      partition: WEB_PARTITION,
      contextIsolation: true,
      nodeIntegration: false,
      backgroundThrottling: false,
    offscreen: false,
    },
  });

  renderWindow.webContents.on("did-finish-load", () => {
    renderReady = true;
    log("[electron-stream] render window loaded", RENDER_URL);
    streamTransformCssKey = null;
    renderWindow.webContents.executeJavaScript(`
      (() => {
        window.__coolerElectronRenderer = true;
        localStorage.setItem('cooler-display:electron-renderer', '1');
      })();
    `).catch(() => {});
    applyStreamTransform().catch((error) => log("[electron-stream] transform failed", error.message));
  });
  renderWindow.webContents.on("did-fail-load", (_event, code, description, url) => {
    renderReady = false;
    log("[electron-stream] render load failed", code, description, url);
  });
  renderWindow.webContents.on("console-message", (_event, level, message) => {
    if (message.includes("[open-aio-monitoring]") || level >= 2) {
      log("[electron-render]", message);
    }
  });
  renderWindow.loadURL(RENDER_URL);
}

function setStreaming(active) {
  streaming = active;
  buildMenu();
  postPreviewActive(active);
  if (active && thumbnailTimer) {
    clearTimeout(thumbnailTimer);
    thumbnailTimer = null;
  }
  if (heartbeatTimer) {
    clearInterval(heartbeatTimer);
    heartbeatTimer = null;
  }
  if (captureTimer) {
    clearInterval(captureTimer);
    captureTimer = null;
  }
  if (active) {
    if (usbTransport === "native") {
      writeDirectUsbOwner(true);
    }
    if (!renderWindow || renderWindow.isDestroyed()) {
      createRenderWindow();
    } else {
      renderReady = false;
      renderWindow.reload();
    }
    heartbeatTimer = setInterval(() => postPreviewActive(true), 1000);
    const captureDelay = usbTransport === "native" ? 1200 : 0;
    setTimeout(() => {
      if (streaming && !captureTimer) {
        captureTimer = setInterval(captureAndPostFrame, Math.max(16, Math.floor(1000 / FPS)));
      }
    }, captureDelay);
    log("[electron-stream] streaming started", { FPS, JPEG_QUALITY, RENDER_URL });
  } else {
    stopNativeStream();
    writeDirectUsbOwner(false);
    log("[electron-stream] streaming stopped");
  }
}

app.commandLine.appendSwitch("disable-background-timer-throttling");
app.commandLine.appendSwitch("disable-renderer-backgrounding");
app.commandLine.appendSwitch("autoplay-policy", "no-user-gesture-required");

const gotLock = app.requestSingleInstanceLock();
if (!gotLock) {
  app.quit();
} else {
  app.on("second-instance", showEditor);
  app.whenReady().then(async () => {
    if (process.platform === "win32") {
      app.setAppUserModelId("com.open-aio.desktop");
    }
    loadSettings();
    writeDirectUsbOwner(usbTransport === "native");
    createTray();
    await ensureBackend();
    backendTimer = setInterval(refreshBackendStatus, 5000);
    installRequestLogging();
    createEditorWindow();
    showEditor();
    setStreaming(true);
  });
}

app.on("before-quit", () => {
  app.isQuitting = true;
  stopNativeStream();
  writeDirectUsbOwner(false);
  streaming = false;
  if (backendTimer) {
    clearInterval(backendTimer);
    backendTimer = null;
  }
  postPreviewActive(false);
  if (managedAgent) {
    managedAgent.kill();
    managedAgent = null;
  }
  if (managedServer) {
    managedServer.kill();
    managedServer = null;
  }
});

app.on("window-all-closed", (event) => {
  event.preventDefault();
});
