(function () {
  const params = new URLSearchParams(window.location.search);
  if (params.get("streamRenderer") === "1") {
    return;
  }
  if (params.get("kraken") === "1" && !params.get("presetId")) {
      fetch("/api/designer/storage", { cache: "no-store" })
        .then((response) => response.ok ? response.json() : null)
        .then((payload) => {
          const items = payload?.items;
          const activePresetId = items?.["nzxt-esc-dev:activePresetId"];
          if (!items || !activePresetId) return;
          for (const [key, value] of Object.entries(items)) {
            if (String(key).startsWith("nzxt-esc-dev:")) {
              window.localStorage.setItem(key, String(value || ""));
            }
          }
          const next = new URL(window.location.href);
          next.searchParams.set("mockLcd", "480");
          next.searchParams.set("mockShape", "circle");
          next.searchParams.set("presetId", String(activePresetId));
          window.location.replace(next.toString());
        })
        .catch(() => {});
    return;
  }

  if (window.__coolerDisplaySyncVersion === "stream-sync-v6") {
    return;
  }
  window.__coolerDisplaySyncVersion = "stream-sync-v6";

  if (!window.__coolerFastAutosaveTimers) {
    window.__coolerFastAutosaveTimers = true;
    const originalSetTimeout = window.setTimeout.bind(window);
    window.setTimeout = (callback, delay, ...args) => {
      const nextDelay = delay === 500 || delay === 700 ? 50 : delay;
      return originalSetTimeout(callback, nextDelay, ...args);
    };
  }

  const prefix = "nzxt-esc-dev:";
  let timer = 0;
  let lastPayload = "";
  let lastActivePresetId = "";
  let activeEditUntil = 0;
  let latestMonitoring = null;
  let previewRepairTimer = 0;
  let previewRepairRunning = false;
  const monitoringSubscribers = new Set();

  window.nzxt = window.nzxt || {};
  window.nzxt.v1 = {
    ...(window.nzxt.v1 || {}),
    width: 480,
    height: 480,
    shape: "circle",
    targetFps: 24,
    getLCDSize: () => ({ width: 480, height: 480, shape: "circle" }),
    onMonitoringDataUpdate: (callback) => {
      if (typeof callback !== "function") return () => {};
      monitoringSubscribers.add(callback);
      if (latestMonitoring) {
        try {
          callback(latestMonitoring);
        } catch {}
      }
      return () => monitoringSubscribers.delete(callback);
    },
    getMonitoringData: () => latestMonitoring,
  };

  async function pollMonitoring() {
    try {
      const response = await fetch("/api/nzxt/v1/monitoring", { cache: "no-store" });
      if (!response.ok) return;
      const payload = await response.json();
      const data = payload && typeof payload.data === "object" ? payload.data : payload;
      latestMonitoring = data;
      for (const callback of monitoringSubscribers) {
        try {
          callback(data);
        } catch {}
      }
      window.dispatchEvent(new CustomEvent("nzxtMonitoringData", { detail: data }));
    } catch {}
  }

  function mediaUrl(media) {
    if (!media || typeof media !== "object" || !media.mediaId) return null;
    const fileName = encodeURIComponent(String(media.fileName || "media.bin"));
    return `/api/designer/gallery-media/${encodeURIComponent(String(media.mediaId))}/${fileName}`;
  }

  function readJson(key, fallback) {
    try {
      const raw = window.localStorage.getItem(key);
      return raw ? JSON.parse(raw) : fallback;
    } catch {
      return fallback;
    }
  }

  function metricName(value) {
    const map = {
      cpuTemp: "cpu_temp",
      cpuLoad: "cpu_load",
      cpuClock: "cpu_frequency",
      cpuPower: "cpu_power",
      gpuTemp: "gpu_temp",
      gpuLoad: "gpu_load",
      gpuClock: "gpu_frequency",
      gpuPower: "gpu_power",
      gpuFan: "gpu_fan_speed",
      gpuFanSpeed: "gpu_fan_speed",
      liquidTemp: "liquid_temp",
      ramUsage: "ram_usage",
      ramTotal: "ram_total",
      ssdTemp: "ssd_temp",
    };
    return map[value] || value || "cpu_temp";
  }

  function sourceMetricName(value) {
    return metricName(value);
  }

  function pxToNorm(value) {
    const n = Number(value);
    return Number.isFinite(n) ? Math.max(-2, Math.min(2, n / 250)) : 0;
  }

  function elementConfig(element) {
    const data = element && typeof element.data === "object" ? element.data : {};
    if (element.type === "text") {
      return {
        content: String(data.text ?? "Text"),
        color: String(data.textColor || data.color || "#FFFFFF"),
        fontSize: Number(data.textSize || data.fontSize || 24),
        fontFamily: data.fontFamily || "default-extrabold",
      };
    }
    if (element.type === "metric") {
      return {
        metricType: metricName(data.metric),
        color: String(data.numberColor || data.textColor || data.color || "#FFFFFF"),
        fontSize: Number(data.numberSize || data.textSize || data.fontSize || 50),
        fontFamily: data.fontFamily || "default-extrabold",
        gpuIndex: data.gpuIndex ?? "auto",
        temperatureUnit: data.temperatureUnit || "C",
        temperatureFormat: data.temperatureFormat || "int_deg",
        loadFormat: data.loadFormat || "int_percent_suffix",
        frequencyFormat: data.frequencyFormat || "int",
        powerFormat: data.powerFormat || "int_unit_short",
        fanSpeedFormat: data.fanSpeedFormat || "int_unit_caps",
      };
    }
    if (element.type === "linear_graphic") {
      return {
        sourceMetric: sourceMetricName(data.sourceMetric),
        width: Number(data.width || 100),
        height: Number(data.height || 12),
        radius: Number(data.radius || 0),
        fillColor: String(data.fillColor || "#FFFFFF"),
        outlineColor: String(data.outlineColor || "#000000"),
        outlineWidth: Number(data.outlineWidth || 0),
        gpuIndex: data.gpuIndex ?? "auto",
      };
    }
    if (element.type === "arc_graphic") {
      return {
        sourceMetric: sourceMetricName(data.sourceMetric),
        strokeWidth: Number(data.strokeWidth || 20),
        totalAngle: Number(data.totalAngle || 270),
        size: Number(data.size || 120),
        strokeColor: String(data.strokeColor || data.fillColor || "#FFFFFF"),
        trackEnabled: data.trackEnabled !== false,
        trackColor: String(data.trackColor || "rgba(255, 255, 255, 0.18)"),
        hotspotColor: String(data.hotspotColor || data.pointerColor || "#FFFFFF"),
        gpuIndex: data.gpuIndex ?? "auto",
      };
    }
    if (element.type === "shape") {
      return {
        width: Number(data.width || 100),
        height: Number(data.height || 100),
        radius: Number(data.radius || 0),
        fillColor: String(data.fillColor || "#FFFFFF"),
        borderColor: String(data.borderColor || "#000000"),
        borderWidth: Number(data.borderWidth || 0),
      };
    }
    return data;
  }

  function convertLegacyElement(element, index) {
    if (!element || typeof element !== "object" || !element.type) return null;
    const supported = new Set(["text", "metric", "linear_graphic", "arc_graphic", "shape", "clock", "date"]);
    if (!supported.has(element.type)) return null;
    return {
      id: String(element.id || `live-${Date.now()}-${index}`),
      elementType: String(element.type),
      typeSeq: Number(element.zIndex || index + 1),
      transform: {
        x: pxToNorm(element.x),
        y: pxToNorm(element.y),
        rotateDeg: Number(element.angle || 0),
      },
      config: elementConfig(element),
      isLocked: false,
    };
  }

  function mirrorRuntimeOverlayToPreset(presetId, runtimeElements) {
    if (!presetId || !Array.isArray(runtimeElements)) return false;
    const raw = window.localStorage.getItem(`${prefix}presets`);
    if (!raw) return false;
    let presets;
    try {
      presets = JSON.parse(raw);
    } catch {
      return false;
    }
    if (!presets || typeof presets !== "object") return false;

    const preset = presets[presetId];
    if (!preset || typeof preset !== "object") return false;
    const converted = runtimeElements.map(convertLegacyElement).filter(Boolean);
    const previous = JSON.stringify(preset.overlay || null);
    preset.overlay = {
      ...(preset.overlay && typeof preset.overlay === "object" ? preset.overlay : {}),
      enabled: converted.length > 0,
      elements: converted,
    };
    const nextOverlay = JSON.stringify(preset.overlay || null);
    if (previous === nextOverlay) return false;

    const previousRaw = raw;
    const nextRaw = JSON.stringify(presets);
    window.localStorage.setItem(`${prefix}presets`, nextRaw);
    window.localStorage.setItem(`${prefix}activePresetId`, presetId);
    window.localStorage.setItem("nzxtActivePresetId", presetId);
    mirrorRuntimeOverlayToNzxtPresets(presetId, runtimeElements);
    window.dispatchEvent(new StorageEvent("storage", {
      key: `${prefix}presets`,
      oldValue: previousRaw,
      newValue: nextRaw,
      storageArea: window.localStorage,
    }));
    window.dispatchEvent(new Event("designerStorageSynced"));
    lastPayload = "";
    syncNow();
    syncSoon([0, 35, 90, 180]);
    return true;
  }

  function cloneRuntimeElement(element, index) {
    if (!element || typeof element !== "object") return null;
    const type = String(element.type || element.elementType || "");
    if (!type) return null;
    return {
      id: String(element.id || `runtime-${Date.now()}-${index}`),
      type,
      x: Number(element.x || 0),
      y: Number(element.y || 0),
      angle: Number(element.angle || 0),
      zIndex: Number(element.zIndex ?? index),
      data: element.data && typeof element.data === "object" ? { ...element.data } : {},
    };
  }

  function mirrorRuntimeOverlayToNzxtPresets(presetId, runtimeElements) {
    if (!presetId || !Array.isArray(runtimeElements)) return false;
    const raw = window.localStorage.getItem("nzxtPresets");
    if (!raw) return false;
    let presets;
    try {
      presets = JSON.parse(raw);
    } catch {
      return false;
    }
    if (!Array.isArray(presets)) return false;
    const index = presets.findIndex((entry) => entry && entry.id === presetId);
    if (index < 0) return false;
    const entry = { ...presets[index] };
    const preset = { ...(entry.preset || {}) };
    const elements = runtimeElements.map(cloneRuntimeElement).filter(Boolean);
    const zOrder = [...elements].sort((a, b) => Number(a.zIndex || 0) - Number(b.zIndex || 0)).map((element) => element.id);
    const previous = JSON.stringify(preset.overlay || null);
    preset.overlay = {
      ...(preset.overlay && typeof preset.overlay === "object" ? preset.overlay : {}),
      mode: elements.length ? "custom" : "none",
      elements,
      zOrder,
    };
    if (previous === JSON.stringify(preset.overlay || null)) return false;
    entry.preset = preset;
    entry.updatedAt = new Date().toISOString();
    presets[index] = entry;
    const nextRaw = JSON.stringify(presets);
    window.localStorage.setItem("nzxtPresets", nextRaw);
    window.localStorage.setItem("nzxtActivePresetId", presetId);
    window.dispatchEvent(new StorageEvent("storage", {
      key: "nzxtPresets",
      oldValue: raw,
      newValue: nextRaw,
      storageArea: window.localStorage,
    }));
    window.dispatchEvent(new StorageEvent("storage", {
      key: "nzxtActivePresetId",
      oldValue: null,
      newValue: presetId,
      storageArea: window.localStorage,
    }));
    return true;
  }

  function mirrorVnextOverlayStateToPreset(presetId, state) {
    if (!presetId || !state || typeof state !== "object") return false;
    const source = state.elements;
    let elements = [];
    if (Array.isArray(source)) {
      elements = source;
    } else if (source && typeof source === "object") {
      elements = Object.values(source);
    }
    if (!elements.length && Array.isArray(state.zOrder) && source && typeof source === "object") {
      elements = state.zOrder.map((id) => source[id]).filter(Boolean);
    }
    const ordered = [...elements].sort((a, b) => {
      const az = Number(a?.zIndex ?? 0);
      const bz = Number(b?.zIndex ?? 0);
      return az - bz;
    });
    return mirrorRuntimeOverlayToPreset(presetId, ordered);
  }

  function convertLegacyPreset(entry, activeId) {
    if (!entry || typeof entry !== "object" || !entry.preset) return null;
    const preset = entry.preset;
    const background = preset.background || {};
    const settings = background.settings || {};
    const url = background.url || background.source?.url || "";
    const elements = Array.isArray(preset.overlay?.elements) ? preset.overlay.elements : [];
    const converted = elements.map(convertLegacyElement).filter(Boolean);
    const next = {
      id: activeId,
      name: String(entry.name || preset.presetName || "Preset"),
      background: {
        base: {
          sourceType: "color",
          color: String(settings.backgroundColor || "#000000"),
        },
      },
      overlay: {
        enabled: (preset.overlay?.mode || "none") !== "none",
        elements: converted,
      },
    };
    if (url) {
      next.background.mediaOverlay = {
        kind: "media-overlay",
        source: "url",
        media: { type: "url", url: String(url) },
        transform: {
          scale: 1,
          autoScale: Number(settings.scale || 1),
          offsetX: Number(settings.x || 0),
          offsetY: Number(settings.y || 0),
          rotateDeg: 0,
        },
      };
    }
    return next;
  }

  function bridgeLegacyPresetState() {
    const activeId = window.localStorage.getItem(`${prefix}activePresetId`) || window.localStorage.getItem("nzxtActivePresetId");
    if (!activeId) return false;
    const legacyPresets = readJson("nzxtPresets", []);
    if (!Array.isArray(legacyPresets)) return false;
    const entry = legacyPresets.find((item) => item && item.id === activeId);
    const converted = convertLegacyPreset(entry, activeId);
    if (!converted) return false;

    const presets = readJson(`${prefix}presets`, {});
    if (!presets || typeof presets !== "object") return false;
    const previous = JSON.stringify(presets[activeId] || null);
    const nextValue = JSON.stringify(converted);
    if (previous === nextValue) return false;
    presets[activeId] = converted;
    window.localStorage.setItem(`${prefix}presets`, JSON.stringify(presets));

    const order = readJson(`${prefix}presetOrder`, []);
    if (Array.isArray(order) && !order.includes(activeId)) {
      order.push(activeId);
      window.localStorage.setItem(`${prefix}presetOrder`, JSON.stringify(order));
    }
    window.localStorage.setItem(`${prefix}activePresetId`, activeId);
    window.localStorage.setItem("nzxtActivePresetId", activeId);
    return true;
  }

  function normalizePresets() {
    const raw = window.localStorage.getItem(`${prefix}presets`);
    if (!raw) return false;
    let presets;
    try {
      presets = JSON.parse(raw);
    } catch {
      return false;
    }
    if (!presets || typeof presets !== "object") return false;

    let changed = false;
    for (const preset of Object.values(presets)) {
      const overlay = preset?.background?.mediaOverlay;
      const media = overlay?.media;
      if (overlay?.source !== "local" || media?.type !== "local") continue;
      const url = mediaUrl(media);
      if (!url) continue;
      overlay.source = "url";
      overlay.media = {
        type: "url",
        url,
        ...(media.intrinsic && typeof media.intrinsic === "object" ? { intrinsic: media.intrinsic } : {}),
      };
      changed = true;
    }
    if (!changed) return false;

    const next = JSON.stringify(presets);
    const previous = raw;
    window.localStorage.setItem(`${prefix}presets`, next);
    window.dispatchEvent(new StorageEvent("storage", {
      key: `${prefix}presets`,
      oldValue: previous,
      newValue: next,
      storageArea: window.localStorage,
    }));
    window.dispatchEvent(new Event("designerStorageSynced"));
    return true;
  }

  function openPreviewDatabase() {
    return new Promise((resolve, reject) => {
      if (typeof indexedDB === "undefined") {
        reject(new Error("IndexedDB is not available"));
        return;
      }
      const request = indexedDB.open("nzxt-esc-dev", 1);
      request.onupgradeneeded = () => {
        const db = request.result;
        if (!db.objectStoreNames.contains("localMedia")) {
          db.createObjectStore("localMedia", { keyPath: "mediaId" }).createIndex("createdAt", "createdAt", { unique: false });
        }
      };
      request.onsuccess = () => resolve(request.result);
      request.onerror = () => reject(request.error || new Error("Failed to open preview database"));
    });
  }

  function getPreviewRecord(db, mediaId) {
    return new Promise((resolve, reject) => {
      const request = db.transaction(["localMedia"], "readonly").objectStore("localMedia").get(mediaId);
      request.onsuccess = () => resolve(request.result || null);
      request.onerror = () => reject(request.error || new Error("Failed to read preview"));
    });
  }

  function putPreviewRecord(db, record) {
    return new Promise((resolve, reject) => {
      const request = db.transaction(["localMedia"], "readwrite").objectStore("localMedia").put(record);
      request.onsuccess = () => resolve();
      request.onerror = () => reject(request.error || new Error("Failed to write preview"));
    });
  }

  function canvasToBlob(canvas) {
    return new Promise((resolve) => {
      canvas.toBlob((blob) => resolve(blob), "image/png");
    });
  }

  async function hydrateServerPresetPreviews(db) {
    try {
      const response = await fetch("/api/designer/preset-previews", { cache: "no-store" });
      if (!response.ok) return 0;
      const payload = await response.json();
      const items = payload?.items;
      if (!items || typeof items !== "object") return 0;
      let count = 0;
      for (const [mediaId, dataUrl] of Object.entries(items)) {
        if (!mediaId || typeof dataUrl !== "string" || !dataUrl.startsWith("data:image/")) continue;
        const blob = await fetch(dataUrl).then((item) => item.blob());
        await putPreviewRecord(db, {
          mediaId,
          blob,
          fileName: "preview.png",
          fileType: blob.type || "image/png",
          fileSize: blob.size,
          createdAt: Date.now(),
        });
        count += 1;
      }
      return count;
    } catch {
      return 0;
    }
  }

  async function createFallbackPreviewBlob(preset) {
    const canvas = document.createElement("canvas");
    canvas.width = 256;
    canvas.height = 256;
    const ctx = canvas.getContext("2d");
    if (!ctx) return null;
    const baseColor = preset?.background?.base?.color || "#101820";
    const name = String(preset?.name || "Preset").slice(0, 24);
    ctx.fillStyle = "#05070a";
    ctx.fillRect(0, 0, canvas.width, canvas.height);
    ctx.beginPath();
    ctx.arc(128, 128, 123, 0, Math.PI * 2);
    ctx.clip();
    ctx.fillStyle = baseColor;
    ctx.fillRect(0, 0, canvas.width, canvas.height);
    const gradient = ctx.createLinearGradient(0, 0, 256, 256);
    gradient.addColorStop(0, "rgba(0, 220, 255, 0.38)");
    gradient.addColorStop(0.48, "rgba(255, 255, 255, 0.08)");
    gradient.addColorStop(1, "rgba(255, 70, 160, 0.32)");
    ctx.fillStyle = gradient;
    ctx.fillRect(0, 0, 256, 256);
    ctx.strokeStyle = "rgba(255, 255, 255, 0.32)";
    ctx.lineWidth = 5;
    ctx.stroke();
    ctx.fillStyle = "rgba(0, 0, 0, 0.35)";
    ctx.fillRect(20, 94, 216, 68);
    ctx.fillStyle = "#ffffff";
    ctx.font = "700 24px system-ui, -apple-system, Segoe UI, sans-serif";
    ctx.textAlign = "center";
    ctx.textBaseline = "middle";
    const words = name.split(/\s+/).filter(Boolean);
    const lines = words.length > 1 ? [words.slice(0, Math.ceil(words.length / 2)).join(" "), words.slice(Math.ceil(words.length / 2)).join(" ")] : [name];
    lines.slice(0, 2).forEach((line, index) => ctx.fillText(line, 128, lines.length === 1 ? 128 : 116 + index * 28, 196));
    return canvasToBlob(canvas);
  }

  async function repairMissingPreviewImages() {
    if (previewRepairRunning) return;
    previewRepairRunning = true;
    let db = null;
    try {
      const raw = window.localStorage.getItem(`${prefix}presets`);
      if (!raw) return;
      const presets = JSON.parse(raw);
      if (!presets || typeof presets !== "object") return;
      db = await openPreviewDatabase();
      const hydratedCount = await hydrateServerPresetPreviews(db);
      let changed = false;
      for (const [presetId, preset] of Object.entries(presets)) {
        if (!preset || typeof preset !== "object") continue;
        let previewImageId = typeof preset.previewImageId === "string" && preset.previewImageId ? preset.previewImageId : "";
        if (previewImageId) {
          const existing = await getPreviewRecord(db, previewImageId).catch(() => null);
          if (existing) continue;
        } else {
          previewImageId = `preview_${Date.now()}_${Math.random().toString(36).slice(2, 9)}`;
          preset.previewImageId = previewImageId;
          changed = true;
        }
        const blob = await createFallbackPreviewBlob(preset);
        if (!blob) continue;
        await putPreviewRecord(db, {
          mediaId: previewImageId,
          blob,
          fileName: "preview.png",
          fileType: "image/png",
          fileSize: blob.size,
          createdAt: Date.now(),
        });
      }
      if (changed) {
        window.localStorage.setItem(`${prefix}presets`, JSON.stringify(presets));
        window.dispatchEvent(new StorageEvent("storage", {
          key: `${prefix}presets`,
          oldValue: raw,
          newValue: JSON.stringify(presets),
          storageArea: window.localStorage,
        }));
      }
      if (hydratedCount || changed) window.dispatchEvent(new Event("presetPreviewImagesRepaired"));
    } catch (error) {
      console.warn("Preset preview repair failed", error);
    } finally {
      try {
        db?.close();
      } catch {}
      previewRepairRunning = false;
    }
  }

  function schedulePreviewRepair(delay = 250) {
    if (previewRepairTimer) window.clearTimeout(previewRepairTimer);
    previewRepairTimer = window.setTimeout(() => {
      previewRepairTimer = 0;
      repairMissingPreviewImages();
    }, delay);
  }

  function snapshot() {
    bridgeLegacyPresetState();
    normalizePresets();
    const items = {};
    for (let index = 0; index < window.localStorage.length; index += 1) {
      const key = window.localStorage.key(index);
      if (key && key.startsWith(prefix)) {
        items[key] = window.localStorage.getItem(key) || "";
      }
    }
    return items;
  }

  function hasPresetState(items) {
    return !!(items && items[`${prefix}presets`] && items[`${prefix}activePresetId`]);
  }

  function applySnapshot(items) {
    if (!hasPresetState(items)) return false;
    let changed = false;
    for (const [key, value] of Object.entries(items)) {
      if (!String(key).startsWith(prefix)) continue;
      const nextValue = String(value || "");
      const oldValue = window.localStorage.getItem(key);
      if (oldValue === nextValue) continue;
      window.localStorage.setItem(key, nextValue);
      window.dispatchEvent(new StorageEvent("storage", {
        key,
        oldValue,
        newValue: nextValue,
        storageArea: window.localStorage,
      }));
      changed = true;
    }
    if (changed) window.dispatchEvent(new Event("designerStorageSynced"));
    return changed;
  }

  function hydrateFromServer() {
    if (hasPresetState(snapshot())) return;
    fetch("/api/designer/storage")
      .then((response) => response.ok ? response.json() : null)
      .then((payload) => {
        if (!payload || !payload.items) return;
        applySnapshot(payload.items);
      })
      .catch(() => {});
  }

  function syncNow() {
    timer = 0;
    const items = snapshot();
    if (!hasPresetState(items)) {
      hydrateFromServer();
      return;
    }
    const payload = JSON.stringify({ items });
    if (payload === lastPayload) return;
    lastPayload = payload;
    fetch("/api/designer/storage", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: payload,
    }).catch(() => {});
  }

  function syncActiveIfChanged() {
    const active = window.localStorage.getItem(`${prefix}activePresetId`) || "";
    if (!active || active === lastActivePresetId) return;
    lastActivePresetId = active;
    lastPayload = "";
    syncNow();
  }

  function scheduleSync() {
    if (timer) window.clearTimeout(timer);
    timer = window.setTimeout(syncNow, 35);
  }

  function syncSoon(delays) {
    for (const delay of delays) {
      window.setTimeout(() => {
        lastPayload = "";
        syncNow();
      }, delay);
    }
  }

  function markEditorActivity(event) {
    const target = event && event.target;
    const isPointerMove = event && event.type === "pointermove";
    if (isPointerMove && event.buttons !== 1) return;
    if (target && target.closest && target.closest("input, textarea, select, button, [contenteditable='true'], .overlay-preview, .overlay-options-area, [data-element-id]")) {
      activeEditUntil = Date.now() + 1800;
      scheduleSync();
    }
  }

  function endEditorActivity() {
    activeEditUntil = Date.now() + 1200;
    syncSoon([0, 35, 90, 180, 360]);
  }

  const storagePrototype = Object.getPrototypeOf(window.localStorage);
  const originalSetItem = storagePrototype.setItem;
  storagePrototype.setItem = function (key, value) {
    const result = originalSetItem.call(this, key, value);
      if (String(key).startsWith(prefix)) {
        if (String(key) === `${prefix}presets`) normalizePresets();
        if (String(key) === `${prefix}presets`) schedulePreviewRepair();
        scheduleSync();
      }
    return result;
  };

  const originalRemoveItem = storagePrototype.removeItem;
  storagePrototype.removeItem = function (key) {
    const result = originalRemoveItem.call(this, key);
    if (String(key).startsWith(prefix)) scheduleSync();
    return result;
  };

  window.addEventListener("storage", (event) => {
    if (event.key === "nzxt-esc-v2:sync:activePreset") {
      syncActiveIfChanged();
      return;
    }
    scheduleSync();
  });
  window.addEventListener("pointerdown", markEditorActivity, true);
  window.addEventListener("pointermove", markEditorActivity, true);
  window.addEventListener("pointerup", endEditorActivity, true);
  window.addEventListener("mouseup", endEditorActivity, true);
  window.addEventListener("keyup", endEditorActivity, true);
  window.addEventListener("input", endEditorActivity, true);
  window.addEventListener("change", endEditorActivity, true);
  window.addEventListener("click", endEditorActivity, true);
  window.addEventListener("beforeunload", syncNow);
  if (typeof BroadcastChannel !== "undefined") {
    try {
      const channel = new BroadcastChannel("nzxt-esc-v2:sync");
      channel.onmessage = (event) => {
        if (event.data?.type === "activePreset") {
          syncActiveIfChanged();
        }
      };
    } catch {}
    try {
      const runtimeChannel = new BroadcastChannel("nzxtesc_overlay_runtime");
      runtimeChannel.onmessage = (event) => {
        const message = event.data || {};
        if (message.type !== "runtime_update" || !message.presetId || !Array.isArray(message.elements)) return;
        activeEditUntil = Date.now() + 1800;
        mirrorRuntimeOverlayToPreset(String(message.presetId), message.elements);
      };
    } catch {}
    try {
      const runtimeVnextChannel = new BroadcastChannel("nzxtesc_overlay_runtime_vnext");
      runtimeVnextChannel.onmessage = (event) => {
        const message = event.data || {};
        if (
          message.type !== "state-update" &&
          message.type !== "state-sync-response"
        ) {
          return;
        }
        const state = message.state;
        const presetId = state?.meta?.presetId ||
          window.localStorage.getItem(`${prefix}activePresetId`) ||
          window.localStorage.getItem("nzxtActivePresetId");
        if (!presetId) return;
        activeEditUntil = Date.now() + 1800;
        mirrorVnextOverlayStateToPreset(String(presetId), state);
      };
    } catch {}
  }
  window.__coolerSyncDesignerStorage = () => {
    lastPayload = "";
    syncNow();
  };
  window.setTimeout(hydrateFromServer, 0);
  window.setTimeout(pollMonitoring, 0);
  window.setTimeout(() => schedulePreviewRepair(0), 250);
  window.setTimeout(syncNow, 500);
  window.setInterval(() => {
    if (Date.now() < activeEditUntil) {
      lastPayload = "";
      syncNow();
    } else {
      syncNow();
    }
  }, 75);
  window.setInterval(syncActiveIfChanged, 100);
  window.setInterval(pollMonitoring, 1000);
})();
