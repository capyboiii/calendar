/**
 * CalForge Studio — Front-End Application Logic
 */

const STATE = {
  projects: [],
  currentConceptPath: null,
  currentConcept: null,
  activeTab: 'months',
  artType: 'final', // 'final' or 'raw'
  proofOverlay: true, // show proof template overlay by default
  activeTaskId: null,
  taskPollTimer: null,
  taskLogOffset: 0,
};

// --------------------------------------------------------------------------
// Initialization
// --------------------------------------------------------------------------
document.addEventListener('DOMContentLoaded', () => {
  initEventListeners();
  loadStyleFamilies();
  loadProjects();
  loadAccounts();
});

function initEventListeners() {
  // Tabs
  document.querySelectorAll('.tab-btn').forEach((btn) => {
    btn.addEventListener('click', () => switchTab(btn.dataset.tab));
  });

  // Proof Overlay Toggle
  const proofToggle = document.getElementById('proofOverlayToggle');
  if (proofToggle) {
    proofToggle.addEventListener('change', (e) => {
      STATE.proofOverlay = e.target.checked;
      renderProofsTab();
    });
  }

  // Art Type Toggle
  document.querySelectorAll('.toggle-pill[data-art-type]').forEach((pill) => {
    pill.addEventListener('click', (e) => {
      document.querySelectorAll('.toggle-pill[data-art-type]').forEach((p) => p.classList.remove('active'));
      pill.classList.add('active');
      STATE.artType = pill.dataset.artType;
      renderArtTab();
    });
  });



  // New Project Modal
  const modal = document.getElementById('modalNewProject');
  const btnNewProject = document.getElementById('btnNewProject');
  const btnCloseModal = document.getElementById('btnCloseModal');
  const btnCancelModal = document.getElementById('btnCancelModal');
  const btnSubmitNew = document.getElementById('btnSubmitNewProject');

  btnNewProject.addEventListener('click', () => {
    modal.style.display = 'flex';
    document.getElementById('inputKeyword').focus();
  });
  const closeModal = () => { modal.style.display = 'none'; };
  btnCloseModal.addEventListener('click', closeModal);
  btnCancelModal.addEventListener('click', closeModal);
  modal.addEventListener('click', (e) => { if (e.target === modal) closeModal(); });

  // Accounts Modal
  const modalAcc = document.getElementById('modalAccounts');
  const btnOpenAcc = document.getElementById('btnOpenAccounts');
  const btnCloseAcc = document.getElementById('btnCloseAccountsModal');
  const btnCloseAccFooter = document.getElementById('btnCloseAccountsFooter');
  const btnCreateAcc = document.getElementById('btnCreateAccount');

  btnOpenAcc.addEventListener('click', () => {
    loadAccounts();
    modalAcc.style.display = 'flex';
  });
  const closeAccModal = () => { modalAcc.style.display = 'none'; };
  btnCloseAcc.addEventListener('click', closeAccModal);
  btnCloseAccFooter.addEventListener('click', closeAccModal);
  modalAcc.addEventListener('click', (e) => { if (e.target === modalAcc) closeAccModal(); });
  btnCreateAcc.addEventListener('click', handleCreateAccount);
  document.getElementById('inputNewAccName').addEventListener('keydown', (e) => {
    if (e.key === 'Enter') handleCreateAccount();
  });

  // Radio cards in modal
  document.querySelectorAll('.radio-card').forEach((card) => {
    card.addEventListener('click', () => {
      document.querySelectorAll('.radio-card').forEach((c) => c.classList.remove('active'));
      card.classList.add('active');
      card.querySelector('input').checked = true;
    });
  });

  btnSubmitNew.addEventListener('click', handleCreateProject);

  // Search filter
  document.getElementById('projectSearch').addEventListener('input', (e) => {
    filterProjects(e.target.value.toLowerCase().trim());
  });

  // Action Buttons
  document.getElementById('btnActionContinue').addEventListener('click', () => triggerAction('produce'));
  document.getElementById('btnActionProduce').addEventListener('click', () => triggerAction('produce'));
  document.getElementById('btnActionRender').addEventListener('click', () => triggerAction('render'));
  document.getElementById('btnActionPrintify').addEventListener('click', () => triggerAction('printify'));
  document.getElementById('btnTriggerPrintify').addEventListener('click', () => triggerAction('printify'));

  // Copy buttons
  document.querySelectorAll('.copy-btn').forEach((btn) => {
    btn.addEventListener('click', () => {
      const targetId = btn.dataset.target;
      const el = document.getElementById(targetId);
      if (!el) return;
      const text = el.tagName === 'TEXTAREA' ? el.value : el.innerText;
      copyToClipboard(text, btn);
    });
  });

  document.getElementById('btnCopyAllTags').addEventListener('click', () => {
    const pills = document.querySelectorAll('#tagsCloud .tag-pill');
    const tags = Array.from(pills).map((p) => p.innerText).join(', ');
    copyToClipboard(tags, document.getElementById('btnCopyAllTags'));
  });

  // Lightbox Close
  const lightbox = document.getElementById('lightboxModal');
  document.getElementById('btnCloseLightbox').addEventListener('click', () => { lightbox.style.display = 'none'; });
  lightbox.addEventListener('click', (e) => { if (e.target === lightbox) lightbox.style.display = 'none'; });
}

