const fs = require('fs');
const vm = require('vm');
const assert = require('assert');
// Clone now accepts product links. Validate pasted input without discarding extras.
const source = fs.readFileSync('calforge/ui/static/clone.js', 'utf8');
const input = {value: ''};
const context = vm.createContext({$: () => input});
const start = source.indexOf('  function linkError()');
const end = source.indexOf('  function running()');
assert(start >= 0 && end > start, 'clone link validators missing');
vm.runInContext(source.slice(start, end), context);
for (const value of [
  '', 'not a URL', 'javascript:alert(1)',
  'https://example.com/a\nhttps://example.com/b',
  'https://example.com/a,https://example.com/b',
  'https://example.com/a https://example.com/b',
  'https://example.com/a\nhttps://example.com/a',
  'https://example.com/a trailing text',
]) {
  input.value = value;
  assert(vm.runInContext('linkError()', context), value);
  assert.equal(vm.runInContext('links().length', context), 0, value);
}
for (const value of ['https://example.com/a', ' \nhttps://example.com/a?tag=one,two \n']) {
  input.value = value;
  assert.equal(vm.runInContext('linkError()', context), '');
  assert.equal(vm.runInContext('links().length', context), 1);
  assert.equal(vm.runInContext('links()[0]', context), value.trim());
}
console.log('PASS: clipboard product links; exactly one URL; no silent truncation');
