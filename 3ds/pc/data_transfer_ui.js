// Registered asset packages stay on the owner's PC; this view sends package IDs.
window.RemotePilotGameData = (() => {
  'use strict';
  const byId = id => document.getElementById(id);
  let current = {}, catalogue = '';
  const active = () => current.job?.state && !['complete','failed','cancelled','unknown','interrupted'].includes(current.job.state);
  async function action(name, body = {}) {
    const response = await fetch('/api/homebrew/' + name, {method:'POST', headers:{'Content-Type':'application/json','X-Remote-Pilot-Viewer':'1'}, body:JSON.stringify(body)});
    if (!response.ok) throw new Error(await response.text());
    return response.json();
  }
  function render(snapshot) {
    current = snapshot.dataTransfer || {};
    const packages = current.packages || [], select = byId('data-package');
    if (!select) return;
    const signature = packages.map(p => p.id).join(',');
    if (signature !== catalogue) {
      const selected = select.value;
      select.replaceChildren(...packages.map(p => {
        const option = document.createElement('option'); option.value=p.id;
        option.textContent=`${p.name} · ${(p.total/1073741824).toFixed(2)} GiB · ${p.fileCount} files`;
        return option;
      }));
      if (packages.some(p => p.id === selected)) select.value=selected;
      catalogue=signature;
    }
    const ciaActive = (snapshot.jobs || []).some(j => !['uploaded','installed','cancelled','failed','unknown','interrupted','launching'].includes(j.state));
    byId('data-send').disabled=!current.supported || !snapshot.armed || !packages.length || active() || ciaActive;
    byId('data-cancel').hidden=!active();
    byId('data-review').hidden=!['interrupted','unknown','failed'].includes(current.job?.state);
    const job=current.job || {}, done=job.done || 0, total=job.total || 0;
    byId('data-progress').value=done; byId('data-progress').max=Math.max(1,total);
    byId('data-progress').hidden=!job.state;
    byId('data-state').textContent=job.state ? `${job.name || 'Game data'} · ${job.state} · ${job.filesDone || 0}/${job.fileCount || 0} files · ${(done/1048576).toFixed(1)}/${(total/1048576).toFixed(1)} MiB` : 'Choose a registered game-data package.';
    byId('data-speed').textContent=job.state ? `Fast transfer · ${job.mibPerSecond ? job.mibPerSecond.toFixed(2)+' MiB/s measured' : 'measuring speed'} · ${job.activeFile || ''}` : 'Fast transfer is enabled. Each file is checked before it is placed.';
    byId('data-detail').textContent=!current.supported ? 'Update the main RemotePilot app to enable game-data transfers. Recovery handles app updates only.' : job.detail || 'Existing matching files are kept; different destination files and saves are preserved.';
    if(active()) for(const button of document.querySelectorAll('[data-hb-cap],#hb-new-transfer,#hb-send-local-update,#hb-open-updater,#hb-open-companion')) button.disabled=true;
  }
  async function run(name, body) {try {await action(name,body);} catch(error) {byId('data-detail').textContent=error.message;} }
  function init() {
    byId('data-send')?.addEventListener('click',()=>run('data-start',{package:byId('data-package').value}));
    byId('data-cancel')?.addEventListener('click',()=>run('data-cancel',{}));
    byId('data-review')?.addEventListener('click',()=>run('data-review',{}));
  }
  return {render,init};
})();
