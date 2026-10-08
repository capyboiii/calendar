const fs = require('fs');
const vm = require('vm');
const assert = require('assert');
const source = fs.readFileSync('calforge/ui/static/clone.js', 'utf8');
const handlers = {};
const state = {refs: []};
let errors = [];
const context = vm.createContext({
  Promise, Array, MAX_REFS: 10, S: state,
  loadImage: async f => { await Promise.resolve(); return {name: f.name}; },
  renderRefs: () => {}, toast: msg => errors.push(msg),
  $: () => ({addEventListener: (name, fn) => handlers[name] = fn, focus: () => {}}),
});
vm.runInContext(source.slice(source.indexOf('let fileQueue'), source.indexOf('function renderRefs')), context);
vm.runInContext(source.slice(source.indexOf("const drop = $('drop');"), source.indexOf("drop.addEventListener('dragover'")), context);
(async () => {
  let prevented = 0;
  const image = {name: 'clipboard.png', type: 'image/png'};
  const event = {clipboardData: {items: [{kind: 'file', type: 'image/png', getAsFile: () => image}], files: [image]}, preventDefault: () => prevented++};
  handlers.paste(event);
  await vm.runInContext('fileQueue', context);
  assert.equal(state.refs.length, 1); // items + files must not duplicate the same image
  assert.equal(prevented, 1);
  for (let i = 0; i < 15; i++) handlers.paste(event);
  await vm.runInContext('fileQueue', context);
  assert.equal(state.refs.length, 10);
  handlers.paste({clipboardData: {items: [], files: []}, preventDefault: () => {throw Error('intercepted text');}});
  state.refs.length = 0;
  handlers.paste({clipboardData: {files: [image]}, preventDefault: () => {}});
  await vm.runInContext('fileQueue', context);
  assert.equal(state.refs.length, 1);
  assert(errors.length > 0);
  console.log('PASS: paste image, no duplicate, rapid paste limit, text handling, files fallback');
})().catch(e => {console.error(e); process.exitCode = 1;});
