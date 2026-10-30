// PSP section: the Memory Stick's folders (read-only, through the device's
// "files" and "file" actions), the system settings backup (the "backup"
// action, fetched and checked by the viewer: settings_backup.py) and the
// Options menu's bug reporting. Uses viewer.js's api(), header, manifest,
// state, feedback() and saveBlob(). Bug reports are saved on this computer
// only (bug_report.py): nothing is sent to GitHub or anywhere else.

let filesPath = 'ms0:/';
let filesBusy = false;
let previewBlob = null;
let previewName = '';
let previewUrl = null;
let backupSeen = '';
let reportSeen = '';

async function waitTask(id, seconds = 30) {
  const deadline = Date.now() + seconds * 1000;
  while (Date.now() < deadline) {
    const current = await api('/api/state');
    const task = (current.tasks || []).find(item => item.id === id);
    if (task && task.state === 'done') return task.result;
    if (task && task.state === 'failed') throw new Error(task.result || 'The PSP declined the request');
    await new Promise(resolve => setTimeout(resolve, 250));
  }
  throw new Error('The PSP did not answer in time');
}

async function deviceFile(kind, path) {
  const queued = await api('/api/action', {kind, payload: path});
  const name = await waitTask(queued.task, kind === 'file' ? 60 : 20);
  const response = await fetch(`/api/artifact/${encodeURIComponent(name)}`, {headers: header, cache: 'no-store'});
  if (!response.ok) throw new Error('The copy is unavailable');
  return {name, blob: await response.blob()};
}

function joinPath(base, name) {
  return base.endsWith('/') ? base + name : `${base}/${name}`;
}

function parentPath(path) {
  if (path === 'ms0:/') return path;
  const cut = path.lastIndexOf('/');
  return cut <= 4 ? 'ms0:/' : path.slice(0, cut);
}

function sizeText(bytes) {
  return bytes >= 1048576 ? `${(bytes / 1048576).toFixed(1)} MB` : bytes >= 1024 ? `${Math.round(bytes / 1024)} KB` : `${bytes} B`;
}

async function listFolder(path) {
  if (filesBusy) return;
  filesBusy = true;
  $('files-path').textContent = `${path} · loading`;
  try {
    const {blob} = await deviceFile('files', path);
    const listing = JSON.parse(await blob.text());
    filesPath = path;
    const list = $('files-list');
    list.replaceChildren();
    const entries = [...listing.entries].sort((a, b) => (b.dir - a.dir) || a.name.localeCompare(b.name));
    for (const entry of entries) {
      const item = document.createElement('li');
      const button = document.createElement('button');
      button.type = 'button';
      button.className = entry.dir ? 'folder' : 'file';
      button.textContent = entry.dir ? `▸ ${entry.name}` : entry.name;
      const size = document.createElement('span');
      size.className = 'muted';
      size.textContent = entry.dir ? 'folder' : sizeText(entry.size);
      button.addEventListener('click', () => entry.dir ? listFolder(joinPath(path, entry.name)) : copyFile(joinPath(path, entry.name), entry.size));
      item.append(button, size);
      list.append(item);
    }
    if (!entries.length) list.textContent = 'Empty folder.';
    $('files-path').textContent = path + (listing.truncated ? ' · first 256 shown' : '') +
      (listing.skipped ? ` · ${listing.skipped} hidden` : '');
  } catch (error) {
    $('files-path').textContent = `${path} · ${error.message}`;
  } finally { filesBusy = false; }
}

async function copyFile(path, size) {
  if (size > 4 * 1024 * 1024) { feedback('Files over 4 MB are not copied over the PSP link.'); return; }
  $('files-preview-name').textContent = `Copying ${path} …`;
  $('files-image').hidden = true;
  $('files-text').hidden = true;
  $('files-save').hidden = true;
  try {
    const {name, blob} = await deviceFile('file', path);
    previewBlob = blob;
    previewName = path.slice(path.lastIndexOf('/') + 1) || name;
    if (previewUrl) URL.revokeObjectURL(previewUrl);
    previewUrl = null;
    if (/\.(png|bmp|jpg)$/i.test(name)) {
      previewUrl = URL.createObjectURL(blob);
      $('files-image').src = previewUrl;
      $('files-image').hidden = false;
    } else if (/\.(txt|json)$/i.test(name)) {
      const text = await blob.text();
      $('files-text').textContent = text.length > 65536 ? `… ${text.slice(-65536)}` : text;
      $('files-text').hidden = false;
      $('files-text').scrollTop = $('files-text').scrollHeight;
    }
    $('files-preview-name').textContent = `${path} · ${sizeText(blob.size)} · copied (${name})`;
    $('files-save').hidden = false;
  } catch (error) { $('files-preview-name').textContent = `${path} · ${error.message}`; }
}

