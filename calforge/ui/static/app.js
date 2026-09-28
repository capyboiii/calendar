/**
 * CalForge Studio — giao diện cho người không rành kỹ thuật:
 * nhập chủ đề + số cuốn -> bấm Bắt đầu -> xem tiến độ bằng lời -> nhận các cuốn lịch.
 */

const MIN_PER_BOOK = 10;           // ước lượng thời gian mỗi cuốn (phút)
const STEPS = [                    // các bước người dùng nhìn thấy (khớp log "▶ Bước N/6")
  { key: 1, label: 'Nghĩ ý tưởng', weight: 0.10 },
  { key: 2, label: 'Vẽ tranh (lâu nhất)', weight: 0.55 },
  { key: 3, label: 'Làm nét ảnh', weight: 0.05 },
  { key: 4, label: 'Dàn trang in', weight: 0.15 },
  { key: 5, label: 'Ảnh quảng cáo & mô tả', weight: 0.15 },
];

const S = {
  projects: [],
  accounts: [],
  task: null,          // tác vụ đang chạy {id, params, start_time, logs}
  logs: [],
  pollTimer: null,
  refreshTimer: null,
  openBook: null,
};

const $ = (id) => document.getElementById(id);

document.addEventListener('DOMContentLoaded', () => {
  bindEvents();
  loadAccounts();
  loadProjects();
  reattachRunningTask();
});

// --------------------------------------------------------------------------
// Sự kiện
// --------------------------------------------------------------------------
function bindEvents() {
  $('btnStart').addEventListener('click', startBatch);
  $('inputKeyword').addEventListener('keydown', (e) => { if (e.key === 'Enter') startBatch(); });
  document.querySelectorAll('.stepper button').forEach((b) => b.addEventListener('click', () => {
    setCount(countValue() + Number(b.dataset.step));
  }));
  $('inputCount').addEventListener('input', () => updateHint());
  $('btnStop').addEventListener('click', stopTask);
  $('btnAccounts').addEventListener('click', openAccounts);
  $('btnNoticeAccounts').addEventListener('click', openAccounts);
  $('btnAccAdd').addEventListener('click', addAccount);
  $('btnBulkGo').addEventListener('click', startBulkLogin);
  $('btnR2Settings').addEventListener('click', openR2);
  $('btnR2Save').addEventListener('click', saveR2);
  $('btnShop').addEventListener('click', runShop);
  $('inputAccName').addEventListener('keydown', (e) => { if (e.key === 'Enter') addAccount(); });

  document.querySelectorAll('.modal').forEach((m) => {
    m.addEventListener('click', (e) => {
      if (e.target === m || e.target.closest('[data-close]')) m.hidden = true;
    });
  });
  document.addEventListener('keydown', (e) => {
    if (e.key === 'Escape') document.querySelectorAll('.modal').forEach((m) => { m.hidden = true; });
  });
}

function countValue() {
  return Math.max(1, Math.min(20, parseInt($('inputCount').value, 10) || 1));
}

function setCount(n) {
  $('inputCount').value = Math.max(1, Math.min(20, n));
  updateHint();
}

function updateHint() {
  const n = countValue();
  $('startHint').textContent = `~${fmtMinutes(n * MIN_PER_BOOK)} (tuỳ số tài khoản còn lượt)`;
}

// --------------------------------------------------------------------------
// Tải dữ liệu
// --------------------------------------------------------------------------
async function api(path, body) {
  const res = await fetch(path, body === undefined ? {} : {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body),
  });
  const data = await res.json().catch(() => ({}));
  if (!res.ok || data.error) throw new Error(data.error || `Lỗi máy chủ (${res.status})`);
  return data;
}

async function loadProjects() {
  try {
    const data = await api('/api/projects');
    S.projects = data.projects || [];
    renderResults();
    if (S.openBook) {
      const b = findBook(S.openBook);
      if (b && !$('bookModal').hidden) renderBook(b.book, b.keyword);
    }
  } catch (err) {
    $('results').innerHTML = `<p class="empty">Không tải được danh sách lịch: ${esc(err.message)}</p>`;
  }
}

