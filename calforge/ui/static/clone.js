// "Clone sản phẩm" trên trang chính (thẻ Làm lịch mới -> Cách làm: Theo ý tưởng | Clone sản phẩm).
// Tải ảnh mẫu lên -> ChatGPT (CHỈ tài khoản Plus) vẽ 12 artwork + bìa + 12 trang lịch -> máy dựng cuốn như trang chính.
// Cuốn làm xong hiện ở "Lịch đã làm" của trang chính (Chi tiết, sửa trang hỏng, đăng bán dùng chung).
// Bọc trong một khối riêng: trang chính (app.js) đã có S, $, api, toast... cùng tên.
(() => {
  const $ = (id) => document.getElementById(id);
  const esc = (s) => String(s ?? '').replace(/[&<>"']/g, (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));
  const thumbUrl = (p, w = 480) => `/api/thumb?w=${w}&path=${encodeURIComponent(p)}`;
  const MAX_REFS = 10;
  // Các bước người dùng nhìn thấy; from/to = phần trăm thanh tiến độ của mỗi bước.
  const STEPS = [
    { key: 1, label: 'Vẽ 12 artwork (lâu nhất)', from: 0, to: 40 },
    { key: 2, label: 'Đặt tên & listing', from: 40, to: 43 },
    { key: 3, label: 'Vẽ bìa', from: 43, to: 48 },
    { key: 4, label: 'Vẽ 12 trang lịch', from: 48, to: 85 },
    { key: 5, label: 'Làm nét, dàn trang in, ảnh quảng cáo', from: 85, to: 99 },
  ];
  const C = { refs: [], data: null, taskId: null, logs: [], since: 0, lastDone: '' };

  async function api(path, body) {
    const res = await fetch(path, body === undefined ? {} : {
      method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body),
    });
    const data = await res.json().catch(() => ({}));
    if (!res.ok || data.error) throw new Error(data.error || `Lỗi máy chủ (${res.status})`);
    return data;
  }

  function toast(msg, kind = 'info') {
    if (typeof window.toast === 'function') return window.toast(msg, kind);
    const t = document.createElement('div');
    t.className = `toast ${kind}`;
    t.textContent = msg;
    $('toasts').appendChild(t);
    setTimeout(() => t.remove(), 6000);
    return t;
  }

  function button(text, cls, fn) {
    const b = document.createElement('button');
    b.className = `btn ${cls}`;
    b.textContent = text;
    b.addEventListener('click', fn);
    return b;
  }

  // ---------------------------------------------------------------- Cách làm: Theo ý tưởng | Clone sản phẩm
  function mode() {
    return (document.querySelector('input[name="make_mode"]:checked') || {}).value || 'idea';
  }

  function applyMode() {
    const m = mode();
    $('ideaPanel').hidden = m !== 'idea';
    $('clonePanel').hidden = m !== 'clone';
    try { localStorage.setItem('makeMode', m); } catch (_) { /* không có bộ nhớ trình duyệt */ }
  }

  // ---------------------------------------------------------------- ảnh mẫu
  // Nhận MỌI loại file. Ảnh trình duyệt đọc được -> JPG (thu về cạnh dài 2048px nếu lớn). File trình duyệt không đọc
  // được (TIFF, PDF...) gửi nguyên cho máy chủ đổi (PDF: mỗi trang thành một ảnh mẫu).
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
    if (!img) return { name: file.name, data: url, raw: true };
    const long = Math.max(img.naturalWidth, img.naturalHeight);
    if (KEEP_TYPES.test(file.type) && long <= 2048 && file.size <= 6 * 1024 * 1024) return { name: file.name, data: url };
    const k = Math.min(1, 2048 / long);
    const c = document.createElement('canvas');
    c.width = Math.max(1, Math.round(img.naturalWidth * k));
    c.height = Math.max(1, Math.round(img.naturalHeight * k));
    const g = c.getContext('2d');
    g.fillStyle = '#fff';
    g.fillRect(0, 0, c.width, c.height);
    g.drawImage(img, 0, 0, c.width, c.height);
    return { name: (file.name || 'anh').replace(/\.[^.]+$/, '') + '.jpg', data: c.toDataURL('image/jpeg', 0.92) };
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
    const room = MAX_REFS - C.refs.length;
    if (files.length > room) toast(`Tối đa ${MAX_REFS} ảnh mẫu mỗi cuốn - bỏ bớt ${files.length - room} file.`, 'error');
    for (const f of files.slice(0, Math.max(0, room))) {
      try {
        C.refs.push(await loadImage(f));
      } catch (e) {
        toast(e.message, 'error');
      }
    }
    renderRefs();
  }

  function renderRefs() {
    const ol = $('cloneRefList');
    ol.innerHTML = '';
    C.refs.forEach((r, i) => {
      const li = document.createElement('li');
      const ext = (r.name.split('.').pop() || 'file').toUpperCase().slice(0, 5);
      li.innerHTML = `${r.raw ? `<div class="file-ph" title="${esc(r.name)}"><b>${esc(ext)}</b><small>${esc(r.name)}</small></div>`
        : `<img src="${r.data}" alt="">`}<span class="no">${i + 1}</span>
        <div class="tools"><button type="button" title="Lên trước" data-a="up">←</button><button type="button" title="Bỏ ảnh" data-a="del">✕</button>
        <button type="button" title="Xuống sau" data-a="down">→</button></div>`;
      li.querySelectorAll('button').forEach((b) => b.addEventListener('click', () => {
        const a = b.dataset.a;
        if (a === 'del') C.refs.splice(i, 1);
        if (a === 'up' && i > 0) [C.refs[i - 1], C.refs[i]] = [C.refs[i], C.refs[i - 1]];
        if (a === 'down' && i < C.refs.length - 1) [C.refs[i + 1], C.refs[i]] = [C.refs[i], C.refs[i + 1]];
        renderRefs();
      }));
      ol.appendChild(li);
    });
    renderStartButton();
  }

  function running() {
    const t = C.data && C.data.task;
    return !!(t && t.status === 'running');
  }

  function renderStartButton() {
    const b = $('btnCloneStart');
    b.disabled = !C.refs.length || !(C.data && C.data.plus.length);
    b.textContent = running() ? 'Thêm vào hàng đợi' : 'Bắt đầu';
    $('cloneStartHint').textContent = !C.refs.length
      ? 'Thêm ảnh mẫu để bắt đầu. Chỉ dùng tài khoản ChatGPT Plus: 12 artwork + bìa (1 tài khoản), 12 trang lịch (tài khoản khác).'
      : `${C.refs.length} ảnh mẫu → 1 cuốn lịch ${$('cloneYear').value}.`
        + (running() ? ' Đang chạy: cuốn này được làm ngay khi có tài khoản rảnh.' : '');
  }

  async function start() {
    const btn = $('btnCloneStart');
    btn.disabled = true;
    btn.textContent = 'Đang tải ảnh lên…';
    try {
      const mockup = (document.querySelector('input[name="clone_mockup_mode"]:checked') || {}).value || 'ai';
      let data = await api('/api/clone/add', {
        images: C.refs, group: $('cloneGroup').value.trim(), year: +$('cloneYear').value || 2027, mockup_mode: mockup,
      });
      C.refs = [];
      renderRefs();
      const wasRunning = running();
      if (!wasRunning) data = await api('/api/clone/start', { show: $('cloneShowChrome').checked });
      toast(wasRunning ? 'Đã thêm vào hàng đợi clone - làm ngay khi có tài khoản rảnh.' : 'Đã bắt đầu clone sản phẩm.', 'success');
      render(data);
    } catch (e) {
      toast(e.message, 'error');
    }
    renderStartButton();
  }

  // ---------------------------------------------------------------- tiến độ
  function stepOf(it) {
    const st = (it.stage || '').toLowerCase();
    const m = st.match(/\((\d+)\/12\)/);
    const frac = m ? +m[1] / 12 : 0;
    if (it.status === 'done') return { step: 6, pct: 100 };
    if (st.startsWith('vẽ artwork')) return { step: 1, pct: frac * 40 };
    if (st.startsWith('đặt tên')) return { step: 2, pct: 41 };
    if (st.startsWith('vẽ bìa')) return { step: 3, pct: 45 };
    if (st.startsWith('vẽ trang lịch') || st.includes('pool trang lịch')) return { step: 4, pct: 48 + frac * 37 };
    if (st.startsWith('upscale') || st.startsWith('dựng') || st.includes('hậu kỳ')) return { step: 5, pct: st.startsWith('upscale') ? 88 : 94 };
    return { step: 1, pct: 0 };
  }

  function renderRun() {
    $('cloneRunCard').hidden = !running();
    if (!running()) return;
    const items = C.data.items;
    const active = items.filter((i) => i.status === 'running');
    const now = active[0];
    const p = now ? stepOf(now) : { step: 1, pct: 0 };
    const waiting = items.filter((i) => i.status === 'pending').length;
    $('cloneRunTitle').textContent = active.length > 1 ? `Đang clone ${active.length} cuốn`
      : `Đang clone ${now ? `"${now.title || 'cuốn mới'}"` : 'sản phẩm'}`;
    const parts = [];
    if (now) parts.push(now.stage || 'đang chuẩn bị');
    if (waiting) parts.push(`${waiting} cuốn đang chờ`);
    $('cloneRunSub').textContent = parts.join(' · ') || 'Đang chuẩn bị…';
    $('cloneRunSteps').innerHTML = STEPS.map((s) => {
      const cls = s.key < p.step ? 'done' : s.key === p.step ? 'now' : '';
      return `<li class="${cls}"><span class="n">${s.key < p.step ? '✓' : s.key}</span>${esc(s.label)}</li>`;
    }).join('');
    const all = active.map((i) => stepOf(i).pct);
    $('cloneRunBar').style.width = `${Math.round(all.length ? all.reduce((a, b) => a + b, 0) / all.length : 2)}%`;
  }

  function renderLog() {
    const log = $('cloneRunLog');
    log.textContent = C.logs.slice(-400).join('\n');
    if ($('cloneLogBox').open) log.scrollTop = log.scrollHeight;
  }

  function thumbs(paths) {
    return `<span class="thumbs">${paths.slice(0, 6).map((p) => `<img src="${thumbUrl(p, 90)}" alt="" loading="lazy">`).join('')}</span>`;
  }

  // Hàng đợi clone: cuốn đang làm / đang chờ / bị dở (Làm tiếp, Bỏ). Cuốn xong nằm ở "Lịch đã làm".
  function renderQueue() {
    // Không có lượt clone nào chạy thật mà cuốn vẫn ghi "running" (bấm Dừng / tắt tool giữa chừng): là "Đã dừng".
    const live = running();
    const items = C.data.items.filter((i) => ['pending', 'running', 'failed', 'rejected'].includes(i.status))
      .map((i) => (i.status === 'running' && !live ? { ...i, status: 'failed', stopped: true,
        reason: i.reason || 'đã dừng giữa chừng - bấm Làm tiếp để làm phần còn thiếu' } : i));
    $('cloneQueueCard').hidden = !items.length;
    $('btnCloneRun').hidden = running() || !items.some((i) => i.status === 'pending');
    const ol = $('cloneQueue');
    ol.innerHTML = '';
    let k = 0;
    const order = { running: 0, pending: 1, failed: 2, rejected: 3 };
    items.slice().reverse().sort((a, b) => order[a.status] - order[b.status]).forEach((i) => {
      const li = document.createElement('li');
      const tag = i.status === 'running' ? '<span class="tag run">Đang làm</span>'
        : i.status === 'pending' ? `<span class="tag">Chờ ${++k}</span>`
          : `<span class="tag bad">${i.status === 'rejected' ? 'Bị loại' : i.stopped ? 'Đã dừng' : 'Bị dở'}</span>`;
      li.innerHTML = `${tag} ${thumbs(i.ref_paths || [])} <strong>${esc(i.title || 'Chưa có tên')}</strong>
        <span class="muted">${esc(i.group || '')} · lịch ${esc(i.year)} · ${i.refs} ảnh mẫu${i.stage ? ` · ${esc(i.stage)}` : ''}</span>
        ${i.reason ? `<span class="why">${esc(i.reason)}</span>` : ''}<span class="grow"></span>`;
      if (i.status === 'failed' || i.status === 'rejected') {
        li.appendChild(button('Làm tiếp', 'btn-small btn-accent', () => op('retry', i.id, true)));
      }
      if (i.status !== 'running' || !running()) {
        li.appendChild(button('Bỏ', 'btn-small btn-danger-ghost', () => {
          if (confirm('Bỏ cuốn này khỏi hàng đợi clone? (Thư mục cuốn đã làm được vẫn giữ nguyên)')) op('remove', i.id);
        }));
      }
      ol.appendChild(li);
    });
  }

  function renderPlus() {
    const d = C.data;
    const note = $('clonePlusNotice');
    note.hidden = d.plus.length > 0;
    note.innerHTML = '<strong>Không có tài khoản ChatGPT Plus / K12 nào còn hạn.</strong> Clone sản phẩm chỉ dùng tài khoản Plus / K12.'
      + (d.unknown.length ? ` Chưa rõ gói: ${esc(d.unknown.join(', '))} - bấm "Kiểm tra gói Plus" trong Tài khoản ChatGPT.` : '');
  }

  function render(data) {
    C.data = data;
    if (data.task && data.task.id !== C.taskId) {
      C.taskId = data.task.id;
      C.logs = [];
      C.since = 0;
    }
    renderPlus();
    renderRun();
    renderQueue();
    renderStartButton();
    // một cuốn vừa xong: tải lại "Lịch đã làm" của trang chính để thấy ngay
    const done = data.items.filter((i) => i.status === 'done').map((i) => i.id).join(',');
    if (done !== C.lastDone) {
      if (C.lastDone && typeof window.loadProjects === 'function') window.loadProjects();
      C.lastDone = done;
    }
  }

  async function op(name, id, autostart = false) {
    try {
      let data = await api(`/api/clone/${name}`, { id });
      if (autostart && !running()) data = await api('/api/clone/start', { show: $('cloneShowChrome').checked });
      render(data);
    } catch (e) {
      toast(e.message, 'error');
    }
  }

  async function refresh() {
    try {
      render(await api('/api/clone/items'));
    } catch (_) { /* máy chủ bận: lần sau đọc lại */ }
    if (C.taskId && running()) {
      const t = await api(`/api/task?id=${encodeURIComponent(C.taskId)}&since=${C.since}`).catch(() => null);
      if (t && t.logs) {
        C.logs.push(...t.logs);
        C.since = t.total_logs;
        renderLog();
      }
    }
  }

  async function stop() {
    if (!C.taskId || !confirm('Dừng clone? Ảnh đã vẽ được giữ lại, lần sau chạy tiếp phần còn thiếu.')) return;
    await api('/api/task/stop', { id: C.taskId }).catch((e) => toast(e.message, 'error'));
    refresh();
  }

  // ---------------------------------------------------------------- gắn sự kiện
  document.querySelectorAll('input[name="make_mode"]').forEach((r) => r.addEventListener('change', applyMode));
  let saved = '';
  try { saved = new URLSearchParams(location.search).get('mode') || localStorage.getItem('makeMode') || ''; } catch (_) { /* bỏ qua */ }
  const pick = document.querySelector(`input[name="make_mode"][value="${saved === 'clone' ? 'clone' : 'idea'}"]`);
  if (pick) pick.checked = true;
  applyMode();

  $('clonePick').addEventListener('click', () => $('cloneFiles').click());
  $('cloneFiles').addEventListener('change', (e) => { addFiles(e.target.files); e.target.value = ''; });
  const drop = $('cloneDrop');
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
  document.querySelectorAll('.stepper-y button').forEach((b) => b.addEventListener('click', () => {
    const y = $('cloneYear');
    y.value = Math.max(2025, Math.min(2100, (+y.value || 2027) + Number(b.dataset.ystep)));
    renderStartButton();
  }));
  $('cloneYear').addEventListener('input', renderStartButton);
  $('btnCloneStart').addEventListener('click', start);
  $('btnCloneStop').addEventListener('click', stop);
  $('btnCloneRun').addEventListener('click', () => api('/api/clone/start', { show: $('cloneShowChrome').checked })
    .then(render).catch((e) => toast(e.message, 'error')));
  try { $('cloneShowChrome').checked = localStorage.getItem('cloneShowChrome') === '1'; } catch (_) { /* bỏ qua */ }
  $('cloneShowChrome').addEventListener('change', () => {
    try { localStorage.setItem('cloneShowChrome', $('cloneShowChrome').checked ? '1' : '0'); } catch (_) { /* bỏ qua */ }
  });
  refresh();
  setInterval(refresh, 3000);
})();