// --------------------------------------------------------------------------
// API Calls & Data Loading
// --------------------------------------------------------------------------
async function loadStyleFamilies() {
  try {
    const res = await fetch('/api/styles');
    const data = await res.json();
    const select = document.getElementById('selectFamily');
    (data.families || []).forEach((f) => {
      const opt = document.createElement('option');
      opt.value = f.id;
      opt.textContent = `${f.name} — ${f.medium}`;
      select.appendChild(opt);
    });
  } catch (err) {
    console.error('Lỗi tải danh sách phong cách:', err);
  }
}

async function loadProjects() {
  try {
    const res = await fetch('/api/projects');
    const data = await res.json();
    STATE.projects = data.projects || [];

    if (data.year) document.getElementById('metaYear').textContent = data.year;
    if (data.market) document.getElementById('metaMarket').textContent = data.market;

    renderSidebar(STATE.projects);

    // Auto-select first concept if available and none selected
    if (!STATE.currentConceptPath) {
      for (const p of STATE.projects) {
        if (p.concepts && p.concepts.length > 0) {
          selectConcept(p.concepts[0].path);
          break;
        }
      }
    }
  } catch (err) {
    console.error('Lỗi tải danh sách dự án:', err);
  }
}

async function selectConcept(conceptPath) {
  STATE.currentConceptPath = conceptPath;

  // Highlight in sidebar
  document.querySelectorAll('.concept-item').forEach((item) => {
    item.classList.toggle('active', item.dataset.path === conceptPath);
  });

  try {
    const res = await fetch(`/api/concept?path=${encodeURIComponent(conceptPath)}`);
    const data = await res.json();
    if (data.error) throw new Error(data.error);

    STATE.currentConcept = data;
    renderConceptView(data);
  } catch (err) {
    alert(`Không thể tải concept: ${err.message}`);
  }
}

// --------------------------------------------------------------------------
// Sidebar Rendering
// --------------------------------------------------------------------------
function renderSidebar(projects) {
  const container = document.getElementById('projectList');
  container.innerHTML = '';

  let totalConcepts = 0;
  projects.forEach((p) => { totalConcepts += (p.concepts || []).length; });
  document.getElementById('projectCount').textContent = totalConcepts;

  if (projects.length === 0) {
    container.innerHTML = '<div class="empty-state-sidebar">Chưa có dự án nào.<br>Bấm "Tạo Dự Án Mới" để bắt đầu!</div>';
    return;
  }

  projects.forEach((proj) => {
    const group = document.createElement('div');
    group.className = 'keyword-group';

    const header = document.createElement('div');
    header.className = 'keyword-label';
    header.innerHTML = `<span>${escapeHtml(proj.keyword)}</span><span class="badge">${(proj.concepts || []).length}</span>`;
    group.appendChild(header);

    (proj.concepts || []).forEach((c) => {
      const item = document.createElement('div');
      item.className = 'concept-item' + (c.path === STATE.currentConceptPath ? ' active' : '');
      item.dataset.path = c.path;
      item.dataset.keyword = proj.keyword.toLowerCase();
      item.dataset.title = (c.title || '').toLowerCase();

      // Dot color
      let dotClass = 'amber';
      const stage = (c.status || {}).stage || '';
      if (c.status && c.status.ok && (stage === 'printify' || stage === 'listing' || c.has_digital)) {
        dotClass = 'green';
      } else if (c.status && c.status.ok === false) {
        dotClass = 'red';
      }

      item.innerHTML = `
        <div class="concept-item-top">
          <span class="concept-item-title">${escapeHtml(c.title)}</span>
          <span class="status-dot ${dotClass}" title="${escapeHtml(stage || 'Mới')}"></span>
        </div>
        <div class="concept-item-meta">
          <span>${escapeHtml(c.family || 'Chưa rõ style')}</span>
          <span>•</span>
          <span>${c.final_count || c.raw_count}/13 ảnh</span>
        </div>
      `;

      item.addEventListener('click', () => selectConcept(c.path));
      group.appendChild(item);
    });

    container.appendChild(group);
  });
}

function filterProjects(query) {
  document.querySelectorAll('.concept-item').forEach((item) => {
    const kw = item.dataset.keyword || '';
    const title = item.dataset.title || '';
    const match = !query || kw.includes(query) || title.includes(query);
    item.style.display = match ? 'flex' : 'none';
  });
}

