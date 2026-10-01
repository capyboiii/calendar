/**
 * CalForge Studio — giao diện cho người không rành kỹ thuật:
 * nhập chủ đề + số cuốn -> bấm Bắt đầu -> xem tiến độ bằng lời -> nhận các cuốn lịch.
 */

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
  queue: { paused: false, items: [] },
};

const $ = (id) => document.getElementById(id);
const STYLE_LABEL = {
  styled_photography: 'Styled photography',
  papercut_collage: 'Layered papercut',
  mid_century_retro: 'Mid-century poster',
};

function batchStyle(selection) {
  const families = Object.keys(STYLE_LABEL);
  return {
    family: selection === 'random' ? families[Math.floor(Math.random() * families.length)] : selection,
    family_selection: selection,
  };
}

document.addEventListener('DOMContentLoaded', () => {
  bindEvents();
  loadAccounts();
  loadProjects();
  reattachRunningTask();
  loadQueue();
  setInterval(loadQueue, 3000);
});

// --------------------------------------------------------------------------
// Sự kiện
// --------------------------------------------------------------------------
function bindEvents() {
  $('btnStart').addEventListener('click', startBatch);
  $('btnQuit').addEventListener('click', quitTool);
  $('inputKeyword').addEventListener('keydown', (e) => { if (e.key === 'Enter') startBatch(); });
  document.querySelectorAll('.stepper button').forEach((b) => b.addEventListener('click', () => {
    setCount(countValue() + Number(b.dataset.step));
  }));
  $('inputCount').addEventListener('input', () => updateHint());
  // "Trang lịch" (AI vẽ cả trang / AI vẽ nền) chỉ áp dụng cho Wall Calendar (Blank)
  const syncGridMode = () => {
    const product = (document.querySelector('input[name="product"]:checked') || {}).value;
    const mode = (document.querySelector('input[name="grid_mode"]:checked') || {}).value;
    $('gridModePicker').hidden = product !== 'wall_grid';
    $('mockupPicker').hidden = product !== 'wall_grid' || mode !== 'ai_page';   // chỉ "AI vẽ cả trang"
  };
  document.querySelectorAll('input[name="product"], input[name="grid_mode"]')
    .forEach((r) => r.addEventListener('change', syncGridMode));
  syncGridMode();
  $('btnStop').addEventListener('click', stopTask);
  $('btnQueuePause').addEventListener('click', toggleQueuePause);
  $('btnRedo').addEventListener('click', redoPages);
  $('btnFinishAll').addEventListener('click', finishAll);
  $('btnQueueClear').addEventListener('click', () => queueOp('clear'));
  $('btnAccounts').addEventListener('click', openAccounts);
  $('btnNoticeAccounts').addEventListener('click', openAccounts);
  $('btnAccAdd').addEventListener('click', addAccount);
  $('btnBulkGo').addEventListener('click', startBulkLogin);
  $('btnR2Settings').addEventListener('click', openR2);
  $('btnR2Save').addEventListener('click', saveR2);
  $('btnShop').addEventListener('click', () => openShopPicker('printify'));
  $('btnCalendaria').addEventListener('click', () => openShopPicker('calendaria'));
  $('btnShopGo').addEventListener('click', () => {
    const books = [...SHOP.picked];
    $('shopModal').hidden = true;
    runShop(books, SHOP.format);
  });
  $('shopFilter').addEventListener('input', renderShopBooks);
  document.querySelectorAll('[data-pick]').forEach((b) => b.addEventListener('click', () => {
    const mode = b.dataset.pick;
    const shown = shopVisible();
    if (mode === 'none') shown.forEach((x) => SHOP.picked.delete(x.path));
    else shown.forEach((x) => { if (mode === 'all' || !shopExported(x)) SHOP.picked.add(x.path); });
    if (mode === 'new') {
      shown.forEach((x) => { if (shopExported(x)) SHOP.picked.delete(x.path); });
      const n = shown.filter((x) => !shopExported(x)).length;
      toast(n ? `Đã chọn ${n} cuốn chưa xuất.` : 'Không có cuốn nào chưa xuất: mọi cuốn đều đã xuất CSV rồi.', 'info');
    }
    renderShopBooks();
  }));
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
  $('startHint').textContent = '';   // không ước giờ: tuỳ hạn mức tài khoản nên số đoán hay sai
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
    renderStyleSamples();
    renderResults();
    loadUnfinished();
    if (S.openBook) {
      const b = findBook(S.openBook);
      if (b && !$('bookModal').hidden) renderBook(b.book, b.keyword);
    }
  } catch (err) {
    $('results').innerHTML = `<p class="empty">Không tải được danh sách lịch: ${esc(err.message)}</p>`;
  }
}

