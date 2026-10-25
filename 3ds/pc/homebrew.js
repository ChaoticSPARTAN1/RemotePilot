// Homebrew-v1 UI stays separate from game input, controller and capture code.
(() => {
  'use strict';
  const el = id => document.getElementById(id);
  const companionTitle = '000400000f3d5200', updaterTitle = '000400000f3d5300';
  const owner = Array.from(crypto.getRandomValues(new Uint8Array(16)), n => n.toString(16).padStart(2, '0')).join('');
  let snapshot = {}, busy = false, armBusy = false, polling = false, lastPreset = '', autonomyRequest = null, inventoryConnection = '';
  const transferTiming = window.RemotePilotHomebrewFlow.createTransferTracker();
  const focused = () => !document.hidden && document.hasFocus();
  const message = text => { el('hb-feedback').textContent = text; };
  async function api(action, data = {}) {
    const result = await fetch('/api/homebrew/' + action, {method: 'POST',
      headers: {'Content-Type': 'application/json', 'X-Remote-Pilot-Viewer': '1'}, body: JSON.stringify(data)});
    if (!result.ok) throw new Error(await result.text() || 'Homebrew request failed');
    return result.json();
  }
  async function run(action) {
    try { await action(); } catch (error) { message(error.message); }
  }
  function render() {
    const selected = el('game-preset').value;
    document.body.classList.toggle('homebrew-mode', selected === 'homebrew');
    if (selected === 'homebrew') el('intro').textContent = 'Update over Wi-Fi. Follow the current step below and keep the 3DS app open.';
    if (selected !== lastPreset) {
      if (selected === 'homebrew') el('homebrew-panel').open = true;
      else if (lastPreset === 'homebrew' && snapshot.handoff?.state !== 'launching') el('homebrew-panel').open = false;
      lastPreset = selected;
    }
    const caps = new Set(snapshot.capabilities || []);
    if (snapshot.connected) {
      const role = snapshot.updater ? 'recovery' : 'main';
      if (document.documentElement.dataset.homebrewApp !== role) {
        document.documentElement.dataset.homebrewApp = role;
        document.dispatchEvent(new CustomEvent('remote-pilot-homebrew-app-changed'));
      }
    }
    el('homebrew-section').dataset.app = snapshot.updater ? 'recovery' : 'main';
    const guide = window.RemotePilotHomebrewFlow.flow(snapshot);
    const view = window.RemotePilotHomebrewFlow.presentation(snapshot, guide);
    if (el('hb-deployment-name')) {
      el('hb-guide').dataset.tone = view.tone;
      el('hb-guide').classList.toggle('hb-no-progress', !view.showProgress);
      el('hb-deployment-name').textContent = view.name;
      el('hb-deployment-subtitle').textContent = view.subtitle;
      el('hb-phase-badge').textContent = view.badge;
      el('hb-action-location').textContent = view.location;
      el('hb-action-heading').textContent = view.instruction;
      el('hb-after').textContent = view.next;
      el('hb-flow-steps').hidden = !view.showSteps;
      Array.from(el('hb-flow-steps').children).forEach((step,i) => {
        step.dataset.state = view.steps[i].state;
        if (view.steps[i].state === 'current') step.setAttribute('aria-current','step');
        else step.removeAttribute('aria-current');
        step.querySelector('.hb-step-number').textContent = view.steps[i].state === 'complete' ? '✓' : i+1;
        step.querySelector('span:nth-child(2)').textContent=view.steps[i].label;
        step.querySelector('small').textContent = view.steps[i].status || {complete:'Confirmed',current:'Now',stopped:'Check status',pending:'Next'}[view.steps[i].state];
      });
      el('hb-transfer-card').hidden = !view.showProgress;
      el('hb-progress-phase').textContent = view.phase;
      el('hb-percent').textContent = view.percent == null ? '—' : `${view.percent.toFixed(1)}%`;
    }
    const inputCommand = guide.stage === 'awaiting-approval' ? 'PRESS A ON YOUR 3DS' : guide.stage === 'repair-updater' ? 'REPAIR ON YOUR 3DS' : ['clear-launch','review-console','acknowledge-result'].includes(guide.stage) ? 'PRESS B ON YOUR 3DS' : guide.stage === 'arm' ? 'PRESS X ON YOUR 3DS' : guide.stage === 'connect' ? 'OPEN REMOTEPILOT ON YOUR 3DS' : '';
    el('hb-input-cue').hidden = !inputCommand;
    if (el('hb-input-command').textContent !== inputCommand) el('hb-input-command').textContent = inputCommand;
    el('hb-guide').classList.toggle('hb-input-required', Boolean(inputCommand));
    el('hb-guide').classList.toggle('hb-pc-input-required', guide.action !== 'none' && guide.stage !== 'ready');
    el('hb-new-transfer').hidden = guide.action !== 'choose-file';
    el('hb-new-transfer').disabled = busy || !snapshot.armed || !caps.has('upload');
    const localKind = guide.action === 'send-helper' ? 'updater' : guide.action === 'send-main' ? 'companion' : null;
    const localBuild = localKind && snapshot.localUpdates?.[localKind];
    const acknowledge = inputCommand === 'PRESS B ON YOUR 3DS';
    el('hb-state').textContent = snapshot.connected ? acknowledge ? 'Connected · press B' : (snapshot.armed ? 'Connected · armed' : 'Connected · press X') : 'Waiting for 3DS';
    el('homebrew-title').textContent = snapshot.connected ? snapshot.updater ? 'Recovery updater connected' : 'Your 3DS, connected' : 'Waiting for your 3DS';
    el('hb-detail').textContent = snapshot.connected ? 'Your paired 3DS is connected.' : 'Keep the companion open on your 3DS. The page is waiting for a connection.';
    el('hb-next-title').textContent = guide.title;
    el('hb-next-console').textContent = guide.console;
    el('hb-next-pc').textContent = guide.pc;
    for (const [id, action] of [['hb-update-helper','send-helper'],['hb-open-updater','open-helper'],['hb-update-main','send-main'],['hb-open-companion','open-main']]) el(id).hidden = guide.action !== action;
    if (localBuild) {
      el(localKind === 'updater' ? 'hb-update-helper' : 'hb-update-main').hidden = true;
      el('hb-next-pc').textContent = `Verified ${localKind === 'updater' ? 'recovery updater' : 'companion'} build ${localBuild.version} is ready on this PC. Use the button below to send it.`;
    }
    el('hb-next-update').hidden = !localBuild;
    el('hb-next-update').disabled = busy || !snapshot.armed || !caps.has('upload') || !caps.has('install');
    el('hb-next-update').textContent = localKind === 'updater' ? guide.stage === 'update-helper' ? 'Update recovery updater' : 'Install recovery updater' : 'Update RemotePilot';
    el('hb-next-inspect').hidden = guide.action !== 'inspect';
    if (el('hb-open-installed')) {
      el('hb-open-installed').hidden = guide.action !== 'open-installed';
      el('hb-open-installed').disabled = busy || !snapshot.armed || !caps.has('launch');
    }
    const guideProgress = view.progressJob;
    el('hb-next-progress').hidden = !view.showProgress;
    if (view.showProgress) {
      el('hb-next-progress').max = Math.max(1, guideProgress.total || 1);
      el('hb-next-progress').value = view.percent / 100 * guideProgress.total;
      el('hb-next-progress').setAttribute('aria-label', view.phase);
      el('hb-next-progress').setAttribute('aria-valuetext', `${view.percent.toFixed(1)} percent`);
    }
    el('hb-next-progress-text').textContent = view.showProgress ? `${((view.percent === 100 ? guideProgress.total : guideProgress.done || 0) / 1048576).toFixed(1)} MiB of ${(guideProgress.total / 1048576).toFixed(1)} MiB` : '';
    const timing = el('hb-transfer-eta');
    const timingInfo = transferTiming(guideProgress, performance.now(), snapshot.connected, true);
    if (timing) {
      timing.textContent = timingInfo ? timingInfo.state === 'waiting' ? 'Waiting for new progress from the console. The estimate will return when bytes advance.' : timingInfo.state === 'calculating' ? 'Measuring recent speed. Your transfer is continuing.' : 'Estimate uses recent transfer speed. File checking and installation follow.' : '';
      timing.hidden = !timingInfo;
    }
    if (el('hb-transfer-metrics')) {
      el('hb-transfer-metrics').hidden = !timingInfo;
      if (timingInfo) {
        el('hb-eta-value').textContent = timingInfo.eta;
        el('hb-speed-value').textContent = timingInfo.speed;
        el('hb-elapsed-value').textContent = timingInfo.elapsed;
        if (timingInfo.state === 'waiting' && el('hb-phase-badge')) {
          el('hb-phase-badge').textContent = 'Waiting for progress';
          el('hb-guide').dataset.tone = 'warning';
        }
      }
    }
    for (const button of document.querySelectorAll('[data-hb-cap]')) button.disabled = busy || !caps.has(button.dataset.hbCap) ||
      (button.dataset.hbCap === 'upload' && !snapshot.armed);
    const updater = snapshot.updater === true;
    const activeJob = (snapshot.jobs || []).some(job => !['uploaded', 'installed', 'cancelled', 'failed', 'unknown', 'interrupted', 'launching'].includes(job.state));
    const needsReview=snapshot.remoteJob?.state==='unknown'||(snapshot.jobs||[]).some(job=>['unknown','interrupted'].includes(job.state));
    if (el('hb-autonomy')) {
      const supported=snapshot.autonomousSupported===true, automatic=snapshot.autonomousEnabled===true;
      if(autonomyRequest!==null&&snapshot.connected&&automatic===autonomyRequest)autonomyRequest=null;
      el('hb-autonomy').dataset.tone=automatic?'ready':'neutral';
      el('hb-autonomy-badge').textContent=!snapshot.connected?'Mode not confirmed':automatic?'Autonomous ON':'Manual · press A';
      el('hb-autonomy-detail').textContent=!snapshot.connected?'Reconnect the companion to confirm its install approval mode.':
        !supported?'This installed companion uses A for every install. Autonomous mode requires the newer companion build; the current transfer keeps its original approval mode.':
        automatic?'The paired PC or AI can send, check and install new updates without an A press for each one. Title, version, SHA-256 and storage checks still apply.':
        'Manual mode asks for A on each checked update. To opt into autonomous installs, use the button below, then press Y on the 3DS once.';
      el('hb-autonomy-setup').hidden=!snapshot.connected||!supported;
      el('hb-autonomy-setup').disabled=!snapshot.armed||(!automatic&&(activeJob||needsReview));
      el('hb-autonomy-setup').textContent=automatic?'Turn off autonomous installs':'Enable autonomous installs for this session';
      el('hb-autonomy-cue').hidden=autonomyRequest===null||!snapshot.connected||!supported;
      el('hb-autonomy-cue-detail').textContent=`Waiting for your 3DS to confirm autonomous mode ${autonomyRequest?'ON':'OFF'}…`;
      el('hb-autonomy-next').textContent=automatic?'Y turns this mode off. Disarming, restarting or 15 minutes without job activity removes permission. An update already being written must finish or be cancelled on the console.':
        needsReview?'Next: follow the previous-outcome review instruction above before enabling autonomous mode.':!snapshot.armed?'Next: press X on the 3DS to arm the session first.':activeJob?'Next: finish this job before enabling autonomous mode. No current manual job is approved retroactively.':
        'Next: choose manual approval or opt in for this session. Turn Luma input injection off before changing mode; the console confirms the choice.';
    }
    for (const id of ['hb-update-helper-send', 'hb-open-updater']) el(id).disabled ||= updater || !snapshot.armed || activeJob;
    for (const id of ['hb-update-main-send', 'hb-open-companion']) el(id).disabled ||= !updater || !snapshot.armed || activeJob;
    el('hb-update-state').textContent = !snapshot.connected ? 'Open the companion or recovery updater to connect.' :
      `${updater ? 'Recovery updater' : 'Main companion'} connected${snapshot.buildVersion == null ? ' · bootstrap build' : ` · build ${snapshot.buildVersion}`}. ${acknowledge ? 'Press B to acknowledge the previous result.' : snapshot.armed ? 'Session armed.' : 'Press X on the 3DS.'}`;
    const armed = el('hb-system-arm').checked && focused() && snapshot.system?.armed === true && !activeJob;
    if(el('hb-system-guide')) {
      el('hb-system-guide').dataset.tone=activeJob?'waiting':armed?'ready':'neutral';
      el('hb-system-guide-title').textContent=activeJob?'System input is off during installation':armed?'System controls armed':!focused()?'Input paused · tab not focused':'Set up system input';
      el('hb-system-guide-text').textContent=activeJob?'Keep RemotePilot open. Finish the current deployment before using HOME Menu input.':armed?'Use a bounded button or touch press below. The console receives Luma input; this page cannot confirm delivery.':'On the 3DS, enable Luma InputRedirection. Then check the arm switch below and keep this tab focused.';
      el('hb-system-guide-next').textContent=activeJob?'Next: follow the current install step above.':'Next: watch the actual 3DS response. Release system input or disable InputRedirection when finished.';
    }
    for (const button of document.querySelectorAll('[data-hb-button], #hb-home, #hb-touch button')) button.disabled = !armed;
    const rows = (snapshot.jobs || []).slice(-3).reverse().map(job => {
      const row = document.createElement('div'); row.className = 'hb-job';
      const details = document.createElement('details'), summary = document.createElement('summary');
      const names = {'awaiting-approval':'Press A on the 3DS',unknown:'Transfer needs checking',cancelled:'Transfer cancelled',installed:'Installation complete',uploading:'Transferring',verifying:'Checking file',rechecking:'Rechecking file',installing:'Installing',failed:'Stopped',launching:'Opening app',interrupted:'Transfer needs checking'};
      summary.textContent = `${job.titleId === updaterTitle ? 'Recovery updater' : job.titleId === companionTitle ? 'RemotePilot' : job.titleId === '000400000f3d5000' ? 'Morrowind · Guidebook' : 'Application'} · ${names[job.state] || job.state} · details`;
      details.append(summary);
      const text = document.createElement('p');
      text.textContent = `${job.id.slice(0, 8)} · ${job.state} · ${job.titleId} v${job.version ?? '?'} · ${job.done || 0}/${job.total || 0} bytes · ${job.detail || job.error || ''}`;
      details.append(text); row.append(details);
      const inspect = document.createElement('button'); inspect.textContent = 'Inspect console outcome';
      inspect.addEventListener('click', () => run(async () => { await api('inspect', {id: job.id}); await poll(); })); details.append(inspect);
      if (!['uploaded', 'installed', 'cancelled', 'failed', 'unknown', 'interrupted', 'launching'].includes(job.state)) {
        const cancel = document.createElement('button'); cancel.textContent = 'Request cancellation';
        cancel.addEventListener('click', () => run(async () => { message((await api('cancel', {id: job.id})).detail); })); details.append(cancel);
      }
      return row;
    });
    el('hb-jobs').replaceChildren(...rows);
    const titles = (snapshot.titles || []).map(title => {
      const row = document.createElement('div'); row.className = 'hb-title';
      const label = document.createElement('span'); label.textContent = `${title.titleId} · version ${title.version} `;
      const launch = document.createElement('button'); launch.textContent = 'Launch'; launch.disabled = !caps.has('launch') || !snapshot.armed;
      launch.addEventListener('click', () => run(async () => {
        await disarm();
        await api('launch', {titleId: title.titleId, preset: el('hb-handoff').value});
        message('Launch prepared. Waiting for the new application; a companion disconnect is expected.');
        await poll();
      }));
      row.append(label, launch); return row;
    });
    el('hb-title-list').replaceChildren(...titles);
    window.RemotePilotGameData?.render(snapshot);
    window.RemotePilotDiagnostics?.render(snapshot);
    const handoff = snapshot.handoff;
    el('hb-handoff-state').textContent = handoff ? `${handoff.state}: ${handoff.detail}` : '';
  }
  async function poll() {
    if (polling) return;
    polling = true;
    try {
      const response = await fetch('/api/homebrew/status', {cache: 'no-store'});
      if (!response.ok) throw new Error(await response.text());
      snapshot = await response.json();
      const connection = snapshot.connected ? `${snapshot.applicationTitleId}:${snapshot.buildVersion}` : '';
      if (!connection) inventoryConnection = '';
      if (connection && connection !== inventoryConnection && snapshot.capabilities?.includes('titles')) {
        // FBI can update titles outside this job history. Refresh read-only
        // inventory on each new app connection before deriving setup steps.
        try {
          snapshot.titles = (await api('titles')).titles;
          inventoryConnection = connection;
        } catch (error) { message(`Could not refresh installed apps: ${error.message}`); }
      }
      const remote = snapshot.remoteJob;
      const interrupted = snapshot.jobs?.find(job => job.id === remote?.id &&
        ['unknown','interrupted'].includes(job.state) && job.titleId === remote.titleId &&
        job.version === remote.version && job.total === remote.total);
      if (snapshot.connected && interrupted && ['failed','cancelled','installed'].includes(remote.state)) {
        // Read the exact receipt after console acknowledgement; do not replay
        // any install, clear unknown outcomes, or invent completion from bytes.
        try {
          const checked = (await api('inspect',{id:remote.id})).job;
          Object.assign(interrupted,checked);
        } catch (error) { message(`Could not check the previous outcome: ${error.message}`); }
      }
      render();
    } catch (error) {
      snapshot = {...snapshot,connected:false,armed:false,detail:'The PC receiver is unavailable. Keep RemotePilot open on your 3DS while this page reconnects.'};
      render();
      el('hb-detail').textContent = snapshot.detail;
    }
    finally { polling = false; }
  }
  el('hb-pair').addEventListener('submit', event => {
    event.preventDefault(); run(async () => {
      const data = new FormData(event.target);
      const result = await api('configure', {host: data.get('host').trim(), port: 38765});
      message(result.existingPairing ? 'Console address updated. Existing pairing kept; no SD card copying is needed.' :
        `Prepared local/homebrew/${result.pairingFile}. Copy it to the companion folder on the verified SD card, then relaunch the companion.`);
      await poll();
    });
  });
  el('hb-next-inspect').addEventListener('click', () => run(async () => {
    const guide = window.RemotePilotHomebrewFlow.flow(snapshot);
    if (guide.action === 'inspect' && guide.job) await api('inspect', {id:guide.job.id});
    await poll();
  }));
  el('hb-new-transfer').addEventListener('click', () => {
    el('hb-advanced').open = true;
    el('hb-upload').scrollIntoView({block:'center',behavior:'smooth'});
    el('hb-upload').querySelector('input[name="file"]').focus();
    message('Choose a CIA app, enter its expected title ID, then choose whether to install it. Nothing transfers until you submit.');
  });
  el('hb-autonomy-setup')?.addEventListener('click', () => {
    autonomyRequest=!(snapshot.autonomousEnabled===true);
    render();
  });
  el('hb-next-update').addEventListener('click', () => run(async () => {
    const guide = window.RemotePilotHomebrewFlow.flow(snapshot);
    const kind = guide.action === 'send-helper' ? 'updater' : guide.action === 'send-main' ? 'companion' : null;
    if (!kind) return;
    busy = true; render();
    try { await disarm(); await api('update', {kind}); message('Transfer started. Follow “On your 3DS now” above.'); }
    finally { busy = false; await poll(); }
  }));
  el('hb-open-installed')?.addEventListener('click', () => run(async () => {
    const guide = window.RemotePilotHomebrewFlow.flow(snapshot);
    if (guide.action !== 'open-installed') return;
    await disarm();
    const titleId = guide.job.titleId;
    await api('launch', {titleId, preset:titleId === '000400000f3d5000' ? 'morrowind' : ''});
    message('Opening the updated application. Watch your 3DS while the connection changes.');
    await poll();
  }));
  async function upload(file, title, install) {
      if (!file || file.size > 512 * 1024 * 1024) throw new Error('Choose a CIA no larger than 512 MiB');
      if (!crypto.subtle) throw new Error('Browser hashing needs the PC viewer at http://127.0.0.1:38764/. URL downloads are also available.');
      busy = true; render();
      try {
        message('Hashing the selected CIA on this PC…');
        const digest = await crypto.subtle.digest('SHA-256', await file.arrayBuffer());
        const sha = Array.from(new Uint8Array(digest), n => n.toString(16).padStart(2, '0')).join('');
        const response = await fetch('/api/homebrew/file', {method: 'POST', body: file, headers: {
          'Content-Type': 'application/octet-stream', 'X-Remote-Pilot-Viewer': '1',
          'X-File-Sha256': sha, 'X-Title-Id': title, 'X-Install': install ? '1' : '0'}});
        if (!response.ok) throw new Error(await response.text());
        const value = await response.json(); message(`Deployment ${value.id.slice(0, 8)} queued. Follow its verified stages below.`);
      } finally { busy = false; await poll(); }
  }
  el('hb-upload').addEventListener('submit', event => {
    event.preventDefault(); run(async () => {
      const form = new FormData(event.target);
      await upload(form.get('file'), form.get('titleId').trim().toLowerCase(), form.has('install'));
    });
  });
  for (const [formId, title] of [['hb-update-helper', updaterTitle], ['hb-update-main', companionTitle]]) {
    el(formId).addEventListener('submit', event => {
      event.preventDefault(); run(async () => {
        await disarm();
        await upload(new FormData(event.target).get('file'), title, true);
      });
    });
  }
  for (const [buttonId, title] of [['hb-open-updater', updaterTitle], ['hb-open-companion', companionTitle]]) {
    el(buttonId).addEventListener('click', () => run(async () => {
      await disarm();
      await api('launch', {titleId: title});
      message('Launch prepared. Wait for the target app to connect, then press X on the 3DS.');
      await poll();
    }));
  }
  el('hb-download').addEventListener('submit', event => {
    event.preventDefault(); run(async () => {
      const form = new FormData(event.target);
      const result = await api('download', {url: form.get('url').trim(), sha256: form.get('sha256').trim().toLowerCase(),
        titleId: form.get('titleId').trim().toLowerCase(), install: form.has('install')});
      message(`Download ${result.id.slice(0, 8)} queued.`); await poll();
    });
  });
  el('hb-titles').addEventListener('click', () => run(async () => { await api('titles'); await poll(); }));
  async function disarm() {
    el('hb-system-arm').checked = false; render();
    await api('system-release');
    el('hb-system-state').textContent = 'Neutral packets sent; console receipt is unacknowledged';
  }
  async function lease() {
    if (!el('hb-system-arm').checked || !focused() || armBusy) return;
    armBusy = true;
    try {
      await api('system-arm', {enabled: true, owner, inputRedirectionEnabled: true, version: el('hb-luma-version').value.trim()});
      el('hb-system-state').textContent = 'Armed · bounded presses · UDP receipt unacknowledged';
    } catch (error) { el('hb-system-arm').checked = false; message(error.message); }
    finally { armBusy = false; render(); }
  }
  el('hb-system-arm').addEventListener('change', () => run(async () => { if (el('hb-system-arm').checked) await lease(); else await disarm(); }));
  for (const button of document.querySelectorAll('[data-hb-button]')) button.addEventListener('click', () => run(async () => {
    await api('system-input', {owner, button: button.dataset.hbButton});
  }));
  el('hb-home').addEventListener('click', () => run(async () => { await api('system-input', {owner, home: true}); }));
  el('hb-release').addEventListener('click', () => run(disarm));
  el('hb-touch').addEventListener('submit', event => {
    event.preventDefault(); run(async () => {
      const form = new FormData(event.target); await api('system-input', {owner, touch: [Number(form.get('x')), Number(form.get('y'))]});
    });
  });
  window.addEventListener('blur', () => { if (el('hb-system-arm').checked) run(disarm); });
  document.addEventListener('visibilitychange', () => { if (!focused() && el('hb-system-arm').checked) run(disarm); });
  window.addEventListener('pagehide', () => { fetch('/api/homebrew/system-release', {method: 'POST', keepalive: true,
    headers: {'Content-Type': 'application/json', 'X-Remote-Pilot-Viewer': '1'}, body: '{}'}).catch(() => {}); });
  window.RemotePilotGameData?.init();
  window.RemotePilotDiagnostics?.init();
  setInterval(lease, 500); setInterval(poll, 1000); poll();
})();