// ----- the settings backup

function backupLine(item) {
  const row = document.createElement('li');
  const name = document.createElement('strong');
  name.textContent = item.name;
  const detail = document.createElement('span');
  detail.className = item.checked ? 'muted' : 'problem';
  detail.textContent = item.checked
    ? `${item.files} files · ${sizeText(item.bytes)} · every file matches the PSP's · custom theme ${item.theme ? 'included' : 'not installed'}` +
      (item.failed ? ` · ${item.failed} couldn't be copied on the PSP` : '')
    : `not usable: ${item.problem}`;
  const place = document.createElement('code');
  place.textContent = item.place;
  row.append(name, detail, place);
  return row;
}

async function loadBackups() {
  try {
    const {backups} = await api('/api/backups');
    const list = $('backup-list');
    list.replaceChildren(...backups.map(backupLine));
    if (!backups.length) list.textContent = 'No backups on this computer yet.';
  } catch (error) { $('backup-list').textContent = error.message; }
}

async function startBackup(folder) {
  try {
    const {started} = await api('/api/backup', folder ? {folder} : {});
    feedback(started ? 'Backing up the PSP settings…' : 'A backup is already running.');
    $('backup-card-list').hidden = true;
  } catch (error) { feedback(error.message); }
}

async function listCardBackups() {
  const list = $('backup-card-list');
  list.hidden = false;
  list.textContent = 'Looking in ms0:/BACKUP …';
  try {
    const {blob} = await deviceFile('files', 'ms0:/BACKUP');
    const folders = JSON.parse(await blob.text()).entries
      .filter(entry => entry.dir && /^flash1-\d{8}-\d{6}(-[2-9])?$/.test(entry.name))
      .sort((a, b) => b.name.localeCompare(a.name));
    list.replaceChildren();
    for (const entry of folders) {
      const item = document.createElement('li');
      const button = document.createElement('button');
      button.type = 'button';
      button.className = 'folder';
      button.textContent = `▸ ${entry.name}`;
      button.addEventListener('click', () => startBackup(`ms0:/BACKUP/${entry.name}`));
      item.append(button);
      list.append(item);
    }
    if (!folders.length) list.textContent = 'No backups on the Memory Stick yet. Press TRIANGLE in RemotePilot PSP to make one.';
  } catch (error) {
    list.textContent = `No backups on the Memory Stick yet (${error.message}).`;
  }
}

function backupRender(connected) {
  const available = Boolean(manifest?.capabilities.includes('backup'));
  $('backup-panel').hidden = !available;
  if (!available) return;
  const job = state?.backup;
  const working = job?.state === 'working';
  for (const id of ['backup-make', 'backup-card']) $(id).disabled = !connected || working;
  $('backup-step').textContent = job ? job.step : connected ? 'Ready' : 'Connect the PSP first';
  $('backup-step').className = job?.state === 'failed' ? 'problem' : job?.state === 'done' ? 'good' : 'muted';
  // a finished job: show the copies kept here, once
  const seen = job && job.state !== 'working' ? `${job.state}:${job.result?.name || job.step}` : '';
  if (seen && seen !== backupSeen) {
    backupSeen = seen;
    feedback(job.state === 'done' ? `PSP settings backed up and checked: ${job.result.name}` : `Backup failed: ${job.step}`);
    loadBackups();
  }
}

// ----- local bug reports