function renderStyleSamples() {
  const families = Object.keys(STYLE_LABEL);
  const candidates = S.projects.flatMap((project) => project.concepts || [])
    .filter((book) => families.includes(book.family) && book.cover)
    .sort((a, b) => {
      const doneA = bookState(a) === 'done' ? 1 : 0;
      const doneB = bookState(b) === 'done' ? 1 : 0;
      if (doneA !== doneB) return doneB - doneA;
      const timeA = Date.parse(((a.status || {}).updated || '').replace(' ', 'T')) || 0;
      const timeB = Date.parse(((b.status || {}).updated || '').replace(' ', 'T')) || 0;
      return timeB - timeA;
    });
  const samples = {};
  candidates.forEach((book) => { if (!samples[book.family]) samples[book.family] = book.cover; });

  families.forEach((family) => {
    const box = document.querySelector(`[data-style-family="${family}"] .style-sample`);
    if (!box) return;
    box.replaceChildren();
    box.classList.toggle('has-image', !!samples[family]);
    box.tabIndex = samples[family] ? 0 : -1;
    box.title = samples[family] ? 'Bấm để xem ảnh mẫu lớn' : '';
    if (samples[family]) {
      const img = document.createElement('img');
      img.src = thumbUrl(samples[family], 160);
      img.dataset.full = thumbUrl(samples[family], 1600);
      img.alt = '';
      img.loading = 'lazy';
      box.appendChild(img);
    }
  });

  const random = document.querySelector('[data-style-family="random"] .style-sample');
  if (!random) return;
  random.replaceChildren();
  families.forEach((family) => {
    if (!samples[family]) return;
    const img = document.createElement('img');
    img.src = thumbUrl(samples[family], 100);
    img.dataset.full = thumbUrl(samples[family], 1600);
    img.alt = '';
    img.loading = 'lazy';
    random.appendChild(img);
  });
  random.classList.toggle('has-image', random.childElementCount > 0);
  random.tabIndex = random.childElementCount ? 0 : -1;
  random.title = random.childElementCount ? 'Bấm vào từng ảnh để xem lớn' : '';

  document.querySelectorAll('.style-sample.has-image').forEach((box) => {
    const open = (img) => {
      if (!img) return;
      $('lightboxImg').src = img.dataset.full;
      $('lightbox').hidden = false;
    };
    box.onclick = (event) => {
      event.preventDefault();
      event.stopPropagation();
      const radio = box.closest('.style-kind').querySelector('input[name="family"]');
      radio.checked = true;
      radio.dispatchEvent(new Event('change', { bubbles: true }));
      open(event.target.closest('img') || box.querySelector('img'));
    };
    box.onkeydown = (event) => {
      if (event.key !== 'Enter' && event.key !== ' ') return;
      event.preventDefault();
      box.click();
    };
  });
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
  const selection = (document.querySelector('input[name="family"]:checked') || {}).value || 'random';
  const params = { keyword, batch_size: countValue(), product, ...batchStyle(selection) };
  if (product === 'wall_grid') {
    params.grid_mode = (document.querySelector('input[name="grid_mode"]:checked') || {}).value || 'ai_page';
    if (params.grid_mode === 'ai_page') {
      params.mockup_mode = (document.querySelector('input[name="mockup_mode"]:checked') || {}).value || 'template';
    }
  }
  const busy = !!S.task || (S.queue.items || []).some((i) => i.status === 'queued' || i.status === 'running');
  try {
    await queueOp('add', { params });
    $('inputKeyword').value = '';
    toast(busy ? `Đã xếp "${keyword}" vào hàng đợi.` : `Bắt đầu làm "${keyword}".`, 'info');
    setTimeout(loadQueue, 800);
  } catch (err) {
    toast(err.message, 'error');
  }
}

// ---- Hàng đợi batch: bấm Bắt đầu nhiều lần = xếp nhiều batch, máy làm lần lượt -----------------------------
async function queueOp(op, body = {}) {
  S.queue = await api(`/api/queue/${op}`, body);
  renderQueue();
}

