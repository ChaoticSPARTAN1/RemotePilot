const $ = (id) => document.getElementById(id);
const header = {'X-Remote-Pilot-Viewer': '1'};
let manifest = null;
let state = null;
let frameVersion = 0;
let frameUrl = null;
let audioVersion = 0;
let audioContext = null;
let nextAudioTime = 0;
let liveTimer = null;
let setupTarget = '';
let setupFilename = '';
let setupMessage = '';
let graphSamples = [];
let lastPerfStamp = -1;
let controlTimer = null;
let lastControl = '';
let pointerButtons = 0;
let lastTouchPosition = null;
const sticks = {move: {x: 0, y: 0}, look: {x: 0, y: 0}};

async function api(path, data) {
  const options = {headers: {...header}, cache: 'no-store'};
  if (data !== undefined) {
    options.method = 'POST';
    options.headers['Content-Type'] = 'application/json';
    options.body = JSON.stringify(data);
  }
  const response = await fetch(path, options);
  if (!response.ok) {
    let message = `Request failed (${response.status})`;
    try { message = (await response.json()).error || message; } catch (_) {}
    throw new Error(message);
  }
  return response.status === 204 ? null : response.json();
}

function feedback(message) { $('feedback').textContent = message; }

function enabled(capability) {
  return Boolean(manifest && state && state.linkEnabled && state.connected &&
                 manifest.capabilities.includes(capability));
}

function setColors(theme) {
  const root = document.documentElement;
  for (const [key, value] of Object.entries(theme)) root.style.setProperty(`--${key}`, value);
  $('color-accent').value = theme.accent;
  $('color-background').value = theme.background;
}

function renderPreset() {
  if (!manifest) return;
  const display = manifest.display;
  $('display').style.aspectRatio = `${display.width} / ${display.height}`;
  $('display').classList.toggle('touch-ready', Boolean(display.touch));
  $('display-title').textContent = `${manifest.name} display`;
  $('placeholder').textContent = manifest.id === 'example' ?
    'Example preview · choose an integrated preset for device frames' : 'Waiting for a device frame';
  $('display-help').textContent = display.touch ?
    'Click or drag within the touch region to send bounded device coordinates.' :
    'This preset has no touch region.';
  $('live').checked = false;
  $('sound').checked = false;
  stopLive();
  frameVersion = 0;
  audioVersion = 0;
  if (frameUrl) URL.revokeObjectURL(frameUrl);
  frameUrl = null;
  $('frame').hidden = true;
  $('placeholder').hidden = false;
  $('frame-info').textContent = 'No frame yet';
  graphSamples = [];
  lastPerfStamp = -1;
  drawGraph();
  setupTarget = '';
  setupFilename = '';
  setupMessage = '';
  $('install-config').hidden = true;
  $('download-config').hidden = true;
  $('manual-host-row').hidden = true;
  $('setup-result').textContent = manifest.id === 'example' ?
    'Example works offline. Follow the integration guide to add a device preset.' :
    'Prepare pairing, then copy the generated device config to the build’s documented location.';
  setColors(manifest.theme);
  const buttons = $('buttons');
  buttons.replaceChildren();
  for (const name of manifest.buttons || []) {
    const button = document.createElement('button');
    button.type = 'button';
    button.textContent = name.replaceAll('_', ' ');
    button.dataset.button = name;
    button.addEventListener('click', () => action('input', {button: name, frames: 1}));
    buttons.append(button);
  }
  $('control-help').textContent = manifest.buttons?.length ?
    'Each button sends one short press. Controller snapshots are opt in.' :
    'The integrated build has not declared manual buttons.';
  loadCatalog();
}

async function choosePreset(id) {
  await api('/api/select', {id});
  manifest = (await api('/api/presets')).presets.find(item => item.id === id);
  renderPreset();
  await refresh();
}

