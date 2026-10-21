const fs = require('node:fs');
const vm = require('node:vm');
const assert = require('node:assert/strict');
const app = fs.readFileSync('calforge/ui/static/app.js', 'utf8');
const clone = fs.readFileSync('calforge/ui/static/clone.js', 'utf8');
const nodes = new Map();
const node = () => ({value: '', textContent: '', innerHTML: '', hidden: false, disabled: false,
  children: [], classList: {toggle() {}}, appendChild(c) {this.children.push(c);}});
const $ = id => {if (!nodes.has(id)) nodes.set(id, node()); return nodes.get(id);};
const calls = [];
const data = {paused: false, items: [
  {id: 'a', status: 'running', task_id: 't1', params: {keyword: 'Idea A'}},
  {id: 'b', status: 'queued', params: {action: 'clone', title: 'Clone B', clone_ids: ['x', 'y']}},
  {id: 'c', status: 'queued', params: {keyword: 'Idea C'}}
]};
const context = vm.createContext({$, S: {queue: data, task: null}, PRODUCT_LABEL: {}, STYLE_LABEL: {},
  document: {createElement: node}, esc: String, projectName: () => 'Project', syncQueueCard() {},
  button: (text, cls, fn) => ({text, fn}), queueOp: async (...args) => calls.push(args), toast() {}});
vm.runInContext(app.slice(app.indexOf('function renderQueue()'), app.indexOf('async function toggleQueuePause()')), context);
vm.runInContext('renderQueue()', context);
const rows = $('queueWaiting').children;
assert.equal(rows.length, 3);
assert.match(rows[0].innerHTML, /Idea A/);
assert.match(rows[1].innerHTML, /Clone B/);
assert.match(rows[1].innerHTML, /2 cuốn/);
assert.match(rows[2].innerHTML, /Idea C/);
rows[2].children.find(b => b.text === '↑').fn();
assert.equal(calls[0][0], 'move');
assert.equal(calls[0][1].id, 'c');

(async () => {
  const requests = [];
  $('cloneGroup').value = 'cats';
  $('cloneLinks').value = 'https://example.com/cats';
  $('cloneBookCount').value = '3';
  $('cloneYear').value = '2027';
  let refreshed = 0;
  const c = vm.createContext({$, document: {querySelector: () => ({value: 'ai'})},
    window: {selectedProject: () => 'p', refreshUnifiedQueue: async () => refreshed++},
    api: async (path, body) => {requests.push({path, body}); return {};},
    linkError: () => '', links: () => [$('cloneLinks').value], render() {}, renderStartButton() {}, toast() {}});
  vm.runInContext(clone.slice(clone.indexOf('  async function start()'), clone.indexOf('  // ---------------------------------------------------------------- tiến độ')), c);
  await vm.runInContext('start()', c);
  assert.equal(requests.length, 1);
  assert.equal(requests[0].path, '/api/clone/add');
  assert.equal(requests[0].body.book_count, 3);
  assert.equal(requests[0].body.project_id, 'p');
  assert.equal(refreshed, 1);
  assert.equal($('cloneLinks').value, '');
  console.log('PASS: mixed queue order, reorder controls and clone submission through shared queue');
})().catch(e => {console.error(e); process.exitCode = 1;});