async function loadAccounts() {
  try {
    const data = await api('/api/accounts');
    S.accounts = data.accounts || [];
  } catch (_) {
    S.accounts = [];
  }
  const ready = S.accounts.filter((a) => a.has_session).length;
  $('accSummary').textContent = `(${ready}/${S.accounts.length} sẵn sàng)`;
  $('accDot').className = 'dot ' + (ready ? 'ok' : 'bad');
  $('accNotice').hidden = ready > 0;
  renderAccounts();
}

// --------------------------------------------------------------------------
// Bắt đầu / theo dõi / dừng
// --------------------------------------------------------------------------
async function startBatch() {
  const keyword = $('inputKeyword').value.trim();
  if (!keyword) {
    toast('Nhập chủ đề trước đã (ví dụ: chickens).', 'error');
    $('inputKeyword').focus();
    return;
  }
  if (!S.accounts.some((a) => a.has_session)) {
    toast('Cần đăng nhập ít nhất một tài khoản ChatGPT.', 'error');
    openAccounts();
    return;
  }
  const product = (document.querySelector('input[name="product"]:checked') || {}).value || 'wall_grid';
  const params = { keyword, batch_size: countValue(), product };   // phong cách: máy tự chia đều
  $('btnStart').disabled = true;
  try {
    const data = await api('/api/action', { action: 'run', params });
    attachTask({ id: data.task_id, params, start_time: Date.now() / 1000 });
  } catch (err) {
    toast(err.message, 'error');
    $('btnStart').disabled = false;
  }
}

async function reattachRunningTask() {
  try {
    const data = await api('/api/tasks');
    const t = (data.tasks || []).find((x) => x.status === 'running' && x.action === 'run');
    if (t) attachTask(t);
  } catch (_) { /* máy chủ cũ không có danh sách tác vụ */ }
}

function attachTask(task) {
  S.task = task;
  S.logs = [];
  $('runCard').hidden = false;
  $('startCard').classList.add('dim');
  $('btnStart').disabled = true;
  $('runTitle').textContent = `Đang làm ${task.params.batch_size || 1} cuốn lịch "${task.params.keyword}"`;
  renderProgress();
  clearInterval(S.pollTimer);
  clearInterval(S.refreshTimer);
  S.pollTimer = setInterval(pollTask, 1500);
  S.refreshTimer = setInterval(loadProjects, 20000);   // cuốn nào xong hiện ngay bên dưới
  pollTask();
  $('runCard').scrollIntoView({ behavior: 'smooth', block: 'start' });
}

async function pollTask() {
  if (!S.task) return;
  let t;
  try {
    t = await api(`/api/task?id=${S.task.id}&since=${S.logs.length}`);
  } catch (_) {
    return;
  }
  S.logs.push(...(t.logs || []));
  S.task.start_time = t.start_time || S.task.start_time;
  renderProgress();
  if (t.status !== 'running') finishTask(t.status);
}

function finishTask(status) {
  clearInterval(S.pollTimer);
  clearInterval(S.refreshTimer);
  const kw = S.task.params.keyword;
  S.task = null;
  $('runCard').hidden = true;
  $('startCard').classList.remove('dim');
  $('btnStart').disabled = false;
  loadProjects().then(() => {
    const proj = S.projects.find((p) => p.keyword === slug(kw));
    const rows = ((proj && proj.batch) || {}).report || [];
    const ok = rows.filter((r) => r.ok).length;
    if (status === 'stopped') toast('Đã dừng. Bấm Bắt đầu lại với cùng chủ đề để làm tiếp phần còn dở.', 'info', 8000);
    else if (rows.length && ok === rows.length) toast(`Xong! ${ok} cuốn lịch "${kw}" đã sẵn sàng.`, 'success', 10000);
    else if (rows.length) toast(`Xong ${ok}/${rows.length} cuốn. Cuốn lỗi có ghi lý do và nút "Làm tiếp".`, 'info', 12000);
    else if (status === 'success') toast('Đã xong.', 'success');
    else toast('Có lỗi khi chạy. Mở "Chi tiết" hoặc thử lại.', 'error', 10000);
  });
  loadAccounts();
}

async function stopTask() {
  if (!S.task) return;
  if (!confirm('Dừng lại? Phần đã làm được giữ nguyên. Lần sau bấm Bắt đầu với cùng chủ đề sẽ làm tiếp.')) return;
  try {
    await api('/api/task/stop', { id: S.task.id });
  } catch (err) {
    toast(err.message, 'error');
  }
}