async function refresh() {
  try {
    state = await api('/api/state');
    if (!manifest || manifest.id !== state.preset) {
      const presets = await api('/api/presets');
      manifest = presets.presets.find(item => item.id === state.preset);
      $('preset').value = state.preset;
      renderPreset();
    }
    const connected = state.connected && state.linkEnabled;
    const status = $('status');
    status.textContent = manifest.id === 'example' ? 'Example · offline' :
      connected ? 'Device connected' : state.linkEnabled ? 'Waiting for device' : 'PC link paused';
    status.classList.toggle('connected', connected);
    status.classList.toggle('warning', manifest.id !== 'example' && !connected);
    $('connection-detail').textContent = state.discovery || 'Waiting for adapter status';
    $('link').textContent = state.linkEnabled ? 'Pause PC link' : 'Resume PC link';
    $('prepare').disabled = !state.setupAvailable;
    $('manual-host-row').hidden = !state.manualHostAvailable || !setupFilename;
    $('setup-result').textContent = setupMessage || (setupFilename ?
      `Pairing file ready. Copy ${setupFilename} to ${setupTarget || 'the path documented by this build'}.` :
      manifest.id === 'example' ? 'Example works offline. Follow the integration guide to add a device preset.' :
      state.setupAvailable ? 'Prepare pairing to generate a private device config.' :
      'This adapter needs its own setup instructions; see its preset documentation.');
    for (const [id, capability] of [['capture','screenshot'], ['live','stream'], ['sound','audio'],
                                     ['report','report'], ['log','log'], ['perf-request','perf'],
                                     ['console','console'], ['controls-enabled','controller']]) {
      $(id).disabled = !enabled(capability);
    }
    $('retry').disabled = !state.linkEnabled || manifest.id === 'example';
    $('diagnostic').querySelector('[value="log"]').disabled = !manifest.capabilities.includes('log');
    $('diagnostic').querySelector('[value="report"]').disabled = !manifest.capabilities.includes('report');
    for (const button of $('buttons').querySelectorAll('button')) button.disabled = !enabled('input');
    if (!connected) {
      $('live').checked = false;
      stopLive();
      if ($('controls-enabled').checked) $('controls-enabled').checked = false;
      clearControls();
    }
    if (state.frameVersion > frameVersion) await loadFrame();
    if ($('sound').checked && state.audioVersion > audioVersion) await loadAudio();
    renderActivity(state.tasks, state.captures);
    updateGraph(state.perf);
    $('controller-state').textContent = $('controls-enabled').checked ?
      (navigator.getGamepads?.() || []).some(Boolean) ? 'Controller ready' : 'Mouse controls ready' : 'Off';
  } catch (error) {
    $('status').textContent = 'Viewer unavailable';
    feedback(error.message);
  }
}

async function loadFrame() {
  const response = await fetch('/api/frame', {headers: header, cache: 'no-store'});
  if (response.status === 204 || !response.ok) return;
  const blob = await response.blob();
  const url = URL.createObjectURL(blob);
  $('frame').src = url;
  $('frame').hidden = false;
  $('placeholder').hidden = true;
  if (frameUrl) URL.revokeObjectURL(frameUrl);
  frameUrl = url;
  frameVersion = Number(response.headers.get('X-Frame-Version')) || frameVersion + 1;
  $('frame-info').textContent = `Frame ${frameVersion}`;
}

async function loadAudio() {
  const response = await fetch(`/api/audio?since=${audioVersion}`, {headers: header, cache: 'no-store'});
  if (response.status === 204 || !response.ok) return;
  const bytes = await response.arrayBuffer();
  audioVersion = Number(response.headers.get('X-Audio-Sequence')) || audioVersion + 1;
  if (!bytes.byteLength || !$('sound').checked) return;
  if (!audioContext) audioContext = new AudioContext();
  await audioContext.resume();
  const rate = Number(response.headers.get('X-Sample-Rate')) || 16000;
  const input = new DataView(bytes);
  const output = audioContext.createBuffer(1, bytes.byteLength / 2, rate);
  const samples = output.getChannelData(0);
  for (let i = 0; i < samples.length; i++) samples[i] = input.getInt16(i * 2, true) / 32768;
  const source = audioContext.createBufferSource();
  source.buffer = output;
  source.connect(audioContext.destination);
  nextAudioTime = Math.max(audioContext.currentTime + .02, Math.min(nextAudioTime, audioContext.currentTime + .35));
  source.start(nextAudioTime);
  nextAudioTime += output.duration;
}

