// Trang "Làm theo ảnh mẫu" - cùng khung với trang chính: thẻ Làm lịch mới, thẻ Đang chạy (các bước + thanh tiến độ +
// chi tiết), Hàng đợi, Lịch đã làm. Chỉ dùng tài khoản ChatGPT Plus còn hạn.
const $ = (id) => document.getElementById(id);
const esc = (s) => String(s ?? '').replace(/[&<>"']/g, (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));
const thumbUrl = (p, w = 480) => `/api/thumb?w=${w}&path=${encodeURIComponent(p)}`;
const MAX_REFS = 10;
// Các bước người dùng nhìn thấy; tỉ lệ = phần thời gian thường mất của mỗi bước.
const STEPS = [
  { key: 1, label: 'Vẽ 12 artwork (lâu nhất)', from: 0, to: 40 },
  { key: 2, label: 'Đặt tên & listing', from: 40, to: 43 },
  { key: 3, label: 'Vẽ bìa', from: 43, to: 48 },
  { key: 4, label: 'Vẽ 12 trang lịch', from: 48, to: 85 },
  { key: 5, label: 'Làm nét, dàn trang in, ảnh quảng cáo', from: 85, to: 99 },
];
const STATE = {
  pending: ['Chờ', ''], running: ['Đang làm', 'run'], done: ['Xong', 'ok'], failed: ['Bị dở', 'bad'], rejected: ['Bị loại', 'bad'],
};
const S = { refs: [], data: null, taskId: null, logs: [], since: 0 };

async function api(path, body) {
  const res = await fetch(path, body === undefined ? {} : {
    method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body),
  });
  const data = await res.json().catch(() => ({}));
  if (!res.ok || data.error) throw new Error(data.error || `Lỗi máy chủ (${res.status})`);
  return data;
}

function toast(msg, kind = 'info') {
  const t = document.createElement('div');
  t.className = `toast ${kind}`;
  t.textContent = msg;
  $('toasts').appendChild(t);
  setTimeout(() => t.remove(), 6000);
}

function button(text, cls, fn) {
  const b = document.createElement('button');
  b.className = `btn ${cls}`;
  b.textContent = text;
  b.addEventListener('click', fn);
  return b;
}

const openFolder = (path) => api('/api/open', { path }).catch((e) => toast(e.message, 'error'));

// ---------------------------------------------------------------- ảnh mẫu
// Nhận MỌI loại file. Ảnh trình duyệt đọc được (JPG, PNG, WEBP, GIF, AVIF, BMP, SVG...) -> JPG (thu về cạnh dài
// 2048px nếu lớn: ChatGPT vẫn đọc rõ, tải lên nhanh). File trình duyệt không đọc được (TIFF, PDF...) gửi nguyên cho máy
// chủ đổi (PDF: mỗi trang thành một ảnh mẫu); máy chủ cũng không đọc được thì báo lỗi rõ tên file.
const KEEP_TYPES = /^image\/(png|jpeg|webp)$/;

function readDataUrl(file) {
  return new Promise((resolve, reject) => {
    const reader = new FileReader();
    reader.onerror = () => reject(new Error(`${file.name}: không đọc được file`));
    reader.onload = () => resolve(reader.result);
    reader.readAsDataURL(file);
  });
}

function decode(url) {
  return new Promise((resolve) => {
    const img = new Image();
    img.onload = () => resolve(img.naturalWidth ? img : null);
    img.onerror = () => resolve(null);
    img.src = url;
  });
}

async function loadImage(file) {
  const url = await readDataUrl(file);
  const img = await decode(url);
  if (!img) return { name: file.name, data: url, raw: true };          // để máy chủ đổi (TIFF, PDF...)
  const long = Math.max(img.naturalWidth, img.naturalHeight);
  if (KEEP_TYPES.test(file.type) && long <= 2048 && file.size <= 6 * 1024 * 1024) return { name: file.name, data: url };
  const k = Math.min(1, 2048 / long);
  const c = document.createElement('canvas');
  c.width = Math.max(1, Math.round(img.naturalWidth * k));
  c.height = Math.max(1, Math.round(img.naturalHeight * k));
  const g = c.getContext('2d');
  g.fillStyle = '#fff';                                                 // ảnh trong suốt / SVG: nền trắng
  g.fillRect(0, 0, c.width, c.height);
  g.drawImage(img, 0, 0, c.width, c.height);
  return { name: file.name.replace(/\.[^.]+$/, '') + '.jpg', data: c.toDataURL('image/jpeg', 0.92) };
}

let fileQueue = Promise.resolve();
function addFiles(list) {
  const files = Array.from(list);
  fileQueue = fileQueue.then(() => appendFiles(files)).catch((e) => toast(e.message, 'error'));
  return fileQueue;
}

async function appendFiles(list) {
  const files = Array.from(list);
  if (!files.length) return;
  const room = MAX_REFS - S.refs.length;
  if (files.length > room) toast(`Tối đa ${MAX_REFS} ảnh mẫu mỗi cuốn - bỏ bớt ${files.length - room} file.`, 'error');
  for (const f of files.slice(0, Math.max(0, room))) {
    try {
      S.refs.push(await loadImage(f));
    } catch (e) {
      toast(e.message, 'error');
    }
  }
  renderRefs();
}

function renderRefs() {
  const ol = $('refList');
  ol.innerHTML = '';
  S.refs.forEach((r, i) => {
    const li = document.createElement('li');
    const ext = (r.name.split('.').pop() || 'file').toUpperCase().slice(0, 5);
    li.innerHTML = `${r.raw ? `<div class="file-ph" title="${esc(r.name)}"><b>${esc(ext)}</b><small>${esc(r.name)}</small></div>`
      : `<img src="${r.data}" alt="">`}<span class="no">${i + 1}</span>
      <div class="tools"><button title="Lên trước" data-a="up">←</button><button title="Bỏ ảnh" data-a="del">✕</button>
      <button title="Xuống sau" data-a="down">→</button></div>`;
    li.querySelectorAll('button').forEach((b) => b.addEventListener('click', () => {
      const a = b.dataset.a;
      if (a === 'del') S.refs.splice(i, 1);
      if (a === 'up' && i > 0) [S.refs[i - 1], S.refs[i]] = [S.refs[i], S.refs[i - 1]];
      if (a === 'down' && i < S.refs.length - 1) [S.refs[i + 1], S.refs[i]] = [S.refs[i], S.refs[i + 1]];
      renderRefs();
    }));
    ol.appendChild(li);
  });
  renderStartButton();
}

function running() {
  const t = S.data && S.data.task;
  return !!(t && t.status === 'running');
}

function renderStartButton() {
  const b = $('btnStart');
  b.disabled = !S.refs.length || !(S.data && S.data.plus.length);
  b.textContent = running() ? 'Thêm vào hàng đợi' : 'Bắt đầu';
  $('startHint').textContent = !S.refs.length
    ? 'Thêm ảnh mẫu để bắt đầu. Mỗi cuốn: 12 artwork + bìa (1 tài khoản Plus), 12 trang lịch (tài khoản Plus khác).'
    : `${S.refs.length} ảnh mẫu → 1 cuốn lịch ${$('year').value}.` + (running() ? ' Đang chạy: cuốn này được làm ngay khi có tài khoản rảnh.' : '');
}

async function start() {
  const btn = $('btnStart');
  btn.disabled = true;
  btn.textContent = 'Đang tải ảnh lên…';
  try {
    const mockup = document.querySelector('input[name="mockup_mode"]:checked').value;
    let data = await api('/api/clone/add', {
      images: S.refs, group: $('group').value.trim(), year: +$('year').value || 2027, mockup_mode: mockup,
    });
    S.refs = [];
    renderRefs();
    if (!running()) data = await api('/api/clone/start', { show: $('showChrome').checked });
    toast(running() ? 'Đã thêm vào hàng đợi - làm ngay khi có tài khoản Plus rảnh.' : 'Đã bắt đầu.', 'success');
    render(data);
  } catch (e) {
    toast(e.message, 'error');
  }
  renderStartButton();
}

// ---------------------------------------------------------------- tiến độ
function stepOf(it) {
  const st = (it.stage || '').toLowerCase();
  const frac = (() => { const m = st.match(/\((\d+)\/12\)/); return m ? +m[1] / 12 : 0; })();
  if (it.status === 'done') return { step: 6, pct: 100 };
  if (st.startsWith('vẽ artwork')) return { step: 1, pct: STEPS[0].from + frac * 40 };
  if (st.startsWith('đặt tên')) return { step: 2, pct: 41 };
  if (st.startsWith('vẽ bìa')) return { step: 3, pct: 45 };
  if (st.startsWith('vẽ trang lịch')) return { step: 4, pct: 48 + frac * 37 };
  if (st.startsWith('upscale') || st.startsWith('dựng')) return { step: 5, pct: st.startsWith('upscale') ? 88 : 94 };
  return { step: 1, pct: 0 };
}

function renderRun() {
  const card = $('runCard');
  const t = S.data.task;
  card.hidden = !running();
  if (!running()) return;
  const items = S.data.items;
  const active = items.filter((i) => i.status === 'running');
  const now = active[0];
  const p = now ? stepOf(now) : { step: 1, pct: 0 };
  const done = items.filter((i) => i.status === 'done' && i.updated >= new Date(t.start_time * 1000).toISOString().slice(0, 19).replace('T', ' ')).length;
  const waiting = items.filter((i) => i.status === 'pending').length;
  $('runTitle').textContent = active.length > 1 ? `Đang làm ${active.length} cuốn` : `Đang làm ${now ? (now.title || 'cuốn mới') : 'lịch'}`;
  const parts = [];
  if (now) parts.push(now.stage || 'đang chuẩn bị');
  if (done) parts.push(`xong ${done} cuốn`);
  if (waiting) parts.push(`${waiting} cuốn đang chờ`);
  $('runSub').textContent = parts.join(' · ') || 'Đang chuẩn bị…';
  $('runSteps').innerHTML = STEPS.map((s) => {
    const cls = s.key < p.step ? 'done' : s.key === p.step ? 'now' : '';
    return `<li class="${cls}"><span class="n">${s.key < p.step ? '✓' : s.key}</span>${esc(s.label)}</li>`;
  }).join('');
  const all = active.map((i) => stepOf(i).pct);
  $('runBar').style.width = `${Math.round(all.length ? all.reduce((a, b) => a + b, 0) / all.length : 2)}%`;
}

function renderLog() {
  const log = $('runLog');
  log.textContent = S.logs.slice(-400).join('\n');
  if ($('logBox').open) log.scrollTop = log.scrollHeight;
}

// ---------------------------------------------------------------- hàng đợi + kết quả
function thumbs(paths) {
  return `<span class="thumbs">${paths.slice(0, 6).map((p) => `<img src="${thumbUrl(p, 90)}" alt="" loading="lazy">`).join('')}</span>`;
}

function renderQueue() {
  const items = S.data.items.filter((i) => i.status === 'pending' || i.status === 'running');
  $('queueCard').hidden = !items.length;
  $('btnRun').hidden = running() || !items.length;
  const ol = $('queueWaiting');
  ol.innerHTML = '';
  let k = 0;
  items.slice().reverse().forEach((i) => {
    const li = document.createElement('li');
    const tag = i.status === 'running' ? '<span class="tag run">Đang làm</span>' : `<span class="tag">Chờ ${++k}</span>`;
    li.innerHTML = `${tag} ${thumbs(i.ref_paths || [])} <strong>${esc(i.title || 'Chưa có tên')}</strong>
      <span class="muted">${esc(i.group || '')} · lịch ${esc(i.year)} · ${i.refs} ảnh mẫu${i.stage ? ` · ${esc(i.stage)}` : ''}</span>
      <span class="grow"></span>`;
    if (i.status !== 'running' || !running()) {
      li.appendChild(button('Bỏ', 'btn-small btn-danger-ghost', () => {
        if (confirm('Bỏ cuốn này khỏi hàng đợi?')) op('remove', i.id);
      }));
    }
    ol.appendChild(li);
  });
}

function bookCard(i) {
  const [label, cls] = STATE[i.status] || [i.status, ''];
  const state = { ok: 'done', bad: i.status === 'rejected' ? 'rejected' : 'error' }[cls] || 'pending';
  const el = document.createElement('button');
  el.className = `book ${state}`;
  el.innerHTML = `
    <div class="thumb">${i.cover ? `<img loading="lazy" src="${thumbUrl(i.cover)}" alt="">` : thumbs(i.ref_paths || [])}</div>
    <div class="book-meta">
      <strong>${esc(i.title || 'Chưa có tên')}</strong>
      <span class="pill ${state}">${label}</span>
    </div>
    ${i.sku ? `<p class="sku" title="Mã SKU - bấm để chép">${esc(i.sku)}</p>` : ''}
    ${i.reason ? `<p class="why">${esc(i.reason)}</p>` : ''}
    ${i.status !== 'done' && i.stage ? `<p class="stage">Dừng ở: ${esc(i.stage)}</p>` : ''}`;
  el.title = i.book ? 'Bấm để mở thư mục cuốn này' : 'Cuốn chưa có thư mục (chưa vẽ xong 12 artwork)';
  el.addEventListener('click', () => { if (i.book) openFolder(i.book); });
  const sku = el.querySelector('.sku');
  if (sku) {
    sku.addEventListener('click', (e) => {
      e.stopPropagation();
      navigator.clipboard?.writeText(i.sku).then(() => toast(`Đã chép SKU ${i.sku}`), () => {});
    });
  }
  if (i.status === 'failed' || i.status === 'rejected') {
    const acts = document.createElement('div');
    acts.className = 'book-actions';
    acts.appendChild(button('Làm tiếp', 'btn-small btn-accent', (e) => { e.stopPropagation(); op('retry', i.id, true); }));
    acts.appendChild(button('Xoá', 'btn-small btn-danger-ghost', (e) => {
      e.stopPropagation();
      if (confirm('Xoá cuốn này khỏi danh sách? (Thư mục cuốn đã làm được vẫn giữ nguyên)')) op('remove', i.id);
    }));
    el.appendChild(acts);
  }
  return el;
}

function renderResults() {
  const items = S.data.items.filter((i) => ['done', 'failed', 'rejected'].includes(i.status));
  const box = $('results');
  $('bookCount').textContent = items.length ? `${items.length} cuốn` : '';
  if (!items.length) {
    box.innerHTML = '<p class="empty">Chưa có cuốn nào. Cuốn làm xong cũng hiện ở trang chính (mục Lịch đã làm).</p>';
    return;
  }
  const groups = {};
  items.forEach((i) => (groups[i.group || 'lam-theo-mau'] ||= []).push(i));
  box.innerHTML = '';
  Object.entries(groups).forEach(([g, list]) => {
    const sec = document.createElement('div');
    sec.className = 'group';
    const done = list.filter((i) => i.status === 'done').length;
    sec.innerHTML = `<div class="group-head"><h3>${esc(g)}</h3><span class="count">${done}/${list.length} xong</span></div>
      <div class="books"></div>`;
    list.forEach((i) => sec.querySelector('.books').appendChild(bookCard(i)));
    box.appendChild(sec);
  });
}

function renderAccounts() {
  const d = S.data;
  const n = d.plus.length;
  $('accSummary').textContent = `(${n})`;
  $('accDot').className = 'dot ' + (n ? 'ok' : 'bad');
  $('accPill').title = n ? 'Chạy bằng: ' + d.plus.map((a) => `${a.name}${a.expires ? ` (hết hạn ${a.expires.split('-').reverse().join('/')})` : ''}`).join(', ')
    : 'Không có tài khoản Plus nào còn hạn';
  const note = $('plusNotice');
  note.hidden = n > 0;
  note.innerHTML = '<strong>Không có tài khoản ChatGPT Plus nào còn hạn.</strong> Trang này chỉ dùng tài khoản Plus.'
    + (d.unknown.length ? ` Chưa rõ gói: ${esc(d.unknown.join(', '))} - bấm "Kiểm tra gói Plus" ở trang chính.` : '');
}

function render(data) {
  S.data = data;
  if (data.task && data.task.id !== S.taskId) {
    S.taskId = data.task.id;
    S.logs = [];
    S.since = 0;
  }
  renderAccounts();
  renderRun();
  renderQueue();
  renderResults();
  renderStartButton();
}

async function op(name, id, autostart = false) {
  try {
    let data = await api(`/api/clone/${name}`, { id });
    if (autostart && !running()) data = await api('/api/clone/start', { show: $('showChrome').checked });
    render(data);
  } catch (e) {
    toast(e.message, 'error');
  }
}

async function refresh() {
  try {
    render(await api('/api/clone/items'));
  } catch (_) { /* máy chủ bận: lần sau đọc lại */ }
  if (S.taskId) {
    const t = await api(`/api/task?id=${encodeURIComponent(S.taskId)}&since=${S.since}`).catch(() => null);
    if (t && t.logs) {
      S.logs.push(...t.logs);
      S.since = t.total_logs;
      renderLog();
    }
  }
}

async function stop() {
  if (!S.taskId || !confirm('Dừng chạy? Ảnh đã vẽ được giữ lại, lần sau chạy tiếp phần còn thiếu.')) return;
  await api('/api/task/stop', { id: S.taskId }).catch((e) => toast(e.message, 'error'));
  refresh();
}

$('btnPick').addEventListener('click', () => $('files').click());
$('files').addEventListener('change', (e) => { addFiles(e.target.files); e.target.value = ''; });
const drop = $('drop');
drop.addEventListener('click', (e) => {
  if (!e.target.closest('button, input')) drop.focus();
});
drop.addEventListener('paste', (e) => {
  const clipboard = e.clipboardData;
  if (!clipboard) return;
  let images = Array.from(clipboard.items || [])
    .filter((item) => item.kind === 'file' && item.type.startsWith('image/'))
    .map((item) => item.getAsFile()).filter(Boolean);
  if (!images.length) images = Array.from(clipboard.files || []).filter((file) => file.type.startsWith('image/'));
  if (!images.length) {
    toast('Clipboard chưa có ảnh. Hãy sao chép ảnh hoặc chụp màn hình rồi dán vào đây.', 'error');
    return;
  }
  e.preventDefault();
  addFiles(images);
});
drop.addEventListener('dragover', (e) => { e.preventDefault(); drop.classList.add('over'); });
drop.addEventListener('dragleave', () => drop.classList.remove('over'));
drop.addEventListener('drop', (e) => { e.preventDefault(); drop.classList.remove('over'); addFiles(e.dataTransfer.files); });
document.querySelectorAll('.stepper button').forEach((b) => b.addEventListener('click', () => {
  const y = $('year');
  y.value = Math.max(2025, Math.min(2100, (+y.value || 2027) + Number(b.dataset.step)));
  renderStartButton();
}));
$('btnStart').addEventListener('click', start);
$('btnStop').addEventListener('click', stop);
$('btnRun').addEventListener('click', () => api('/api/clone/start', { show: $('showChrome').checked }).then(render).catch((e) => toast(e.message, 'error')));
try { $('showChrome').checked = localStorage.getItem('cloneShowChrome') === '1'; } catch (_) { /* không có bộ nhớ trình duyệt */ }
$('showChrome').addEventListener('change', () => {
  try { localStorage.setItem('cloneShowChrome', $('showChrome').checked ? '1' : '0'); } catch (_) { /* bỏ qua */ }
});
refresh();
setInterval(refresh, 3000);
