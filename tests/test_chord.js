// Exercise the viewer's Ctrl+click chord behavior without a device connection.
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');

const source = fs.readFileSync(`${__dirname}/../viewer.js`, 'utf8');
const logic = source.slice(source.indexOf('function feedback('), source.indexOf('function setColors('));
const elements = ['SELECT', 'X'].map(name => ({dataset: {button: name},
  classList: {toggle() {}, remove() {}}}));
const status = {textContent: ''};
const sent = [];
const singles = [];
const context = vm.createContext({Object, Set, performance: {now: () => 100},
  manifest: {capabilities: ['controller', 'input'], buttonBits: {SELECT: 8, X: 2}},
  state: {connected: true, linkEnabled: true}, chordButtons: new Set(), chordUntil: 0,
  document: {querySelectorAll: () => elements}, $: () => status,
  api: async (path, body) => { sent.push({path, body}); return {ok: true}; },
  action: (kind, body) => singles.push({kind, body})});
vm.runInContext(logic, context);
const ctrl = {ctrlKey: true, preventDefault() {}};
context.buttonClick(ctrl, 'SELECT');
context.buttonClick(ctrl, 'X');
assert.match(status.textContent, /SELECT \+ X/);
context.releaseChord().then(() => {
  assert.equal(sent.length, 1);
  assert.equal(sent[0].path, '/api/control');
  assert.equal(sent[0].body.payload.buttons, (1 << 8) | (1 << 2));
  assert.equal(sent[0].body.payload.frames, 8);
  assert.equal(context.chordButtons.size, 0);
  context.buttonClick({ctrlKey: false}, 'X');
  assert.equal(singles.length, 1);
  assert.equal(singles[0].body.button, 'X');
  console.log('viewer chords: selected buttons send one mask; plain clicks remain single presses PASS');
}).catch(error => { console.error(error); process.exitCode = 1; });