// --------------------------------------------------------------------------
// Concept Workspace Rendering
// --------------------------------------------------------------------------
function renderConceptView(data) {
  const concept = data.concept || {};
  const status = data.status || {};
  const cover = concept.cover || {};
  const style = concept.style || {};

  // Show UI elements
  document.getElementById('emptyState').style.display = 'none';
  document.getElementById('conceptHero').style.display = 'flex';
  document.getElementById('studioTabs').style.display = 'flex';
  document.getElementById('tabContent').style.display = 'block';

  // Hero section
  document.getElementById('heroTitle').textContent = cover.title || data.name;
  document.getElementById('heroSubtitle').textContent = cover.subtitle || '';
  document.getElementById('heroFamily').textContent = style.family || style.name || 'Art';
  document.getElementById('heroAngle').textContent = concept.angle_id || 'concept';

  const stage = status.stage || 'ideation';
  const isOk = status.ok !== false;
  document.getElementById('heroStatus').textContent = `Giai đoạn: ${stage.toUpperCase()}` + (isOk ? '' : ' (Cần xử lý)');

  // Render Stepper
  renderStepper(status, data.files);
  updateContinueButton(status, data.files);

  // Tab 1: Months & Design System
  renderMonthsTab(data);

  // Tab 2: Art & QC
  renderArtTab();

  // Tab 3: Proofs & 26 Pages
  renderProofsTab();

  // Tab 4: Listing
  renderListingTab(data);
}

// Bước còn thiếu tiếp theo (dùng cho nhãn nút "Chạy Tiếp"). produce() tự bỏ qua bước đã xong.
function nextUnfinishedStage(status, files) {
  const raw = (files.art_raw || []).length;
  const final = (files.art_final || []).length;
  const render = (files.render_printify || []).length;
  if (raw < 14) return { label: `Chạy Tiếp: Sinh ảnh (${raw}/14)`, done: false };
  if (final < 13) return { label: `Chạy Tiếp: Upscale (${final}/13)`, done: false };
  if (render < 26) return { label: `Chạy Tiếp: Render (${render}/26)`, done: false };
  if (!(status.stage === 'listing' || status.stage === 'printify' || status.product_id))
    return { label: 'Chạy Tiếp: Listing', done: false };
  if (!status.product_id) return { label: 'Chạy Tiếp: Printify', done: false };
  return { label: 'Đã hoàn tất ✓', done: true };
}

function updateContinueButton(status, files) {
  const btn = document.getElementById('btnActionContinue');
  const label = document.getElementById('btnContinueLabel');
  if (!btn || !label) return;
  const next = nextUnfinishedStage(status, files);
  label.textContent = next.label;
  btn.disabled = next.done;
  btn.classList.toggle('btn-primary', !next.done);
  btn.classList.toggle('btn-secondary', next.done);
}

function renderStepper(status, files) {
  const stepper = document.getElementById('pipelineStepper');
  stepper.innerHTML = '';

  const rawCount = (files.art_raw || []).length;
  const finalCount = (files.art_final || []).length;
  const renderCount = (files.render_printify || []).length;

  const steps = [
    { num: '01', name: 'Ý tưởng', desc: 'P1 góc ➔ P2 concept', done: true },
    { num: '02', name: 'Sinh ảnh', desc: `${rawCount}/14 ảnh`, done: rawCount >= 13, active: rawCount > 0 && rawCount < 13 },
    { num: '03', name: 'Upscale', desc: `${finalCount}/13 Real-ESRGAN`, done: finalCount >= 13, active: finalCount > 0 && finalCount < 13 },
    { num: '04', name: 'Render', desc: `${renderCount}/26 trang in`, done: renderCount >= 26, active: renderCount > 0 && renderCount < 26 },
    { num: '05', name: 'Listing', desc: 'Title, tags & mô tả', done: !!(status.stage === 'listing' || status.stage === 'printify') },
    { num: '06', name: 'Printify', desc: status.product_id ? `ID: ${status.product_id.slice(-6)}` : 'Sản phẩm nháp', done: !!status.product_id },
  ];

  steps.forEach((s) => {
    const node = document.createElement('div');
    node.className = 'step-node' + (s.done ? ' done' : '') + (s.active ? ' active' : '');
    node.innerHTML = `
      <div class="step-header">
        <span class="step-num">${s.num}</span>
        ${s.done ? '<svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="#3fb950" stroke-width="3"><polyline points="20 6 9 17 4 12"></polyline></svg>' : ''}
      </div>
      <div class="step-name">${s.name}</div>
      <div class="step-desc">${s.desc}</div>
    `;
    stepper.appendChild(node);
  });
}