function stopLive() {
  if (liveTimer) clearTimeout(liveTimer);
  liveTimer = null;
}

async function liveTick() {
  if (!$('live').checked || !enabled('stream')) return stopLive();
  try { await api('/api/stream', {}); } catch (error) { feedback(error.message); }
  liveTimer = setTimeout(liveTick, Number($('rate').value));
}

async function action(kind, payload = '-') {
  try {
    const result = await api('/api/action', {kind, payload});
    feedback(`Queued ${kind} request ${result.task}.`);
    await refresh();
  } catch (error) { feedback(error.message); }
}

function renderActivity(tasks, captures) {
  const root = $('activity');
  root.replaceChildren();
  const files = new Map();
  for (const bundle of captures || []) for (const item of bundle.items || []) if (item.file) files.set(item.task, item.file);
  for (const task of tasks || []) {
    const row = document.createElement('div');
    row.className = 'activity-row';
    const stateCell = document.createElement('span');
    stateCell.className = 'state';
    stateCell.textContent = `${task.id} · ${task.state}`;
    const result = document.createElement('span');
    result.className = 'result';
    result.textContent = `${task.kind}: ${task.result || 'Waiting'}`;
    row.append(stateCell, result);
    const filename = files.get(task.id) || (typeof task.result === 'string' && /^[a-zA-Z0-9_.-]+\.(png|bmp|txt)$/.test(task.result) ? task.result : null);
    if (filename) {
      const link = document.createElement('a');
      link.href = '#';
      link.textContent = 'Download';
      link.addEventListener('click', (event) => { event.preventDefault(); downloadArtifact(filename); });
      row.append(link);
    }
    root.append(row);
  }
  if (!root.children.length) root.textContent = 'No requests yet.';
}

async function downloadArtifact(filename) {
  try {
    const response = await fetch(`/api/artifact/${encodeURIComponent(filename)}`, {headers: header});
    if (!response.ok) throw new Error('Artifact unavailable');
    saveBlob(await response.blob(), filename);
  } catch (error) { feedback(error.message); }
}

function saveBlob(blob, filename) {
  const url = URL.createObjectURL(blob);
  const anchor = document.createElement('a');
  anchor.href = url;
  anchor.download = filename;
  anchor.click();
  setTimeout(() => URL.revokeObjectURL(url), 1000);
}

async function loadCatalog() {
  const panel = $('catalog-panel');
  panel.hidden = true;
  $('catalog').replaceChildren();
  if (!manifest.capabilities.includes('catalog')) return;
  try {
    const data = await api('/api/catalog');
    for (const group of data.groups || []) {
      const section = document.createElement('section');
      section.className = 'catalog-group';
      const title = document.createElement('h3');
      title.textContent = String(group.name || 'Items');
      section.append(title);
      for (const item of group.items || []) {
        const line = document.createElement('div');
        line.className = 'catalog-item';
        const label = document.createElement('span');
        label.textContent = String(item.label || item.id || 'Item');
        line.append(label);
        if (manifest.capabilities.includes('preview')) {
          const button = document.createElement('button');
          button.textContent = 'Preview';
          button.className = 'secondary';
          button.disabled = !enabled('preview');
          button.addEventListener('click', () => action('preview', String(item.id)));
          line.append(button);
        }
        section.append(line);
      }
      $('catalog').append(section);
    }
    panel.hidden = !$('catalog').children.length;
  } catch (error) { feedback(error.message); }
}

