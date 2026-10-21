const fs=require('node:fs'),vm=require('node:vm'),assert=require('node:assert/strict');
const source=fs.readFileSync('calforge/ui/static/app.js','utf8');
const start=source.indexOf('async function exportSkuTxt()');
const end=source.indexOf('\nfunction ',start);
const nodes={skuTxtFile:{files:[{size:20,text:async()=>'WCB-HH-RJJ8A'}],value:'file'},btnImportSkuTxt:{},skuTxtResult:{}};
const c=vm.createContext({$:id=>nodes[id],toast:()=>{},api:async()=>{throw Object.assign(new Error('Not found'),{status:404})}});
vm.runInContext(source.slice(start,end),c);
(async()=>{
 await vm.runInContext('exportSkuTxt()',c);
 assert.match(nodes.skuTxtResult.textContent,/Backend.*bản cũ/);
 assert.equal(nodes.btnImportSkuTxt.disabled,false);
 assert.equal(nodes.skuTxtFile.value,'');
 c.api=async()=>{throw Object.assign(new Error('Không tìm thấy SKU chung: WCB-MISSING-12345'),{status:400})};
 await vm.runInContext('exportSkuTxt()',c);
 assert.match(nodes.skuTxtResult.textContent,/Không tìm thấy SKU chung/);
 console.log('PASS: stale backend 404 distinguished from missing SKU; input/button recover');
})().catch(e=>{console.error(e);process.exitCode=1});