// --------------------------------------------------------------------------
// Tab 1: Months & Design System
// --------------------------------------------------------------------------
function renderMonthsTab(data) {
  const concept = data.concept || {};
  const style = concept.style || {};
  const palette = (data.palette && data.palette.paper) ? data.palette : (style.palette || {});

  document.getElementById('metaBuyer').textContent = concept.buyer || 'Người yêu thích nghệ thuật & trang trí không gian sống';
  document.getElementById('metaHook').textContent = concept.hook || concept.style_bible || '-';
  document.getElementById('metaStyle').textContent = `${style.name || ''} (${style.family || ''})`;

  // Swatches
  const swatchesGrid = document.getElementById('swatchesGrid');
  swatchesGrid.innerHTML = '';
  const roleNames = { paper: 'Nền giấy', title: 'Tiêu đề', text: 'Chữ thân', accent: 'Điểm nhấn', grid_line: 'Đường kẻ lưới' };

  for (const [key, color] of Object.entries(palette)) {
    if (key.startsWith('_') || key === 'note') continue;
    const card = document.createElement('div');
    card.className = 'swatch-card';
    card.innerHTML = `
      <div class="swatch-color-pill" style="background-color: ${color}"></div>
      <div class="swatch-role">${roleNames[key] || key}</div>
      <div class="swatch-hex">${color}</div>
    `;
    swatchesGrid.appendChild(card);
  }

  // Fonts
  const fontsList = document.getElementById('fontsList');
  fontsList.innerHTML = '';
  const fonts = style.fonts || {};
  [
    { role: 'Tiêu đề (Display)', name: fonts.title || 'Cormorant Garamond' },
    { role: 'Chữ đọc (Body)', name: fonts.body || 'Montserrat' },
    { role: 'Số ngày (Numbers)', name: fonts.numbers || 'Montserrat' },
  ].forEach((f) => {
    const item = document.createElement('div');
    item.className = 'font-item';
    item.innerHTML = `<span class="font-role">${f.role}</span><span class="font-name">${escapeHtml(f.name)}</span>`;
    fontsList.appendChild(item);
  });

  // 12 Months Grid
  const monthsGrid = document.getElementById('monthsGrid');
  monthsGrid.innerHTML = '';
  (concept.months || []).forEach((m) => {
    const card = document.createElement('div');
    card.className = 'month-card';

    const monthNames = ['', 'Tháng 1 (Jan)', 'Tháng 2 (Feb)', 'Tháng 3 (Mar)', 'Tháng 4 (Apr)', 'Tháng 5 (May)', 'Tháng 6 (Jun)', 'Tháng 7 (Jul)', 'Tháng 8 (Aug)', 'Tháng 9 (Sep)', 'Tháng 10 (Oct)', 'Tháng 11 (Nov)', 'Tháng 12 (Dec)'];
    const titleText = monthNames[m.month] || `Tháng ${m.month}`;
    const verse = (m.content || {}).text || '';
    const verseRef = (m.content || {}).value || '';

    card.innerHTML = `
      <div class="month-card-header">
        <span class="month-card-title">${titleText}</span>
        <span class="month-card-subtitle">${escapeHtml(m.subtitle || '')}</span>
      </div>

      ${verse ? `
        <div class="quote-box">
          <p class="quote-text">"${escapeHtml(verse)}"</p>
          <span class="quote-ref">— ${escapeHtml(verseRef)} (KJV)</span>
        </div>
      ` : ''}

      <div class="prompt-box">
        <strong>Chủ đề tranh:</strong> ${escapeHtml(m.visual_prompt || m.scene || '')}
      </div>

      ${m.holiday_tie ? `<div class="holiday-pill">Lễ hội: ${escapeHtml(m.holiday_tie)}</div>` : ''}
    `;
    monthsGrid.appendChild(card);
  });
}

