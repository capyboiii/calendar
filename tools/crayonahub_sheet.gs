// Deploy once as a Web app, execute as owner. Keep SHEET_SYNC_SECRET in Script Properties.
// appsscript.json must use only the spreadsheets scope. The receiver always targets this sheet.
const TARGET_SHEET = '1qD3M9OQ57JPdW0rV_X3_-ik4pSvywMuPCPNyPLs_CGg';
const COLUMNS = ['SKU', 'Description', 'Tags', 'Title', 'Sizes', 'Paper', 'Design', 'Mockup'];

function reply_(data) {
  return ContentService.createTextOutput(JSON.stringify(data)).setMimeType(ContentService.MimeType.JSON);
}

function doPost(e) {
  let lock;
  try {
    const secret = PropertiesService.getScriptProperties().getProperty('SHEET_SYNC_SECRET');
    if (!secret || secret.length < 32) return reply_({ok: false, code: 'config'});
    const envelope = JSON.parse(e.postData.contents);
    if (typeof envelope.payload !== 'string' || envelope.payload.length > 2000000) {
      return reply_({ok: false, code: 'invalid'});
    }
    const expected = Utilities.computeHmacSha256Signature(envelope.payload, secret, Utilities.Charset.UTF_8)
      .map(b => ('0' + ((b + 256) % 256).toString(16)).slice(-2)).join('');
    const signature = String(envelope.signature || '');
    let diff = expected.length ^ signature.length;
    for (let i = 0; i < expected.length; i++) diff |= expected.charCodeAt(i) ^ (signature.charCodeAt(i) || 0);
    if (diff) return reply_({ok: false, code: 'auth'});
    const data = JSON.parse(envelope.payload);
    if (!Number.isFinite(data.timestamp) || Math.abs(Date.now() / 1000 - data.timestamp) > 600) {
      return reply_({ok: false, code: 'auth'});
    }
    if (data.version !== 1 || data.spreadsheet_id !== TARGET_SHEET || data.sheet_id !== 0 ||
        JSON.stringify(data.header) !== JSON.stringify(COLUMNS) || !Array.isArray(data.rows) ||
        data.rows.length < 2 || data.rows.length > 20 || data.rows.some(row =>
          !Array.isArray(row) || row.length !== COLUMNS.length || row.some(v => typeof v !== 'string' || v.length > 49000) ||
          !row[0] || /[\r\n\t]/.test(row[0]))) return reply_({ok: false, code: 'invalid'});
    const skus = data.rows.map(row => row[0]);
    if (new Set(skus).size !== skus.length) return reply_({ok: false, code: 'duplicate'});
    lock = LockService.getScriptLock();
    if (!lock.tryLock(20000)) return reply_({ok: false, code: 'busy'});
    const sheet = SpreadsheetApp.openById(TARGET_SHEET).getSheets().find(s => s.getSheetId() === 0);
    if (!sheet) return reply_({ok: false, code: 'config'});
    const header = sheet.getRange(1, 1, 1, COLUMNS.length).getDisplayValues()[0];
    if (JSON.stringify(header) !== JSON.stringify(COLUMNS)) return reply_({ok: false, code: 'schema'});
    const count = Math.max(0, sheet.getLastRow() - 1);
    const current = count ? sheet.getRange(2, 1, count, 1).getDisplayValues().flat() : [];
    const index = new Map();
    for (let i = 0; i < current.length; i++) {
      const sku = current[i];
      if (!sku) continue;
      if (index.has(sku) && skus.includes(sku)) return reply_({ok: false, code: 'duplicate'});
      index.set(sku, i + 2);
    }
    const widths = [180, 220, 160, 220, 90, 90, 260, 420];
    widths.forEach((width, i) => sheet.setColumnWidth(i + 1, width));
    let next = Math.max(2, sheet.getLastRow() + 1);
    const positions = data.rows.map(row => index.get(row[0]) || next++);
    const needed = Math.max(...positions);
    if (needed > sheet.getMaxRows()) sheet.insertRowsAfter(sheet.getMaxRows(), needed - sheet.getMaxRows());
    for (let i = 0; i < data.rows.length; i++) {
      const range = sheet.getRange(positions[i], 1, 1, COLUMNS.length);
      range.breakApart(); // A merged SKU/Description cell otherwise silently discards Description.
      // setValues interprets leading '=' as a formula, so explicitly escape such content.
      const values = data.rows[i].map(v => v.startsWith('=') ? "'" + v : v);
      range.setNumberFormat('@').setValues([values]).setHorizontalAlignment('left')
        .setVerticalAlignment('top').setWrapStrategy(SpreadsheetApp.WrapStrategy.WRAP);
      // Mockup URLs are newline-separated in the base SKU row. Give that row
      // enough room to display the list, while keeping variant rows compact.
      const mockupLines = data.rows[i][7] ? data.rows[i][7].split('\n').length : 0;
      sheet.setRowHeightsForced(positions[i], 1, mockupLines ? Math.min(409, Math.max(160, mockupLines * 42)) : 64);
    }
    SpreadsheetApp.flush();
    return reply_({ok: true, skus: skus});
  } catch (_) {
    return reply_({ok: false, code: 'write'});
  } finally {
    if (lock && lock.hasLock()) lock.releaseLock();
  }
}
