const fs = require('node:fs');
const vm = require('node:vm');
const assert = require('node:assert/strict');
const app = fs.readFileSync('calforge/ui/static/app.js', 'utf8');
class Node {
  constructor() { this.children = []; this.selectors = new Map(); this.value = ''; }
  set innerHTML(value) { this.html = value; this.children = []; this.selectors.clear(); }
  get innerHTML() { return this.html || ''; }
  appendChild(child) { this.children.push(child); child.parent = this; return child; }
  querySelector(selector) {
    if (!this.selectors.has(selector)) this.selectors.set(selector, this.appendChild(new Node()));
    return this.selectors.get(selector);
  }
  remove() { this.parent.children = this.parent.children.filter(c => c !== this); }
}
const nodes = new Map();
const $ = id => { if (!nodes.has(id)) nodes.set(id, new Node()); return nodes.get(id); };
const S = { openWorkspace: null, workspaces: [{id:'a',name:'Alpha'}, {id:'b',name:'Beta'}], projects: [
  {project_id:'a', keyword:'Cats', concepts:[{sku:'WCB-CAT-1',path:'a/1',state:'done'}]},
  {project_id:'b', keyword:'Birds', concepts:[{sku:'WCB-CAT-2',path:'b/2',state:'broken'}]},
  {keyword:'Flowers', concepts:[{sku:'WCB-FLW-3',path:'legacy/3',state:'running'}]}
] };
const tiles = [], rows = [];
let renders = 0;
const context = vm.createContext({S, $, document:{createElement:()=>new Node()}, esc:String,
  button:(text,cls,fn)=>Object.assign(new Node(),{text,fn}),
  zoneOf:c=>c.state, doneTile:(c,k)=>{tiles.push(c.sku);return new Node();},
  bookRow:(c,k,z)=>{rows.push(c.sku);return new Node();},
  renderResults:()=>renders++, deleteProject:()=>{}
});
vm.runInContext(app.slice(app.indexOf('function bookQuery()'),app.indexOf('function renderProjectPicker()')),context);
vm.runInContext(app.slice(app.indexOf('function scopedProjects()'),app.indexOf('async function deleteProject(')),context);
vm.runInContext(app.match(/^function projectName\(.*$/m)[0],context);
vm.runInContext(app.slice(app.indexOf('function renderWorkspaceCards()'),app.indexOf('// "Lịch đã làm"')),context);
const hits = () => JSON.parse(vm.runInContext('JSON.stringify(searchHits().map(c=>c.sku))',context));
const render = () => { tiles.length=0;rows.length=0;vm.runInContext('renderWorkspaceCards()',context); };
$('bookSearch').value = '  wcb-cat  ';
assert.deepEqual(hits(),['WCB-CAT-1','WCB-CAT-2']);
render();
assert.deepEqual(tiles,['WCB-CAT-1']);
assert.deepEqual(rows,['WCB-CAT-2']);
assert.equal($('results').children.length,2);
assert.match($('results').children[0].innerHTML,/Alpha/);
assert.match($('results').children[1].innerHTML,/Beta/);
assert.equal($('bookCount').textContent,'2 cuốn khớp');
// A global result can open its project; clearing search restores project browsing.
$('results').children[1].querySelector('.done-group-head').children.find(n=>n.text==='Mở dự án').fn();
assert.equal(S.openWorkspace,'b');assert.equal($('bookSearch').value,'');assert.equal(renders,1);
S.openWorkspace='a';$('bookSearch').value='wcb-cat';
assert.deepEqual(hits(),['WCB-CAT-1']);
S.openWorkspace=null;$('bookSearch').value='wcb-flw';render();
assert.deepEqual(hits(),['WCB-FLW-3']);assert.deepEqual(rows,['WCB-FLW-3']);
assert.match($('results').children[0].innerHTML,/Chưa phân dự án/);
$('bookSearch').value='Alpha';render();
assert.equal($('results').children.length,1);assert.match($('bookCount').textContent,/1 dự án/);
$('bookSearch').value='missing-sku';render();assert.match($('results').innerHTML,/Không tìm thấy/);
$('bookSearch').value='';render();assert.equal($('results').children.length,3);
assert.equal(tiles.length+rows.length,0,'empty overview must not expose every book');
console.log('Workspace search: global SKU, local scope, legacy, project navigation and empty results OK');
