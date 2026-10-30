const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const source = fs.readFileSync('viewer.js', 'utf8');
const html = fs.readFileSync('viewer.html', 'utf8');
for (const name of ['perf-toggle', 'perf-detail', 'perf-graph', 'perf-scale'])
  assert.ok(html.includes(`id="${name}"`), `Missing performance DOM field ${name}`);
const strokes = [];
const context = {fillRect() {strokes.length = 0;}, beginPath() {}, moveTo(x,y) {strokes.push({x,y});}, lineTo() {}, stroke() {}};
const elements = {'perf-toggle': {checked: true}, 'perf-detail': {}, 'perf-scale': {}, 'perf-graph': {width:640,height:140,getContext:()=>context}};
const scope = vm.createContext({Math, Number, document: {documentElement:{}},
  $: name => elements[name], getComputedStyle:()=>({getPropertyValue:()=> '#fff'})});
const start = source.indexOf('function updateGraph(perf) {');
const end = source.indexOf('\nasync function prepareSetup()', start);
vm.runInContext('let graphSamples=[]; let graphScale=33.4; let lastPerfStamp=-1;\n'+source.slice(start,end), scope);
function sample(stamp,frame=33.3,work=10) {
  vm.runInContext(`updateGraph({timestampMs:${stamp},frameMs:${frame},workMs:${work},fps:30})`,scope);
}
sample(1);
sample(2,100);
assert.equal(vm.runInContext('graphSamples.length',scope),2);
assert.equal(vm.runInContext('graphScale',scope),133.6);
assert.ok(Math.abs(strokes[0].y - (140 - 16.7 / 133.6 * 128 - 5)) < 1e-8, 'Guide must share trace scale');
for (let stamp=3;stamp<70;stamp++) sample(stamp);
assert.equal(vm.runInContext('graphScale',scope),133.6, 'Dropping old spike must not jump the scale');
sample(1);
assert.equal(vm.runInContext('graphSamples.length',scope),1,'Device reboot resumes samples');
elements['perf-toggle'].checked=false;
sample(2);
assert.equal(vm.runInContext('graphSamples.length',scope),0);
assert.equal(elements['perf-detail'].textContent,'Performance capture off');
assert.equal(vm.runInContext('graphScale',scope),33.4);
console.log('Performance graph: shared stable scale, reboot, off and DOM bindings PASS');