// --------------------------------------------------------------------------
// Tab 2: Art Gallery & QC
// --------------------------------------------------------------------------
function renderArtTab() {
  if (!STATE.currentConcept) return;
  const data = STATE.currentConcept;
  const conceptPath = data.path;
  const files = data.files || {};
  const isFinal = STATE.artType === 'final';
  const subFolder = isFinal ? 'art/final' : 'art/raw';

  // Badge count
  const count = isFinal ? (files.art_final || []).length : (files.art_raw || []).length;
  document.getElementById('artCountBadge').textContent = `${count}/13`;

  // Anchor spotlight
  const anchorCard = document.getElementById('anchorCard');
  const anchorFile = isFinal ? 'anchor.png' : 'anchor.png';
  const anchorSrc = `/api/file?path=${conceptPath}/${subFolder}/${anchorFile}`;

  anchorCard.innerHTML = `
    <div class="anchor-thumb-wrap" onclick="openLightbox('${anchorSrc}', 'Ảnh Neo Phong Cách (Anchor Art)')">
      <img src="${anchorSrc}" alt="Anchor Art" onerror="this.src='data:image/svg+xml;utf8,<svg xmlns=\\'http://www.w3.org/2000/svg\\' width=\\'300\\' height=\\'200\\' fill=\\'%23222\\'><text x=\\'50%\\' y=\\'50%\\' fill=\\'%23666\\' text-anchor=\\'middle\\'>Chưa có ảnh neo</text></svg>'">
    </div>
    <div class="anchor-details">
      <span class="tag-chip family-chip" style="align-self: flex-start;">ẢNH NEO THIẾT KẾ</span>
      <h3>${escapeHtml((data.concept.cover || {}).title || 'Phong cách chủ đạo')}</h3>
      <p class="subtext">Ảnh neo được sinh đầu tiên và đính kèm vào từng cuộc hội thoại sinh tranh 12 tháng kế tiếp, giúp đảm bảo toàn bộ bộ lịch giữ nguyên phong cách màu sắc, nét cọ và ánh sáng.</p>
      <div class="p-detail"><strong>Vị trí file:</strong> <code>${conceptPath}/${subFolder}/anchor.png</code></div>
    </div>
  `;

  // 12 Months Artworks
  const grid = document.getElementById('artworksGrid');
  grid.innerHTML = '';

  for (let m = 1; m <= 12; m++) {
    const jobTag = `m${String(m).padStart(2, '0')}`;
    const imgFile = `${jobTag}.png`;
    const imgSrc = `/api/file?path=${conceptPath}/${subFolder}/${imgFile}`;
    const monthData = (data.concept.months || [])[m - 1] || {};

    const card = document.createElement('div');
    card.className = 'art-card';
    card.innerHTML = `
      <div class="art-preview-wrap" onclick="openLightbox('${imgSrc}', 'Tháng ${m}: ${escapeHtml(monthData.subtitle || jobTag)}')">
        <img src="${imgSrc}" alt="${jobTag}" onerror="this.src='data:image/svg+xml;utf8,<svg xmlns=\\'http://www.w3.org/2000/svg\\' width=\\'300\\' height=\\'200\\' fill=\\'%231a1a1a\\'><text x=\\'50%\\' y=\\'50%\\' fill=\\'%23555\\' text-anchor=\\'middle\\'>Chưa sinh ảnh</text></svg>'">
        <div class="art-badge-overlay">${isFinal ? 'Real-ESRGAN' : 'ChatGPT'}</div>
      </div>
      <div class="art-card-body">
        <span class="art-month-label">Tháng ${m}</span>
        <span class="art-spec">${jobTag}.png</span>
      </div>
    `;
    grid.appendChild(card);
  }
}

// --------------------------------------------------------------------------
// Tab 3: Proofs & 26 Pages (Hero View)
// --------------------------------------------------------------------------
function renderProofsTab() {
  if (!STATE.currentConcept) return;
  const data = STATE.currentConcept;
  const conceptPath = data.path;
  const files = data.files || {};
  const useProof = STATE.proofOverlay;

  // Download links
  const btnLetter = document.getElementById('btnDownloadDigitalPdf');
  const btnPages = document.getElementById('btnDownloadPagesPdf');
  btnLetter.href = `/api/file?path=${conceptPath}/render/digital/calendar_11x8_5.pdf`;
  btnPages.href = `/api/file?path=${conceptPath}/render/pages.pdf`;

  // Preflight badge & box
  const issues = [];
  if (data.render_report && data.render_report.includes('Preflight: 0 vấn đề')) {
    document.getElementById('preflightBadge').textContent = '0 lỗi';
    document.getElementById('preflightBox').className = 'preflight-status-card';
    document.getElementById('preflightTitle').textContent = 'Preflight Sạch — Chuẩn In District Photo 100%';
    document.getElementById('preflightDesc').textContent = '26 trang đã qua kiểm định: lề an toàn 0.25", không chạm lỗ treo và lò xo, font chữ rõ nét.';
  } else {
    document.getElementById('preflightBadge').textContent = 'Hoàn tất';
  }

  // 26 Pages List
  const pages = [
    { id: 'front_cover', title: 'Bìa Trước (Front Cover)', kind: 'Bìa' },
  ];
  for (let m = 1; m <= 12; m++) {
    const tag = `m${String(m).padStart(2, '0')}`;
    pages.push({ id: `${tag}_month`, title: `Tháng ${m} — Tranh Minh Họa`, kind: 'Trang tranh' });
    pages.push({ id: `${tag}_grid`, title: `Tháng ${m} — Lưới Lịch & Lễ Hội`, kind: 'Trang lưới' });
  }
  pages.push({ id: 'back_cover', title: 'Bìa Sau (Back Cover)', kind: 'Bìa' });

  const grid = document.getElementById('pagesStripGrid');
  grid.innerHTML = '';

  pages.forEach((p) => {
    const card = document.createElement('div');
    card.className = 'page-proof-card';

    const folder = useProof ? 'render/proof' : 'render/printify';
    const filename = useProof ? `${p.id}_proof.png` : `${p.id}.png`;
    const imgSrc = `/api/file?path=${conceptPath}/${folder}/${filename}`;

    card.innerHTML = `
      <div class="page-proof-thumb" onclick="openLightbox('${imgSrc}', '${p.title}')">
        <img src="${imgSrc}" alt="${p.title}" onerror="this.src='data:image/svg+xml;utf8,<svg xmlns=\\'http://www.w3.org/2000/svg\\' width=\\'337\\' height=\\'262\\' fill=\\'%23161b22\\'><text x=\\'50%\\' y=\\'50%\\' fill=\\'%23555\\' text-anchor=\\'middle\\'>Chưa render trang</text></svg>'">
      </div>
      <div class="page-proof-info">
        <span class="page-proof-name">${p.title}</span>
        <span class="page-proof-type">${p.kind}</span>
      </div>
    `;
    grid.appendChild(card);
  });
}

