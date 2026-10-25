const assert = require('node:assert/strict');
const {flow,createTransferTracker,presentation} = require('./homebrew_flow.js');
const main='000400000f3d5200', helper='000400000f3d5300';
const ready={connected:true,armed:true,updater:false,jobs:[],titles:[]};
assert.equal(flow(ready).action,'send-helper');
assert.match(flow(ready).console,/Keep RemotePilot open/);
assert.equal(flow({...ready,armed:false}).stage,'arm');
for(const state of ['uploading','verifying','rechecking','installing','committing']){
  const next=flow({...ready,jobs:[{state,titleId:helper}]});
  assert.equal(next.action,'none');assert.match(next.console,/open/);
  assert.doesNotMatch(next.console,/Press A/);
}
let next=flow({...ready,jobs:[{state:'awaiting-approval',titleId:helper}]});
assert.match(next.console,/Press A on the 3DS/);
assert.equal(next.action,'none');
next=flow({...ready,jobs:[{id:'test',state:'unknown',titleId:helper}],remoteJob:{id:'test',state:'uploading'}});
assert.equal(next.action,'inspect');assert.match(next.console,/Installation has not started/);
assert.equal(flow({...ready,jobs:[{state:'cancelled',titleId:helper}]}).action,'send-helper');
assert.equal(flow({...ready,jobs:[{state:'installed',titleId:helper}]}).action,'open-helper');
assert.equal(flow({...ready,updater:true}).action,'send-main');
assert.equal(flow({...ready,updater:true,jobs:[{state:'installed',titleId:main,version:4}]}).action,'open-main');
assert.equal(flow({...ready,buildVersion:4,jobs:[{state:'installed',titleId:main,version:4}]}).stage,'ready');
assert.equal(flow({...ready,connected:false}).action,'none');
assert.equal(flow({...ready,connected:false,handoff:{state:'launching'}}).stage,'launching');
assert.equal(flow({...ready,connected:false,jobs:[{state:'installing',titleId:helper}]}).title,'Connection interrupted');
next=flow({...ready,remoteJob:{id:'old-launch',state:'unknown',titleId:helper,version:3},jobs:[{id:'old-launch',state:'launching',titleId:helper}],titles:[{titleId:helper,version:3}]});
assert.equal(next.stage,'clear-launch');assert.match(next.console,/Press B once/);
assert.notEqual(flow({...ready,remoteJob:{id:'other',state:'unknown',titleId:helper,version:3}}).stage,'clear-launch');
assert.equal(flow({...ready,remoteJob:{id:'other',state:'unknown',titleId:helper,version:3}}).stage,'review-console');
next=flow({...ready,buildVersion:4,jobs:[{state:'installed',titleId:main,version:4},{state:'installed',titleId:'000400000f3d5000',version:6}]});
assert.equal(next.action,'open-installed');assert.match(next.title,/Morrowind/);
const refused={state:'failed',titleId:'000400000f3d5000',detail:'Companion: receipt-write-failed'};
assert.equal(flow({...ready,connected:false,jobs:[refused]}).stage,'repair-updater');
assert.equal(flow({...ready,updater:true,jobs:[refused]}).action,'send-main');
next=flow({...ready,buildVersion:5,localUpdates:{companion:{version:5},updater:{version:4}},titles:[{titleId:helper,version:3}],jobs:[{state:'installed',titleId:main,version:5}]});
assert.equal(next.stage,'update-helper');assert.equal(next.action,'send-helper');
assert.equal(flow({...ready,connected:false,handoff:{state:'launching',titleId:'000400000f3d5000'}}).console.includes('press X'),false);
console.log('Update guidance: keep app open, explicit A approval, lost-ack review, helper/main transitions, no premature success PASS');
const timing=createTransferTracker();
const transfer={id:'transfer-one',state:'uploading',done:0,total:10*1024*1024};
assert.match(timing(transfer,0),/Calculating transfer ETA/);
assert.match(timing({...transfer,done:1024*1024},10000),/About 2 min remaining · 102\.4 KiB\/s/);
assert.match(timing({...transfer,done:1024*1024},26000),/Waiting for transfer progress · ETA unavailable/);
assert.match(timing({...transfer,done:2*1024*1024},30000),/remaining/);
assert.match(timing({...transfer,done:transfer.total},40000),/Transfer sent/);
assert.equal(timing({...transfer,state:'awaiting-approval'},41000),'');
assert.match(timing({...transfer,id:'transfer-two',done:1024*1024},42000),/Calculating/);
assert.equal(timing(transfer,43000,false),'');
assert.match(timing({...transfer,done:5*1024*1024},44000),/Calculating/);
assert.match(timing({...transfer,done:4*1024*1024},45000),/Calculating/);
assert.equal(timing({...transfer,done:Infinity},46000),'');
// A minute of recent samples replaces the earlier fast burst on a long job.
const recent=createTransferTracker(), long={...transfer,total:100*1024*1024};
recent(long,0);recent({...long,done:10*1024*1024},10000);
let label;
for(let i=11;i<=80;i++)label=recent({...long,done:10*1024*1024+(i-10)*1024},i*1000);
assert.match(label,/1\.0 KiB\/s/);
assert.match(label,/Transfer only/);
assert.doesNotMatch(label,/NaN|Infinity/);
console.log('Transfer ETA: measured rate, recent speed changes, stalls, completion, phase/job changes and reconnects PASS');
const gameJob={id:'game-update',titleId:'000400000f3d5000',version:6,done:25,total:100,state:'uploading'};
for(const [state,index] of [['uploading',0],['verifying',1],['awaiting-approval',2],['rechecking',3],['installing',3],['committing',3],['installed',4]]) {
  const panel=presentation({...ready,jobs:[{...gameJob,state}]});
  assert.match(panel.name,/Morrowind/);
  assert.equal(panel.steps[index].state,index===4?'complete':'current');
  assert.ok(panel.next.length>20);
  if(index<4)assert.equal(panel.steps[4].state,'pending');
  assert.equal(panel.percent,index===4?100:25);
}
let panel=presentation({...ready,jobs:[{...gameJob,state:'awaiting-approval'}]});
assert.equal(panel.location,'ON YOUR 3DS');assert.equal(panel.tone,'approval');assert.match(panel.next,/After you press A/);
panel=presentation({...ready,jobs:[{...gameJob,state:'installed'}]});
assert.equal(panel.location,'ON THIS PC');assert.equal(panel.badge,'Confirmed');
panel=presentation({...ready,connected:false,jobs:[gameJob]});
assert.equal(panel.phase,'Last confirmed progress');assert.equal(panel.percent,25);assert.ok(panel.steps.every(step=>step.state!=='complete'));
panel=presentation({...ready,jobs:[{...gameJob,state:'unknown'}]});
assert.equal(panel.tone,'warning');assert.match(panel.next,/check the console outcome/i);assert.ok(panel.steps.every(step=>step.state!=='complete'));
assert.equal(presentation({...ready,armed:false}).showProgress,false);
assert.equal(presentation({...ready,jobs:[{...gameJob,done:99.999}]}).percent,99.9);
const metrics=createTransferTracker();metrics(gameJob,0,true,true);
assert.equal(metrics({...gameJob,done:35},10000,true,true).state,'measured');
console.log('Mission UI: honest phase progress, explicit action location, next-step feedback, completion and interrupted transfer states PASS');
next=flow({...ready,jobs:[{...gameJob,state:'verifying',approvalMode:'autonomous'}]});
assert.match(next.console,/No A press is needed/);
assert.doesNotMatch(next.console,/Press A on the 3DS/);
panel=presentation({...ready,jobs:[{...gameJob,state:'installing',approvalMode:'autonomous'}]});
assert.equal(panel.steps[2].label,'Auto mode');assert.equal(panel.steps[2].status,'Session opt-in');
next=flow({...ready,autonomousEnabled:true,jobs:[{...gameJob,state:'awaiting-approval',approvalMode:'manual'}]});
assert.match(next.console,/Press A on the 3DS/); // session mode never changes an existing manual job
const currentTools={...ready,buildVersion:7,localUpdates:{companion:{version:7},updater:{version:6}},
  titles:[{titleId:helper,version:6},{titleId:'000400000f3d5000',version:7}]};