async function loadQueue() {
  try {
    S.queue = await api('/api/queue');
  } catch (_) {
    return;
  }
  renderQueue();
  const run = (S.queue.items || []).find((i) => i.status === 'running' && i.task_id);
  if (run && (!S.task || S.task.id !== run.task_id)) {        // hàng đợi vừa chạy batch kế tiếp -> hiện tiến độ
    attachTask({ id: run.task_id, params: run.params, start_time: Date.now() / 1000 });
  }
}

const PRODUCT_LABEL = { wall_grid: 'Wall Calendar (Blank)', wall_premade: 'Wall Calendar' };

function renderQueue() {
  const items = S.queue.items || [];
  const active = items.filter((i) => i.status === 'queued' || i.status === 'running');
  const queued = items.filter((i) => i.status === 'queued');
  const done = items.filter((i) => !['queued', 'running'].includes(i.status)).reverse();
  $('queueCard').hidden = !items.length && !S.queue.paused;
  $('btnQueuePause').textContent = S.queue.paused ? 'Tiếp tục' : 'Tạm dừng';
  $('btnQueuePause').classList.toggle('btn-primary', !!S.queue.paused);
  $('queuePaused').hidden = !S.queue.paused;
  $('btnStart').textContent = (S.task || active.length) ? 'Thêm vào hàng đợi' : 'Bắt đầu';
  $('btnStart').disabled = false;

  const label = (i) => {
    const p = i.params;
    if (p.action === 'produce') return `<strong>Làm tiếp</strong> <span class="muted">${esc(p.title || '')}</span>`;
    if (p.action === 'finish') {
      return `<strong>${p.redo_previews ? 'Làm lại ảnh quảng cáo' : 'Hoàn thiện'}</strong> <span class="muted">${esc(p.title || '')}</span>`;
    }
    if (p.action === 'redo') {
      return `<strong>Vẽ lại ${(p.pages || []).length} trang</strong> <span class="muted">${esc(p.title || '')}</span>`;
    }
    const mode = p.product === 'wall_grid' ? (p.grid_mode === 'background' ? ' · AI vẽ nền'
      : ` · AI vẽ cả trang${p.mockup_mode === 'ai' ? ' · AI mockup' : ''}`) : '';
    const style = STYLE_LABEL[p.family];
    const styleText = style ? ` · ${p.family_selection === 'random' ? 'Ngẫu nhiên: ' : ''}${style}` : '';
    return `<strong>${esc(p.keyword)}</strong>
    <span class="muted">${p.batch_size || 1} cuốn · ${PRODUCT_LABEL[p.product] || ''}${mode}${styleText}</span>`;
  };
  const wl = $('queueWaiting');
  wl.innerHTML = '';
  active.forEach((i) => {
    const li = document.createElement('li');
    const tag = i.status === 'running' ? '<span class="tag run">Đang làm</span>'
      : `<span class="tag">Chờ ${queued.indexOf(i) + 1}</span>`;
    li.innerHTML = `${tag} ${label(i)}<span class="grow"></span>`;
    if (i.status === 'queued') {
      const k = queued.indexOf(i);
      if (k > 0) li.appendChild(button('↑', 'btn-small btn-ghost', () => queueOp('move', { id: i.id, delta: -1 })));
      if (k < queued.length - 1) li.appendChild(button('↓', 'btn-small btn-ghost', () => queueOp('move', { id: i.id, delta: 1 })));
      li.appendChild(button('Bỏ', 'btn-small btn-danger-ghost', () => queueOp('remove', { id: i.id })));
    }
    wl.appendChild(li);
  });
  if (!active.length) wl.innerHTML = '<li class="muted">Không có batch nào đang chờ.</li>';

  $('queueDoneBox').hidden = !done.length;
  $('queueDoneCount').textContent = `(${done.length})`;
  const dl = $('queueDone');
  dl.innerHTML = '';
  done.forEach((i) => {
    const li = document.createElement('li');
    const res = i.total ? `${i.ok}/${i.total} cuốn đạt` : '';
    const tag = i.status === 'done' ? '<span class="tag ok">Xong</span>'
      : i.status === 'partial' ? '<span class="tag part">Xong một phần</span>'
        : i.status === 'stopped' ? '<span class="tag">Đã dừng</span>' : '<span class="tag bad">Lỗi</span>';
    li.innerHTML = `${tag} ${label(i)}<span class="grow"></span>
      <span class="muted">${esc(i.error || res)}${(i.error || res) ? ' · ' : ''}${esc((i.finished_at || '').slice(5, 16))}</span>`;
    if ((i.status !== 'done' || (i.total && i.ok < i.total)) && i.retryable !== false) {
      const again = i.params.action ? 'Thử lại' : 'Làm nốt phần thiếu';
      li.appendChild(button(again, 'btn-small btn-accent', async () => {
        try {
          // batch: "Làm nốt phần thiếu" = mở lại đúng batch đó (không làm thêm N cuốn mới)
          await queueOp('add', { params: i.params.action ? i.params : { ...i.params, resume: true } });
          toast('Đã xếp lại vào hàng đợi.', 'info');
        } catch (err) {
          toast(err.message, 'error');
        }
      }));
    }
    li.appendChild(button('Xoá', 'btn-small btn-ghost', () => queueOp('remove', { id: i.id })));
    dl.appendChild(li);
  });
}

