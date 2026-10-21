const fs = require('node:fs');
const vm = require('node:vm');
const assert = require('node:assert/strict');
const source = fs.readFileSync('calforge/ui/static/app.js','utf8');
const picker = source.slice(source.indexOf('const SHOP ='), source.indexOf('async function runShop('));
const nodes = new Map();
const node = () => ({value:'',textContent:'',innerHTML:'',children:[],appendChild(child) {this.children.push(child);},
  querySelector() {return {addEventListener() {}};}});
const context = vm.createContext({$:id => {if(!nodes.has(id)) nodes.set(id,node()); return nodes.get(id);},
  document:{createElement:node}, PRODUCT_LABEL:{}, esc:String, thumbUrl:String});
vm.runInContext(picker,context);
vm.runInContext(`
SHOP.format='calendaria';
SHOP.books=[{path:'printify', exported_at:'2026-10-17'},
  {path:'legacy', exported_csv:'printify.csv'}, {path:'new'}];
SHOP.picked=new Set(['printify','legacy','new']);
updateShopPicked();
`,context);
assert.equal(vm.runInContext('SHOP.picked.size',context),1);
assert.equal(vm.runInContext('SHOP.picked.has("new")',context),true);
assert.equal(vm.runInContext('shopBlocked(SHOP.books[0])',context),true);
assert.equal(vm.runInContext('shopBlocked(SHOP.books[1])',context),true);
vm.runInContext("SHOP.format='printify';",context);
assert.equal(vm.runInContext('shopBlocked(SHOP.books[0])',context),false);
assert.equal(nodes.get('btnShopGo').disabled,false);
console.log('PASS Crayonahub selection excludes Printify and legacy export state; Printify remains selectable');