// --------------------------------------------------------------------------
// Tab 4: Listing & Publish
// --------------------------------------------------------------------------
function renderListingTab(data) {
  const listing = data.listing || {};
  const status = data.status || {};
  const printify = data.printify || {};

  document.getElementById('listingTitle').textContent = listing.title || 'Chưa sinh tiêu đề';
  document.getElementById('listingDescPreview').innerHTML = listing.description || '<p>Chưa có mô tả</p>';
  document.getElementById('listingDescRaw').value = listing.description || '';

  // Tags cloud
  const tagsCloud = document.getElementById('tagsCloud');
  tagsCloud.innerHTML = '';
  (listing.tags || []).forEach((tag) => {
    const pill = document.createElement('div');
    pill.className = 'tag-pill';
    pill.textContent = tag;
    pill.title = 'Bấm để sao chép tag này';
    pill.addEventListener('click', () => copyToClipboard(tag, pill));
    tagsCloud.appendChild(pill);
  });

  // Printify details
  const uploadsCount = Object.keys(printify.uploads || {}).length;
  document.getElementById('printifyUploadsCount').textContent = `${uploadsCount} / 26 trang`;

  const prodBadge = document.getElementById('printifyProductBadge');
  const prodRow = document.getElementById('printifyProductIdRow');
  const prodCode = document.getElementById('printifyProductId');

  if (status.product_id || printify.product_id) {
    const pid = status.product_id || printify.product_id;
    prodBadge.className = 'badge';
    prodBadge.style.backgroundColor = 'var(--status-green-bg)';
    prodBadge.style.color = 'var(--status-green-light)';
    prodBadge.textContent = status.published ? 'Đã Publish' : 'Bản Nháp (Draft)';
    prodRow.style.display = 'block';
    prodCode.textContent = pid;
  } else {
    prodBadge.textContent = 'Chưa tạo';
    prodRow.style.display = 'none';
  }
}

// --------------------------------------------------------------------------
// Tab Navigation
// --------------------------------------------------------------------------
function switchTab(tabId) {
  STATE.activeTab = tabId;
  document.querySelectorAll('.tab-btn').forEach((b) => {
    b.classList.toggle('active', b.dataset.tab === tabId);
  });
  document.querySelectorAll('.tab-pane').forEach((p) => {
    p.classList.toggle('active', p.id === `pane-${tabId}`);
  });
}

// --------------------------------------------------------------------------
// --------------------------------------------------------------------------
// Toast Notifications & Action Polling
// --------------------------------------------------------------------------
function showToast(message, type = 'info', duration = 4000) {
  let container = document.getElementById('toastContainer');
  if (!container) {
    container = document.createElement('div');
    container.id = 'toastContainer';
    container.className = 'toast-container';
    document.body.appendChild(container);
  }

  const toast = document.createElement('div');
  toast.className = `toast toast-${type}`;

  let iconHtml = '';
  if (type === 'running') {
    iconHtml = '<div class="toast-spinner"></div>';
  } else if (type === 'success') {
    iconHtml = '<span style="color: var(--status-green-light); font-size: 1rem;">✔</span>';
  } else if (type === 'error') {
    iconHtml = '<span style="color: var(--status-red); font-size: 1rem;">❌</span>';
  } else {
    iconHtml = '<span style="color: var(--accent-gold); font-size: 1rem;">ℹ</span>';
  }

  toast.innerHTML = `${iconHtml}<span>${escapeHtml(message)}</span>`;
  container.appendChild(toast);

  if (duration > 0) {
    setTimeout(() => {
      toast.style.opacity = '0';
      toast.style.transform = 'translateY(10px) scale(0.95)';
      setTimeout(() => toast.remove(), 300);
    }, duration);
  }

  return toast;
}

async function triggerAction(actionName) {
  if (!STATE.currentConceptPath) return;

  const toast = showToast(`Đang khởi chạy: ${actionName}...`, 'running', 0);

  try {
    const res = await fetch('/api/action', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        action: actionName,
        params: { concept: STATE.currentConceptPath },
      }),
    });
    const data = await res.json();
    toast.remove();
    if (data.error) throw new Error(data.error);

    startTaskPolling(data.task_id, data.description);
  } catch (err) {
    toast.remove();
    showToast(`Lỗi khởi chạy tác vụ: ${err.message}`, 'error', 5000);
  }
}