async function toggleQueuePause() {
  if (!S.queue.paused && S.task
      && !confirm('Tạm dừng? Batch đang làm dừng lại (phần đã làm giữ nguyên) và được đưa về đầu hàng đợi.')) return;
  try {
    await queueOp(S.queue.paused ? 'resume' : 'pause');
  } catch (err) {
    toast(err.message, 'error');
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
  $('btnStart').textContent = 'Thêm vào hàng đợi';   // đang chạy vẫn bấm được: xếp batch mới vào hàng đợi
  const p = task.params || {};
  $('runTitle').textContent = p.action === 'finish' ? `Đang hoàn thiện "${p.title || ''}"`
    : p.action === 'produce' ? `Đang làm tiếp "${p.title || ''}"`
    : p.action === 'redo' ? `Đang vẽ lại ${(p.pages || []).length} trang của "${p.title || ''}"`
      : `Đang làm ${p.batch_size || 1} cuốn lịch "${p.keyword}"`;
  renderProgress();
  clearInterval(S.pollTimer);
  clearInterval(S.refreshTimer);
  S.pollTimer = setInterval(pollTask, 1500);
  S.refreshTimer = setInterval(loadProjects, 20000);   // cuốn nào xong hiện ngay bên dưới
  pollTask();
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
  const single = S.task.params.action ? S.task.params : null;     // việc một cuốn: làm tiếp / vẽ lại trang
  S.task = null;
  $('runCard').hidden = true;
  $('startCard').classList.remove('dim');
  $('btnStart').disabled = false;
  loadProjects().then(() => {
    const proj = S.projects.find((p) => p.keyword === slug(kw));
    const batch = (proj && proj.batch) || {};
    const rows = batch.report || [];
    const ok = rows.filter((r) => r.ok).length;
    const total = Number(batch.target) || rows.length;
    if (single && status === 'success') toast(`Xong "${single.title || ''}".`, 'success', 8000);
    else if (single && status !== 'stopped') {
      toast(`"${single.title || ''}" chưa xong - mở cuốn đó xem lý do, hoặc bấm Thử lại ở Hàng đợi.`, 'error', 12000);
    } else if (status === 'stopped' && S.queue.paused) toast('Đã tạm dừng hàng đợi. Bấm Tiếp tục để làm tiếp.', 'info', 8000);
    else if (status === 'stopped') toast('Đã dừng batch này. Hàng đợi (nếu có) chạy batch kế tiếp.', 'info', 8000);
    else if (rows.length && ok === total) toast(`Xong! ${ok} cuốn lịch "${kw}" đã sẵn sàng.`, 'success', 10000);
    else if (rows.length) toast(`Xong ${ok}/${total} cuốn. Mở cuốn chưa đạt để xem lý do và thao tác phù hợp.`, 'info', 12000);
    else if (status === 'success') toast('Đã xong.', 'success');
    else toast('Có lỗi khi chạy. Mở "Chi tiết" hoặc thử lại.', 'error', 10000);
  });
  loadAccounts();
}

async function stopTask() {
  if (!S.task) return;
  if (!confirm('Dừng batch này? Phần đã làm giữ nguyên (bấm Bắt đầu lại cùng chủ đề sẽ làm tiếp). '
    + 'Hàng đợi sẽ chạy batch kế tiếp; muốn dừng hết thì bấm Tạm dừng.')) return;
  try {
    await api('/api/task/stop', { id: S.task.id });
  } catch (err) {
    toast(err.message, 'error');
  }
}

// Đọc log thành tiến độ dễ hiểu. Nhiều cuốn chạy SONG SONG: đếm cuốn đã xong / đang làm / lỗi theo các mốc
// "◆ CUỐN XONG|LỖI" và "===== Sản xuất"; bước hiện tại = bước xa nhất đang có cuốn làm.
function readProgress(logs, target) {
  const started = new Set(), done = new Set(), failed = new Set();
  let step = 1, sweep = false, stepText = '', ideating = false;
  logs.forEach((line) => {
    const prod = line.match(/===== Sản xuất: (.+?) =====/);
    if (prod) { started.add(prod[1]); failed.delete(prod[1]); step = Math.max(step, 2); return; }
    const end = line.match(/◆ CUỐN (XONG|LỖI): (.+)$/);
    if (end) { (end[1] === 'XONG' ? done : failed).add(end[2].trim()); return; }
    if (/▶ (Lượt lên ý|P1|P1b|P2|Bước 1\/6)/.test(line)) ideating = true;
    if (/Batch xong/.test(line)) ideating = false;
    const m = line.match(/▶ Bước (\d)(?:\/6|b| \()/);
    if (m) step = Math.max(step, /Bước 4b/.test(line) ? 5 : Number(m[1]));
    if (/\[hậu kỳ/.test(line)) step = Math.max(step, 4);
    if (/▶ Vòng vét/.test(line)) { sweep = true; stepText = 'Đang chờ tài khoản hồi lượt rồi làm lại cuốn bị dở'; }
    const pause = line.match(/⏸ Tất cả tài khoản hết lượt .*thử lại lúc (\d\d:\d\d)/);
    if (pause) stepText = `Tài khoản ChatGPT tạm hết lượt - máy tự chờ, thử lại lúc ${pause[1]}`;
    if (/▶ Hết giờ chờ/.test(line)) stepText = '';
  });
  const running = [...started].filter((n) => !done.has(n) && !failed.has(n)).length;
  const pct = sweep ? 97 : Math.min(97, Math.round(((done.size + failed.size + running * 0.4) / Math.max(1, target)) * 100));
  return { done: done.size, failed: failed.size, running, ideating, step, pct, sweep, stepText };
}

function renderProgress() {
  if (!S.task) return;
  const target = Number(S.task.params.batch_size) || 1;
  const p = readProgress(S.logs, target);
  const parts = [`Xong ${p.done}/${target} cuốn`];
  if (p.running) parts.push(`đang làm ${p.running} cuốn`);
  if (p.ideating && p.done + p.failed + p.running < target) parts.push('đang nghĩ ý cuốn tiếp');
  if (p.failed) parts.push(`${p.failed} cuốn lỗi`);
  if (p.stepText) parts.push(p.stepText);
  $('runSub').textContent = p.sweep ? 'Đang làm lại các cuốn bị dở' : parts.join(' · ');
  $('runSteps').innerHTML = STEPS.map((s) => {
    const cls = s.key < p.step ? 'done' : s.key === p.step ? 'now' : '';
    return `<li class="${cls}"><span class="n">${s.key < p.step ? '✓' : s.key}</span>${esc(s.label)}</li>`;
  }).join('');
  $('runBar').style.width = `${p.pct}%`;
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
  if (st.stage === 'ip_rejected') return 'rejected';
  if (st.ok === false) return 'error';
  return 'pending';
}

const STATE_LABEL = { done: 'Xong', rejected: 'Bỏ · TM/bản quyền', error: 'Bị dở', pending: 'Chưa xong' };

function friendlyReason(st) {
  const stage = (st || {}).stage;
  const raw = (st || {}).reason || '';
  if (stage === 'ip_rejected') return raw || 'Bỏ cuốn: ChatGPT từ chối vì TM/bản quyền hoặc quyền bên thứ ba.';
  if (stage === 'images') return 'ChatGPT chưa vẽ đủ tranh (thường do tài khoản hết lượt). Chờ một lúc rồi bấm "Làm tiếp".';
  if (stage === 'render') return 'Lỗi khi dàn trang in. Bấm "Làm tiếp"; nếu vẫn lỗi, gửi phần chi tiết cho người kỹ thuật.';
  if (stage === 'printify') return 'Chưa đưa lên được Printify. Kiểm tra mạng rồi bấm "Làm tiếp".';
  if (stage === 'mockup') return 'Thiếu ảnh quảng cáo (mockup). Bấm "Làm lại ảnh quảng cáo" - không tốn lượt ChatGPT.';
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
    ${(state === 'error' || state === 'rejected') ? `<p class="why">${esc(friendlyReason(c.status))}</p>` : ''}`;
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
  err.hidden = state !== 'error' && state !== 'rejected';
  err.textContent = (state === 'error' || state === 'rejected') ? friendlyReason(c.status) : '';

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
  if (state !== 'done' && state !== 'rejected') {
    a.appendChild(button('Làm tiếp', 'btn-accent', () => continueBook(c)));
  }
  if ((c.pdfs || []).length) {            // đã có trang in: làm lại mockup không cần ChatGPT
    if (state !== 'rejected') a.appendChild(button('Làm lại ảnh quảng cáo', '', () => finishBook(c, true)));
  }
  $('btnRedo').hidden = state === 'rejected';
  loadBookPages(c);
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
    const busy = !!S.task;
    await queueOp('add', { params: { action: 'produce', concept: c.path, title: c.title } });
    $('bookModal').hidden = true;
    toast(busy ? `Đã xếp "Làm tiếp ${c.title}" vào hàng đợi.` : `Đang làm tiếp "${c.title}".`, 'info', 8000);
    setTimeout(loadQueue, 800);
  } catch (err) {
    toast(err.message, 'error');
  }
}

// ---- Hoàn thiện cuốn đã vẽ đủ tranh (không cần ChatGPT) ------------------------------------------------------
async function finishBook(c, redoPreviews) {
  try {
    await queueOp('add', { params: { action: 'finish', concept: c.path, title: c.title, redo_previews: !!redoPreviews } });
    $('bookModal').hidden = true;
    toast(redoPreviews ? `Đã xếp "Làm lại ảnh quảng cáo" cho "${c.title}".` : `Đã xếp "Hoàn thiện ${c.title}".`, 'info');
    setTimeout(loadQueue, 800);
  } catch (err) {
    toast(err.message, 'error');
  }
}

async function loadUnfinished() {
  const d = await api('/api/unfinished').catch(() => null);
  const books = (d && d.books) || [];
  S.unfinished = books;
  $('unfinishedNotice').hidden = !books.length;
  $('unfinishedText').textContent = books.length
    ? `${books.length} cuốn đã vẽ đủ tranh nhưng chưa hoàn thiện (bị dừng giữa chừng hoặc thiếu ảnh quảng cáo). `
      + 'Hoàn thiện không tốn lượt ChatGPT.'
    : '';
}

async function finishAll() {
  const books = S.unfinished || [];
  try {
    for (const b of books) {
      await queueOp('add', { params: { action: 'finish', concept: b.path, title: b.title } });
    }
    toast(`Đã xếp ${books.length} cuốn vào hàng đợi để hoàn thiện.`, 'info');
    $('unfinishedNotice').hidden = true;
    setTimeout(loadQueue, 800);
  } catch (err) {
    toast(err.message, 'error');
  }
}

// ---- Sửa trang hỏng: tick trang lỗi -> vẽ lại đúng các trang đó ------------------------------------------------
const PAGE_NAMES = { cover: 'Bìa', grid: 'Nền trang lịch' };
const BOOK_PAGES = { book: null, picked: new Set() };

async function loadBookPages(c) {
  BOOK_PAGES.book = c;
  BOOK_PAGES.picked = new Set();
  const box = $('bookPages');
  box.innerHTML = '<p class="empty">Đang tải…</p>';
  let data;
  try {
    data = await api(`/api/concept?path=${encodeURIComponent(c.path)}`);
  } catch (err) {
    box.innerHTML = `<p class="empty">${esc(err.message)}</p>`;
    return;
  }
  if (BOOK_PAGES.book !== c) return;                      // người dùng đã mở cuốn khác
  const files = (data.files || {}).art_raw || [];
  const ver = (data.files || {}).art_raw_v || {};              // ảnh vẽ lại cùng tên: URL mới, không hiện ảnh cũ
  const ids = ['cover', ...Array.from({ length: 12 }, (_, i) => `m${String(i + 1).padStart(2, '0')}`)];
  const aiPage = ((data.concept || {}).style || {}).grid_mode === 'ai_page';
  if (aiPage) ids.push(...Array.from({ length: 12 }, (_, i) => `g${String(i + 1).padStart(2, '0')}`));
  else if (c.product !== 'wall_premade') ids.push('grid');
  box.innerHTML = '';
  ids.forEach((id) => {
    const f = files.find((n) => n.startsWith(`${id}.`) && /\.(png|jpe?g|webp)$/i.test(n));
    const label = PAGE_NAMES[id] || (id[0] === 'g' ? `Lịch tháng ${Number(id.slice(1))}` : `Tranh tháng ${Number(id.slice(1))}`);
    const el = document.createElement('label');
    el.className = 'page-item';
    el.innerHTML = `<input type="checkbox">
      ${f ? `<img loading="lazy" src="${thumbUrl(`${c.path}/_he_thong/anh_ai/${f}?v=${ver[f] || ''}`, 240)}" alt="">`
    : '<div class="miss">Chưa có</div>'}<span>${esc(label)}</span>`;
    el.querySelector('input').addEventListener('change', (e) => {
      if (e.target.checked) BOOK_PAGES.picked.add(id); else BOOK_PAGES.picked.delete(id);
      el.classList.toggle('on', e.target.checked);
      updateRedoButton();
    });
    if (f) {
      el.querySelector('img').addEventListener('dblclick', () => {
        $('lightboxImg').src = thumbUrl(`${c.path}/_he_thong/anh_ai/${f}?v=${ver[f] || ''}`, 1600);
        $('lightbox').hidden = false;
      });
    }
    box.appendChild(el);
  });
  updateRedoButton();
}

function updateRedoButton() {
  const n = BOOK_PAGES.picked.size;
  $('btnRedo').disabled = !n;
  $('btnRedo').textContent = n ? `Vẽ lại ${n} trang` : 'Vẽ lại';
  $('bookPagesPicked').textContent = n ? 'Bấm đúp ảnh để xem to.' : 'Chưa chọn trang nào. Bấm đúp ảnh để xem to.';
}

async function redoPages() {
  const c = BOOK_PAGES.book;
  const pages = [...BOOK_PAGES.picked];
  if (!c || !pages.length) return;
  if (!confirm(`Vẽ lại ${pages.length} trang của "${c.title}"? Ảnh cũ được cất lại, không mất.`)) return;
  try {
    const busy = !!S.task;
    await queueOp('add', { params: { action: 'redo', concept: c.path, title: c.title, pages } });
    $('bookModal').hidden = true;
    toast(busy ? `Đã xếp "Vẽ lại ${pages.length} trang" vào hàng đợi.` : `Đang vẽ lại ${pages.length} trang của "${c.title}".`,
      'info', 8000);
    setTimeout(loadQueue, 800);
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
    const busy = LOGGING_IN.has(acc.name);
    const lb = button(busy ? 'Đang đăng nhập…' : acc.has_session ? 'Đăng nhập lại' : 'Đăng nhập', 'btn-small',
      () => loginAccount(acc.name));
    lb.disabled = busy;
    li.appendChild(lb);
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

// ---- Chọn cuốn đẩy R2 + xuất CSV -----------------------------------------------------------------------------
const SHOP = { books: [], picked: new Set(), format: 'printify' };

function shopExported(book) {
  return SHOP.format === 'calendaria' ? book.calendaria_exported_at : book.exported_at;
}

async function openShopPicker(format = 'printify') {
  SHOP.format = format;
  const label = format === 'calendaria' ? 'Crayonahub' : 'Printify';
  $('shopTitle').textContent = `Chọn cuốn xuất CSV ${label}`;
  $('shopModal').hidden = false;
  $('shopFilter').value = '';
  $('shopBooks').innerHTML = '<p class="empty">Đang tải…</p>';
  try {
    SHOP.books = (await api('/api/shop/books')).books || [];
  } catch (err) {
    $('shopBooks').innerHTML = `<p class="empty">${esc(err.message)}</p>`;
    return;
  }
  SHOP.picked = new Set(SHOP.books.filter((b) => !shopExported(b)).map((b) => b.path));
  renderShopBooks();
}

function shopVisible() {
  const q = $('shopFilter').value.trim().toLowerCase();
  return SHOP.books.filter((b) => !q || `${b.title} ${b.keyword}`.toLowerCase().includes(q));
}

function renderShopBooks() {
  const box = $('shopBooks');
  const shown = shopVisible();
  box.innerHTML = '';
  if (!SHOP.books.length) box.innerHTML = '<p class="empty">Chưa có cuốn nào làm xong.</p>';
  else if (!shown.length) box.innerHTML = '<p class="empty">Không có cuốn nào khớp.</p>';
  let group = '';
  shown.forEach((b) => {
    const g = `${b.keyword} · ${PRODUCT_LABEL[b.product] || ''}`;
    if (g !== group) {
      group = g;
      const h = document.createElement('div');
      h.className = 'shop-group';
      h.textContent = g;
      box.appendChild(h);
    }
    const row = document.createElement('label');
    row.className = 'shop-book';
    const exportedAt = shopExported(b);
    const state = exportedAt ? `<span class="tag">Đã xuất ${esc(exportedAt.slice(5, 16))}</span>`
      : b.pushed_at ? '<span class="tag">Đã đẩy R2, chưa xuất CSV</span>' : '<span class="tag new">Mới</span>';
    row.innerHTML = `<input type="checkbox" ${SHOP.picked.has(b.path) ? 'checked' : ''}>
      ${b.cover ? `<img src="${thumbUrl(b.cover, 120)}" alt="" loading="lazy">` : '<img alt="">'}
      <span class="t"><strong>${esc(b.title)}</strong><small>Xong ${esc(b.done_at.slice(5))}</small></span>${state}`;
    row.querySelector('input').addEventListener('change', (e) => {
      if (e.target.checked) SHOP.picked.add(b.path); else SHOP.picked.delete(b.path);
      updateShopPicked();
    });
    box.appendChild(row);
  });
  updateShopPicked();
}

function updateShopPicked() {
  const n = SHOP.picked.size;
  const again = SHOP.books.filter((b) => SHOP.picked.has(b.path) && shopExported(b)).length;
  $('shopPicked').textContent = n ? `Đã chọn ${n} cuốn${again ? ` (${again} cuốn đã xuất trước đây, sẽ xuất lại)` : ''}` : 'Chưa chọn cuốn nào';
  $('btnShopGo').disabled = !n;
  $('btnShopGo').textContent = n ? `Đẩy R2 + xuất CSV (${n} cuốn)` : 'Đẩy R2 + xuất CSV';
}

async function runShop(books, format = 'printify') {
  const btn = format === 'calendaria' ? $('btnCalendaria') : $('btnShop');
  btn.disabled = true;
  const box = $('shopResult');
  box.hidden = false;
  box.textContent = 'Đang đẩy lên R2…';
  try {
    const data = await api('/api/action', { action: 'shop', params: { books, format } });
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

const LOGGING_IN = new Set();                          // tài khoản đang mở cửa sổ đăng nhập

async function loginAccount(name) {
  if (LOGGING_IN.has(name)) return;
  try {
    const data = await api('/api/action', { action: 'login', params: { profile: name } });
    LOGGING_IN.add(name);
    renderAccounts();
    toast(`Đã mở Chrome cho "${name}". Đăng nhập ChatGPT xong, cửa sổ sẽ tự đóng.`, 'info', 10000);
    const poll = setInterval(async () => {
      const t = await api(`/api/task?id=${data.task_id}&since=0`).catch(() => null);
      if (t && t.status === 'running') return;
      clearInterval(poll);
      LOGGING_IN.delete(name);
      const logs = (t && t.logs) || [];
      const last = [...logs].reverse().find((l) => /^\s*(✔|⚠|❌)/.test(l)) || '';
      if (t && t.status === 'success') toast(`"${name}" đã đăng nhập xong.`, 'success', 6000);
      else if (t && t.status === 'stopped') toast(`Đã huỷ đăng nhập "${name}".`, 'info');
      else toast(last.replace(/^\s*[✔⚠❌]\s*/, '') || `"${name}" chưa đăng nhập được.`, 'error', 10000);
      loadAccounts();
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

async function quitTool() {
  const running = S.task ? '\nViệc đang chạy sẽ dừng (phần đã làm vẫn còn, lần sau bấm "Làm tiếp").' : '';
  if (!confirm('Tắt CalForge Studio?' + running)) return;
  try { await fetch('/api/shutdown', { method: 'POST' }); } catch (e) { /* máy chủ đã tắt */ }
  document.body.innerHTML = '<main style="padding:60px;text-align:center;font:18px Segoe UI,sans-serif">' +
    'Đã tắt CalForge Studio. Bạn có thể đóng cửa sổ này.<br><br>Muốn dùng lại: bấm biểu tượng <b>CalForge Studio</b>.</main>';
}
