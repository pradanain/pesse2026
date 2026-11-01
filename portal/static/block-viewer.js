/* Navigation changes presentation only. Data and access stay on the server. */
const viewer = document.querySelector('[data-block-viewer]');
if (viewer) {
  const blocks = [...viewer.querySelectorAll('details[data-section]')];
  const jump = viewer.querySelector('#section-jump');
  const previous = viewer.querySelector('[data-block-prev]');
  const next = viewer.querySelector('[data-block-next]');
  const stage = viewer.querySelector('[data-slide-stage]');
  const focusButton = viewer.querySelector('[data-reader-focus]');
  function setFocusMode(enabled) {
    document.body.classList.toggle('reader-focus', enabled);
    focusButton.setAttribute('aria-pressed', String(enabled));
    focusButton.setAttribute('aria-label', enabled ? 'Kembalikan ukuran area baca' : 'Perbesar area baca');
    focusButton.querySelector('span').textContent = enabled ? 'Kembalikan' : 'Perbesar';
    window.dispatchEvent(new Event('resize'));
    window.scrollTo({ top: 0, behavior: 'instant' });
  }
  focusButton.hidden = false;
  focusButton.addEventListener('click', () => setFocusMode(!document.body.classList.contains('reader-focus')));
  document.addEventListener('keydown', event => {
    if (event.key === 'Escape' && document.body.classList.contains('reader-focus') && !document.querySelector('.select-trigger[aria-expanded="true"]')) setFocusMode(false);
  });
  const savedScroll = new Map();
  let active = -1, touchStart;

  function setupRosters(detail) {
    const body = detail.querySelector('.block-body');
    const cards = [...body.querySelectorAll(':scope > .roster-card')];
    if (!cards.length) return;
    const workspace = document.createElement('div');
    workspace.className = 'roster-workspace';
    const picker = document.createElement('div');
    picker.className = 'roster-picker';
    picker.setAttribute('role', 'group');
    const kind = cards[0].dataset.rosterKind === 'member' ? 'anggota keluarga' : 'usaha';
    picker.setAttribute('aria-label', 'Daftar ' + kind);
    const label = document.createElement('label');
    label.className = 'roster-select-label';
    label.textContent = 'Pilih ' + kind;
    const select = document.createElement('select');
    select.id = detail.id + '-roster-select';
    label.htmlFor = select.id;
    select.setAttribute('aria-label', 'Pilih ' + kind);
    label.append(select);
    const content = document.createElement('div');
    content.className = 'roster-content';
    content.id = detail.id + '-roster-content';
    select.setAttribute('aria-controls', content.id);
    const buttons = [], positions = new Map();
    let selected = -1;
    function choose(index) {
      if (selected === index) return;
      const previousIndex = selected;
      if (selected >= 0) positions.set(selected, detail.scrollTop);
      selected = index;
      cards.forEach((card, i) => {
        card.hidden = i !== index;
        card.open = i === index;
        buttons[i].classList.toggle('selected', i === index);
        buttons[i].setAttribute('aria-pressed', String(i === index));
      });
      select.value = String(index);
      window.PortalControls?.refresh(select);
      if (previousIndex >= 0) requestAnimationFrame(() => {
        detail.scrollTop = positions.get(index) ?? Math.max(0, workspace.getBoundingClientRect().top - detail.getBoundingClientRect().top + detail.scrollTop - detail.querySelector(':scope > summary').offsetHeight - 12);
      });
    }
    cards.forEach((card, index) => {
      const title = card.querySelector(':scope > summary strong').textContent;
      const number = card.dataset.rosterIndex;
      const button = document.createElement('button');
      button.type = 'button';
      button.className = 'roster-choice';
      button.textContent = number + ' · ' + title;
      button.addEventListener('click', () => choose(index));
      buttons.push(button);
      picker.append(button);
      select.add(new Option(number + ' · ' + title, String(index)));
      card.querySelector(':scope > summary').addEventListener('click', (event) => event.preventDefault());
      content.append(card);
    });
    select.addEventListener('change', () => choose(Number(select.value)));
    workspace.append(label, picker, content);
    body.append(workspace);
    choose(0);
  }

  async function loadBlock(detail) {
    if (!detail.dataset.block || detail.dataset.loaded || detail.dataset.loading || detail.dataset.restricted) return;
    detail.dataset.loading = '1';
    const body = detail.querySelector('.block-body');
    body.setAttribute('aria-busy', 'true');
    const controller = new AbortController();
    const timeout = setTimeout(() => controller.abort(), 12000);
    try {
      const response = await fetch(detail.dataset.block, { credentials: 'same-origin', redirect: 'error', signal: controller.signal });
      if (!response.ok) throw new Error(response.status === 403 ? 'Akses ke rincian ini belum tersedia atau sesi telah berakhir.' : 'Rincian belum dapat dimuat. Periksa koneksi lalu coba lagi.');
      body.innerHTML = await response.text();
      setupRosters(detail);
      detail.dataset.loaded = '1';
    } catch (error) {
      body.replaceChildren();
      const message = document.createElement('p');
      message.className = 'notice warning';
      message.textContent = error.name === 'AbortError' ? 'Rincian terlalu lama dimuat. Silakan coba lagi.' : error instanceof TypeError ? 'Koneksi belum tersedia. Silakan coba lagi.' : error.message;
      const retry = document.createElement('button');
      retry.type = 'button'; retry.className = 'button'; retry.textContent = 'Coba lagi';
      retry.addEventListener('click', () => loadBlock(detail));
      body.append(message, retry);
      if (error.message.includes('sesi telah berakhir')) {
        const login = document.createElement('a');
        login.href = '/login?next=' + encodeURIComponent(location.pathname + location.search + location.hash);
        login.className = 'button primary';
        login.textContent = 'Masuk kembali';
        body.append(login);
      }
    } finally {
      clearTimeout(timeout);
      delete detail.dataset.loading;
      body.removeAttribute('aria-busy');
    }
  }

  function showBlock(index, { updateURL = true, focus = true } = {}) {
    if (index < 0 || index >= blocks.length || index === active) return;
    if (active >= 0) savedScroll.set(blocks[active].id, blocks[active].scrollTop);
    const direction = index > active ? 'slide-from-right' : 'slide-from-left';
    active = index;
    blocks.forEach((block, i) => {
      block.hidden = i !== index;
      block.open = i === index;
      block.classList.remove('slide-from-right', 'slide-from-left');
    });
    const block = blocks[index];
    block.classList.add(direction);
    block.style.setProperty('--block-heading-height', block.querySelector(':scope > summary').offsetHeight + 'px');
    jump.value = block.id;
    window.PortalControls?.refresh(jump);
    viewer.querySelector('[data-block-position]').textContent = (index + 1) + ' / ' + blocks.length + ' bagian';
    viewer.querySelector('[data-block-progress]').value = index + 1;
    previous.disabled = index === 0;
    next.disabled = index === blocks.length - 1;
    document.querySelectorAll('[data-open-section]').forEach((link) => {
      const selected = link.dataset.openSection === block.id;
      link.classList.toggle('active', selected);
      if (selected) link.setAttribute('aria-current', 'location');
      else link.removeAttribute('aria-current');
    });
    if (updateURL) history.pushState(history.state, '', '#' + block.id);
    if (focus) block.querySelector(':scope > summary').focus({ preventScroll: true });
    requestAnimationFrame(() => { if (active === index) block.scrollTop = savedScroll.get(block.id) || 0; });
    loadBlock(block);
  }

  function fromHash() {
    const index = blocks.findIndex((block) => '#' + block.id === location.hash);
    showBlock(index < 0 ? 0 : index, { updateURL: false, focus: false });
  }
  blocks.forEach((block) => block.querySelector(':scope > summary').addEventListener('click', (event) => event.preventDefault()));
  document.querySelectorAll('[data-open-section]').forEach((link) => link.addEventListener('click', (event) => {
    event.preventDefault();
    showBlock(blocks.findIndex((block) => block.id === link.dataset.openSection));
  }));
  jump.addEventListener('change', () => showBlock(blocks.findIndex((block) => block.id === jump.value)));
  previous.addEventListener('click', () => showBlock(active - 1));
  next.addEventListener('click', () => showBlock(active + 1));
  viewer.addEventListener('keydown', (event) => {
    if (event.altKey || event.ctrlKey || event.metaKey || event.shiftKey || event.target.closest('input, select, textarea, [role="combobox"], [contenteditable="true"]') || window.getSelection()?.toString()) return;
    if (event.key === 'ArrowLeft' || event.key === 'ArrowRight') {
      event.preventDefault();
      showBlock(active + (event.key === 'ArrowRight' ? 1 : -1));
    }
  });
  stage.addEventListener('pointerdown', (event) => {
    if (event.pointerType !== 'touch' || !event.isPrimary || event.target.closest('a, button, input, select, textarea, summary, .select-control')) return;
    touchStart = { id: event.pointerId, x: event.clientX, y: event.clientY, time: performance.now() };
  });
  stage.addEventListener('pointercancel', () => { touchStart = null; });
  stage.addEventListener('pointerup', (event) => {
    const start = touchStart;
    touchStart = null;
    if (!start || event.pointerId !== start.id) return;
    const dx = event.clientX - start.x, dy = event.clientY - start.y;
    if (Math.abs(dx) >= 70 && Math.abs(dy) < Math.abs(dx) * .55 && performance.now() - start.time < 750) showBlock(active + (dx < 0 ? 1 : -1));
  });
  window.addEventListener('hashchange', fromHash);
  window.addEventListener('popstate', fromHash);
  if (window.ResizeObserver) new ResizeObserver(() => {
    const block = blocks[active];
    if (block) block.style.setProperty('--block-heading-height', block.querySelector(':scope > summary').offsetHeight + 'px');
  }).observe(stage);
  document.body.classList.add('viewer-page');
  viewer.classList.add('slides-ready');
  viewer.querySelector('[data-slide-controls]').hidden = false;
  fromHash();
}
