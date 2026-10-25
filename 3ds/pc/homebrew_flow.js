// Human instructions are derived from confirmed job and application states.
((root) => {
  'use strict';
  const main = '000400000f3d5200', helper = '000400000f3d5300';
  const terminal = new Set(['installed','uploaded','cancelled','failed','unknown','interrupted','launching']);
  function duration(seconds) {
    const minutes = Math.ceil(seconds / 60);
    if (minutes < 1) return 'less than 1 min';
    if (minutes < 60) return `${minutes} min`;
    return `${Math.floor(minutes / 60)} hr${minutes % 60 ? ` ${minutes % 60} min` : ''}`;
  }
  function createTransferTracker() {
    let current;
    return (job, now, connected = true, structured = false) => {
      let elapsedLabel = 'less than 1 min';
      const result = (text, eta = 'Calculating…', speed = '—', state = 'calculating') =>
        structured ? {text,eta,speed,elapsed:elapsedLabel,state} : text;
      if (!connected || !job || job.state !== 'uploading' || !job.id ||
          !Number.isFinite(now) || !Number.isFinite(job.done) || !Number.isFinite(job.total) ||
          job.total <= 0 || job.done < 0 || job.done > job.total) {
        current = undefined;
        return structured ? null : '';
      }
      if (!current || current.id !== job.id || current.total !== job.total ||
          job.done < current.done || now < current.lastTime) {
        current = {id:job.id,total:job.total,done:job.done,start:now,lastTime:now,
          lastAdvance:now,samples:[{time:now,done:job.done}]};
      }
      if (job.done > current.done) current.lastAdvance = now;
      current.done = job.done;
      if (now > current.lastTime) current.samples.push({time:now,done:job.done});
      current.lastTime = now;
      while (current.samples.length > 2 && current.samples[1].time <= now - 60000) current.samples.shift();
      const elapsed = Math.floor((now-current.start)/60000);
      elapsedLabel = elapsed < 1 ? 'less than 1 min' : duration(elapsed*60);
      const observed = `Elapsed on this page: ${elapsedLabel}`;
      if (job.done === job.total) return result(`Transfer sent · ${observed}. File checking and installation follow.`, 'File sent', '—', 'sent');
      if (now-current.lastAdvance >= 15000) return result(`Waiting for transfer progress · ETA unavailable · ${observed}`, 'Waiting for progress', '—', 'waiting');
      const first = current.samples[0], span = (now-first.time)/1000;
      const rate = span >= 5 ? (job.done-first.done)/span : 0;
      if (rate <= 0) return result(`Calculating transfer ETA… · ${observed}`);
      const speed = rate >= 1048576 ? `${(rate/1048576).toFixed(1)} MiB/s` : `${(rate/1024).toFixed(1)} KiB/s`;
      const eta = `About ${duration((job.total-job.done)/rate)}`;
      return result(`${eta} remaining · ${speed} · ${observed}. Transfer only; file checking, approval and installation follow.`, eta, speed, 'measured');
    };
  }
  function presentation(s, guide = flow(s)) {
    const automatic=(guide.progress||guide.job)?.approvalMode==='autonomous';
    const stages = ['Send','Check',automatic?'Auto mode':'Approve','Install','Ready'];
    const indices = {receiving:0,downloading:0,queued:0,uploading:0,verifying:1,'awaiting-approval':2,
      rechecking:3,installing:3,committing:3,'game-installed':4,'acknowledge-result':4,done:4};
    const index = indices[guide.stage];
    const problem = ['reconnect','review','review-console','failed','repair-updater'].includes(guide.stage);
    const job = guide.progress || guide.job || (problem ? s.jobs?.at(-1) : null);
    const completed = index === 4;
    const names = {[main]:'RemotePilot companion',[helper]:'Recovery updater','000400000f3d5000':'Morrowind · Guidebook'};
    const name = job ? names[job.titleId] || 'Application update' : s.updater ? 'RemotePilot recovery updater' : 'RemotePilot companion';
    const knownProgress = job && Number.isFinite(job.total) && job.total > 0;
    const percent = knownProgress ? completed || job.done >= job.total ? 100 : Math.min(99.9,Math.max(0,100*(job.done || 0)/job.total)) : null;
    const phases = {uploading:'File transfer',receiving:'Sending to this PC',downloading:'Downloading to this PC',
      verifying:'Checking file',rechecking:'Checking before install',installing:'Installation',committing:'Finishing installation','awaiting-approval':'File checked'};
    const next = {
      uploading:'Next: your 3DS checks the file, then asks you to approve it with A.',
      verifying:'Next: approve the checked update with A on your 3DS when prompted.',
      'awaiting-approval':'After you press A, the 3DS rechecks and installs the update. Keep this app open.',
      rechecking:'Next: installation starts after the file check. Keep the app and lid open.',
      installing:'Next: the installed version is checked before this page confirms completion.',
      committing:'Next: wait for the confirmed installation result before opening another app.',
      'game-installed':'Next: launch the updated application with the button above.',
      arm:'Next: the PC action becomes available when your 3DS confirms Session ARMED.',
      launching:'Next: watch the 3DS as the next app opens. The connection changes during the switch.',
      review:'Next: check the console outcome using the button above. A new transfer stays blocked.',
      reconnect:'Next: this page waits for the paired console. Keep the current 3DS app open.',
      ready:'Next: choose a CIA app on this PC. The transfer, file check and install approval each have their own step.',
      'recovery-ready':'Next: open the main companion for everyday CIA-app transfers. Recovery stays available for companion updates.',
      'acknowledge-result':'Next: both screens return to ready. The completed result stays in transfer history.',
      done:'Ready for your next wireless install. Keep RemotePilot open when using remote tools.'
    };
    return {name,subtitle:job?.version != null ? `Version ${job.version} · Wireless install` : 'Private PC → 3DS connection',
      percent,phase:problem ? 'Last confirmed progress' : phases[guide.stage] || (completed ? 'Installation confirmed' : 'Session status'),
      progressJob:job,showProgress:Boolean(knownProgress),showSteps:index != null || problem,
      steps:stages.map((label,i)=>({label,status:automatic&&i===2?'Session opt-in':null,state:problem ? i === 0 ? 'stopped' : 'pending' : index == null ? 'pending' : i < index || completed ? 'complete' : i === index ? 'current' : 'pending'})),
      badge:['ready','recovery-ready'].includes(guide.stage) ? 'Ready' : problem ? 'Needs attention' : guide.stage === 'awaiting-approval' ? 'Approval needed' : completed ? 'Confirmed' :
        guide.action !== 'none' || guide.stage === 'arm' || guide.stage === 'connect' || guide.stage === 'clear-launch' ? 'Your next action' : 'In progress',
      tone:problem ? 'warning' : guide.stage === 'awaiting-approval' ? 'approval' : completed ? 'complete' : 'normal',
      location:guide.action !== 'none' ? 'ON THIS PC' : 'ON YOUR 3DS',
      instruction:guide.action !== 'none' ? 'Use the button below' : guide.stage === 'awaiting-approval' ? 'Approval needed' :
        guide.stage === 'uploading' || guide.stage === 'verifying' || guide.stage === 'installing' || guide.stage === 'rechecking' || guide.stage === 'committing' ? 'Keep the app open' : 'Your next step',
      next:automatic&&['uploading','verifying'].includes(guide.stage)?'Next: the 3DS checks the file, then installs automatically under your session permission. No A press is needed.':
        next[guide.stage] || (guide.action !== 'none' ? 'After this PC action, follow the next instruction shown here. This page confirms each console response.' : 'Follow the instruction above. This page advances when the console confirms the change.')};
  }
  function flow(s) {
    const jobs = s.jobs || [], latest = jobs.at(-1), remote = s.remoteJob;
    const reviewed = latest?.reviewed === true || latest?.error === 'owner-reviewed-unknown-outcome' ||
      remote?.id === latest?.id && (['failed','installed'].includes(remote?.state) && remote.reviewed === true ||
        remote?.state === 'failed' && remote.error === 'owner-reviewed-unknown-outcome');
    const base = {stage:'connect', title:'Connect your 3DS', console:'Open RemotePilot on the 3DS and leave it open. Keep the lid open.', pc:'The page connects using your saved pairing.', action:'none', progress:null};
    if (latest?.state === 'failed' && !reviewed && latest.detail?.includes('receipt-write-failed') && !s.updater) return {...base, stage:'repair-updater', title:'One-time repair before the game update',
      console:'Exit RemotePilot with START. In FBI, open SD → 3ds → RemotePilotUpdater. Rename receipt.txt to receipt-reviewed-v3.txt. Then open RemotePilot Updater from HOME and press X.',
      pc:'The fixed companion is ready on this PC. The old receipt is preserved under its new name. This page advances when the recovery updater connects. No game file data was sent.'};
    if (s.handoff?.state === 'launching') return {...base, stage:'launching', title:'Opening the next app',
      console:[main,helper].includes(s.handoff.titleId) ? 'Wait for the next app to open on the 3DS, then press X once to arm it.' : 'Wait for the game to open on your 3DS. Follow any setup shown in the game.', pc:'A brief disconnect is expected while the app changes.'};
    if (!s.connected) return {...base, stage:latest && (!terminal.has(latest.state) || ['unknown','interrupted'].includes(latest.state)) ? 'reconnect' : 'connect', title:latest && !terminal.has(latest.state) ? 'Connection interrupted' : 'Waiting for your 3DS',
      console:'Keep RemotePilot open on the 3DS. Do not exit or start another install.', pc:s.detail || 'Waiting for the paired console to respond.'};
    const reviewedLaunch = remote?.state === 'unknown' && jobs.some(j => j.id === remote.id && j.state === 'launching') &&
      [main,helper].includes(remote.titleId) && (s.titles || []).some(t => t.titleId === remote.titleId && t.version >= remote.version);
    if (reviewedLaunch) return {...base, stage:'clear-launch', title:'Clear the previous app switch',
      console:'Press B once in RemotePilot on the 3DS, then leave it open.',
      pc:'The earlier RemotePilot update is verified installed. Reopening the app left its previous launch record waiting for review. B acknowledges that record; this page waits for confirmation.'};
    if (remote?.state === 'unknown') return {...base, stage:'review-console', title:'Review the previous console outcome', job:remote,
      console:'Check the previous title and result on the PC. Then press B on the 3DS to acknowledge it.',
      pc:'The console has an uncertain result. Acknowledgement does not retry the transfer or install it.'};
    if (latest && ['unknown','interrupted'].includes(latest.state)) return {...base, stage:'review', title:'Transfer needs checking', action:'inspect', job:latest,
      console:remote?.id === latest.id && ['uploading','cancelled','verified'].includes(remote.state) ? 'Keep RemotePilot open. Installation has not started for this transfer.' : 'Keep the app open. Check its job status before doing anything else.',
      pc:'The transfer stopped before its result could be confirmed. Check the console outcome before starting another transfer.'};
    const active = [...jobs].reverse().find(j => !terminal.has(j.state));
    if (active) {
      const stages = {
        receiving:['Sending file to the PC','Leave RemotePilot open. No button press is needed.'],
        downloading:['Downloading on the PC','Leave RemotePilot open. No button press is needed.'],
        queued:['Preparing transfer','Keep RemotePilot open. No button press is needed.'],
        uploading:['Transferring to your 3DS','Keep RemotePilot open. Do not exit. No button press is needed.'],
        verifying:['Checking the transferred file','Keep RemotePilot open. Wait for the approval screen.'],
        'awaiting-approval':['Your 3DS needs approval','Press A on the 3DS to install the title and version shown. B rejects it. Keep Luma InputRedirection off.'],
        rechecking:['Rechecking before installation','Wait on the 3DS. Keep the app and lid open.'],
        installing:['Installing on your 3DS','Wait. Keep the app and lid open until installation finishes.'],
        committing:['Finishing installation','Wait. Keep the app and lid open.']
      };
      const [title,console] = stages[active.state] || ['Working on the update','Keep the app open and wait.'];
      if(active.approvalMode==='autonomous'&&['verifying','rechecking','installing','committing'].includes(active.state))
        return {...base,stage:active.state,title:active.state==='verifying'?'Checking file for autonomous install':'Installing automatically on your 3DS',
          console:'Keep the app and lid open. This job uses the autonomous mode you enabled for this session. No A press is needed.',
          pc:'The paired console will recheck the file and confirm the installed version. This page follows the result.',progress:active,job:active};
      return {...base, stage:active.state, title, console, pc:active.state === 'awaiting-approval' ? 'Continue on the 3DS. This page will advance after installation.' : 'This page updates automatically.',
        progress:active, job:active};
    }
    if (!s.armed) return {...base, stage:'arm', title:'Arm this session on the 3DS',
      console:'Press X once in the open 3DS app. Wait until it says Session ARMED.', pc:'The install button becomes available when the console is armed.'};
    if (!s.updater && latest?.state === 'failed' && !reviewed && ![main,helper].includes(latest.titleId)) return {...base, stage:'failed', title:'Application transfer stopped',
      console:'Keep RemotePilot open. No new install will start automatically.',
      pc:latest.detail?.includes('receipt-write-failed') ? 'The 3DS could not save its transfer receipt. No game file data was sent. Repair RemotePilot before sending this update again.' : latest.detail || 'The console stopped this job. Check the result before starting another transfer.'};
    if (latest?.state === 'installed' && !reviewed && ![main,helper].includes(latest.titleId)) return {...base, stage:'game-installed', action:'open-installed', job:latest,
      title:latest.titleId === '000400000f3d5000' ? 'Morrowind Guidebook update installed' : 'Application update installed',
      console:'Keep RemotePilot open. Use the button below to launch the updated application.',
      pc:`Version ${latest.version} was installed and checked on your 3DS.`};
    const mainInstalled = [...jobs].reverse().find(j => j.titleId === main && j.state === 'installed');
    const helperVersion = s.localUpdates?.updater?.version || 0;
    const helperCurrent = (s.titles || []).some(t => t.titleId === helper && t.version >= helperVersion) ||
      jobs.some(j => j.titleId === helper && j.state === 'installed' && j.version >= helperVersion);
    if (!s.updater && mainInstalled && helperVersion && !helperCurrent)
      return {...base, stage:'update-helper', action:'send-helper', title:'Update the recovery app',
        console:'Keep RemotePilot open. Press A on the 3DS when it asks you to approve the recovery updater update.',
        pc:'The corrected recovery updater has its own amber shield artwork. Send this update from the main companion.'};
    if (!s.updater && remote?.state === 'installed' && remote.reviewed === false && latest?.id === remote.id)
      return {...base,stage:'acknowledge-result',title:'Update installed · return to ready',job:remote,
        console:'Press B once on the 3DS to acknowledge the completed update. The result stays in history.',
        pc:'Installation is confirmed. After B, both screens return to ready for a new transfer.'};
    if (!s.updater && (mainInstalled || s.localUpdates?.companion) && s.buildVersion >= Math.max(mainInstalled?.version || 0,s.localUpdates?.companion?.version || 0)) return {...base, stage:'ready', action:'choose-file', title:'Ready for a new transfer',
      console:'No transfer is running. Keep RemotePilot open on your 3DS.', pc:'Choose a CIA app to transfer from this PC. Previous results stay in Transfer history.'};
    if (s.updater) {
      const wanted = s.localUpdates?.companion?.version || mainInstalled?.version || 0;
      const mainCurrent = wanted && ((s.titles || []).some(t => t.titleId === main && t.version >= wanted) ||
        jobs.some(j => j.titleId === main && j.state === 'installed' && j.version >= wanted));
      if (mainCurrent) return {...base,stage:'recovery-ready',action:'open-main',title:'Recovery ready',
        console:'No recovery transfer is running. Keep this app open while switching to the main companion.',
        pc:'The main companion is current. Open RemotePilot for everyday CIA-app transfers; recovery remains available when needed.'};
      if (latest?.titleId === main && latest.state === 'installed') return {...base, stage:'reopen', action:'open-main', title:'Step 3 of 3 · Reopen RemotePilot',
        console:'Keep the updater open. Use the button on this page to reopen RemotePilot.', pc:'After RemotePilot opens, press X if you want to continue using remote tools.'};
      return {...base, stage:'update', action:'send-main', title:'Step 2 of 3 · Update RemotePilot',
        console:'Keep the recovery updater open. It will ask you to press A after the transfer is checked.', pc:'Choose the new companion CIA below, then send the update.'};
    }
    const helperInstalled = (s.titles || []).some(t => t.titleId === helper) || jobs.some(j => j.titleId === helper && j.state === 'installed');
    if (helperInstalled) return {...base, stage:'open-updater', action:'open-helper', title:'Step 1 complete · Open the recovery updater',
      console:'Keep RemotePilot open. The button below opens the updater; press X once after it opens.', pc:'The recovery updater is already installed.'};
    return {...base, stage:'setup', action:'send-helper', title:'Step 1 of 3 · Install the recovery updater',
      console:'Keep RemotePilot open. After the transfer is checked, press A when the 3DS asks you to approve.', pc:'Choose RemotePilotUpdater.cia below, then send it wirelessly. No SD card copying is needed.'};
  }
  if (typeof module !== 'undefined') module.exports = {flow,createTransferTracker,presentation};
  else root.RemotePilotHomebrewFlow = {flow,createTransferTracker,presentation};
})(typeof window !== 'undefined' ? window : globalThis);
