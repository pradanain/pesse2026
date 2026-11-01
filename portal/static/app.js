// Keep server-side filtering, pagination and permissions as the source of truth.
const portalTopbar = document.querySelector('.topbar');
if (portalTopbar) {
  const updateHeaderHeight = () => document.documentElement.style.setProperty('--portal-header-height', portalTopbar.getBoundingClientRect().height + 'px');
  if (window.ResizeObserver) new ResizeObserver(updateHeaderHeight).observe(portalTopbar);
  updateHeaderHeight();
}
// Only the results change, so typing never replaces or blurs the search field.
document.querySelectorAll('[data-live-search]').forEach((root) => {
  const form = root.querySelector('[data-live-form]');
  const results = root.querySelector('[data-search-results]');
  const status = root.querySelector('[data-search-status]');
  if (!form || !results || !status || !window.fetch || !window.AbortController) return;
  const input = form.elements.namedItem('q');
  const clear = form.querySelector('[data-search-clear]');
  const retry = root.querySelector('[data-search-retry]');
  let controller, timer, revision = 0, composing = false, lastRequest;

  function highlightMatches(term) {
    if (term.trim().length < 2) return;
    const needle = term.trim().toLocaleLowerCase('id');
    results.querySelectorAll('.assignment-card h3, .assignment-code, .building-label b, .region-card h3, .region-village, .region-card .code').forEach((element) => {
      const text = element.textContent;
      const lower = text.toLocaleLowerCase('id');
      if (!lower.includes(needle)) return;
      const fragment = document.createDocumentFragment();
      let offset = 0, index;
      while ((index = lower.indexOf(needle, offset)) !== -1) {
        fragment.append(document.createTextNode(text.slice(offset, index)));
        const mark = document.createElement('mark');
        mark.textContent = text.slice(index, index + needle.length);
        fragment.append(mark);
        offset = index + needle.length;
      }
      fragment.append(document.createTextNode(text.slice(offset)));
      element.replaceChildren(fragment);
    });
  }

  function updateControls() {
    if (clear) clear.hidden = !input.value;
    const reset = form.querySelector('[data-search-reset]');
    if (reset) reset.hidden = !input.value && !form.elements.namedItem('district')?.value;
  }

  function formURL() {
    const url = new URL(location.href);
    url.search = '';
    for (const [key, value] of new FormData(form)) {
      if (String(value).trim()) url.searchParams.set(key, value);
    }
    return url;
  }

  function syncForm(url) {
    for (const control of form.elements) {
      if (!control.name) continue;
      if (control.type === 'checkbox') control.checked = url.searchParams.get(control.name) === control.value;
      else if (control.tagName === 'SELECT') {
        const value = url.searchParams.get(control.name);
        control.value = value ?? control.options[0].value;
      } else control.value = url.searchParams.get(control.name) || '';
      if (control.tagName === 'SELECT') window.PortalControls?.refresh(control);
    }
    updateControls();
  }

  function cancelPending() {
    revision += 1;
    clearTimeout(timer);
    controller?.abort();
  }

  function showBusy() {
    root.classList.add('is-searching');
    root.classList.remove('search-failed');
    results.setAttribute('aria-busy', 'true');
    results.inert = true;
    status.textContent = 'Mencari data…';
    retry.hidden = true;
  }

  async function search(url, { historyMode = 'replace', sync = false, focus = '' } = {}) {
    cancelPending();
    const current = revision;
    controller = new AbortController();
    const requestController = controller;
    lastRequest = { url, options: { historyMode, sync, focus } };
    showBusy();
    let timedOut = false;
    const timeout = setTimeout(() => { timedOut = true; requestController.abort(); }, 12000);
    try {
      const response = await fetch(url, { credentials: 'same-origin', redirect: 'error', headers: { 'X-Portal-Request': '1' }, signal: requestController.signal });
      if (response.status === 403) throw new Error('session-expired');
      if (!response.ok) throw new Error('response');
      const doc = new DOMParser().parseFromString(await response.text(), 'text/html');
      if (current !== revision) return;
      const incoming = doc.querySelector('[data-search-results]');
      if (!incoming || !doc.querySelector('[data-live-form]')) throw new Error('response');
      results.replaceChildren(...incoming.childNodes);
      highlightMatches(url.searchParams.get('q') || '');
      results.inert = false;
      const total = root.querySelector('[data-search-total]');
      const newTotal = doc.querySelector('[data-search-total]');
      if (total && newTotal) total.replaceChildren(...newTotal.childNodes);
      if (sync) syncForm(url);
      if (historyMode !== 'none' && url.href !== location.href) {
        history[historyMode === 'push' ? 'pushState' : 'replaceState'](history.state, '', url);
      }
      const count = results.querySelector('.result-count') || total;
      status.textContent = count ? count.textContent.trim().replace(/\s+/g, ' ') + '.' : 'Hasil pencarian diperbarui.';
      if (focus === 'page') {
        const heading = results.querySelector('h2');
        heading?.setAttribute('tabindex', '-1');
        heading?.focus({ preventScroll: true });
        heading?.scrollIntoView({ block: 'start' });
      } else if (focus === 'chip') results.querySelector('.filter-chip.selected')?.focus({ preventScroll: true });
      else if (focus === 'input') input.focus({ preventScroll: true });
    } catch (error) {
      if (current !== revision) return;
      root.classList.add('search-failed');
      status.textContent = timedOut ? 'Pencarian terlalu lama. Hasil sebelumnya masih ditampilkan. Coba lagi.' : 'Hasil belum dapat diperbarui. Hasil sebelumnya masih ditampilkan. Periksa koneksi lalu coba lagi.';
      if (error.message === 'session-expired') {
        status.textContent = 'Sesi berakhir. ';
        const login = document.createElement('a');
        login.textContent = 'Masuk kembali';
        login.href = '/login?next=' + encodeURIComponent(location.pathname + location.search);
        status.append(login);
      }
      retry.hidden = false;
    } finally {
      clearTimeout(timeout);
      if (current === revision) {
        root.classList.remove('is-searching');
        results.removeAttribute('aria-busy');
        results.inert = false;
      }
    }
  }

  function schedule() {
    cancelPending();
    updateControls();
    showBusy();
    timer = setTimeout(() => search(formURL()), 300);
  }

  input.addEventListener('compositionstart', () => { composing = true; cancelPending(); });
  input.addEventListener('compositionend', () => { composing = false; schedule(); });
  input.addEventListener('input', (event) => { if (!composing && !event.isComposing) schedule(); });
  form.addEventListener('change', (event) => {
    if (event.target.matches('select, input[type="checkbox"]')) search(formURL());
  });
  form.addEventListener('submit', (event) => { event.preventDefault(); search(formURL()); });
  clear?.addEventListener('click', () => {
    input.value = '';
    updateControls();
    input.focus();
    search(formURL());
  });
  retry.addEventListener('click', () => { if (lastRequest) search(lastRequest.url, lastRequest.options); });
  root.addEventListener('click', (event) => {
    const link = event.target.closest('a');
    if (!link || event.defaultPrevented || event.button !== 0 || event.metaKey || event.ctrlKey || event.shiftKey || event.altKey) return;
    if (!link.matches('.filter-chip, .pagination a, .reset-link, .empty .button')) return;
    const url = new URL(link.href);
    if (url.origin !== location.origin || url.pathname !== location.pathname) return;
    event.preventDefault();
    search(url, { historyMode: 'push', sync: true, focus: link.matches('.filter-chip') ? 'chip' : link.closest('.pagination') ? 'page' : 'input' });
  });
  window.addEventListener('popstate', () => {
    const url = new URL(location.href);
    syncForm(url);
    search(url, { historyMode: 'none' });
  });
  updateControls();
  highlightMatches(input.value);
  status.textContent = status.dataset.idle;
  root.classList.add('live-search-ready');
});
