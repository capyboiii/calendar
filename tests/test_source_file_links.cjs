const fs = require('node:fs');
const vm = require('node:vm');
const assert = require('node:assert/strict');
const src = fs.readFileSync('calforge/clone/session.py', 'utf8');
const js = src.match(/FILE_LINKS_JS = r"""([\s\S]*?)"""/)[1];
function link(text, href = '/files/opaque-id') {
  return {textContent:text, innerText:text, children:[], attrs:{href},
    getAttribute(k) {return this.attrs[k] || null;}, hasAttribute(k) {return k in this.attrs;},
    setAttribute(k,v) {this.attrs[k]=v;}, querySelector() {return null;}, closest() {return null;}};
}
function count(links) {
  const last = {querySelectorAll:s => s === 'span' ? [] : links};
  return vm.runInNewContext('('+js+')()', {document:{
    querySelectorAll:s => s.includes('assistant') ? [last] : [], querySelector:() => last}});
}
for (const label of ['Tải 12 artwork PNG — file ZIP', 'Tải bộ artwork PNG', 'Download artwork ZIP']) {
  const l=link(label);
  assert.equal(count([l]),1,label);
  assert.equal(l.attrs['data-calforge-file'],'0');
}
assert.equal(count([link('Copy download link')]),0);
assert.equal(count([link('Share file ZIP')]),0);
assert.equal(count([link('Read more')]),0);
assert.equal(count([link('artworks.zip','sandbox:/mnt/data/artworks.zip')]),1);
assert.equal(count([]),0,'a plain text promise is not a download');
console.log('PASS: opaque ZIP download links in Vietnamese/English; no copy/share/plain promises');