function updateGraph(perf) {
  if (perf && Number.isFinite(perf.timestampMs) && perf.timestampMs > lastPerfStamp &&
      Number.isFinite(perf.frameMs) && Number.isFinite(perf.workMs)) {
    lastPerfStamp = perf.timestampMs;
    graphSamples.push({frame: perf.frameMs, work: perf.workMs});
    if (graphSamples.length > 60) graphSamples.shift();
  }
  $('perf-detail').textContent = perf && Number.isFinite(perf.fps) ?
    `${perf.fps.toFixed(1)} fps · ${perf.frameMs.toFixed(1)} ms frame · ${perf.workMs.toFixed(1)} ms work` :
    'Waiting for device timing';
  drawGraph();
}

function drawGraph() {
  const canvas = $('perf-graph');
  const context = canvas.getContext('2d');
  context.clearRect(0, 0, canvas.width, canvas.height);
  context.strokeStyle = '#3d7761';
  context.beginPath();
  context.moveTo(0, 103);
  context.lineTo(canvas.width, 103);
  context.stroke();
  if (!graphSamples.length) return;
  const max = Math.max(33.3, ...graphSamples.map(item => item.frame), ...graphSamples.map(item => item.work));
  for (const [key, color] of [['frame', '#b2ffd5'], ['work', '#55e59a']]) {
    context.strokeStyle = color;
    context.lineWidth = 2;
    context.beginPath();
    graphSamples.forEach((item, index) => {
      const x = index * (canvas.width - 1) / 59;
      const y = canvas.height - Math.min(item[key] / max, 1) * (canvas.height - 12) - 5;
      if (index) context.lineTo(x, y); else context.moveTo(x, y);
    });
    context.stroke();
  }
}

async function prepareSetup() {
  try {
    const result = await api('/api/setup', {});
    setupTarget = result.deviceConfigPath || '';
    setupFilename = result.configFile;
    setupMessage = `Ready: ${setupFilename}. Copy it to ${setupTarget || 'the path documented by this build'}.`;
    $('download-config').hidden = false;
    $('install-config').hidden = !setupTarget || !window.showDirectoryPicker;
    $('manual-host-row').hidden = !state?.manualHostAvailable;
    $('setup-result').textContent = setupMessage;
  } catch (error) { setupMessage = error.message; $('setup-result').textContent = setupMessage; }
}

async function configBlob() {
  const response = await fetch('/api/setup/config', {headers: header, cache: 'no-store'});
  if (!response.ok) throw new Error('Prepare pairing first');
  return response.blob();
}

async function installConfig() {
  try {
    const pieces = setupTarget.replace(/^[a-zA-Z][a-zA-Z0-9_-]*:\/?/, '').split('/');
    if (!pieces.length || pieces.some(part => !/^[a-zA-Z0-9_.-]+$/.test(part) || part === '..' || part === '.'))
      throw new Error('The preset has an unsafe device path');
    const root = await window.showDirectoryPicker({mode: 'readwrite'});
    let folder = root;
    for (const name of pieces.slice(0, -1)) folder = await folder.getDirectoryHandle(name, {create: true});
    const file = await folder.getFileHandle(pieces.at(-1), {create: true});
    const writable = await file.createWritable();
    await writable.write(await configBlob());
    await writable.close();
    setupMessage = `Copied pairing file to ${setupTarget} in the selected folder. Start the integrated build.`;
    $('setup-result').textContent = setupMessage;
  } catch (error) { setupMessage = error.message; $('setup-result').textContent = setupMessage; }
}

function clearControls() {
  pointerButtons = 0;
  for (const key of Object.keys(sticks)) { sticks[key] = {x: 0, y: 0}; updateStickVisual(key); }
  if (lastControl && manifest?.capabilities.includes('controller')) sendGamepad(true);
}

function updateStickVisual(key) {
  const element = document.querySelector(`[data-stick="${key}"] i`);
  if (element) element.style.transform = `translate(${sticks[key].x * 20}px, ${sticks[key].y * 20}px)`;
}

