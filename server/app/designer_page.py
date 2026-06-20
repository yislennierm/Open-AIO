from __future__ import annotations


def designer_html() -> str:
    return r"""
<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>Open AIO Designer</title>
  <style>
    :root {
      color-scheme: dark;
      font-family: "Segoe UI", system-ui, sans-serif;
      background: #0c0d0f;
      color: #eef2f7;
      --panel: #15181b;
      --panel2: #1d2126;
      --line: #333941;
      --muted: #9aa5b1;
      --focus: #41a6ff;
    }
    * { box-sizing: border-box; }
    body { margin: 0; min-height: 100vh; overflow: hidden; }
    button, input, select, textarea {
      font: inherit;
      color: inherit;
      background: #101317;
      border: 1px solid var(--line);
      border-radius: 6px;
      min-height: 34px;
    }
    button { cursor: pointer; padding: 6px 10px; background: var(--panel2); }
    button:hover { border-color: var(--focus); }
    button.icon { width: 36px; padding: 0; font-weight: 700; }
    input, select { padding: 6px 8px; min-width: 0; }
    textarea { width: 100%; min-height: 160px; padding: 8px; resize: vertical; font-family: Consolas, monospace; font-size: 12px; }
    .app { display: grid; grid-template-columns: 280px 1fr 300px; height: 100vh; }
    aside, .inspector { background: var(--panel); border-color: var(--line); overflow: auto; }
    aside { border-right: 1px solid var(--line); }
    .inspector { border-left: 1px solid var(--line); }
    .bar { height: 48px; display: flex; align-items: center; gap: 8px; padding: 8px; border-bottom: 1px solid var(--line); }
    .bar input, .bar select { flex: 1; }
    .section { padding: 10px; border-bottom: 1px solid var(--line); }
    .section h2 { font-size: 12px; font-weight: 650; color: var(--muted); margin: 0 0 8px; text-transform: uppercase; }
    .grid2 { display: grid; grid-template-columns: 1fr 1fr; gap: 8px; }
    .grid3 { display: grid; grid-template-columns: 1fr 1fr 1fr; gap: 8px; }
    .field { display: grid; gap: 4px; margin-bottom: 8px; }
    .field label { font-size: 12px; color: var(--muted); }
    .layers { display: grid; gap: 6px; }
    .layer {
      display: grid;
      grid-template-columns: 1fr auto;
      gap: 8px;
      align-items: center;
      min-height: 38px;
      padding: 7px 8px;
      border: 1px solid var(--line);
      border-radius: 6px;
      background: #101317;
      cursor: pointer;
    }
    .layer.active { border-color: var(--focus); background: #14202b; }
    .layer small { display: block; color: var(--muted); overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
    main { min-width: 0; display: grid; grid-template-rows: 48px 1fr; background: #090a0c; }
    .top { display: flex; align-items: center; justify-content: space-between; gap: 8px; padding: 8px 12px; border-bottom: 1px solid var(--line); background: #101317; }
    .top .left, .top .right { display: flex; align-items: center; gap: 8px; min-width: 0; }
    .status { color: var(--muted); font-size: 12px; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
    .stageWrap { display: grid; place-items: center; overflow: hidden; }
    .stage {
      position: relative;
      width: min(72vh, 72vw);
      height: min(72vh, 72vw);
      min-width: 360px;
      min-height: 360px;
      max-width: 720px;
      max-height: 720px;
    }
    canvas { width: 100%; height: 100%; display: block; border-radius: 50%; background: #05070a; box-shadow: 0 0 0 1px #222932, 0 24px 80px rgba(0,0,0,.45); }
    .hotspot {
      position: absolute;
      border: 1px dashed rgba(65,166,255,.8);
      background: rgba(65,166,255,.08);
      transform-origin: center;
      display: none;
      cursor: move;
    }
    .hotspot.active { display: block; }
    .pill { padding: 4px 8px; border: 1px solid var(--line); border-radius: 999px; color: var(--muted); font-size: 12px; }
    .modal {
      position: fixed;
      inset: 0;
      display: none;
      place-items: center;
      background: rgba(0,0,0,.6);
      z-index: 20;
    }
    .modal.open { display: grid; }
    .modalBox { width: min(720px, calc(100vw - 32px)); max-height: calc(100vh - 48px); overflow: auto; border: 1px solid var(--line); background: var(--panel); border-radius: 8px; padding: 12px; }
    .modalHead { display: flex; justify-content: space-between; align-items: center; gap: 8px; margin-bottom: 8px; }
    @media (max-width: 980px) {
      body { overflow: auto; }
      .app { grid-template-columns: 1fr; height: auto; min-height: 100vh; }
      aside, .inspector { max-height: none; border: 0; }
      main { min-height: 620px; }
      .stage { width: min(92vw, 620px); height: min(92vw, 620px); min-width: 300px; min-height: 300px; }
    }
  </style>
</head>
<body>
<div class="app">
  <aside>
    <div class="bar">
      <input id="apiKey" value="change-me" aria-label="API key">
      <button class="icon" id="refreshBtn" title="Refresh">R</button>
    </div>
    <div class="section">
      <h2>Preset</h2>
      <div class="field"><select id="presetSelect"></select></div>
      <div class="grid2">
        <button id="loadBtn">Load</button>
        <button id="saveBtn">Save</button>
      </div>
    </div>
    <div class="section">
      <h2>Add</h2>
      <div class="grid2">
        <button data-add="metric_text">Metric</button>
        <button data-add="arc_metric">Arc</button>
        <button data-add="text">Text</button>
        <button data-add="app_logo">Logo</button>
      </div>
    </div>
    <div class="section">
      <h2>Layers</h2>
      <div id="layers" class="layers"></div>
    </div>
  </aside>

  <main>
    <div class="top">
      <div class="left">
        <input id="layoutName" aria-label="Layout name">
        <span class="pill" id="devicePill">cooler-display-01</span>
      </div>
      <div class="right">
        <button id="jsonBtn">JSON</button>
        <button id="resetBtn">Reset</button>
        <span class="status" id="status">Ready</span>
      </div>
    </div>
    <div class="stageWrap">
      <div class="stage" id="stage">
        <canvas id="preview" width="480" height="480"></canvas>
        <div id="hotspot" class="hotspot"></div>
      </div>
    </div>
  </main>

  <section class="inspector">
    <div class="section">
      <h2>Element</h2>
      <div id="emptyInspector" class="status">Select a layer</div>
      <div id="inspectorFields"></div>
    </div>
  </section>
</div>

<div class="modal" id="jsonModal">
  <div class="modalBox">
    <div class="modalHead">
      <strong>Layout JSON</strong>
      <div>
        <button id="importJsonBtn">Import</button>
        <button id="closeJsonBtn">Close</button>
      </div>
    </div>
    <textarea id="jsonText"></textarea>
  </div>
</div>

<script>
const apiKeyEl = document.getElementById('apiKey');
const presetSelect = document.getElementById('presetSelect');
const layoutName = document.getElementById('layoutName');
const layersEl = document.getElementById('layers');
const fieldsEl = document.getElementById('inspectorFields');
const emptyInspector = document.getElementById('emptyInspector');
const statusEl = document.getElementById('status');
const canvas = document.getElementById('preview');
const ctx = canvas.getContext('2d');
const stage = document.getElementById('stage');
const hotspot = document.getElementById('hotspot');
const jsonModal = document.getElementById('jsonModal');
const jsonText = document.getElementById('jsonText');
const deviceId = 'cooler-display-01';

let layout = null;
let state = {};
let selectedId = null;
let logoCache = new Map();
let drag = null;

apiKeyEl.value = localStorage.getItem('coolerApiKey') || apiKeyEl.value;
apiKeyEl.addEventListener('change', () => localStorage.setItem('coolerApiKey', apiKeyEl.value));

function setStatus(text) { statusEl.textContent = text; }

async function api(path, options = {}) {
  const headers = {'X-API-Key': apiKeyEl.value, ...(options.headers || {})};
  const res = await fetch(path, {...options, headers});
  if (!res.ok) throw new Error(await res.text());
  return res;
}

function deepClone(value) { return JSON.parse(JSON.stringify(value)); }
function selected() { return (layout?.elements || []).find(el => el.id === selectedId) || null; }
function clamp(value, min, max) { return Math.max(min, Math.min(max, value)); }
function metricValue(metric) {
  const value = state?.[metric];
  return Number.isFinite(Number(value)) ? Number(value) : 0;
}
function textFor(el) {
  if (el.type === 'metric_text') {
    const value = metricValue(el.metric);
    const digits = el.metric && el.metric.includes('temp') ? 0 : 0;
    return `${value.toFixed(digits)}${el.suffix || ''}`;
  }
  return String(el.text || '')
    .replaceAll('{display_name}', state.display_name || 'Unknown')
    .replaceAll('{local_time}', state.local_time || '--:--')
    .replaceAll('{local_date}', state.local_date || '');
}

function angleToRad(deg) { return deg * Math.PI / 180; }

function drawArc(el) {
  const value = clamp(metricValue(el.metric), 0, 100);
  const start = angleToRad(Number(el.start_deg ?? 120));
  const sweep = Number(el.sweep_deg ?? 300) * Math.PI / 180;
  const radius = Number(el.radius ?? 200);
  const width = Number(el.width ?? 10);
  ctx.save();
  ctx.lineWidth = width;
  ctx.lineCap = 'round';
  ctx.strokeStyle = el.track_color || '#20262d';
  ctx.beginPath();
  ctx.arc(Number(el.x ?? 240), Number(el.y ?? 240), radius, start, start + sweep);
  ctx.stroke();
  ctx.strokeStyle = el.color || '#ffffff';
  ctx.beginPath();
  ctx.arc(Number(el.x ?? 240), Number(el.y ?? 240), radius, start, start + sweep * value / 100);
  ctx.stroke();
  ctx.restore();
}

function drawText(el) {
  const x = Number(el.x ?? 0);
  const y = Number(el.y ?? 0);
  const width = Number(el.width ?? 160);
  const height = Number(el.height ?? 32);
  const size = Number(el.font_size ?? 22);
  ctx.save();
  ctx.globalAlpha = Number(el.opacity ?? 1);
  ctx.fillStyle = el.color || '#ffffff';
  ctx.font = `700 ${size}px "Segoe UI", Arial, sans-serif`;
  ctx.textBaseline = 'middle';
  ctx.textAlign = el.align || 'left';
  const tx = el.align === 'center' ? x + width / 2 : el.align === 'right' ? x + width : x;
  ctx.fillText(textFor(el), tx, y + height / 2, width);
  ctx.restore();
}

async function getLogoImage() {
  const appId = state.app_id || 'unknown';
  if (logoCache.has(appId)) return logoCache.get(appId);
  try {
    const res = await api(`/assets/apps/${appId}/logo_160x160.rgb565`);
    const data = new Uint8Array(await res.arrayBuffer());
    const off = document.createElement('canvas');
    off.width = 160; off.height = 160;
    const offCtx = off.getContext('2d');
    const image = offCtx.createImageData(160, 160);
    for (let i = 0, p = 0; i + 1 < data.length && p < image.data.length; i += 2, p += 4) {
      const v = data[i] | (data[i + 1] << 8);
      image.data[p] = (v >> 8) & 0xf8;
      image.data[p + 1] = (v >> 3) & 0xfc;
      image.data[p + 2] = (v << 3) & 0xf8;
      image.data[p + 3] = 255;
    }
    offCtx.putImageData(image, 0, 0);
    logoCache.set(appId, off);
    return off;
  } catch {
    logoCache.set(appId, null);
    return null;
  }
}

async function drawLogo(el) {
  const logo = await getLogoImage();
  const x = Number(el.x ?? 140);
  const y = Number(el.y ?? 100);
  const w = Number(el.width ?? 180);
  const h = Number(el.height ?? 180);
  ctx.save();
  ctx.globalAlpha = Number(el.opacity ?? 1);
  if (logo) {
    ctx.drawImage(logo, x, y, w, h);
  } else {
    ctx.strokeStyle = '#56616f';
    ctx.lineWidth = 2;
    ctx.strokeRect(x, y, w, h);
    ctx.fillStyle = '#8792a0';
    ctx.font = '700 46px Segoe UI';
    ctx.textAlign = 'center';
    ctx.textBaseline = 'middle';
    ctx.fillText('?', x + w / 2, y + h / 2);
  }
  ctx.restore();
}

async function render() {
  if (!layout) return;
  const bg = layout.canvas?.background || '#05070a';
  ctx.clearRect(0, 0, 480, 480);
  ctx.fillStyle = bg;
  ctx.fillRect(0, 0, 480, 480);
  ctx.save();
  ctx.beginPath();
  ctx.arc(240, 240, 240, 0, Math.PI * 2);
  ctx.clip();
  const elements = [...(layout.elements || [])].sort((a, b) => Number(a.z || 0) - Number(b.z || 0));
  for (const el of elements) {
    if (el.type === 'arc_metric') drawArc(el);
    if (el.type === 'text' || el.type === 'metric_text') drawText(el);
    if (el.type === 'app_logo') await drawLogo(el);
  }
  ctx.restore();
  updateHotspot();
}

function updateLayers() {
  layersEl.innerHTML = '';
  const elements = [...(layout?.elements || [])].sort((a, b) => Number(b.z || 0) - Number(a.z || 0));
  for (const el of elements) {
    const row = document.createElement('div');
    row.className = 'layer' + (el.id === selectedId ? ' active' : '');
    row.innerHTML = `<div><strong>${el.id}</strong><small>${el.type}${el.metric ? ' / ' + el.metric : ''}</small></div><button class="icon" title="Delete">X</button>`;
    row.onclick = () => { selectedId = el.id; updateAll(); };
    row.querySelector('button').onclick = event => {
      event.stopPropagation();
      layout.elements = layout.elements.filter(item => item.id !== el.id);
      if (selectedId === el.id) selectedId = layout.elements[0]?.id || null;
      updateAll();
    };
    layersEl.appendChild(row);
  }
}

function inputField(label, key, type = 'text', options = null) {
  const el = selected();
  const wrap = document.createElement('div');
  wrap.className = 'field';
  const id = `field_${key}`;
  const labelEl = document.createElement('label');
  labelEl.htmlFor = id;
  labelEl.textContent = label;
  let input;
  if (options) {
    input = document.createElement('select');
    for (const option of options) {
      const opt = document.createElement('option');
      opt.value = option;
      opt.textContent = option;
      input.appendChild(opt);
    }
  } else {
    input = document.createElement('input');
    input.type = type;
  }
  input.id = id;
  input.value = el[key] ?? '';
  input.oninput = () => {
    const numeric = ['x','y','width','height','radius','start_deg','sweep_deg','font_size','z','opacity'].includes(key);
    el[key] = numeric ? Number(input.value) : input.value;
    updateLayers();
    render();
  };
  wrap.append(labelEl, input);
  return wrap;
}

function updateInspector() {
  fieldsEl.innerHTML = '';
  const el = selected();
  emptyInspector.style.display = el ? 'none' : 'block';
  if (!el) return;
  fieldsEl.append(inputField('ID', 'id'));
  fieldsEl.append(inputField('Type', 'type', 'text', ['text', 'metric_text', 'arc_metric', 'app_logo']));
  if (el.type === 'metric_text' || el.type === 'arc_metric') {
    fieldsEl.append(inputField('Metric', 'metric', 'text', ['cpu_temp', 'cpu_load', 'gpu_temp', 'gpu_load', 'ram_used_percent']));
  }
  if (el.type === 'text') fieldsEl.append(inputField('Text', 'text'));
  if (el.type === 'metric_text') fieldsEl.append(inputField('Suffix', 'suffix'));
  const group = document.createElement('div');
  group.className = 'grid2';
  for (const item of [inputField('X', 'x', 'number'), inputField('Y', 'y', 'number'), inputField('W', 'width', 'number'), inputField('H', 'height', 'number')]) group.append(item);
  fieldsEl.append(group);
  if (el.type === 'arc_metric') {
    const arc = document.createElement('div');
    arc.className = 'grid2';
    for (const item of [inputField('Radius', 'radius', 'number'), inputField('Stroke', 'width', 'number'), inputField('Start', 'start_deg', 'number'), inputField('Sweep', 'sweep_deg', 'number')]) arc.append(item);
    fieldsEl.append(arc);
    fieldsEl.append(inputField('Track', 'track_color', 'color'));
  }
  if (el.type === 'text' || el.type === 'metric_text') {
    fieldsEl.append(inputField('Font', 'font_size', 'number'));
    fieldsEl.append(inputField('Align', 'align', 'text', ['left', 'center', 'right']));
  }
  fieldsEl.append(inputField('Color', 'color', 'color'));
  fieldsEl.append(inputField('Z', 'z', 'number'));
}

function updateHotspot() {
  const el = selected();
  if (!el || el.type === 'arc_metric') {
    hotspot.className = 'hotspot';
    return;
  }
  const rect = stage.getBoundingClientRect();
  const scale = rect.width / 480;
  hotspot.className = 'hotspot active';
  hotspot.style.left = `${Number(el.x || 0) * scale}px`;
  hotspot.style.top = `${Number(el.y || 0) * scale}px`;
  hotspot.style.width = `${Number(el.width || 80) * scale}px`;
  hotspot.style.height = `${Number(el.height || 32) * scale}px`;
}

function updateAll() {
  layoutName.value = layout?.name || '';
  updateLayers();
  updateInspector();
  render();
}

function newId(type) {
  let i = 1;
  while ((layout.elements || []).some(el => el.id === `${type}_${i}`)) i++;
  return `${type}_${i}`;
}

function addElement(type) {
  const base = { id: newId(type), type, x: 160, y: 180, width: 160, height: 40, color: '#ffffff', z: Date.now() % 100000 };
  if (type === 'metric_text') Object.assign(base, { metric: 'cpu_temp', suffix: 'C', font_size: 32, align: 'center' });
  if (type === 'text') Object.assign(base, { text: '{local_time}', font_size: 24, align: 'center' });
  if (type === 'app_logo') Object.assign(base, { x: 150, y: 100, width: 180, height: 180 });
  if (type === 'arc_metric') Object.assign(base, { metric: 'cpu_load', x: 240, y: 240, radius: 210, width: 10, start_deg: 120, sweep_deg: 300, track_color: '#222832' });
  layout.elements.push(base);
  selectedId = base.id;
  updateAll();
}

async function refreshState() {
  try {
    const res = await api(`/api/v1/device/${deviceId}/state`);
    state = await res.json();
    setStatus(`${state.display_name || 'Unknown'} / CPU ${Math.round(state.cpu_temp || 0)}C / GPU ${Math.round(state.gpu_temp || 0)}C`);
    await render();
  } catch (err) {
    setStatus(err.message);
  }
}

async function loadPresets() {
  const res = await api('/api/v1/layouts');
  const items = await res.json();
  presetSelect.innerHTML = '';
  for (const item of items) {
    const opt = document.createElement('option');
    opt.value = item.id;
    opt.textContent = `${item.name} (${item.element_count})`;
    presetSelect.appendChild(opt);
  }
}

async function loadPreset(id = presetSelect.value || 'classic') {
  const res = await api(`/api/v1/layouts/${id}`);
  const data = await res.json();
  layout = data.layout;
  selectedId = layout.elements?.[0]?.id || null;
  updateAll();
}

async function savePreset() {
  layout.name = layoutName.value || layout.name || layout.id || 'Layout';
  const id = (layout.id || layout.name || 'layout').toLowerCase().replace(/[^a-z0-9_-]+/g, '-').replace(/^-+|-+$/g, '') || 'layout';
  const res = await api(`/api/v1/layouts/${id}`, {
    method: 'POST',
    headers: {'Content-Type': 'application/json'},
    body: JSON.stringify({layout}),
  });
  const data = await res.json();
  layout = data.layout;
  setStatus('Saved');
  await loadPresets();
  presetSelect.value = layout.id;
  updateAll();
}

for (const button of document.querySelectorAll('[data-add]')) button.onclick = () => addElement(button.dataset.add);
document.getElementById('refreshBtn').onclick = refreshState;
document.getElementById('loadBtn').onclick = () => loadPreset();
document.getElementById('saveBtn').onclick = savePreset;
document.getElementById('resetBtn').onclick = () => loadPreset('classic');
document.getElementById('jsonBtn').onclick = () => {
  jsonText.value = JSON.stringify(layout, null, 2);
  jsonModal.classList.add('open');
};
document.getElementById('closeJsonBtn').onclick = () => jsonModal.classList.remove('open');
document.getElementById('importJsonBtn').onclick = () => {
  layout = JSON.parse(jsonText.value);
  selectedId = layout.elements?.[0]?.id || null;
  jsonModal.classList.remove('open');
  updateAll();
};
layoutName.oninput = () => { if (layout) layout.name = layoutName.value; };

hotspot.addEventListener('pointerdown', event => {
  const el = selected();
  if (!el) return;
  hotspot.setPointerCapture(event.pointerId);
  drag = { startX: event.clientX, startY: event.clientY, x: Number(el.x || 0), y: Number(el.y || 0) };
});
hotspot.addEventListener('pointermove', event => {
  if (!drag) return;
  const el = selected();
  const scale = stage.getBoundingClientRect().width / 480;
  el.x = Math.round(drag.x + (event.clientX - drag.startX) / scale);
  el.y = Math.round(drag.y + (event.clientY - drag.startY) / scale);
  updateInspector();
  render();
});
hotspot.addEventListener('pointerup', () => { drag = null; });
window.addEventListener('resize', updateHotspot);

async function boot() {
  localStorage.setItem('coolerApiKey', apiKeyEl.value);
  try {
    await loadPresets();
    presetSelect.value = 'classic';
    await loadPreset('classic');
    await refreshState();
    setInterval(refreshState, 2000);
  } catch (err) {
    setStatus(err.message);
  }
}

boot();
</script>
</body>
</html>
"""