async function handleCreateProject() {
  const keyword = document.getElementById('inputKeyword').value.trim();
  if (!keyword) {
    showToast('Vui lòng nhập từ khóa chủ đề.', 'error');
    return;
  }

  const family = document.getElementById('selectFamily').value;
  const mode = document.querySelector('input[name="runMode"]:checked').value;

  document.getElementById('modalNewProject').style.display = 'none';
  const toast = showToast(`Đang khởi tạo dự án '${keyword}'...`, 'running', 0);

  try {
    const action = mode === 'full' ? 'run' : 'ideate';
    const res = await fetch('/api/action', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        action,
        params: { keyword, family: family || undefined },
      }),
    });
    const data = await res.json();
    toast.remove();
    if (data.error) throw new Error(data.error);

    startTaskPolling(data.task_id, data.description, async () => {
      await loadProjects();
    });
  } catch (err) {
    toast.remove();
    showToast(`Lỗi tạo dự án: ${err.message}`, 'error', 5000);
  }
}

function startTaskPolling(taskId, description, onDone, opts = {}) {
  STATE.activeTaskId = taskId;
  // Một số tác vụ (đăng nhập) chặn lâu do chờ người dùng -> không hiện spinner "đang chạy"
  // để khỏi trông như bị treo; chỉ âm thầm chờ rồi làm mới khi xong.
  const runningToast = opts.silent
    ? { remove() {} }
    : showToast(description || 'Đang thực thi tác vụ...', 'running', 0);

  if (STATE.taskPollTimer) clearInterval(STATE.taskPollTimer);

  STATE.taskPollTimer = setInterval(async () => {
    try {
      const res = await fetch(`/api/task?id=${taskId}`);
      const task = await res.json();
      if (task.error) {
        clearInterval(STATE.taskPollTimer);
        runningToast.remove();
        showToast(`Lỗi tác vụ: ${task.error}`, 'error', 5000);
        return;
      }

      if (task.status !== 'running') {
        clearInterval(STATE.taskPollTimer);
        STATE.activeTaskId = null;
        runningToast.remove();

        if (task.status === 'success') {
          showToast(`Hoàn thành: ${description || 'Tác vụ đã xong'}!`, 'success', 5000);
        } else {
          showToast(`Thất bại: ${task.error || description}`, 'error', 6000);
        }

        if (STATE.currentConceptPath) {
          selectConcept(STATE.currentConceptPath);
        }
        if (onDone) onDone();
      }
    } catch (err) {
      console.error('Lỗi kiểm tra trạng thái task:', err);
    }
  }, 1200);
}

// --------------------------------------------------------------------------
// Helpers
// --------------------------------------------------------------------------
function openLightbox(src, caption) {
  const modal = document.getElementById('lightboxModal');
  const img = document.getElementById('lightboxImg');
  const cap = document.getElementById('lightboxCaption');
  img.src = src;
  cap.textContent = caption || '';
  modal.style.display = 'flex';
}

function copyToClipboard(text, btnElement) {
  if (!text) return;
  navigator.clipboard.writeText(text).then(() => {
    const originalText = btnElement.innerText;
    btnElement.innerText = 'Đã chép! ✓';
    btnElement.style.color = 'var(--status-green-light)';
    setTimeout(() => {
      btnElement.innerText = originalText;
      btnElement.style.color = '';
    }, 1500);
  }).catch((err) => {
    console.error('Không thể copy:', err);
  });
}