function stickPointer(element, key) {
  function sample(event) {
    const rect = element.getBoundingClientRect();
    const dx = (event.clientX - rect.left - rect.width / 2) / (rect.width / 2);
    const dy = (event.clientY - rect.top - rect.height / 2) / (rect.height / 2);
    const length = Math.max(1, Math.hypot(dx, dy));
    sticks[key] = {x: Math.max(-1, Math.min(1, dx / length)), y: Math.max(-1, Math.min(1, dy / length))};
    updateStickVisual(key);
  }
  element.addEventListener('pointerdown', event => {
    if (!$('controls-enabled').checked) return;
    element.setPointerCapture(event.pointerId);
    sample(event);
  });
  element.addEventListener('pointermove', event => { if (element.hasPointerCapture(event.pointerId)) sample(event); });
  const release = () => { sticks[key] = {x: 0, y: 0}; updateStickVisual(key); };
  element.addEventListener('pointerup', release);
  element.addEventListener('pointercancel', release);
}

function gamepadPayload(forceZero = false) {
  const gamepad = forceZero ? null : (navigator.getGamepads?.() || []).find(item => item && item.mapping === 'standard');
  const axes = gamepad?.axes || [];
  let buttons = forceZero ? 0 : pointerButtons;
  if (gamepad) gamepad.buttons.slice(0, 16).forEach((button, index) => { if (button.pressed) buttons |= 1 << index; });
  const axis = (index, fallback) => forceZero ? 0 : Math.abs(fallback) > .03 ? fallback :
    Math.abs(axes[index] || 0) > .08 ? axes[index] : 0;
  return {buttons, lx: axis(0, sticks.move.x), ly: axis(1, sticks.move.y),
          rx: axis(2, sticks.look.x), ry: axis(3, sticks.look.y),
          lt: forceZero ? 0 : gamepad?.buttons[6]?.value || 0,
          rt: forceZero ? 0 : gamepad?.buttons[7]?.value || 0, frames: 8};
}

async function sendGamepad(forceZero = false) {
  if (!forceZero && (!$('controls-enabled').checked || !document.hasFocus() || document.hidden || !enabled('controller'))) return;
  const payload = gamepadPayload(forceZero);
  const value = JSON.stringify(payload);
  const active = payload.buttons || payload.lx || payload.ly || payload.rx || payload.ry || payload.lt || payload.rt;
  if (value === lastControl && !forceZero && !active) return;
  lastControl = value;
  try { await api('/api/control', {kind: 'gamepad', payload}); } catch (_) {}
}

function touchPosition(event) {
  const touch = manifest?.display?.touch;
  if (!touch) return null;
  const rect = $('display').getBoundingClientRect();
  const scale = Math.min(rect.width / manifest.display.width, rect.height / manifest.display.height);
  const drawnWidth = manifest.display.width * scale;
  const drawnHeight = manifest.display.height * scale;
  const left = rect.left + (rect.width - drawnWidth) / 2;
  const top = rect.top + (rect.height - drawnHeight) / 2;
  const x = (event.clientX - left) / scale - touch.x;
  const y = (event.clientY - top) / scale - touch.y;
  if (x < 0 || y < 0 || x >= touch.width || y >= touch.height) return null;
  return {x: Math.min(touch.deviceWidth - 1, Math.floor(x * touch.deviceWidth / touch.width)),
          y: Math.min(touch.deviceHeight - 1, Math.floor(y * touch.deviceHeight / touch.height))};
}

async function sendTouch(event, down) {
  if (!enabled('touch') || !$('controls-enabled').checked) return;
  const position = touchPosition(event) || (!down ? lastTouchPosition : null);
  if (!position) return;
  lastTouchPosition = down ? position : null;
  try { await api('/api/control', {kind: 'touch', payload: {...position, down}}); } catch (_) {}
}

async function init() {
  try {
    const presets = await api('/api/presets');
    for (const item of presets.presets) {
      const option = document.createElement('option');
      option.value = item.id;
      option.textContent = item.name;
      $('preset').append(option);
    }
    $('preset').value = presets.selected;
    manifest = presets.presets.find(item => item.id === presets.selected);
    renderPreset();
    await refresh();
  } catch (error) { feedback(error.message); }
  setInterval(refresh, 1000);
  controlTimer = setInterval(() => sendGamepad(), 100);
}