async function loadReports() {
  try {
    const {reports} = await api('/api/bug-reports');
    const list = $('bug-saved');
    list.replaceChildren(...reports.slice(0, 5).map(item => {
      const row = document.createElement('li');
      const name = document.createElement('strong');
      name.textContent = item.name;
      const files = document.createElement('span');
      files.className = 'muted';
      files.textContent = item.files.join(', ');
      const place = document.createElement('code');
      place.textContent = item.place;
      row.append(name, files, place);
      return row;
    }));
  } catch (error) { $('bug-result').textContent = error.message; }
}

async function saveReport() {
  try {
    const {started} = await api('/api/bug-report', {what: $('bug-what').value, steps: $('bug-steps').value,
      expected: $('bug-expected').value, include: $('bug-include').checked});
    $('bug-result').textContent = started ? 'Saving…' : 'A report is already being saved.';
  } catch (error) { $('bug-result').textContent = error.message; }
}

function reportRender() {
  const job = state?.bugReport;
  $('bug-save').disabled = job?.state === 'working';
  const seen = job && job.state !== 'working' ? `${job.state}:${job.result?.name || job.step}` : '';
  if (seen && seen !== reportSeen) {
    reportSeen = seen;
    const text = job.state === 'done' ? `Saved on this computer: ${job.result.place}` : job.step;
    $('bug-result').textContent = text;
    feedback(text);
    if (job.state === 'done') for (const id of ['bug-what', 'bug-steps', 'bug-expected']) $(id).value = '';
    loadReports();
  }
}

// ----- the PSP guide: one step at a time, what to do on the PSP and here

const COPIED_KEY = 'remotepilot-psp-pairing-copied';

function copiedPairing() {
  try { return localStorage.getItem(COPIED_KEY) === '1'; } catch (_) { return false; }
}

function markCopied(value) {
  try { value ? localStorage.setItem(COPIED_KEY, '1') : localStorage.removeItem(COPIED_KEY); } catch (_) {}
}

function guideFlow() {
  const connected = Boolean(state?.connected && state.linkEnabled);
  if (connected) markCopied(true);
  if (!state?.session) return {
    stage: 0, tone: 'action', badge: 'Your next action', title: 'Pair this PC with your PSP',
    cue: 'Nothing yet', psp: 'Leave the PSP for now.',
    pc: 'Press Prepare pairing. It makes a private pairing file only your PSP and this PC share.',
    actions: [['Prepare pairing', () => $('prepare').click()]],
    next: 'Next: copy that file to the Memory Stick.'};
  if (!copiedPairing()) return {
    stage: 1, tone: 'action', badge: 'Your next action', title: 'Copy the pairing file to the Memory Stick',
    cue: 'Card in the PC', psp: 'Put the Memory Stick in this PC\'s card reader (or connect the PSP over USB).',
    pc: `Press Copy to card and choose the Memory Stick. It writes ${(manifest?.setup?.deviceConfigPath || 'ms0:/remotepilot/remotepilot.cfg').replace('ms0:/', '')}. Treat that file like a password.`,
    actions: [['Copy to card', () => ($('install-config').hidden ? $('download-config') : $('install-config')).click()],
              ['I copied it', () => { markCopied(true); guideRender(); }]],
    next: 'Next: put the card back in the PSP and start RemotePilot PSP.'};
  if (!connected) return {
    stage: 2, tone: 'wait', badge: 'Waiting for the PSP', title: 'Start RemotePilot PSP and press ✕ Connect',
    cue: 'Press ✕ Connect',
    psp: 'Game → Memory Stick → RemotePilot PSP. Turn the WLAN switch on, then press ✕ on its home screen. It shows its address when it\'s on your Wi-Fi.',
    pc: `This page looks for it by itself (${state?.discovery || 'searching'}). If it doesn't find it, type the address the PSP shows.`,
    actions: [['Type the address', () => { $('manual-host-row').hidden = false; $('setup').hidden = false; $('device-host').focus(); }],
              ['Search again', () => $('retry').click()]],
    next: 'Next: the PSP says Connected and this card turns green.'};
  return {
    stage: 4, tone: 'done', badge: 'Connected', title: 'Your PSP is connected',
    cue: 'Keep it on Connect', psp: 'Leave RemotePilot PSP open on its Connect screen. ○ goes back without disconnecting.',
    pc: 'Live view, screenshots, folders and the settings backup are ready.',
    actions: [['Back up PSP settings', () => startBackup(null)], ['Live view', () => { $('live').checked = true; $('live').dispatchEvent(new Event('change')); }]],
    next: 'To restore: on the PSP press □ Restore. Only the PSP can put settings back.'};
}

