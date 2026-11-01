/* Native selects remain the form data source and fallback without JavaScript. */
(() => {
  const instances = new WeakMap();
  let opened = null, serial = 0;

  function enhance(select) {
    if (instances.has(select) || select.multiple || select.size > 1) return;
    const wrapper = document.createElement('div');
    wrapper.className = 'select-control';
    const trigger = document.createElement('button');
    trigger.type = 'button';
    trigger.id = (select.id || 'portal-select-' + ++serial) + '-control';
    trigger.className = 'select-trigger';
    trigger.setAttribute('role', 'combobox');
    trigger.setAttribute('aria-haspopup', 'listbox');
    trigger.setAttribute('aria-expanded', 'false');
    const labelText = select.getAttribute('aria-label') || [...select.labels].map(label => label.childNodes[0]?.textContent.trim()).filter(Boolean).join(' ') || 'Pilih opsi';
    trigger.setAttribute('aria-label', labelText);
    const value = document.createElement('span');
    value.className = 'select-value';
    value.id = trigger.id + '-value';
    trigger.setAttribute('aria-describedby', value.id);
    trigger.append(value);
    const arrow = document.createElement('span');
    arrow.className = 'select-arrow';
    arrow.setAttribute('aria-hidden', 'true');
    trigger.append(arrow);
    const popup = document.createElement('div');
    popup.id = trigger.id + '-list';
    popup.className = 'select-popup';
    popup.setAttribute('role', 'listbox');
    popup.setAttribute('aria-label', trigger.getAttribute('aria-label'));
    popup.hidden = true;
    trigger.setAttribute('aria-controls', popup.id);
    let cursor = -1, typeBuffer = '', typedAt = 0;
    select.before(wrapper);
    wrapper.append(select, trigger, popup);
    select.classList.add('enhanced-select');
    select.tabIndex = -1;
    select.setAttribute('aria-hidden', 'true');

    function refresh() {
      value.textContent = select.selectedOptions[0]?.textContent || 'Pilih opsi';
      trigger.disabled = select.disabled;
      if (select.disabled && opened === api) close();
      if (select.getAttribute('aria-controls')) trigger.dataset.contentTarget = select.getAttribute('aria-controls');
      if (opened === api) render();
    }

    function render() {
      popup.replaceChildren();
      [...select.options].forEach((option, index) => {
        const row = document.createElement('div');
        row.className = 'select-option';
        row.id = popup.id + '-' + index;
        row.setAttribute('role', 'option');
        row.setAttribute('aria-selected', String(option.selected));
        row.setAttribute('aria-disabled', String(option.disabled));
        row.dataset.index = String(index);
        row.textContent = option.textContent;
        row.classList.toggle('is-current', index === cursor);
        row.addEventListener('pointermove', () => setCursor(index, false));
        row.addEventListener('pointerdown', event => event.preventDefault());
        row.addEventListener('click', () => commit(index));
        popup.append(row);
      });
      if (cursor >= 0) trigger.setAttribute('aria-activedescendant', popup.id + '-' + cursor);
    }

    function position() {
      if (opened !== api) return;
      const rect = trigger.getBoundingClientRect();
      const viewport = window.visualViewport;
      const leftEdge = (viewport?.offsetLeft || 0) + 10;
      const topEdge = (viewport?.offsetTop || 0) + 10;
      const width = viewport?.width || innerWidth;
      const height = viewport?.height || innerHeight;
      const bottomEdge = topEdge + height - 20;
      const below = bottomEdge - rect.bottom - 7;
      const above = rect.top - topEdge - 7;
      const upward = below < 180 && above > below;
      const available = Math.max(60, Math.min(320, upward ? above : below));
      const menuWidth = Math.min(Math.max(rect.width, 240), width - 20);
      popup.style.width = menuWidth + 'px';
      popup.style.maxHeight = available + 'px';
      popup.style.left = Math.min(Math.max(rect.left, leftEdge), leftEdge + width - 20 - menuWidth) + 'px';
      popup.style.top = (upward ? rect.top - Math.min(popup.scrollHeight, available) - 7 : rect.bottom + 7) + 'px';
      popup.dataset.direction = upward ? 'up' : 'down';
    }

    function setCursor(index, scroll = true) {
      if (!select.options[index] || select.options[index].disabled) return;
      cursor = index;
      for (const row of popup.children) row.classList.toggle('is-current', Number(row.dataset.index) === cursor);
      trigger.setAttribute('aria-activedescendant', popup.id + '-' + cursor);
      if (scroll) {
        const row = popup.children[cursor];
        if (row && row.offsetTop < popup.scrollTop) popup.scrollTop = row.offsetTop - 5;
        else if (row && row.offsetTop + row.offsetHeight > popup.scrollTop + popup.clientHeight) popup.scrollTop = row.offsetTop + row.offsetHeight - popup.clientHeight + 5;
      }
    }

    function close() {
      popup.hidden = true;
      wrapper.append(popup);
      trigger.setAttribute('aria-expanded', 'false');
      trigger.removeAttribute('aria-activedescendant');
      wrapper.classList.remove('is-open');
      if (opened === api) opened = null;
    }

    function open() {
      if (trigger.disabled) return;
      opened?.close();
      opened = api;
      cursor = select.selectedIndex;
      render();
      document.body.append(popup);
      popup.hidden = false;
      wrapper.classList.add('is-open');
      trigger.setAttribute('aria-expanded', 'true');
      position();
      if (cursor >= 0) setCursor(cursor);
    }

    function commit(index) {
      if (select.options[index].disabled) return;
      const changed = select.selectedIndex !== index;
      select.selectedIndex = index;
      close();
      refresh();
      trigger.focus({ preventScroll: true });
      if (changed) {
        select.dispatchEvent(new Event('input', { bubbles: true }));
        select.dispatchEvent(new Event('change', { bubbles: true }));
      }
    }

    const api = { refresh, close, trigger, popup, wrapper, position };
    instances.set(select, api);
    trigger.addEventListener('click', event => { event.preventDefault(); opened === api ? close() : open(); });
    trigger.addEventListener('keydown', event => {
      const isOpen = opened === api;
      if (event.key === 'Escape') { if (isOpen) { event.preventDefault(); event.stopPropagation(); close(); } return; }
      if (event.key === 'Tab') { close(); return; }
      if (['ArrowDown', 'ArrowUp', 'Home', 'End'].includes(event.key)) {
        event.preventDefault(); event.stopPropagation();
        if (!isOpen) open();
        const enabled = [...select.options].map((option, index) => option.disabled ? -1 : index).filter(index => index >= 0);
        let index = enabled.indexOf(cursor);
        index = event.key === 'Home' ? 0 : event.key === 'End' ? enabled.length - 1 : Math.max(0, Math.min(enabled.length - 1, index + (event.key === 'ArrowDown' ? 1 : -1)));
        if (enabled.length) setCursor(enabled[index]);
      } else if (event.key === 'Enter' || event.key === ' ') {
        event.preventDefault(); event.stopPropagation();
        if (isOpen && cursor >= 0) commit(cursor); else open();
      } else if (event.key.length === 1 && !event.ctrlKey && !event.metaKey && !event.altKey) {
        event.preventDefault();
        if (!isOpen) open();
        const now = performance.now();
        typeBuffer = now - typedAt < 700 ? typeBuffer + event.key : event.key;
        typedAt = now;
        const index = [...select.options].findIndex(option => !option.disabled && option.textContent.trim().toLocaleLowerCase('id').startsWith(typeBuffer.toLocaleLowerCase('id')));
        if (index >= 0) setCursor(index);
      }
    });
    trigger.addEventListener('blur', () => { if (opened === api) close(); });
    [...select.labels].forEach(label => label.addEventListener('click', event => {
      if (event.target === label) { event.preventDefault(); trigger.focus(); }
    }));
    select.addEventListener('change', refresh);
    select.addEventListener('invalid', event => { event.preventDefault(); trigger.focus(); });
    select.form?.addEventListener('reset', () => setTimeout(refresh, 0));
    refresh();
  }

  function scan(root = document) {
    if (root.matches?.('select')) enhance(root);
    root.querySelectorAll?.('select').forEach(enhance);
  }
  window.PortalControls = { refresh(select) { if (select) { enhance(select); instances.get(select)?.refresh(); } } };
  scan();
  new MutationObserver(records => {
    if (opened && !opened.trigger.isConnected) opened.close();
    for (const record of records) {
      if (record.type === 'attributes' && record.target.matches('select, option')) {
        const select = record.target.matches('select') ? record.target : record.target.closest('select');
        instances.get(select)?.refresh();
      } else if (record.type === 'childList') {
        record.addedNodes.forEach(node => { if (node.nodeType === 1) scan(node); });
        if (record.target.matches?.('select')) instances.get(record.target)?.refresh();
      }
    }
  }).observe(document.body, { childList: true, subtree: true, attributes: true, attributeFilter: ['disabled', 'selected'] });
  document.addEventListener('pointerdown', event => {
    if (opened && !opened.popup.contains(event.target) && !opened.wrapper.contains(event.target)) opened.close();
  });
  document.addEventListener('scroll', event => {
    if (opened && !opened.popup.contains(event.target)) {
      if (!opened.trigger.getClientRects().length) opened.close(); else opened.position();
    }
  }, true);
  window.addEventListener('resize', () => opened?.close());
  window.visualViewport?.addEventListener('resize', () => opened?.close());
})();