// Đọc log thành "đang ở cuốn mấy, bước nào" bằng lời dễ hiểu.
function readProgress(logs, target) {
  let book = 0, bookName = '', step = 1, sweep = false, stepText = '';
  logs.forEach((line) => {
    const prod = line.match(/===== Sản xuất: (.+?) =====/);
    if (prod) {
      if (prod[1] !== bookName) book += 1;
      bookName = prod[1];
      step = 2;
      stepText = '';
      return;
    }
    if (/▶ (Lượt lên ý|P1|P1b|P2|Bước 1\/6)/.test(line)) { step = 1; stepText = ''; }
    const m = line.match(/▶ Bước (\d)(?:\/6|b| \()/);
    if (m) {
      step = /Bước 4b/.test(line) ? 5 : Number(m[1]);
      stepText = '';
    }
    if (/▶ Vòng vét/.test(line)) { sweep = true; stepText = 'Đang chờ tài khoản ChatGPT hồi lượt rồi làm lại cuốn bị dở'; }
    if (/hết lượt|limit/i.test(line) && /chuyển tài khoản/.test(line)) stepText = 'Một tài khoản hết lượt, đang đổi sang tài khoản khác';
    const pause = line.match(/⏸ Tất cả tài khoản hết lượt .*thử lại lúc (\d\d:\d\d)/);
    if (pause) stepText = `Cả 5 tài khoản ChatGPT tạm hết lượt - máy tự chờ, thử lại lúc ${pause[1]}`;
    if (/▶ Hết giờ chờ/.test(line)) stepText = '';
  });
  const done = STEPS.filter((s) => s.key < step).reduce((a, s) => a + s.weight, 0);
  const current = Math.max(0, book - 1) + (book ? done : done * 0.5);
  const pct = sweep ? 97 : Math.min(97, Math.round((current / Math.max(1, target)) * 100));
  return { book: Math.max(book, 1), bookName, step, pct, sweep, stepText };
}

function renderProgress() {
  if (!S.task) return;
  const target = Number(S.task.params.batch_size) || 1;
  const p = readProgress(S.logs, target);
  $('runSub').textContent = p.sweep
    ? 'Đang làm lại các cuốn bị dở'
    : `Cuốn ${Math.min(p.book, target)}/${target}` + (p.bookName ? ` · ${prettyName(p.bookName)}` : '')
      + (p.stepText ? ` · ${p.stepText}` : '');
  $('runSteps').innerHTML = STEPS.map((s) => {
    const cls = s.key < p.step ? 'done' : s.key === p.step ? 'now' : '';
    return `<li class="${cls}"><span class="n">${s.key < p.step ? '✓' : s.key}</span>${esc(s.label)}</li>`;
  }).join('');
  $('runBar').style.width = `${p.pct}%`;
  const elapsed = (Date.now() / 1000 - (S.task.start_time || Date.now() / 1000)) / 60;
  const left = Math.max(1, target * MIN_PER_BOOK - elapsed);
  $('runTime').textContent = `${fmtMinutes(elapsed)} · còn ~${fmtMinutes(left)}`;
  const log = $('runLog');
  log.textContent = S.logs.slice(-400).join('\n');
  if ($('logBox').open) log.scrollTop = log.scrollHeight;
}

// --------------------------------------------------------------------------
// Kết quả
// --------------------------------------------------------------------------
function bookState(b) {
  const st = b.status || {};
  if (st.ok && (st.stage === 'listing' || st.stage === 'printify')) return 'done';
  if (st.ok === false) return 'error';
  return 'pending';
}

const STATE_LABEL = { done: 'Xong', error: 'Bị dở', pending: 'Chưa xong' };

function friendlyReason(st) {
  const stage = (st || {}).stage;
  const raw = (st || {}).reason || '';
  if (stage === 'images') return 'ChatGPT chưa vẽ đủ tranh (thường do tài khoản hết lượt). Chờ một lúc rồi bấm "Làm tiếp".';
  if (stage === 'render') return 'Lỗi khi dàn trang in. Bấm "Làm tiếp"; nếu vẫn lỗi, gửi phần chi tiết cho người kỹ thuật.';
  if (stage === 'printify') return 'Chưa đưa lên được Printify. Kiểm tra mạng rồi bấm "Làm tiếp".';
  if (stage === 'crash') return 'Gặp lỗi bất ngờ (mất mạng, Chrome bị tắt…). Bấm "Làm tiếp" để thử lại.';
  return raw || 'Chưa làm xong. Bấm "Làm tiếp".';
}

function renderResults() {
  const box = $('results');
  const books = S.projects.reduce((n, p) => n + (p.concepts || []).length, 0);
  $('bookCount').textContent = books ? `${books} cuốn` : '';
  if (!books) {
    box.innerHTML = '<p class="empty">Chưa có cuốn nào.</p>';
    return;
  }
  const running = S.task ? slug(S.task.params.keyword) : '';
  const runProd = S.task ? (S.task.params.product || 'wall_grid') : '';
  const groups = [...S.projects]
    .filter((p) => (p.concepts || []).length)
    .sort((a, b) => newest(b) - newest(a));
  box.innerHTML = '';
  groups.forEach((proj) => {
    const done = proj.concepts.filter((c) => bookState(c) === 'done').length;
    const sec = document.createElement('div');
    sec.className = 'group';
    sec.innerHTML = `
      <div class="group-head">
        <h3>${esc(proj.keyword)}${proj.group ? ` <small class="muted">· ${esc(proj.group)}</small>` : ''}</h3>
        <span class="count">${done}/${proj.concepts.length} xong${proj.keyword === running && (!proj.product || proj.product === runProd) ? ' · đang chạy' : ''}</span>
        <button class="btn btn-small btn-ghost" data-open="${esc(proj.path)}">Mở thư mục</button>
      </div>
      <div class="books"></div>`;
    sec.querySelector('[data-open]').addEventListener('click', () => openFolder(proj.path));
    const grid = sec.querySelector('.books');
    proj.concepts.forEach((c) => grid.appendChild(bookCard(c, proj.keyword)));
    box.appendChild(sec);
  });
}

function bookCard(c, keyword) {
  const state = bookState(c);
  const el = document.createElement('button');
  el.className = `book ${state}`;
  el.innerHTML = `
    <div class="thumb">${c.cover ? `<img loading="lazy" src="${thumbUrl(c.cover)}" alt="">` : '<span>Chưa có ảnh</span>'}</div>
    <div class="book-meta">
      <strong>${esc(c.title)}</strong>
      <span class="pill ${state}">${STATE_LABEL[state]}</span>
    </div>
    ${c.product === 'wall_premade' ? '<p class="kind-tag">Wall Calendar</p>' : ''}
    ${state === 'error' ? `<p class="why">${esc(friendlyReason(c.status))}</p>` : ''}`;
  el.addEventListener('click', () => { S.openBook = c.path; renderBook(c, keyword); $('bookModal').hidden = false; });
  return el;
}

function renderBook(c, keyword) {
  const state = bookState(c);
  $('bookTitle').textContent = c.title;
  $('bookSub').textContent = [keyword, c.product === 'wall_premade' ? 'Wall Calendar' : 'Wall Calendar (Blank)', c.subtitle].filter(Boolean).join(' · ');
  $('bookState').textContent = STATE_LABEL[state];
  $('bookState').className = `pill ${state}`;
  const err = $('bookError');
  err.hidden = state !== 'error';
  err.textContent = state === 'error' ? friendlyReason(c.status) : '';

  const g = $('bookGallery');
  g.innerHTML = (c.previews || []).length
    ? c.previews.map((p) => `<img loading="lazy" src="${thumbUrl(p, 400)}" alt="" data-full="${thumbUrl(p, 1600)}">`).join('')
    : `<p class="empty">Ảnh quảng cáo sẽ có khi cuốn này làm xong.</p>`;
  g.querySelectorAll('img').forEach((img) => img.addEventListener('click', () => {
    $('lightboxImg').src = img.dataset.full;
    $('lightbox').hidden = false;
  }));

  const a = $('bookActions');
  a.innerHTML = '';
  a.appendChild(button('Mở thư mục cuốn này', 'btn-primary', () => openFolder(c.path)));
  (c.pdfs || []).forEach((pdf) => {
    const link = document.createElement('a');
    link.className = 'btn';
    link.href = fileUrl(pdf.path);
    link.target = '_blank';
    link.textContent = `PDF in tại nhà ${pdf.label}"`;
    a.appendChild(link);
  });
  if (state !== 'done') {
    a.appendChild(button('Làm tiếp', 'btn-accent', () => continueBook(c)));
  }
  const L = c.listing || {};
  const lb = $('bookListing');
  if (!L.title) {
    lb.innerHTML = '';
    return;
  }
  lb.innerHTML = `
    <h3>Nội dung đăng bán</h3>
    <div class="copy-row"><div><span class="label">Tiêu đề</span><p>${esc(L.title)}</p></div><button class="btn btn-small" data-copy="title">Chép</button></div>
    <div class="copy-row"><div><span class="label">Thẻ tìm kiếm</span><p class="tags">${(L.tags || []).map((t) => `<span>${esc(t)}</span>`).join('')}</p></div><button class="btn btn-small" data-copy="tags">Chép</button></div>
    <div class="copy-row"><div><span class="label">Mô tả</span><div class="desc">${sanitizeDesc(L.description || '')}</div></div><button class="btn btn-small" data-copy="description">Chép</button></div>`;
  const texts = { title: L.title, tags: (L.tags || []).join(', '), description: L.description || '' };
  lb.querySelectorAll('[data-copy]').forEach((btn) => btn.addEventListener('click', () => copy(texts[btn.dataset.copy], btn)));
}

async function continueBook(c) {
  try {
    await api('/api/action', { action: 'produce', params: { concept: c.path } });
    $('bookModal').hidden = true;
    toast(`Đang làm tiếp "${c.title}". Kết quả sẽ tự hiện ở đây.`, 'info', 8000);
    const poll = setInterval(async () => {
      const data = await api('/api/tasks').catch(() => ({ tasks: [] }));
      if (!(data.tasks || []).some((t) => t.status === 'running')) {
        clearInterval(poll);
        loadProjects();
        toast(`Đã chạy xong "${c.title}".`, 'success');
      }
    }, 5000);
  } catch (err) {
    toast(err.message, 'error');
  }
}

async function openFolder(path) {
  try {
    await api('/api/open', { path });
  } catch (err) {
    toast(err.message, 'error');
  }
}

// --------------------------------------------------------------------------
// Tài khoản ChatGPT
// --------------------------------------------------------------------------
function openAccounts() {
  loadAccounts();
  $('accModal').hidden = false;
}

function renderAccounts() {
  const ul = $('accList');
  if (!S.accounts.length) {
    ul.innerHTML = '<li class="empty">Chưa có tài khoản nào.</li>';
    return;
  }
  ul.innerHTML = '';
  S.accounts.forEach((acc) => {
    const li = document.createElement('li');
    const state = acc.is_locked ? ['Đang mở', 'warn'] : acc.has_session ? ['Sẵn sàng', 'ok'] : ['Chưa đăng nhập', 'bad'];
    li.innerHTML = `
      <span class="dot ${state[1]}"></span>
      <strong>${esc(acc.name)}</strong>
      <span class="muted">${state[0]}${acc.email ? ` · ${esc(acc.email)}` : ''}</span>
      <span class="grow"></span>`;
    li.appendChild(button(acc.has_session ? 'Đăng nhập lại' : 'Đăng nhập', 'btn-small', () => loginAccount(acc.name)));
    li.appendChild(button('Xoá', 'btn-small btn-danger-ghost', () => deleteAccount(acc.name)));
    ul.appendChild(li);
  });
}

// Đăng nhập hàng loạt: mỗi dòng email|mật khẩu|mã 2FA; máy chủ mở mỗi tài khoản một Chrome, tự điền form.
const BULK_LABEL = {
  pending: 'Chờ', running: 'Đang đăng nhập', done: 'Xong', failed: 'Lỗi', needs_human: 'Cần bạn xác minh',
};
let bulkPoll = null;
let bulkSkipped = [];                                  // dòng bị bỏ qua (email đã có, trùng, sai định dạng...)

async function startBulkLogin() {
  const box = $('bulkCreds');
  const creds = box.value.trim();
  if (!creds) return;
  $('btnBulkGo').disabled = true;
  try {
    const res = await api('/api/accounts/bulk-login', { creds });
    box.value = '';                                   // xoá mật khẩu khỏi màn hình ngay
    bulkSkipped = res.skipped || [];
    renderBulk(res.items || []);
    clearInterval(bulkPoll);
    bulkPoll = setInterval(pollBulk, 2000);
  } catch (err) {
    toast(err.message, 'error');
    $('btnBulkGo').disabled = false;
  }
}

async function pollBulk() {
  const d = await api('/api/accounts/bulk-login/status').catch(() => null);
  if (!d) return;
  renderBulk(d.items || []);
  if (!d.active) {
    clearInterval(bulkPoll);
    $('btnBulkGo').disabled = false;
    const ok = (d.items || []).filter((i) => i.status === 'done').length;
    toast(`Đăng nhập xong ${ok}/${(d.items || []).length} tài khoản.`, ok ? 'success' : 'error', 8000);
    loadAccounts();
  }
}

function renderBulk(items) {
  $('bulkList').innerHTML = items.map((it) => {
    const st = it.needs_human ? 'needs_human' : it.status;
    const cls = st === 'done' ? 'ok' : st === 'failed' ? 'bad' : 'warn';
    return `<li><span class="dot ${cls}"></span><strong>${esc(it.profile)}</strong>
      <span class="muted grow">${esc(it.email)}</span>
      <span class="pill ${st === 'done' ? 'done' : st === 'failed' ? 'error' : 'pending'}">${BULK_LABEL[st] || st}</span>
      ${it.error && st !== 'done' ? `<span class="why">${esc(it.error)}</span>` : ''}</li>`;
  }).join('') + bulkSkipped.map((why) =>
    `<li><span class="dot"></span><span class="muted grow">${esc(why)}</span><span class="pill">Bỏ qua</span></li>`).join('');
}

// ---- Cloudflare R2 + CSV sản phẩm -------------------------------------------------------------
async function openR2() {
  const d = await api('/api/r2').catch(() => ({}));
  $('r2Account').value = d.account_id || '';
  $('r2Key').value = d.access_key_id || '';
  $('r2Secret').value = '';
  $('r2Secret').placeholder = d.secret_set ? `Đã lưu (${d.secret_hint || '••••'}) - để trống để giữ` : '';
  $('r2Bucket').value = d.bucket || '';
  $('r2Public').value = d.public_url || '';
  $('r2Modal').hidden = false;
}

async function saveR2() {
  try {
    await api('/api/r2', {
      account_id: $('r2Account').value, access_key_id: $('r2Key').value, secret_access_key: $('r2Secret').value,
      bucket: $('r2Bucket').value, public_url: $('r2Public').value,
    });
    $('r2Secret').value = '';
    $('r2Modal').hidden = true;
    toast('Đã lưu khoá R2.', 'success');
  } catch (err) {
    toast(err.message, 'error');
  }
}

async function runShop() {
  const btn = $('btnShop');
  btn.disabled = true;
  const box = $('shopResult');
  box.hidden = false;
  box.textContent = 'Đang đẩy lên R2…';
  try {
    const data = await api('/api/action', { action: 'shop', params: {} });
    const poll = setInterval(async () => {
      const t = await api(`/api/task?id=${data.task_id}`).catch(() => null);
      if (!t) return;
      const logs = t.logs || [];
      const up = logs.filter((l) => l.includes('↑')).length;
      if (t.status === 'running') { box.textContent = `Đang đẩy lên R2… ${up} file`; return; }
      clearInterval(poll);
      btn.disabled = false;
      const err = logs.find((l) => l.startsWith('✘'));
      const summary = logs.find((l) => l.startsWith('Đã đẩy lên R2')) || '';
      const csvLine = logs.find((l) => l.startsWith('CSV: ')) || '';
      const csvPath = csvLine.slice(5).trim();
      const rel = csvPath.includes('projects') ? csvPath.slice(csvPath.indexOf('projects')).split(String.fromCharCode(92)).join('/') : '';
      box.innerHTML = t.status === 'success'
        ? `${esc(summary)}${rel ? ` · <a href="${fileUrl(rel)}" download="${esc(rel.split('/').pop())}">Tải CSV</a>` : ` · ${esc(csvPath)}`}`
        : `<span class="why">${esc(err || 'Có lỗi, xem Chi tiết.')}</span>`;
      if (t.status !== 'success' && /khoá R2/.test(err || '')) openR2();
    }, 2000);
  } catch (err) {
    btn.disabled = false;
    box.textContent = err.message;
  }
}

async function addAccount() {
  const name = $('inputAccName').value.trim();
  if (!name) return;
  try {
    await api('/api/accounts/create', { name });
    $('inputAccName').value = '';
    await loadAccounts();
    loginAccount(name);
  } catch (err) {
    toast(err.message, 'error');
  }
}

async function loginAccount(name) {
  try {
    const data = await api('/api/action', { action: 'login', params: { profile: name } });
    toast(`Đã mở Chrome cho "${name}". Đăng nhập ChatGPT xong thì đóng cửa sổ Chrome.`, 'info', 10000);
    const poll = setInterval(async () => {
      const t = await api(`/api/task?id=${data.task_id}&since=999999`).catch(() => null);
      if (!t || t.status !== 'running') {
        clearInterval(poll);
        loadAccounts();
      }
    }, 3000);
  } catch (err) {
    toast(err.message, 'error');
  }
}

async function deleteAccount(name) {
  if (!confirm(`Xoá tài khoản "${name}" khỏi máy này?`)) return;
  try {
    await api('/api/accounts/delete', { name });
    loadAccounts();
  } catch (err) {
    toast(err.message, 'error');
  }
}

// --------------------------------------------------------------------------
// Tiện ích
// --------------------------------------------------------------------------
function button(text, cls, onClick) {
  const b = document.createElement('button');
  b.className = `btn ${cls || ''}`;
  b.textContent = text;
  b.addEventListener('click', onClick);
  return b;
}

function toast(msg, type = 'info', ms = 5000) {
  const t = document.createElement('div');
  t.className = `toast ${type}`;
  t.textContent = msg;
  $('toasts').appendChild(t);
  setTimeout(() => t.remove(), ms);
}

function copy(text, btn) {
  navigator.clipboard.writeText(text || '').then(() => {
    const old = btn.textContent;
    btn.textContent = 'Đã chép ✓';
    setTimeout(() => { btn.textContent = old; }, 1500);
  });
}

function findBook(path) {
  for (const p of S.projects) {
    const book = (p.concepts || []).find((c) => c.path === path);
    if (book) return { book, keyword: p.keyword };
  }
  return null;
}

function newest(proj) {
  return Math.max(0, ...(proj.concepts || []).map((c) => Date.parse(((c.status || {}).updated || '').replace(' ', 'T')) || 0));
}

function prettyName(dir) {
  return dir.replace(/^r\d+a\d+-/, '').replace(/-/g, ' ');
}

function slug(text) {
  return (text || '').toLowerCase().replace(/[^a-z0-9]+/g, '-').replace(/^-|-$/g, '');
}

function thumbUrl(path, w = 480) {
  return `/api/thumb?path=${encodeURIComponent(path)}&w=${w}`;
}

function fileUrl(path) {
  return `/api/file?path=${encodeURIComponent(path)}`;
}

function fmtMinutes(min) {
  const m = Math.round(min);
  if (m < 60) return `${Math.max(1, m)} phút`;
  const h = Math.floor(m / 60);
  return `${h} giờ${m % 60 ? ` ${m % 60} phút` : ''}`;
}

function esc(s) {
  return String(s ?? '').replace(/[&<>"']/g, (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));
}

// Mô tả listing là HTML đơn giản do máy viết; chỉ giữ vài thẻ định dạng an toàn.
function sanitizeDesc(html) {
  const tmp = new DOMParser().parseFromString(`<div>${html}</div>`, 'text/html').body.firstChild;
  tmp.querySelectorAll('*').forEach((el) => {
    if (!['P', 'BR', 'UL', 'OL', 'LI', 'B', 'STRONG', 'I', 'EM', 'H3', 'H4'].includes(el.tagName)) {
      el.replaceWith(...el.childNodes);
    } else {
      [...el.attributes].forEach((a) => el.removeAttribute(a.name));
    }
  });
  return tmp.innerHTML;
}