const oldFailure={...gameJob,state:'failed',error:'owner-reviewed-unknown-outcome',detail:'Receiver restarted; inspect console job'};
next=flow({...currentTools,jobs:[oldFailure]});
assert.equal(next.stage,'ready');assert.equal(next.title,'Ready for a new transfer');assert.equal(next.action,'choose-file');
panel=presentation({...currentTools,jobs:[oldFailure]});
assert.equal(panel.showProgress,false);assert.equal(panel.showSteps,false);assert.equal(panel.badge,'Ready');
assert.equal(panel.name,'RemotePilot companion');assert.doesNotMatch(panel.subtitle,/Version 6/);
assert.match(next.pc,/CIA app/);assert.match(next.pc,/history/);
assert.equal(oldFailure.state,'failed'); // Preserve the historical receipt.
next=flow({...currentTools,jobs:[{...oldFailure,error:'invalid-cia'}]});
assert.equal(next.stage,'failed'); // Unacknowledged failures still need attention.
next=flow({...currentTools,jobs:[{...oldFailure,error:'invalid-cia'}],remoteJob:{...oldFailure,error:'invalid-cia',reviewed:true}});
assert.equal(next.stage,'ready');
for(const state of ['unknown','interrupted','uploading','verifying','awaiting-approval'])
  assert.notEqual(flow({...currentTools,jobs:[{...oldFailure,state}]}).stage,'ready');
assert.equal(flow({...currentTools,jobs:[oldFailure],remoteJob:{id:'untracked',state:'unknown'}}).stage,'review-console');
assert.equal(flow({...currentTools,armed:false,jobs:[oldFailure]}).stage,'arm');
assert.equal(flow({...currentTools,jobs:[]}).stage,'ready'); // FBI setup has no OTA install history.
assert.equal(flow({...currentTools,jobs:[{...gameJob,state:'installed'}],remoteJob:{...gameJob,state:'installed',reviewed:true}}).stage,'ready');
next=flow({...currentTools,updater:true,titles:[...currentTools.titles,{titleId:main,version:7}]});
assert.equal(next.stage,'recovery-ready');assert.equal(next.action,'open-main');
assert.equal(presentation({...currentTools,updater:true},next).badge,'Ready');
assert.equal(presentation({...currentTools,updater:true},next).showProgress,false);
console.log('Ready state: generic CIA transfers, reviewed history retained, no stale progress, FBI inventory and unknown-outcome guards PASS');
