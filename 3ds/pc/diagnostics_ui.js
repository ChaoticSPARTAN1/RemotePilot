// Private diagnostic copies. File contents are never interpreted as HTML.
window.RemotePilotDiagnostics = (() => {
  'use strict';
  const el = id => document.getElementById(id);
  let current = {}, signature = '', blobURL = null, resultId = null, loading = false;
  async function action(name, body={}) {
    const response = await fetch('/api/homebrew/'+name, {method:'POST',headers:{'Content-Type':'application/json','X-Remote-Pilot-Viewer':'1'},body:JSON.stringify(body)});
    if(!response.ok) throw new Error(await response.text());
    return response.json();
  }
  async function run(name,body) {
    try { const reply=await action(name,body); if(reply.files) render({...current,diagnostics:{...current.diagnostics,files:reply.files}}); }
    catch(error) {el('diag-detail').textContent=error.message;}
  }
  async function show(id) {
    loading=true;
    try {
      const value=await action('diag-result',{id});
      const bytes=Uint8Array.from(atob(value.base64),c=>c.charCodeAt(0));
      const extension=value.path.split('.').pop().toLowerCase();
      const type=value.kind==='text'?'text/plain':({png:'image/png',jpg:'image/jpeg',jpeg:'image/jpeg',bmp:'image/bmp'}[extension]||'application/octet-stream');
      if(blobURL) URL.revokeObjectURL(blobURL);
      blobURL=URL.createObjectURL(new Blob([bytes],{type}));
      const link=el('diag-download');link.href=blobURL;link.download=value.path.split('/').pop();link.hidden=false;
      const text=el('diag-preview');text.hidden=value.kind!=='text';
      text.textContent=value.kind==='text'?new TextDecoder().decode(bytes.slice(-65536)):'';
      const image=el('diag-image');image.hidden=value.kind!=='image';
      if(value.kind==='image') image.src=blobURL;else image.removeAttribute('src');
      el('diag-detail').textContent=`Verified ${value.size.toLocaleString()} bytes. Saved privately on this PC. ${value.kind==='text'&&value.size>65536?'Preview shows the last 64 KiB.':''}`;
      resultId=id;
    } catch(error) {el('diag-detail').textContent=error.message;}
    finally {loading=false;}
  }
  function render(snapshot) {
    current=snapshot;const data=snapshot.diagnostics||{},files=data.files||[],job=data.job||{},select=el('diag-file');
    if(!select) return;
    const stamp=JSON.stringify(files);
    if(stamp!==signature) {
      const selected=select.value;
      select.replaceChildren(...files.map(file=>{const option=document.createElement('option');option.value=file.id;option.textContent=`${file.path} · ${(file.size/1024).toFixed(1)} KiB`;return option;}));
      if(files.some(file=>file.id===selected))select.value=selected;
      signature=stamp;
    }
    const busy=job.state==='collecting'||snapshot.dataTransfer?.job?.state&& !['complete','failed','cancelled','unknown','interrupted'].includes(snapshot.dataTransfer.job.state)||(snapshot.jobs||[]).some(j=>!['uploaded','installed','cancelled','failed','unknown','interrupted','launching'].includes(j.state));
    el('diag-refresh').disabled=!data.supported||!snapshot.armed||Boolean(busy);
    el('diag-collect').disabled=el('diag-refresh').disabled||!files.length;
    el('diag-state').textContent=!snapshot.connected?'Open the main companion and press X, then refresh.':snapshot.updater?'Open the main companion to read diagnostics.':!data.supported?'Update the main companion to read diagnostics.':job.state==='collecting'?`Collecting ${job.path} · ${(job.done/1024).toFixed(0)}/${(job.total/1024).toFixed(0)} KiB`:job.state==='failed'?job.detail:`${files.length} diagnostic files available`;
    if(job.state==='complete'&&job.id!==resultId&&!loading)show(job.id);
    if(job.state==='collecting')for(const button of document.querySelectorAll('[data-hb-cap],#data-send,#hb-new-transfer,#hb-send-local-update,#hb-open-updater,#hb-open-companion'))button.disabled=true;
  }
  function init() {
    el('diag-refresh')?.addEventListener('click',()=>run('diag-list',{}));
    el('diag-collect')?.addEventListener('click',()=>run('diag-collect',{id:el('diag-file').value}));
  }
  return {render,init};
})();