let guideStage = -1;

function guideRender() {
  const show = manifest?.display?.layout === 'psp';
  $('psp-guide').hidden = !show;
  if (!show) return;
  const flow = guideFlow();
  $('psp-guide').dataset.tone = flow.tone;
  $('guide-badge').querySelector('b').textContent = flow.badge;
  $('guide-title').textContent = flow.title;
  $('guide-cue').textContent = flow.cue;
  $('guide-psp').textContent = flow.psp;
  $('guide-pc').textContent = flow.pc;
  $('guide-next').textContent = `↳ ${flow.next}`;
  $('guide-status').textContent = $('setup-result').textContent;
  [...$('guide-steps').children].forEach((step, k) => {
    step.className = k < flow.stage ? 'done' : k === flow.stage ? 'current' : '';
  });
  // the buttons only change with the step, so a click isn't lost to a redraw
  if (guideStage !== flow.stage) {
    guideStage = flow.stage;
    $('guide-actions').replaceChildren(...flow.actions.map(([label, run], k) => {
      const button = document.createElement('button');
      button.type = 'button';
      button.className = k ? 'secondary' : '';
      button.textContent = label;
      button.addEventListener('click', run);
      return button;
    }));
  }
}

function toggleOptions(open) {
  $('options-menu').hidden = !open;
  $('options-open').setAttribute('aria-expanded', String(open));
}

function pspRender() {
  const files = Boolean(manifest?.capabilities.includes('files'));
  $('files-panel').hidden = !files;
  const connected = Boolean(state?.connected && state.linkEnabled);
  for (const id of ['files-up', 'files-refresh', 'files-logs', 'files-games', 'files-pictures'])
    $(id).disabled = !files || !connected;
  $('psp-label').textContent = state?.meta?.label || manifest?.name || 'PSP';
  $('psp-link-light').classList.toggle('on', connected);
  backupRender(connected);
  reportRender();
  guideRender();
}

$('options-open').addEventListener('click', () => toggleOptions($('options-menu').hidden));
document.addEventListener('click', event => {
  if (!event.target.closest('.options')) toggleOptions(false);
});
document.addEventListener('keydown', event => { if (event.key === 'Escape') toggleOptions(false); });
$('bug-report').addEventListener('click', () => {
  toggleOptions(false);
  $('bug-result').textContent = '';
  $('bug-dialog').showModal();
  loadReports();
});
$('bug-save').addEventListener('click', saveReport);
$('bug-close').addEventListener('click', () => $('bug-dialog').close());
$('bug-bundle').addEventListener('click', async () => {
  toggleOptions(false);
  try {
    const diagnostic = manifest?.capabilities.includes('log') ? 'log' : manifest?.capabilities.includes('report') ? 'report' : null;
    await api('/api/capture', {diagnostic});
    feedback('Saving a bug capture (screen' + (diagnostic ? ` + ${diagnostic}` : '') + '). It appears under Requests and captures.');
  } catch (error) { feedback(error.message); }
});
$('files-up').addEventListener('click', () => listFolder(parentPath(filesPath)));
$('files-refresh').addEventListener('click', () => listFolder(filesPath));
$('files-logs').addEventListener('click', () => listFolder('ms0:/halo/log'));
$('files-games').addEventListener('click', () => listFolder('ms0:/PSP/GAME'));
$('files-pictures').addEventListener('click', () => listFolder('ms0:/PICTURE'));
$('files-save').addEventListener('click', () => { if (previewBlob) saveBlob(previewBlob, previewName); });
$('backup-make').addEventListener('click', () => startBackup(null));
$('backup-card').addEventListener('click', listCardBackups);
$('backup-refresh').addEventListener('click', loadBackups);
loadBackups();
setInterval(pspRender, 1000);