$('preset').addEventListener('change', event => choosePreset(event.target.value).catch(error => feedback(error.message)));
$('setup-hide').addEventListener('click', () => { $('setup').hidden = true; $('setup-open').hidden = false; });
$('setup-open').addEventListener('click', () => { $('setup').hidden = false; $('setup-open').hidden = true; });
$('prepare').addEventListener('click', prepareSetup);
$('download-config').addEventListener('click', async () => {
  try { saveBlob(await configBlob(), setupFilename); setupMessage = `Downloaded ${setupFilename}. Copy it to ${setupTarget}.`; $('setup-result').textContent = setupMessage; }
  catch (error) { setupMessage = error.message; $('setup-result').textContent = setupMessage; }
});
$('install-config').addEventListener('click', installConfig);
$('use-device-host').addEventListener('click', async () => {
  try {
    await api('/api/setup/host', {host: $('device-host').value.trim()});
    setupMessage = 'Device address saved privately. Searching for the paired build.';
  } catch (error) { setupMessage = error.message; }
  $('setup-result').textContent = setupMessage;
});
$('auto-device-host').addEventListener('click', async () => {
  try {
    await api('/api/setup/host', {host: 'auto'});
    $('device-host').value = '';
    setupMessage = 'Automatic private-network search resumed.';
  } catch (error) { setupMessage = error.message; }
  $('setup-result').textContent = setupMessage;
});
$('live').addEventListener('change', () => { stopLive(); if ($('live').checked) liveTick(); });
$('sound').addEventListener('change', async () => {
  if ($('sound').checked) {
    try { audioContext ||= new AudioContext(); await audioContext.resume(); } catch (_) { $('sound').checked = false; }
  }
});
$('capture').addEventListener('click', async () => {
  try { const diagnostic = $('diagnostic').value || null; const result = await api('/api/capture', {diagnostic}); feedback(`Capture ${result.capture} queued.`); await refresh(); }
  catch (error) { feedback(error.message); }
});
$('link').addEventListener('click', async () => { try { await api('/api/link', {enabled: !state.linkEnabled}); await refresh(); } catch (error) { feedback(error.message); } });
$('retry').addEventListener('click', async () => { try { await api('/api/retry', {}); feedback('Connection search restarted.'); } catch (error) { feedback(error.message); } });
$('console-form').addEventListener('submit', event => { event.preventDefault(); action('console', $('console').value.trim()); });
for (const [id, kind] of [['report','report'], ['log','log'], ['perf-request','perf']]) $(''+id).addEventListener('click', () => action(kind));
$('colors-save').addEventListener('click', async () => {
  try { await api('/api/theme', {colors: {accent: $('color-accent').value, background: $('color-background').value}}); const presets = await api('/api/presets'); manifest = presets.presets.find(item => item.id === state.preset); setColors(manifest.theme); feedback('Preset colors saved on this computer.'); }
  catch (error) { feedback(error.message); }
});
$('colors-reset').addEventListener('click', async () => {
  try { await api('/api/theme', {colors: {}}); const presets = await api('/api/presets'); manifest = presets.presets.find(item => item.id === state.preset); setColors(manifest.theme); feedback('Preset colors restored.'); }
  catch (error) { feedback(error.message); }
});
for (const element of document.querySelectorAll('[data-stick]')) stickPointer(element, element.dataset.stick);
let lastTouch = 0;
$('display').addEventListener('pointerdown', event => { if (!touchPosition(event)) return; $('display').setPointerCapture(event.pointerId); sendTouch(event, true); });
$('display').addEventListener('pointermove', event => { if ($('display').hasPointerCapture(event.pointerId) && performance.now() - lastTouch > 90) { lastTouch = performance.now(); sendTouch(event, true); } });
$('display').addEventListener('pointerup', event => sendTouch(event, false));
$('display').addEventListener('pointercancel', event => sendTouch(event, false));
$('controls-enabled').addEventListener('change', () => { if (!$('controls-enabled').checked) clearControls(); });
window.addEventListener('blur', clearControls);
document.addEventListener('visibilitychange', () => { if (document.hidden) clearControls(); });
init();