function escapeHtml(str) {
  if (!str) return '';
  return String(str)
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;')
    .replace(/'/g, '&#039;');
}

// --------------------------------------------------------------------------
// ChatGPT Accounts Management
// --------------------------------------------------------------------------
async function loadAccounts() {
  try {
    const res = await fetch('/api/accounts');
    const data = await res.json();
    const accounts = data.accounts || [];
    const countEl = document.getElementById('headerAccCount');
    if (countEl) countEl.textContent = accounts.length;
    const dirEl = document.getElementById('accProfilesDir');
    if (dirEl) dirEl.textContent = `Thư mục profiles: ${data.profiles_dir || ''}`;
    renderAccountsTable(accounts);
  } catch (err) {
    console.error('Lỗi tải danh sách tài khoản:', err);
  }
}

function renderAccountsTable(accounts) {
  const tbody = document.getElementById('accountsTableBody');
  if (!tbody) return;
  tbody.innerHTML = '';

  if (accounts.length === 0) {
    tbody.innerHTML = '<tr><td colspan="5" style="text-align: center; color: var(--text-muted); padding: 24px;">Chưa có tài khoản nào. Nhập tên tài khoản ở trên và bấm "Thêm Tài Khoản".</td></tr>';
    return;
  }

  accounts.forEach((acc) => {
    const tr = document.createElement('tr');

    let statusBadge = '';
    if (acc.is_locked) {
      statusBadge = '<span class="badge" style="background-color: var(--status-red-bg); color: var(--status-red);">Đang mở 🔒</span>';
    } else if (acc.has_session) {
      statusBadge = '<span class="badge" style="background-color: var(--status-green-bg); color: var(--status-green-light);">Đã có session ✔</span>';
    } else {
      statusBadge = '<span class="badge" style="background-color: var(--accent-gold-subtle); color: var(--accent-gold);">Chưa đăng nhập</span>';
    }

    const lastTag = acc.is_last_used ? '<span class="badge" style="font-size: 0.65rem; margin-left: 4px; background-color: var(--bg-subtle);">Gần nhất</span>' : '';

    tr.innerHTML = `
      <td>
        <div class="acc-name-cell">
          <div class="acc-avatar">${acc.name.slice(0, 2).toUpperCase()}</div>
          <span>${escapeHtml(acc.name)}</span>
        </div>
      </td>
      <td>${statusBadge}</td>
      <td>${acc.use_count} lượt ${lastTag}</td>
      <td style="font-size: 0.75rem; color: var(--text-muted); font-family: var(--font-mono);">${acc.modified_at}</td>
      <td style="text-align: right; white-space: nowrap;">
        <button class="btn btn-secondary btn-xs btn-login-acc" data-name="${escapeHtml(acc.name)}">
          <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M15 3h4a2 2 0 0 1 2 2v14a2 2 0 0 1-2 2h-4"></path><polyline points="10 17 15 12 10 7"></polyline><line x1="15" y1="12" x2="3" y2="12"></line></svg>
          Mở Chrome Đăng Nhập
        </button>
        <button class="btn btn-ghost btn-xs btn-delete-acc" data-name="${escapeHtml(acc.name)}" title="Xóa tài khoản và thư mục profile trên ổ đĩa" style="color: var(--status-red); margin-left: 6px;">
          <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><polyline points="3 6 5 6 21 6"></polyline><path d="M19 6v14a2 2 0 0 1-2 2H7a2 2 0 0 1-2-2V6m3 0V4a2 2 0 0 1 2-2h4a2 2 0 0 1 2 2v2"></path></svg>
          Xóa
        </button>
      </td>
    `;

    const delBtn = tr.querySelector('.btn-delete-acc');
    delBtn.addEventListener('click', () => {
      if (delBtn.dataset.confirming === 'true') {
        executeDeleteAccount(acc.name, delBtn);
      } else {
        delBtn.dataset.confirming = 'true';
        delBtn.innerHTML = '⚠️ Chắc chắn xóa?';
        delBtn.style.backgroundColor = 'var(--status-red)';
        delBtn.style.color = '#fff';
        delBtn.style.padding = '3px 8px';
        delBtn.style.borderRadius = 'var(--radius-sm)';
        setTimeout(() => {
          if (delBtn.isConnected && delBtn.dataset.confirming === 'true') {
            delBtn.dataset.confirming = 'false';
            delBtn.innerHTML = '<svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><polyline points="3 6 5 6 21 6"></polyline><path d="M19 6v14a2 2 0 0 1-2 2H7a2 2 0 0 1-2-2V6m3 0V4a2 2 0 0 1 2-2h4a2 2 0 0 1 2 2v2"></path></svg> Xóa';
            delBtn.style.backgroundColor = '';
            delBtn.style.color = 'var(--status-red)';
            delBtn.style.padding = '';
          }
        }, 4000);
      }
    });

    tbody.appendChild(tr);
  });
}

async function executeDeleteAccount(name, btn) {
  btn.disabled = true;
  btn.innerHTML = 'Đang xóa...';
  try {
    const res = await fetch('/api/accounts/delete', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ name }),
    });
    const data = await res.json();
    if (data.error) throw new Error(data.error);

    await loadAccounts();
  } catch (err) {
    alert(`Lỗi xóa tài khoản: ${err.message}`);
    await loadAccounts();
  }
}

async function handleCreateAccount() {
  const input = document.getElementById('inputNewAccName');
  const name = input.value.trim();
  if (!name) {
    alert('Vui lòng nhập tên tài khoản (ví dụ: acc6, my_account).');
    return;
  }

  try {
    const res = await fetch('/api/accounts/create', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ name }),
    });
    const data = await res.json();
    if (data.error) throw new Error(data.error);

    input.value = '';
    await loadAccounts();
    if (confirm(`Đã tạo profile '${name}'. Bạn có muốn mở Chrome để đăng nhập ngay không?`)) {
      handleLoginAccount(name);
    }
  } catch (err) {
    alert(`Lỗi tạo tài khoản: ${err.message}`);
  }
}

async function handleLoginAccount(name) {
  // GIỮ modal tài khoản mở để người dùng thấy bảng tự cập nhật sau khi đăng nhập xong.
  try {
    const res = await fetch('/api/action', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        action: 'login',
        params: { profile: name },
      }),
    });
    const data = await res.json();
    if (data.error) throw new Error(data.error);

    showToast(`Đã mở Chrome cho "${name}". Hãy đăng nhập ChatGPT rồi ĐÓNG cửa sổ để hoàn tất.`,
      'info', 9000);

    // Chờ âm thầm (không spinner). Xong thì làm mới danh sách tài khoản đang hiển thị.
    startTaskPolling(data.task_id, `Đăng nhập ${name}`, async () => {
      await loadAccounts();
      showToast(`Đã cập nhật trạng thái tài khoản "${name}".`, 'success', 4000);
    }, { silent: true });
  } catch (err) {
    showToast(`Lỗi mở trình duyệt đăng nhập: ${err.message}`, 'error', 5000);
  }
}

