// Run the actual Apps Script source against an in-memory SpreadsheetApp adapter.
const fs = require('node:fs');
const vm = require('node:vm');
const crypto = require('node:crypto');
const assert = require('node:assert/strict');
const source = fs.readFileSync('tools/crayonahub_sheet.gs', 'utf8');
const secret = 'x'.repeat(40);
const header = ['SKU','Description','Tags','Title','Sizes','Paper','Design','Mockup'];

function harness(initial = [header]) {
  const state = {cells: initial.map(r => [...r]), widths: {}, heights: {}, released: 0, writes: 0,
    locked: false, busy: false, failAt: 0, opens: 0, merged: false, unmerged: 0};
  const sheet = {
    getSheetId: () => 0,
    getLastRow: () => state.cells.length,
    getMaxRows: () => 1000,
    insertRowsAfter() {},
    setColumnWidth(col, width) { state.widths[col] = width; },
    setRowHeightsForced(row, count, height) {
      for (let i = row; i < row + count; i++) state.heights[i] = height;
    },
    getRange(row, col, count, cols) {
      const range = {
        breakApart() {state.merged = false; state.unmerged++; return range;},
        getDisplayValues() { return Array.from({length: count}, (_, r) =>
          Array.from({length: cols}, (_, c) => state.cells[row+r-1]?.[col+c-1] || '')); },
        setValues(values) {
          assert.equal(state.merged, false, 'Unmerge before writing SKU and Description');
          if (state.failAt && ++state.writes === state.failAt) throw Error('simulated write error');
          values.forEach((values, r) => {
            state.cells[row+r-1] ||= Array(8).fill('');
            values.forEach((v,c) => state.cells[row+r-1][col+c-1] = v);
          });
          return range;
        },
      };
      for (const method of ['setNumberFormat','setHorizontalAlignment','setVerticalAlignment','setWrapStrategy']) {
        range[method] = () => range;
      }
      return range;
    },
  };
  const context = vm.createContext({
    ContentService: {MimeType: {JSON:'JSON'}, createTextOutput(text) {
      return {setMimeType: () => JSON.parse(text)};
    }},
    PropertiesService: {getScriptProperties: () => ({getProperty: () => secret})},
    Utilities: {Charset: {UTF_8:'UTF_8'}, computeHmacSha256Signature: (payload,key) =>
      [...crypto.createHmac('sha256', key).update(payload).digest()].map(v => v > 127 ? v-256 : v)},
    LockService: {getScriptLock: () => ({
      tryLock() {state.locked = !state.busy; return state.locked;},
      hasLock: () => state.locked,
      releaseLock() {state.locked = false; state.released++;},
    })},
    SpreadsheetApp: {WrapStrategy: {CLIP:'CLIP', WRAP:'WRAP'}, flush() {}, openById(id) {
      state.opens++;
      assert.equal(id, '1qD3M9OQ57JPdW0rV_X3_-ik4pSvywMuPCPNyPLs_CGg');
      return {getSheets: () => [sheet]};
    }},
  });
  vm.runInContext(source, context);
  function request(rows, extra = {}, badSignature = false) {
    const payload = JSON.stringify({version:1, spreadsheet_id:'1qD3M9OQ57JPdW0rV_X3_-ik4pSvywMuPCPNyPLs_CGg',
      sheet_id:0, header, timestamp:Math.floor(Date.now()/1000), rows, ...extra});
    const signature = badSignature ? 'bad' : crypto.createHmac('sha256', secret).update(payload).digest('hex');
    return context.doPost({postData:{contents:JSON.stringify({payload,signature})}});
  }
  return {state,request};
}

const rows = [['BASE','Description\n- Paper: Matte or Glossy','tags','Title','','','','M1\nM2'],
  ...['11SM','11SG','14SM','14SG'].map(suffix => ['BASE-'+suffix,'','','','size',suffix.endsWith('SM')?'Matte':'Glossy','URL1\nURL2',''])];
let tests = 0;
function test(name, fn) { fn(); tests++; console.log('PASS', name); }
test('first write, exact cells and formatting', () => {
  const h = harness(); assert.equal(h.request(rows).ok, true);
  assert.deepEqual(h.state.cells, [header,...rows]);
  assert.deepEqual(Object.values(h.state.widths), [180,220,160,220,90,90,260,420]);
  assert.equal(h.state.heights[2],160); assert.equal(h.state.heights[3],64); assert.equal(h.state.released,1);
});
test('replay and changed title upsert without duplicate rows', () => {
  const h = harness(); h.request(rows); h.request(rows);
  const updated = rows.map(r => [...r]); updated[0][3] = 'Changed'; h.request(updated);
  assert.equal(h.state.cells.length,6); assert.equal(h.state.cells[1][3],'Changed');
});
test('merged SKU/Description is separated before writing', () => {
  const h = harness(); h.state.merged = true;
  assert.equal(h.request(rows).ok,true);
  assert.equal(h.state.cells[1][1], rows[0][1]);
  assert.equal(h.state.unmerged,5);
});
test('other book remains untouched', () => {
  const h = harness([header,['OTHER','preserve','','','','','']]); h.request(rows);
  assert.equal(h.state.cells[1][1],'preserve'); assert.equal(h.state.cells.length,7);
});
test('partial write then retry fills missing SKUs without duplicates', () => {
  const h = harness(); h.state.failAt = 3;
  assert.equal(h.request(rows).code,'write'); assert.equal(h.state.locked,false);
  h.state.failAt = 0; assert.equal(h.request(rows).ok,true);
  assert.deepEqual(h.state.cells,[header,...rows]);
});
test('unauthorized and expired requests never open spreadsheet', () => {
  const h = harness(); assert.equal(h.request(rows,{},true).code,'auth');
  assert.equal(h.request(rows,{timestamp:0}).code,'auth'); assert.equal(h.state.opens,0);
});
test('wrong destination and duplicate payload rejected', () => {
  const h = harness(); assert.equal(h.request(rows,{sheet_id:1}).code,'invalid');
  assert.equal(h.request([rows[0],rows[0]]).code,'duplicate'); assert.equal(h.state.opens,0);
});
test('schema mismatch leaves values untouched', () => {
  const h = harness([['wrong',...header.slice(1)]]); const before=JSON.stringify(h.state.cells);
  assert.equal(h.request(rows).code,'schema'); assert.equal(JSON.stringify(h.state.cells),before);
});
test('duplicate existing SKU refuses mutation', () => {
  const h = harness([header,rows[0],rows[0]]); const before=JSON.stringify(h.state.cells);
  assert.equal(h.request(rows).code,'duplicate'); assert.equal(JSON.stringify(h.state.cells),before);
});
test('busy lock and formula escaping', () => {
  const h = harness(); h.state.busy=true; assert.equal(h.request(rows).code,'busy');
  assert.equal(h.state.opens,0); h.state.busy=false;
  const updated = rows.map(r=>[...r]); updated[0][3]='=IMPORTXML("url")'; h.request(updated);
  assert.equal(h.state.cells[1][3],"'=IMPORTXML(\"url\")");
});
console.log(`${tests} receiver tests passed`);
